#!/usr/bin/env python3
"""
Flight Price Report
- Searches for flights from Toronto (YYZ) to Japan (Tokyo, Osaka) and Taiwan
  via the SerpApi Google Flights engine
- Emails an HTML comparison table of results via SMTP

Register free at: https://serpapi.com (100 searches/month, no credit card required)
"""

import json
import os
import sys
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

# Load .env for local development
load_dotenv()

# ---------------------------------------------------------------------------
# SMTP configuration – identical pattern to honda_passport
# ---------------------------------------------------------------------------

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS", "").strip()

EMAIL_FROM = os.environ.get("EMAIL_FROM", SMTP_USER)
# Comma-separated list of recipients, e.g. "a@gmail.com,b@gmail.com"
EMAIL_TO   = [e.strip() for e in os.environ.get("EMAIL_TO", SMTP_USER).split(",") if e.strip()]

# ---------------------------------------------------------------------------
# SerpApi configuration
# ---------------------------------------------------------------------------

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "").strip()
SERPAPI_URL = "https://serpapi.com/search"

# Fixture mode – set SAVE_FIXTURES=1 to cache raw API responses to disk,
# then MOCK_MODE=1 to replay them without consuming API quota.
_bool_env = lambda key: os.environ.get(key, "").strip().lower() in ("1", "true", "yes")
SAVE_FIXTURES = _bool_env("SAVE_FIXTURES")
MOCK_MODE     = _bool_env("MOCK_MODE")
FIXTURES_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

# ---------------------------------------------------------------------------
# Search configuration
# ---------------------------------------------------------------------------

ORIGIN = os.environ.get("ORIGIN", "YYZ")  # Toronto Pearson International

# Destination IATA airport codes.  SerpApi requires specific airport codes —
# metro codes like TYO are not supported by the Google Flights API.
DESTINATIONS: Dict[str, str] = {
    "Japan (Tokyo)": os.environ.get("DEST_JAPAN",  "NRT"),  # Tokyo Narita (or HND for Haneda)
    "Japan (Osaka)": os.environ.get("DEST_OSAKA",  "KIX"),  # Osaka Kansai
    "Taiwan":        os.environ.get("DEST_TAIWAN", "TPE"),  # Taipei Taoyuan
}

# Departure dates – either explicit comma-separated list OR days ahead from today.
# If DEPARTURE_DATES is set it takes priority over DAYS_AHEAD.
DEPARTURE_DATES_ENV = os.environ.get("DEPARTURE_DATES", "").strip()
DAYS_AHEAD_ENV      = os.environ.get("DAYS_AHEAD", "30,60,90").strip()

# Return dates – used for return-leg one-way and round-trip searches.
# If not set, return and round-trip sections are skipped.
RETURN_DATES_ENV = os.environ.get("RETURN_DATES", "").strip()

# Which trip types to include: comma-separated subset of outbound,return,roundtrip
TRIP_TYPES_ENV = os.environ.get("TRIP_TYPES", "outbound,return,roundtrip").strip()

ADULTS      = int(os.environ.get("ADULTS", "1"))
MAX_RESULTS = int(os.environ.get("MAX_RESULTS", "5"))   # results per route per date
CURRENCY    = os.environ.get("CURRENCY", "CAD")

# Optional time-of-day filter for a specific departure date.
# Any flight on EARLIEST_DEP_DATE that departs before EARLIEST_DEP_TIME (HH:MM, 24h,
# local airport time) will be excluded.  Useful when you can only leave after work.
EARLIEST_DEP_DATE = os.environ.get("EARLIEST_DEP_DATE", "").strip()   # e.g. 2026-10-23
EARLIEST_DEP_TIME = os.environ.get("EARLIEST_DEP_TIME", "").strip()   # e.g. 19:00

# ---------------------------------------------------------------------------
# Google Flights deep-link builder
# ---------------------------------------------------------------------------

