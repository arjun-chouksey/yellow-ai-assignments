import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest

import weather_orders as app


def order(city="New York", order_id="1001", status="Pending"):
    return {"order_id": order_id, "customer": "Alice Smith", "city": city, "status": status}


def initial_orders_bytes():
    orders = app.load_orders(app.BASE_DIR / "orders.json")
    for item in orders:
        item["status"] = "Pending"
    return json.dumps(orders).encode()


def execute(orders, handler):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await app.process_orders(orders, client, "test-secret-do-not-log")
    return asyncio.run(scenario())


@pytest.mark.parametrize("condition,description", [
    ("Rain", "heavy rain"), ("Snow", "light snow"), ("Extreme", "extreme weather")
])
def test_all_required_delay_conditions(condition, description):
    orders = [order()]
    results = execute(orders, lambda req: httpx.Response(200, json={
        "weather": [{"main": condition, "description": description}]
    }))
    assert orders[0]["status"] == "Delayed"
    assert results[0].message == (
        f"Hi Alice, we're sorry—your order to New York is delayed due to {description}. "
        "We appreciate your patience!"
    )


@pytest.mark.parametrize("condition", ["Clear", "Clouds", "Drizzle", "Thunderstorm"])
def test_other_conditions_preserve_existing_status(condition):
    orders = [order(), order(order_id="1002", status="Delayed")]
    results = execute(orders, lambda req: httpx.Response(200, json={"weather": [{"main": condition}]}))
    assert [item["status"] for item in orders] == ["Pending", "Delayed"]
    assert all(result.message is None for result in results)


def test_invalid_city_does_not_prevent_successful_updates(caplog):
    orders = [order(), order(city="InvalidCity123", order_id="1004")]
    def handler(request):
        if request.url.params["q"] == "InvalidCity123":
            return httpx.Response(404, json={"message": "city not found"})
        return httpx.Response(200, json={"weather": [{"main": "Rain", "description": "light rain"}]})
    results = execute(orders, handler)
    assert [item["status"] for item in orders] == ["Delayed", "Pending"]
    assert results[0].message and results[1].error == "HTTP 404: city not found"
    assert "InvalidCity123" in caplog.text
    assert "test-secret-do-not-log" not in caplog.text


def test_all_four_requests_are_in_flight_before_any_can_complete():
    async def scenario():
        started = []
        release = asyncio.Event()
        async def handler(request):
            started.append(request.url.params["q"])
            if len(started) == 4:
                release.set()
            await asyncio.wait_for(release.wait(), timeout=2)
            return httpx.Response(200, json={"weather": [{"main": "Clear"}]})
        orders = [order(city=f"City{i}", order_id=str(i)) for i in range(4)]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            results = await app.process_orders(orders, client, "test-key")
        assert len(started) == 4
        assert all(result.error is None for result in results)
    asyncio.run(scenario())


@pytest.mark.parametrize("exception,expected", [
    (httpx.ReadTimeout, "weather request timed out"),
    (httpx.ConnectError, "unable to connect to weather service"),
])
def test_network_failure_is_isolated_and_does_not_leak_key(exception, expected, caplog):
    orders = [order(city="Broken"), order(city="Good", order_id="1002")]
    def handler(request):
        if request.url.params["q"] == "Broken":
            raise exception(f"URL contains test-secret-do-not-log", request=request)
        return httpx.Response(200, json={"weather": [{"main": "Snow"}]})
    results = execute(orders, handler)
    assert results[0].error == expected
    assert orders[1]["status"] == "Delayed"
    assert "test-secret-do-not-log" not in caplog.text


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_http_failures_leave_status_unchanged(status):
    orders = [order()]
    results = execute(orders, lambda req: httpx.Response(status, text="private response body"))
    assert results[0].error.startswith(f"HTTP {status}:")
    assert orders[0]["status"] == "Pending"


