# Flight Price Tracker

Automatically searches for flights from Toronto (YYZ) to Japan and Taiwan, then emails a formatted HTML report with prices, layover details, and direct booking links. Runs weekly via GitHub Actions.

## Features

- Searches **outbound**, **return-leg**, and **round-trip** flights across all configured destinations
- Supports **explicit dates** or **days-ahead** relative scheduling
- Optional **departure time filter** (e.g. exclude flights before 7 pm on a specific date)
- Emails a styled HTML report with a summary table + full per-route breakdowns
- **Deep-links to Google Flights** pre-loaded with the exact search
- Configurable via environment variables — no code changes needed to adjust destinations, dates, or passengers
- **70 tests** covering parsing, HTML rendering, and configuration logic

## How It Works

1. Reads configuration from environment variables (`.env` locally, GitHub Actions variables/secrets in CI)
2. Calls the [SerpApi Google Flights](https://serpapi.com/google-flights-api) endpoint for each destination × date × trip-type combination
3. Parses results: airline, departure/arrival times, layovers, duration, and price
4. Renders an HTML email with a summary table and per-trip-type breakdowns
5. Sends the report via SMTP

## Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/<your-username>/flight-finder.git
cd flight-finder
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your values (see [Configuration](#configuration) below).

### 3. Run locally

```bash
python daily_flight_report.py
```

Progress is printed to stderr. On success, an HTML email is sent to `EMAIL_TO`.

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` and fill in the values.

### SerpApi

| Variable | Description |
|---|---|
| `SERPAPI_KEY` | Your SerpApi API key. Free tier: 100 searches/month. Get one at [serpapi.com](https://serpapi.com). |

### Fixture / Mock Mode (run without consuming API quota)

| Variable | Description |
|---|---|
| `SAVE_FIXTURES=1` | Save raw API responses to `fixtures/` after each call. Run once to capture real data. |
| `MOCK_MODE=1` | Read from saved fixture files instead of calling the API. No quota consumed. |

```bash
# Step 1 – capture real responses to disk (uses API quota once)
SAVE_FIXTURES=1 python daily_flight_report.py

# Step 2 – replay forever without API calls
MOCK_MODE=1 python daily_flight_report.py
```

> `fixtures/` is gitignored because SerpApi responses embed your API key.

### Search Parameters

| Variable | Default | Description |
|---|---|---|
| `ORIGIN` | `YYZ` | Departure airport IATA code |
| `DEST_JAPAN` | `NRT` | Tokyo Narita airport (use `HND` for Haneda) |
| `DEST_OSAKA` | `KIX` | Osaka Kansai International |
| `DEST_TAIWAN` | `TPE` | Taipei Taoyuan |
| `DEPARTURE_DATES` | _(empty)_ | Explicit comma-separated dates to search (`YYYY-MM-DD`). Takes priority over `DAYS_AHEAD`. |
| `DAYS_AHEAD` | `30,60,90` | Days ahead from today to search. Used when `DEPARTURE_DATES` is not set. |
| `RETURN_DATES` | _(empty)_ | Return dates for return-leg and round-trip searches (`YYYY-MM-DD`, comma-separated). Leave blank for outbound-only. |
| `TRIP_TYPES` | `outbound,return,roundtrip` | Which trip types to include. `return` and `roundtrip` are skipped automatically when `RETURN_DATES` is not set. |
| `ADULTS` | `1` | Number of adult passengers |
| `MAX_RESULTS` | `5` | Maximum flight options returned per route per date |
| `CURRENCY` | `CAD` | Currency for prices |
| `EARLIEST_DEP_DATE` | _(empty)_ | Only apply the time filter on this specific date (`YYYY-MM-DD`) |
| `EARLIEST_DEP_TIME` | _(empty)_ | Exclude flights departing before this time on `EARLIEST_DEP_DATE` (`HH:MM`, 24h, local airport time) |

**Example** — fixed dates with an evening-only filter for Oct 23:

```ini
DEPARTURE_DATES=2026-10-23,2026-10-24
EARLIEST_DEP_DATE=2026-10-23
EARLIEST_DEP_TIME=19:00
RETURN_DATES=2026-11-05,2026-11-06,2026-11-07,2026-11-08
```

### Email (SMTP)

| Variable | Example | Description |
|---|---|---|
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server hostname |
| `SMTP_PORT` | `587` | SMTP port (587 for STARTTLS, 465 for SSL) |
| `SMTP_USER` | `you@gmail.com` | SMTP login username |
| `SMTP_PASS` | `abcd efgh ijkl mnop` | SMTP password or app password |
| `EMAIL_FROM` | `you@gmail.com` | Sender address |
| `EMAIL_TO` | `you@gmail.com,other@example.com` | Recipient(s), comma-separated |

> **Gmail tip:** Use an [App Password](https://support.google.com/accounts/answer/185833) (not your main password) with 2FA enabled.

## GitHub Actions

The workflow runs every **Tuesday at 12:00 UTC** (8 am EDT), timed to catch Monday night fare sales. It can also be triggered manually from the Actions tab.

### Secrets (Settings → Secrets and variables → Actions → Secrets)

| Secret | Description |
|---|---|
| `SERPAPI_KEY` | SerpApi API key |
| `SMTP_HOST` | SMTP server hostname |
| `SMTP_USER` | SMTP username |
| `SMTP_PASS` | SMTP password / app password |
| `EMAIL_FROM` | Sender email address |
| `EMAIL_TO` | Recipient(s), comma-separated |

### Variables (Settings → Secrets and variables → Actions → Variables)

These override the workflow defaults. All are optional except the date variables below.

**Set these** — they have no useful defaults and control which flights are searched:

| Variable | Example value |
|---|---|
| `DEPARTURE_DATES` | `2026-10-23,2026-10-24` |
| `RETURN_DATES` | `2026-11-05,2026-11-06,2026-11-07,2026-11-08` |
| `EARLIEST_DEP_DATE` | `2026-10-23` |
| `EARLIEST_DEP_TIME` | `19:00` |

If not set, the workflow falls back to searching 30/60/90 days ahead with no time filter and no return searches.

**Optional overrides** (safe defaults already set in the workflow):

| Variable | Default |
|---|---|
| `ORIGIN` | `YYZ` |
| `DEST_JAPAN` | `TYO` |
| `DEST_OSAKA` | `KIX` |
| `DEST_TAIWAN` | `TPE` |
| `ADULTS` | `1` |
| `MAX_RESULTS` | `5` |
| `CURRENCY` | `CAD` |
| `TRIP_TYPES` | `outbound,return,roundtrip` |

### API budget

SerpApi free tier: **100 searches/month**. Paid plans start at 250/month.

Each weekly run uses **42 API calls** (3 destinations × 2 outbound dates × 1 outbound + 4 return dates × 1 return + 8 date combos × 1 round-trip). At a weekly cadence:

| Plan | Searches/month | Runs/month | Calls/run | Headroom |
|---|---|---|---|---|
| Free (100) | 100 | 2 | 42 | ~16 calls buffer |
| Basic (250) | 250 | 4 | 42 | ~82 calls buffer |

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

The test suite has 70 tests covering:
- Duration and layover formatting
- Departure-time filtering
- Date and trip-type configuration parsing
- Flight offer parsing (direct, multi-stop, round-trip)
- HTML table and email body rendering
- Multi-recipient email configuration

## Project Structure

```
flight_finder/
├── daily_flight_report.py          # Main script
├── requirements.txt                # Runtime dependencies
├── requirements-dev.txt            # Dev/test dependencies
├── conftest.py                     # Pytest root config (adds project root to sys.path)
├── .env.example                    # Environment variable template
├── .github/
│   └── workflows/
│       └── weekly-flight-report.yml
└── tests/
    └── test_daily_flight_report.py
```

## Data Source

Flight data is provided by [SerpApi](https://serpapi.com/google-flights-api), which scrapes Google Flights. Results are for informational purposes only — always verify prices on the airline or booking site before purchasing.