def google_flights_url(origin: str, destination: str, date: str, adults: int = 1) -> str:
    """
    Build a Google Flights search URL for a one-way trip.
    Opens the results page pre-filled with origin, destination, date, and passengers.
    """
    params = (
        f"f={origin}"
        f"&t={destination}"
        f"&d={date}"
        f"&return=0"          # one-way
        f"&adults={adults}"
        f"&curr=CAD"
    )
    return f"https://www.google.com/travel/flights?{params}"


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def get_departure_dates() -> List[str]:
    """Return the list of outbound departure dates to search."""
    if DEPARTURE_DATES_ENV:
        return [d.strip() for d in DEPARTURE_DATES_ENV.split(",") if d.strip()]
    today = datetime.now()
    days_list = [int(d.strip()) for d in DAYS_AHEAD_ENV.split(",") if d.strip()]
    return [(today + timedelta(days=d)).strftime("%Y-%m-%d") for d in days_list]


def get_return_dates() -> List[str]:
    """Return the list of return dates (for return-leg and round-trip searches)."""
    return [d.strip() for d in RETURN_DATES_ENV.split(",") if d.strip()]


def get_active_trip_types() -> List[str]:
    valid = {"outbound", "return", "roundtrip"}
    return [t.strip() for t in TRIP_TYPES_ENV.split(",") if t.strip() in valid]


# ---------------------------------------------------------------------------
# Duration and layover helpers
# ---------------------------------------------------------------------------

def _format_minutes(mins: int) -> str:
    """Convert integer minutes to '14h 30m'."""
    h, m = divmod(int(mins), 60)
    return f"{h}h {m}m" if m else f"{h}h"


def _format_layovers(layovers: List[Dict[str, Any]]) -> str:
    """Return layover airports with durations, e.g. 'ICN (1h 35m) · PVG (2h 10m)'.
    Returns '—' if direct."""
    if not layovers:
        return "—"
    parts = [
        f"{l.get('id', '?')} ({_format_minutes(l.get('duration', 0))})"
        for l in layovers
    ]
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# SerpApi client
# ---------------------------------------------------------------------------

def _fixture_path(origin: str, destination: str, dep_date: str, return_date: Optional[str]) -> str:
    name = f"{origin}_{destination}_{dep_date}"
    if return_date:
        name += f"_ret_{return_date}"
    return os.path.join(FIXTURES_DIR, name + ".json")