@pytest.mark.parametrize("payload", [{}, {"weather": []}, {"weather": None},
    {"weather": [{}]}, {"weather": [{"main": None}]}, {"weather": ["Rain"]}])
def test_malformed_weather_is_handled(payload):
    results = execute([order()], lambda req: httpx.Response(200, json=payload))
    assert results[0].error == "invalid weather response"


def test_non_json_response_is_handled():
    results = execute([order()], lambda req: httpx.Response(200, text="<html>error</html>"))
    assert results[0].error == "invalid weather response"


def test_missing_description_uses_condition_without_inventing_severity():
    results = execute([order()], lambda req: httpx.Response(200, json={"weather": [{"main": "Rain"}]}))
    assert "due to rain." in results[0].message
    assert "heavy" not in results[0].message


def test_full_demo_persists_results_without_modifying_source(tmp_path):
    source = tmp_path / "input.json"
    source.write_bytes(initial_orders_bytes())
    original = source.read_bytes()
    output = tmp_path / "demo.json"
    assert app.main(["--demo", "--orders", str(source), "--output", str(output)]) == 0
    assert source.read_bytes() == original
    result = app.load_orders(output)
    assert [item["status"] for item in result] == ["Delayed", "Pending", "Delayed", "Pending"]
    for before, after in zip(json.loads(original), result):
        assert {k: v for k, v in before.items() if k != "status"} == {
            k: v for k, v in after.items() if k != "status"
        }


def test_demo_cannot_overwrite_its_input(tmp_path):
    source = tmp_path / "orders.json"
    source.write_text(json.dumps([order()]))
    before = source.read_bytes()
    assert app.main(["--demo", "--orders", str(source), "--output", str(source)]) == 1
    assert source.read_bytes() == before


def test_missing_key_does_not_modify_orders(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "load_dotenv", lambda *a: None)
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)
    source = tmp_path / "orders.json"
    source.write_text(json.dumps([order()]))
    before = source.read_bytes()
    assert app.main(["--orders", str(source)]) == 1
    assert source.read_bytes() == before


def test_live_path_saves_valid_results_despite_invalid_city(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(app, "load_dotenv", lambda *a: None)
    monkeypatch.setenv("OPENWEATHER_API_KEY", "test-secret-do-not-log")
    original_client = httpx.AsyncClient
    monkeypatch.setattr(app.httpx, "AsyncClient", lambda **kwargs: original_client(
        timeout=kwargs["timeout"], transport=app.demo_transport()
    ))
    source = tmp_path / "orders.json"
    source.write_bytes(initial_orders_bytes())
    with caplog.at_level(logging.INFO):
        assert app.main(["--orders", str(source)]) == 0
    assert app.load_orders(source)[0]["status"] == "Delayed"
    assert "test-secret-do-not-log" not in caplog.text


def test_all_requests_failing_returns_nonzero_and_preserves_data(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "load_dotenv", lambda *a: None)
    monkeypatch.setenv("OPENWEATHER_API_KEY", "test-key")
    original_client = httpx.AsyncClient
    monkeypatch.setattr(app.httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda req: httpx.Response(401))
    ))
    source = tmp_path / "orders.json"
    source.write_text(json.dumps([order()]))
    assert app.main(["--orders", str(source)]) == 1
    assert app.load_orders(source) == [order()]


def test_failed_atomic_replace_preserves_original(tmp_path, monkeypatch):
    source = tmp_path / "orders.json"
    source.write_text(json.dumps([order()]))
    original = source.read_bytes()
    def fail(*args):
        raise OSError("simulated write failure")
    monkeypatch.setattr(app.os, "replace", fail)
    with pytest.raises(OSError):
        app.save_orders(source, [order(status="Delayed")])
    assert source.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("payload", [{}, [], [None], [{"order_id": "1"}], [order(), order()]])
def test_invalid_order_data_is_rejected(tmp_path, payload):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        app.load_orders(path)
