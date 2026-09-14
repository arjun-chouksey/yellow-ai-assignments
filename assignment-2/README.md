# Weather-aware delivery orders

Python solution for Yellow.ai AI Intern Assignment 2. Reads four orders, fetches weather concurrently, marks Rain/Snow/Extreme orders Delayed, and prints personalized apologies.

## Setup

Requires Python 3.11 or later. From this folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\activate` instead.

Create `.env` beside the script with the following line, replacing the placeholder with your OpenWeatherMap key. The repository excludes this private file; create it locally.

```dotenv
OPENWEATHER_API_KEY=your_api_key_here
```

Keys: https://home.openweathermap.org/api_keys

## Run

```sh
python weather_orders.py
```

Live mode reads and updates `orders.json`. Requests run together through a shared HTTPX client and `asyncio.gather`. Expected errors are caught per order. After all requests finish, the script saves the complete JSON through atomic file replacement.

```sh
python weather_orders.py --demo
python -m pytest -q
```

Demo mode reads the same `orders.json`, uses simulated weather, and saves to `demo/orders.json` without changing the live file. That output is a demonstration result, not another input template. It simulates New York rain, Mumbai clear weather, London snow, and an invalid-city HTTP 404.

Optional `--orders PATH` and `--output PATH` flags select another input or output. Demo mode refuses to overwrite its input or the default live orders file.

## Behavior and decisions

- The exact delay conditions are `Rain`, `Snow`, and `Extreme`, read from `weather[0].main`. The top-level `main` object contains temperature information.
- Apologies use the first name, destination, and reported description. Missing descriptions use a neutral fallback. No delivery estimate or severity is invented.
- AI helped write the apology function; no runtime LLM is needed. Messages are printed, not sent to customers.
- Other conditions and failed checks preserve the existing status. Previously delayed orders are not automatically reset because the assignment provides no recovery rule.
- Invalid cities, HTTP errors, timeouts, connection failures, and malformed responses are handled independently. HTTP request URLs and raw exceptions are not logged because they may contain the key.
- Exit 0 means at least one weather check succeeded and results were saved; an isolated invalid city is expected. Setup/file errors or all requests failing produce exit 1.
- Requests have a 10-second timeout and no automatic retries. One task per order suits the four-record assignment. Do not run multiple processes against the same output file.
- The city-name API is used for the exact assignment inputs. OpenWeather documents its built-in geocoding as deprecated but still available; a production extension could use separate geocoding and coordinates.

## Verification and submission

35 automated tests passed, including a barrier test proving all four requests start before any can complete, delay rules, error isolation, key privacy, and safe persistence.

Live verification succeeded on 13 September 2026. Mumbai and London returned Rain and were marked Delayed; New York returned Clouds and remains Pending. InvalidCity123 returned HTTP 404 without stopping the valid orders. `live-run.txt` records the successful run. The submission ZIP contains the updated live `orders.json`.

| File | Purpose |
|---|---|
| `weather_orders.py` | Script and offline demo |
| `orders.json` | Single live order database |
| `.env` | Local secret; excluded from Git and ZIP |
| `requirements.txt` | Application and test dependencies |
| `test_weather_orders.py` | Behavior and integration tests |
| `AI_LOG.md` | Actual AI prompts and decisions |
| `live-run.txt` | Latest live attempt |
| `demo/orders.json` | Clearly simulated output |
| `demo/demo.mp4` | 51-second simulated demo walkthrough |

The silent video renders captured terminal output with captions; it is not a live API screen recording. The supplied assignment requires code, updated orders, an AI log, and a demo recording. Keep simulated weather clearly labeled and never include `.env` in the submission.

References: https://docs.openweather.co.uk/current and https://www.python-httpx.org/async/