def _parse_response(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    book_url = data.get("search_metadata", {}).get("google_flights_url", "")
    results = data.get("best_flights", []) + data.get("other_flights", [])
    for fg in results:
        fg["_book_url"] = book_url
    return results[:MAX_RESULTS]


def search_flights(
    origin: str,
    destination: str,
    dep_date: str,
    return_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Call SerpApi Google Flights and return combined best + other flight groups.

    With MOCK_MODE=1: reads from a previously saved fixture file (no API call).
    With SAVE_FIXTURES=1: saves the raw API response to fixtures/ after each call.
    """
    fpath = _fixture_path(origin, destination, dep_date, return_date)

    # ── Mock mode: read from saved fixture, no API call ──────────────────────
    if MOCK_MODE:
        if not os.path.exists(fpath):
            raise FileNotFoundError(
                f"Mock mode is on but no fixture found: {fpath}\n"
                f"Run once with SAVE_FIXTURES=1 to capture real responses."
            )
        with open(fpath) as f:
            return _parse_response(json.load(f))

    # ── Live mode: call SerpApi ───────────────────────────────────────────────
    if not SERPAPI_KEY:
        raise RuntimeError(
            "SERPAPI_KEY must be set. Register free at https://serpapi.com"
        )
    params: Dict[str, Any] = {
        "engine":        "google_flights",
        "api_key":       SERPAPI_KEY,
        "departure_id":  origin,
        "arrival_id":    destination,
        "outbound_date": dep_date,
        "currency":      CURRENCY,
        "adults":        ADULTS,
        "type":          1 if return_date else 2,   # 1=round-trip, 2=one-way
    }
    if return_date:
        params["return_date"] = return_date

    resp = requests.get(SERPAPI_URL, params=params, timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        if SAVE_FIXTURES:
            os.makedirs(FIXTURES_DIR, exist_ok=True)
            with open(fpath, "w") as f:
                json.dump(data, f, indent=2)
            print(f"    Fixture saved: {os.path.basename(fpath)}", file=sys.stderr)
        # Grab the pre-built Google Flights URL from the response metadata –
        # it contains the encoded tfs blob that actually pre-loads the search.
        return _parse_response(data)
    if resp.status_code in (400, 404):
        # Log the API error body so we can diagnose issues (e.g. invalid airport codes)
        try:
            err_msg = resp.json().get("error", resp.text[:300])
        except Exception:
            err_msg = resp.text[:300]
        print(f"    API {resp.status_code} for {origin}->{destination} {dep_date}: {err_msg}", file=sys.stderr)
        return []
    resp.raise_for_status()
    return []


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_offer(
    flight_group: Dict[str, Any],
    dest_name: str,
    dest_code: str,
    dep_date: str,
    trip_type: str = "outbound",
    return_date: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Flatten a SerpApi flight group into a display dict.

    trip_type: 'outbound' | 'return' | 'roundtrip'
    For 'roundtrip', SerpApi type=1 returns the outbound leg + combined price only.
    Return leg details are not included in the initial response.
    """
    flights = flight_group.get("flights", [])
    if not flights:
        return None

    first_seg = flights[0]
    last_seg  = flights[-1]

    # Times are formatted as "YYYY-MM-DD HH:MM" (space separator)
    dep_at = first_seg.get("departure_airport", {}).get("time", "")
    arr_at = last_seg.get("arrival_airport", {}).get("time", "")

    dep_time = dep_at[11:16] if len(dep_at) >= 16 else dep_at
    arr_time = arr_at[11:16] if len(arr_at) >= 16 else arr_at
    arr_date = arr_at[:10]   if len(arr_at) >= 10 else ""

    # Collect unique airline names across all segments (SerpApi provides full names)
    seen_airlines: List[str] = []
    seen_set: set = set()
    for seg in flights:
        airline = seg.get("airline", "")
        if airline and airline not in seen_set:
            seen_airlines.append(airline)
            seen_set.add(airline)
    airline_str = " / ".join(seen_airlines)

    layovers  = flight_group.get("layovers", [])
    stops     = len(layovers)
    stops_str = "Direct" if stops == 0 else f"{stops} stop{'s' if stops > 1 else ''}"
    via_str   = _format_layovers(layovers)

    total_dur = flight_group.get("total_duration", 0)
    duration  = _format_minutes(total_dur) if total_dur else ""

    price_raw = float(flight_group.get("price", 0))
    price_str = f"{price_raw:,.0f}"

    # Airport codes for the Google Flights deep link
    origin_code   = first_seg.get("departure_airport", {}).get("id", ORIGIN)
    dest_code_act = last_seg.get("arrival_airport", {}).get("id", dest_code)

    return {
        "trip_type":      trip_type,
        "destination":    dest_name,
        "dest_code":      dest_code,
        "departure_date": dep_date,
        "airline":        airline_str,
        "dep_time":       dep_time,
        "arr_time":       arr_time,
        "arr_date":       arr_date,
        "duration":       duration,
        "stops":          stops_str,
        "via":            via_str,
        "price_str":      price_str,
        "price_raw":      price_raw,
        "currency":       CURRENCY,
        "return_date":    return_date or "",
        "book_url":       (
                              flight_group.get("_book_url")
                              or google_flights_url(origin_code, dest_code_act, dep_date, ADULTS)
                          ),
    }


# ---------------------------------------------------------------------------
# Time-of-day filter
# ---------------------------------------------------------------------------

def _too_early(flight: Dict[str, Any]) -> bool:
    """Return True if this flight should be excluded due to the earliest-departure filter."""
    if not EARLIEST_DEP_DATE or not EARLIEST_DEP_TIME:
        return False
    if flight["departure_date"] != EARLIEST_DEP_DATE:
        return False
    return flight["dep_time"] < EARLIEST_DEP_TIME  # lexicographic HH:MM comparison


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_all_flights(
    dep_dates: List[str],
    ret_dates: List[str],
    trip_types: List[str],
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """Search all destination × date × trip-type combinations.

    Returns a nested dict:  results[trip_type][dest_name] = [flight, ...]
    """
    results: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        tt: {name: [] for name in DESTINATIONS}
        for tt in trip_types
    }

    for dest_name, dest_code in DESTINATIONS.items():

        if "outbound" in trip_types:
            for date in dep_dates:
                print(f"  [outbound]  {ORIGIN} -> {dest_code}  on  {date}", file=sys.stderr)
                try:
                    for fg in search_flights(ORIGIN, dest_code, date):
                        parsed = parse_offer(fg, dest_name, dest_code, date, "outbound")
                        if parsed and not _too_early(parsed):
                            results["outbound"][dest_name].append(parsed)
                except Exception as exc:
                    print(f"    Warning: {exc}", file=sys.stderr)

        if "return" in trip_types:
            for date in ret_dates:
                print(f"  [return]    {dest_code} -> {ORIGIN}  on  {date}", file=sys.stderr)
                try:
                    for fg in search_flights(dest_code, ORIGIN, date):
                        parsed = parse_offer(fg, dest_name, dest_code, date, "return")
                        if parsed:
                            results["return"][dest_name].append(parsed)
                except Exception as exc:
                    print(f"    Warning: {exc}", file=sys.stderr)

        if "roundtrip" in trip_types:
            for dep in dep_dates:
                for ret in ret_dates:
                    if ret <= dep:
                        continue   # return must be after departure
                    print(
                        f"  [roundtrip] {ORIGIN} <-> {dest_code}  {dep} / {ret}",
                        file=sys.stderr,
                    )
                    try:
                        for fg in search_flights(ORIGIN, dest_code, dep, ret):
                            parsed = parse_offer(
                                fg, dest_name, dest_code, dep, "roundtrip", ret
                            )
                            if parsed and not _too_early(parsed):
                                results["roundtrip"][dest_name].append(parsed)
                    except Exception as exc:
                        print(f"    Warning: {exc}", file=sys.stderr)

    return results


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_FLAG: Dict[str, str] = {
    "Japan (Tokyo)": "JP",
    "Japan (Osaka)": "JP",
    "Taiwan":        "TW",
}

_HEADER_COLOR = "#1a4f7a"
_ALT_ROW      = "#f2f7fc"


def _th(text: str) -> str:
    return (
        f'<th style="padding:8px 10px; background:{_HEADER_COLOR}; '
        f'color:#fff; text-align:left; white-space:nowrap;">{text}</th>'
    )


def _td(text: str, bold: bool = False) -> str:
    weight = "font-weight:bold;" if bold else ""
    return f'<td style="padding:7px 10px; {weight} white-space:nowrap;">{text}</td>'


def _td_link(url: str, label: str = "Search") -> str:
    return (
        f'<td style="padding:7px 10px; white-space:nowrap;">'
        f'<a href="{url}" target="_blank" '
        f'style="color:{_HEADER_COLOR}; font-weight:bold;">{label}</a></td>'
    )


def _next_day(dep_date: str, arr_date: str) -> str:
    """Return arrival time string, appending +1 badge when it lands the next day."""
    return '<sup style="color:#c0392b; font-size:9px; margin-left:2px;">+1</sup>' if arr_date and arr_date != dep_date else ""


def _arr_cell(dep_date: str, arr_time: str, arr_date: str) -> str:
    return arr_time + _next_day(dep_date, arr_date)


# ── Section renderers ────────────────────────────────────────────────────────

def _render_oneway_table(
    flights: List[Dict[str, Any]],
    dep_label: str,
    arr_label: str,
) -> str:
    """Render a table of one-way flights (outbound or return leg)."""
    sorted_f = sorted(flights, key=lambda f: (f["departure_date"], f["price_raw"]))
    rows: List[str] = []
    for i, f in enumerate(sorted_f):
        bg = _ALT_ROW if i % 2 == 0 else "#ffffff"
        rows.append(
            f'<tr style="background:{bg};">'
            + _td(f["departure_date"])
            + _td(f["airline"])
            + _td(f["dep_time"])
            + _td(_arr_cell(f["departure_date"], f["arr_time"], f["arr_date"]))
            + _td(f["duration"])
            + _td(f["stops"])
            + _td(f.get("via", "—"))
            + _td(f'{f["currency"]} {f["price_str"]}', bold=True)
            + _td_link(f["book_url"], "Search")
            + "</tr>"
        )
    header = (
        "<tr>"
        + _th("Dep. Date")
        + _th("Airline(s)")
        + _th(f"Departs ({dep_label})")
        + _th(f"Arrives ({arr_label})")
        + _th("Duration")
        + _th("Stops")
        + _th("Via")
        + _th(f"Price ({CURRENCY})")
        + _th("Book")
        + "</tr>"
    )
    return (
        f'<table cellpadding="0" cellspacing="0" border="0" '
        f'style="border-collapse:collapse; font-family:Arial,sans-serif; font-size:13px; '
        f'width:100%; max-width:1100px; border:1px solid #ccc;">'
        f"<thead>{header}</thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        f"</table>"
    )


def _render_roundtrip_table(flights: List[Dict[str, Any]]) -> str:
    """Render a table of round-trip flights.

    SerpApi type=1 returns the outbound leg details + combined total price.
    Return leg details are not included (use the Search link to see them).
    """
    sorted_f = sorted(
        flights, key=lambda f: (f["departure_date"], f.get("return_date", ""), f["price_raw"])
    )
    rows: List[str] = []
    for i, f in enumerate(sorted_f):
        bg = _ALT_ROW if i % 2 == 0 else "#ffffff"
        out_arr = _arr_cell(f["departure_date"], f["arr_time"], f["arr_date"])
        rows.append(
            f'<tr style="background:{bg};">'
            + _td(f["departure_date"])
            + _td(f.get("return_date", ""))
            + _td(f["airline"])
            + _td(f["dep_time"])
            + _td(out_arr)
            + _td(f["duration"])
            + _td(f["stops"])
            + _td(f.get("via", "—"))
            + _td(f'{f["currency"]} {f["price_str"]}', bold=True)
            + _td_link(f["book_url"], "Search")
            + "</tr>"
        )
    header = (
        "<tr>"
        + _th("Departs")
        + _th("Returns")
        + _th("Airline(s)")
        + _th("Dep. Time")
        + _th("Arr. Time")
        + _th("Outbound Duration")
        + _th("Stops")
        + _th("Via")
        + _th(f"Total Price ({CURRENCY})")
        + _th("Book")
        + "</tr>"
    )
    return (
        f'<table cellpadding="0" cellspacing="0" border="0" '
        f'style="border-collapse:collapse; font-family:Arial,sans-serif; font-size:13px; '
        f'width:100%; max-width:1100px; border:1px solid #ccc;">'
        f"<thead>{header}</thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        f"</table>"
    )


def _section_heading(flag: str, dest_name: str, route: str) -> str:
    return (
        f'<h3 style="color:{_HEADER_COLOR}; margin-top:28px; '
        f'border-bottom:2px solid {_HEADER_COLOR}; padding-bottom:4px;">'
        f'{flag} {dest_name}'
        f'<span style="font-size:13px; color:#666; font-weight:normal;"> ({route})</span>'
        f'</h3>'
    )


def render_trip_type_block(
    trip_type: str,
    dest_flights: Dict[str, List[Dict[str, Any]]],
) -> str:
    """Render the full HTML block for one trip type (outbound / return / roundtrip)."""
    labels = {
        "outbound":  ("Outbound Flights", f"{ORIGIN} → Asia"),
        "return":    ("Return Flights",    f"Asia → {ORIGIN}"),
        "roundtrip": ("Round Trip Flights", f"{ORIGIN} ↔ Asia (total price, outbound leg shown)"),
    }
    title, subtitle = labels.get(trip_type, (trip_type.title(), ""))

    sections: List[str] = []
    for dest_name, dest_code in DESTINATIONS.items():
        flights = dest_flights.get(dest_name, [])
        flag = _FLAG.get(dest_name, "")

        if trip_type in ("outbound", "return"):
            dep_label = ORIGIN if trip_type == "outbound" else dest_code
            arr_label = dest_code if trip_type == "outbound" else ORIGIN
            route = f"{dep_label} → {arr_label}"
        else:
            route = f"{ORIGIN} ↔ {dest_code}"

        heading = _section_heading(flag, dest_name, route)

        if not flights:
            sections.append(
                heading
                + "<p style='color:#888; font-style:italic; margin-top:4px;'>"
                "No flights found.</p>"
            )
            continue

        if trip_type == "roundtrip":
            table = _render_roundtrip_table(flights)
        else:
            dep_label = ORIGIN if trip_type == "outbound" else dest_code
            arr_label = dest_code if trip_type == "outbound" else ORIGIN
            table = _render_oneway_table(flights, dep_label, arr_label)

        sections.append(heading + table)

    return (
        f'<h2 style="color:{_HEADER_COLOR}; margin-top:36px;">'
        f'{title} <span style="font-size:14px; color:#666; font-weight:normal;">({subtitle})</span>'
        f'</h2>'
        + "\n".join(sections)
    )


def render_summary_table(
    results: Dict[str, Dict[str, List[Dict[str, Any]]]],
    dep_dates: List[str],
    trip_types: List[str],
) -> str:
    """Cheapest outbound flight per destination per departure date."""
    outbound = results.get("outbound", {})
    rows: List[str] = []

    for date in dep_dates:
        first = True
        for dest_name, dest_code in DESTINATIONS.items():
            dest_flights = [f for f in outbound.get(dest_name, []) if f["departure_date"] == date]
            if not dest_flights:
                continue
            cheapest = min(dest_flights, key=lambda f: f["price_raw"])
            bg = _ALT_ROW if first else "#ffffff"
            first = False
            rows.append(
                f'<tr style="background:{bg};">'
                + _td(date)
                + _td(f'{_FLAG.get(dest_name, "")} {dest_name}')
                + _td(cheapest["airline"])
                + _td(cheapest["dep_time"])
                + _td(_arr_cell(cheapest["departure_date"], cheapest["arr_time"], cheapest["arr_date"]))
                + _td(cheapest["duration"])
                + _td(cheapest["stops"])
                + _td(cheapest.get("via", "—"))
                + _td(f'{cheapest["currency"]} {cheapest["price_str"]}', bold=True)
                + _td_link(cheapest["book_url"], "Search")
                + "</tr>"
            )

    if not rows:
        return "<p style='color:#888;'>No outbound flight data found.</p>"

    header = (
        "<tr>"
        + _th("Departure Date")
        + _th("Destination")
        + _th("Airline(s)")
        + _th(f"Departs ({ORIGIN})")
        + _th("Arrives")
        + _th("Duration")
        + _th("Stops")
        + _th("Via")
        + _th(f"Best Price ({CURRENCY})")
        + _th("Book")
        + "</tr>"
    )
    return f"""
<h3 style="color:{_HEADER_COLOR}; margin-top:0;">
  Cheapest Outbound Flight Per Destination
</h3>
<table cellpadding="0" cellspacing="0" border="0"
       style="border-collapse:collapse; font-family:Arial,sans-serif; font-size:13px;
              width:100%; max-width:1100px; border:1px solid #ccc;">
  <thead>{header}</thead>
  <tbody>{''.join(rows)}</tbody>
</table>
"""


def render_html_body(
    results: Dict[str, Dict[str, List[Dict[str, Any]]]],
    dep_dates: List[str],
    ret_dates: List[str],
    trip_types: List[str],
    today: str,
) -> str:
    """Assemble the full HTML email."""
    total = sum(
        len(flights)
        for tt_dict in results.values()
        for flights in tt_dict.values()
    )
    dep_str = ", ".join(dep_dates)
    ret_str = ", ".join(ret_dates) if ret_dates else "N/A"

    summary_html = render_summary_table(results, dep_dates, trip_types)

    trip_blocks = "\n<hr style='border:none; border-top:1px solid #ddd; margin:32px 0;'>\n".join(
        render_trip_type_block(tt, results.get(tt, {}))
        for tt in trip_types
    )

    return f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif; color:#222; max-width:1100px;
             margin:auto; padding:20px; font-size:14px;">

  <h2 style="color:{_HEADER_COLOR}; margin-bottom:4px;">
    Flight Price Report: Toronto &harr; Asia
  </h2>
  <p style="color:#555; margin-top:0;">
    <strong>Report date:</strong> {today} &nbsp;|&nbsp;
    <strong>Passengers:</strong> {ADULTS} adult{'s' if ADULTS != 1 else ''}
  </p>
  <p style="color:#555;">
    <strong>Outbound dates:</strong> {dep_str}<br>
    <strong>Return dates:</strong> {ret_str}<br>
    <strong>Trip types:</strong> {', '.join(trip_types)}<br>
    <strong>Total options found:</strong> {total}
  </p>

  <hr style="border:none; border-top:1px solid #ddd; margin:20px 0;">

  {summary_html}

  <hr style="border:none; border-top:1px solid #ddd; margin:32px 0;">

  {trip_blocks}

  <p style="font-size:11px; color:#aaa; margin-top:32px;">
    Data source: SerpApi Google Flights.
    Prices are per person, economy class, and are approximate &ndash; confirm at booking.
    Google Flights links open a search for that route and date; final price may differ.
    Round-trip rows show the outbound leg; click Search to see full round-trip details.
    Report generated: {today}.
  </p>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Email sending – copied directly from honda_passport pattern
# ---------------------------------------------------------------------------

def send_email(subject: str, html_body: str) -> None:
    """Send an HTML email using SMTP_* environment settings."""
    if not all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_FROM, EMAIL_TO]):
        raise RuntimeError("SMTP configuration is incomplete; check environment variables.")

    msg = EmailMessage()
    msg["From"]    = EMAIL_FROM
    msg["To"]      = ", ".join(EMAIL_TO)
    msg["Subject"] = subject
    msg.set_content("HTML report attached. Please view this email in an HTML-capable client.")
    msg.add_alternative(html_body, subtype="html")

    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> int:
    today      = datetime.now().strftime("%Y-%m-%d")
    dep_dates  = get_departure_dates()
    ret_dates  = get_return_dates()
    trip_types = get_active_trip_types()

    # Drop roundtrip / return if no return dates are configured
    if not ret_dates:
        trip_types = [t for t in trip_types if t == "outbound"]
        if not trip_types:
            trip_types = ["outbound"]

    print(f"Flight Finder  |  report date: {today}", file=sys.stderr)
    print(f"Trip types:      {', '.join(trip_types)}", file=sys.stderr)
    print(f"Departure dates: {', '.join(dep_dates)}", file=sys.stderr)
    if ret_dates:
        print(f"Return dates:    {', '.join(ret_dates)}", file=sys.stderr)

    # ── Fetch flight data ───────────────────────────────────────────────────
    try:
        results = fetch_all_flights(dep_dates, ret_dates, trip_types)
    except Exception as exc:
        error_html = f"<p><strong>Error fetching flight data:</strong> {exc}</p>"
        try:
            send_email(
                subject=f"[Flight Report] ERROR – data fetch failed ({today})",
                html_body=error_html,
            )
        except Exception as email_err:
            print(f"Failed to send error email: {email_err}", file=sys.stderr)
        return 1

    # ── Build and send the report ───────────────────────────────────────────
    total = sum(
        len(flights)
        for tt_dict in results.values()
        for flights in tt_dict.values()
    )
    html    = render_html_body(results, dep_dates, ret_dates, trip_types, today)
    subject = (
        f"[Flight Report] Toronto <-> Asia | "
        f"dep {dep_dates[0]}–{dep_dates[-1]} | "
        f"{total} options ({today})"
    )

    try:
        send_email(subject=subject, html_body=html)
        print(f"Email sent.  {total} flight options included.", file=sys.stderr)
    except Exception as exc:
        print(f"Failed to send report email: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
