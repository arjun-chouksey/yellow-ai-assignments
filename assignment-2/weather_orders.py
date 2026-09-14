"""Check order weather concurrently and persist delivery delays."""

import argparse
import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
DELAY_CONDITIONS = {"Rain", "Snow", "Extreme"}
LOGGER = logging.getLogger("weather_orders")


@dataclass(frozen=True)
class Outcome:
    order_id: str
    city: str
    condition: str | None = None
    message: str | None = None
    error: str | None = None


class WeatherError(Exception):
    """A safe, user-facing error that never includes the API request URL."""


def weather_aware_apology(customer: str, city: str, description: str) -> str:
    first_name = customer.split()[0]
    return (
        f"Hi {first_name}, we're sorry—your order to {city} "
        f"is delayed due to {description}. We appreciate your patience!"
    )


def load_orders(path: Path) -> list[dict]:
    orders = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(orders, list) or not orders:
        raise ValueError("Orders must be a non-empty JSON array.")
    seen = set()
    for index, order in enumerate(orders):
        if not isinstance(order, dict):
            raise ValueError(f"Order at index {index} must be an object.")
        for field in ("order_id", "customer", "city", "status"):
            value = order.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Order at index {index}: {field} must be a non-empty string.")
        if order["order_id"] in seen:
            raise ValueError("Order IDs must be unique.")
        seen.add(order["order_id"])
    return orders


def save_orders(path: Path, orders: list[dict]) -> None:
    """Replace the file only after a complete JSON document has been written."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(orders, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def fetch_weather(client: httpx.AsyncClient, city: str, api_key: str) -> tuple[str, str]:
    response = await client.get(
        WEATHER_URL, params={"q": city, "appid": api_key, "lang": "en"}
    )
    if response.status_code != 200:
        explanations = {
            401: "API key rejected; check or activate your OpenWeatherMap key",
            403: "API access denied; check your OpenWeatherMap access",
            404: "city not found",
            429: "API rate limit reached; try again later",
        }
        reason = explanations.get(response.status_code, "weather service request failed")
        raise WeatherError(f"HTTP {response.status_code}: {reason}")
    try:
        weather = response.json()["weather"][0]
        condition = weather["main"]
        description = weather.get("description")
        if not isinstance(condition, str) or not condition.strip():
            raise ValueError
        if not isinstance(description, str) or not description.strip():
            description = {
                "Rain": "rain", "Snow": "snow", "Extreme": "extreme weather"
            }.get(condition, condition.lower())
        return condition, description
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        raise WeatherError("invalid weather response") from exc


async def process_order(client: httpx.AsyncClient, order: dict, api_key: str) -> Outcome:
    order_id, city = order["order_id"], order["city"]
    LOGGER.info("START order %s | %s", order_id, city)
    try:
        condition, description = await fetch_weather(client, city, api_key)
    except httpx.TimeoutException:
        error = "weather request timed out"
    except httpx.RequestError:
        error = "unable to connect to weather service"
    except WeatherError as exc:
        error = str(exc)
    else:
        message = None
        if condition in DELAY_CONDITIONS:
            order["status"] = "Delayed"
            message = weather_aware_apology(order["customer"], city, description)
        LOGGER.info("DONE  order %s | %s | %s -> %s", order_id, city, condition, order["status"])
        return Outcome(order_id, city, condition=condition, message=message)
    LOGGER.error("ERROR order %s | %s | %s; status unchanged", order_id, city, error)
    return Outcome(order_id, city, error=error)


async def process_orders(orders: list[dict], client: httpx.AsyncClient, api_key: str) -> list[Outcome]:
    # Expected failures are caught per order, so one bad city cannot abort the batch.
    return await asyncio.gather(*(process_order(client, order, api_key) for order in orders))


def demo_transport() -> httpx.MockTransport:
    """Simulate HTTP responses; the normal parsing and order logic still run."""
    conditions = {
        "New York": ("Rain", "heavy rain"),
        "Mumbai": ("Clear", "clear sky"),
        "London": ("Snow", "light snow"),
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.25)
        city = request.url.params.get("q")
        if city not in conditions:
            return httpx.Response(404, json={"cod": "404", "message": "city not found"})
        condition, description = conditions[city]
        return httpx.Response(200, json={"weather": [{"main": condition, "description": description}]})

    return httpx.MockTransport(handler)


async def run(orders: list[dict], api_key: str, demo: bool) -> list[Outcome]:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        transport=demo_transport() if demo else None,
    ) as client:
        return await process_orders(orders, client, api_key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Use simulated weather; no network or key needed.")
    parser.add_argument("--orders", type=Path, help="Input JSON (default: orders.json).")
    parser.add_argument("--output", type=Path, help="Output JSON (default: update input; demo: demo/orders.json).")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    # HTTPX's info logs include URLs; those URLs contain the API key.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    load_dotenv(BASE_DIR / ".env")
    api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
    if not args.demo and (not api_key or api_key == "your_api_key_here"):
        LOGGER.error("Add OPENWEATHER_API_KEY to the .env file beside this script, then run again.")
        return 1
    input_path = args.orders or BASE_DIR / "orders.json"
    output_path = args.output or (BASE_DIR / "demo" / "orders.json" if args.demo else input_path)
    if args.demo and output_path.resolve() in {
        input_path.resolve(), (BASE_DIR / "orders.json").resolve()
    }:
        LOGGER.error("Choose a separate demo output file so simulated results cannot overwrite the source orders.")
        return 1
    try:
        orders = load_orders(input_path)
    except (OSError, ValueError) as exc:
        LOGGER.error("Cannot read orders: %s", exc)
        return 1
    mode = "DEMO — SIMULATED WEATHER; NO LIVE API CALLS" if args.demo else "LIVE — OpenWeatherMap current weather"
    print(mode, flush=True)
    start = time.perf_counter()
    outcomes = asyncio.run(run(orders, api_key, args.demo))
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        save_orders(output_path, orders)
    except OSError:
        LOGGER.error("Could not save orders. Check output path and permissions.")
        return 1
    for result in outcomes:
        if result.message:
            print(f"\n{result.message}", flush=True)
    failures = sum(result.error is not None for result in outcomes)
    delayed = sum(result.message is not None for result in outcomes)
    print(f"\nProcessed {len(orders)} orders | {len(orders) - failures} weather checks succeeded | "
          f"{failures} failed | {delayed} delay conditions matched", flush=True)
    print(f"Saved: {output_path}\nElapsed: {time.perf_counter() - start:.2f}s", flush=True)
    # An isolated bad city is expected; an entirely failed batch needs attention.
    return 1 if failures == len(orders) else 0


if __name__ == "__main__":
    raise SystemExit(main())
