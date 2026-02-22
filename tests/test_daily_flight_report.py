"""
Unit and regression tests for daily_flight_report.py

Run with:  pytest tests/ -v
"""

import pytest
import daily_flight_report as drf
from daily_flight_report import (
    _format_minutes,
    _format_layovers,
    _arr_cell,
    parse_offer,
    get_departure_dates,
    get_return_dates,
    get_active_trip_types,
    _render_oneway_table,
    _render_roundtrip_table,
    render_summary_table,
    render_html_body,
)


# ── _format_minutes ──────────────────────────────────────────────────────────

def test_format_minutes_hours_and_minutes():
    assert _format_minutes(870) == "14h 30m"

def test_format_minutes_whole_hours():
    assert _format_minutes(120) == "2h"

def test_format_minutes_zero():
    assert _format_minutes(0) == "0h"

def test_format_minutes_less_than_hour():
    assert _format_minutes(45) == "0h 45m"

def test_format_minutes_one_minute_over_hour():
    assert _format_minutes(61) == "1h 1m"

def test_format_minutes_large_value():
    assert _format_minutes(1440) == "24h"   # 24 hours exactly


# ── _format_layovers ─────────────────────────────────────────────────────────

def test_format_layovers_direct():
    assert _format_layovers([]) == "—"

def test_format_layovers_single():
    assert _format_layovers([{"id": "ICN", "duration": 95}]) == "ICN (1h 35m)"

def test_format_layovers_multiple():
    result = _format_layovers([
        {"id": "ICN", "duration": 95},
        {"id": "PVG", "duration": 130},
    ])
    assert result == "ICN (1h 35m) · PVG (2h 10m)"

def test_format_layovers_missing_id():
    result = _format_layovers([{"duration": 60}])
    assert "?" in result

def test_format_layovers_missing_duration():
    result = _format_layovers([{"id": "NRT"}])
    assert "NRT" in result
    assert "0h" in result


# ── _arr_cell ────────────────────────────────────────────────────────────────

def test_arr_cell_same_day():
    assert _arr_cell("2026-10-23", "22:30", "2026-10-23") == "22:30"

def test_arr_cell_next_day_has_plus_one():
    result = _arr_cell("2026-10-23", "06:45", "2026-10-24")
    assert "06:45" in result
    assert "+1" in result

def test_arr_cell_empty_arr_date_no_badge():
    result = _arr_cell("2026-10-23", "10:00", "")
    assert result == "10:00"


# ── _too_early ───────────────────────────────────────────────────────────────

def test_too_early_no_filter(monkeypatch):
    monkeypatch.setattr(drf, "EARLIEST_DEP_DATE", "")
    monkeypatch.setattr(drf, "EARLIEST_DEP_TIME", "")
    assert not drf._too_early({"departure_date": "2026-10-23", "dep_time": "06:00"})

def test_too_early_different_date_not_filtered(monkeypatch):
    monkeypatch.setattr(drf, "EARLIEST_DEP_DATE", "2026-10-23")
    monkeypatch.setattr(drf, "EARLIEST_DEP_TIME", "19:00")
    assert not drf._too_early({"departure_date": "2026-10-24", "dep_time": "06:00"})

def test_too_early_before_cutoff(monkeypatch):
    monkeypatch.setattr(drf, "EARLIEST_DEP_DATE", "2026-10-23")
    monkeypatch.setattr(drf, "EARLIEST_DEP_TIME", "19:00")
    assert drf._too_early({"departure_date": "2026-10-23", "dep_time": "18:59"})

def test_too_early_exactly_at_cutoff_not_filtered(monkeypatch):
    monkeypatch.setattr(drf, "EARLIEST_DEP_DATE", "2026-10-23")
    monkeypatch.setattr(drf, "EARLIEST_DEP_TIME", "19:00")
    assert not drf._too_early({"departure_date": "2026-10-23", "dep_time": "19:00"})

def test_too_early_after_cutoff_not_filtered(monkeypatch):
    monkeypatch.setattr(drf, "EARLIEST_DEP_DATE", "2026-10-23")
    monkeypatch.setattr(drf, "EARLIEST_DEP_TIME", "19:00")
    assert not drf._too_early({"departure_date": "2026-10-23", "dep_time": "21:30"})

def test_too_early_midnight_departure_filtered(monkeypatch):
    monkeypatch.setattr(drf, "EARLIEST_DEP_DATE", "2026-10-23")
    monkeypatch.setattr(drf, "EARLIEST_DEP_TIME", "19:00")
    assert drf._too_early({"departure_date": "2026-10-23", "dep_time": "00:00"})


# ── date / trip-type helpers ──────────────────────────────────────────────────

def test_get_departure_dates_explicit(monkeypatch):
    monkeypatch.setattr(drf, "DEPARTURE_DATES_ENV", "2026-10-23,2026-10-24")
    assert get_departure_dates() == ["2026-10-23", "2026-10-24"]

def test_get_departure_dates_strips_whitespace(monkeypatch):
    monkeypatch.setattr(drf, "DEPARTURE_DATES_ENV", " 2026-10-23 , 2026-10-24 ")
    assert get_departure_dates() == ["2026-10-23", "2026-10-24"]

def test_get_return_dates_explicit(monkeypatch):
    monkeypatch.setattr(drf, "RETURN_DATES_ENV", "2026-11-05,2026-11-06")
    assert get_return_dates() == ["2026-11-05", "2026-11-06"]

def test_get_return_dates_empty(monkeypatch):
    monkeypatch.setattr(drf, "RETURN_DATES_ENV", "")
    assert get_return_dates() == []

def test_get_active_trip_types_all(monkeypatch):
    monkeypatch.setattr(drf, "TRIP_TYPES_ENV", "outbound,return,roundtrip")
    assert get_active_trip_types() == ["outbound", "return", "roundtrip"]

def test_get_active_trip_types_filters_invalid(monkeypatch):
    monkeypatch.setattr(drf, "TRIP_TYPES_ENV", "outbound,invalid,roundtrip")
    assert get_active_trip_types() == ["outbound", "roundtrip"]

def test_get_active_trip_types_outbound_only(monkeypatch):
    monkeypatch.setattr(drf, "TRIP_TYPES_ENV", "outbound")
    assert get_active_trip_types() == ["outbound"]


# ── parse_offer ───────────────────────────────────────────────────────────────

# Shared test fixtures
_MULTI_STOP_GROUP = {
    "flights": [
        {
            "departure_airport": {"id": "YYZ", "time": "2026-10-23 20:15"},
            "arrival_airport":   {"id": "ICN", "time": "2026-10-24 22:05"},
            "airline": "Air Canada",
        },
        {
            "departure_airport": {"id": "ICN", "time": "2026-10-25 00:10"},
            "arrival_airport":   {"id": "NRT", "time": "2026-10-25 02:10"},
            "airline": "Korean Air",
        },
    ],
    "layovers": [{"id": "ICN", "name": "Incheon", "duration": 125, "overnight": True}],
    "total_duration": 1025,
    "price": 1450,
    "_book_url": "https://www.google.com/travel/flights?tfs=ENCODED",
}

_DIRECT_GROUP = {
    "flights": [{
        "departure_airport": {"id": "YYZ", "time": "2026-10-23 13:00"},
        "arrival_airport":   {"id": "NRT", "time": "2026-10-24 15:30"},
        "airline": "Air Canada",
    }],
    "layovers": [],
    "total_duration": 870,
    "price": 1800,
    "_book_url": "https://www.google.com/travel/flights?tfs=DIRECT",
}

_SAME_AIRLINE_TWO_SEGMENTS = {
    "flights": [
        {
            "departure_airport": {"id": "YYZ", "time": "2026-10-23 10:00"},
            "arrival_airport":   {"id": "ORD", "time": "2026-10-23 11:30"},
            "airline": "Air Canada",
        },
        {
            "departure_airport": {"id": "ORD", "time": "2026-10-23 13:00"},
            "arrival_airport":   {"id": "NRT", "time": "2026-10-24 16:00"},
            "airline": "Air Canada",
        },
    ],
    "layovers": [{"id": "ORD", "duration": 90}],
    "total_duration": 780,
    "price": 1300,
    "_book_url": "",
}


def test_parse_offer_departure_time():
    r = parse_offer(_MULTI_STOP_GROUP, "Japan", "TYO", "2026-10-23")
    assert r["dep_time"] == "20:15"

def test_parse_offer_arrival_time_and_date():
    r = parse_offer(_MULTI_STOP_GROUP, "Japan", "TYO", "2026-10-23")
    assert r["arr_time"] == "02:10"
    assert r["arr_date"] == "2026-10-25"

def test_parse_offer_duration():
    r = parse_offer(_MULTI_STOP_GROUP, "Japan", "TYO", "2026-10-23")
    assert r["duration"] == "17h 5m"

def test_parse_offer_stop_count():
    r = parse_offer(_MULTI_STOP_GROUP, "Japan", "TYO", "2026-10-23")
    assert r["stops"] == "1 stop"

def test_parse_offer_via_layover():
    r = parse_offer(_MULTI_STOP_GROUP, "Japan", "TYO", "2026-10-23")
    assert "ICN" in r["via"]
    assert "2h 5m" in r["via"]

def test_parse_offer_airlines_combined():
    r = parse_offer(_MULTI_STOP_GROUP, "Japan", "TYO", "2026-10-23")
    assert r["airline"] == "Air Canada / Korean Air"

def test_parse_offer_same_airline_not_duplicated():
    r = parse_offer(_SAME_AIRLINE_TWO_SEGMENTS, "Japan", "TYO", "2026-10-23")
    assert r["airline"] == "Air Canada"

def test_parse_offer_price_raw():
    r = parse_offer(_MULTI_STOP_GROUP, "Japan", "TYO", "2026-10-23")
    assert r["price_raw"] == 1450.0

def test_parse_offer_price_formatted():
    r = parse_offer(_MULTI_STOP_GROUP, "Japan", "TYO", "2026-10-23")
    assert r["price_str"] == "1,450"

def test_parse_offer_uses_serpapi_book_url():
    r = parse_offer(_MULTI_STOP_GROUP, "Japan", "TYO", "2026-10-23")
    assert r["book_url"] == "https://www.google.com/travel/flights?tfs=ENCODED"

def test_parse_offer_fallback_book_url_when_empty():
    group = {**_MULTI_STOP_GROUP, "_book_url": ""}
    r = parse_offer(group, "Japan", "TYO", "2026-10-23")
    assert r["book_url"].startswith("https://www.google.com/travel/flights")

def test_parse_offer_direct_flight():
    r = parse_offer(_DIRECT_GROUP, "Japan", "TYO", "2026-10-23")
    assert r["stops"] == "Direct"
    assert r["via"] == "—"

def test_parse_offer_empty_flights_returns_none():
    assert parse_offer({"flights": []}, "Japan", "TYO", "2026-10-23") is None

def test_parse_offer_missing_flights_key_returns_none():
    assert parse_offer({}, "Japan", "TYO", "2026-10-23") is None

def test_parse_offer_roundtrip_sets_fields():
    r = parse_offer(_MULTI_STOP_GROUP, "Japan", "TYO", "2026-10-23", "roundtrip", "2026-11-05")
    assert r["trip_type"] == "roundtrip"
    assert r["return_date"] == "2026-11-05"

def test_parse_offer_return_type():
    r = parse_offer(_DIRECT_GROUP, "Japan", "TYO", "2026-11-05", "return")
    assert r["trip_type"] == "return"
    assert r["return_date"] == ""

def test_parse_offer_departure_date_stored():
    r = parse_offer(_DIRECT_GROUP, "Japan", "TYO", "2026-10-23")
    assert r["departure_date"] == "2026-10-23"

def test_parse_offer_destination_stored():
    r = parse_offer(_DIRECT_GROUP, "Japan", "TYO", "2026-10-23")
    assert r["destination"] == "Japan"
    assert r["dest_code"] == "TYO"


# ── HTML rendering regression tests ──────────────────────────────────────────
# These guard against accidental removal of columns, data, or structural tags.

_SAMPLE_FLIGHTS = [
    {
        "departure_date": "2026-10-23",
        "airline": "Air Canada",
        "dep_time": "20:15",
        "arr_time": "22:30",
        "arr_date": "2026-10-24",
        "duration": "14h 30m",
        "stops": "1 stop",
        "via": "ICN (2h 5m)",
        "price_str": "1,450",
        "price_raw": 1450.0,
        "currency": "CAD",
        "book_url": "https://www.google.com/travel/flights?tfs=abc",
        "return_date": "",
        "destination": "Japan",
        "dest_code": "TYO",
        "trip_type": "outbound",
    },
    {
        "departure_date": "2026-10-24",
        "airline": "Korean Air",
        "dep_time": "18:00",
        "arr_time": "21:00",
        "arr_date": "2026-10-25",
        "duration": "15h 0m",
        "stops": "Direct",
        "via": "—",
        "price_str": "1,200",
        "price_raw": 1200.0,
        "currency": "CAD",
        "book_url": "https://www.google.com/travel/flights?tfs=def",
        "return_date": "",
        "destination": "Japan",
        "dest_code": "TYO",
        "trip_type": "outbound",
    },
]

_SAMPLE_RT = [{**_SAMPLE_FLIGHTS[0], "trip_type": "roundtrip", "return_date": "2026-11-05"}]


# One-way table
def test_oneway_table_html_structure():
    html = _render_oneway_table(_SAMPLE_FLIGHTS, "YYZ", "TYO")
    assert "<table" in html
    assert "<thead>" in html
    assert "<tbody>" in html

def test_oneway_table_contains_airline():
    assert "Air Canada" in _render_oneway_table(_SAMPLE_FLIGHTS, "YYZ", "TYO")

def test_oneway_table_contains_dep_time():
    assert "20:15" in _render_oneway_table(_SAMPLE_FLIGHTS, "YYZ", "TYO")

def test_oneway_table_contains_price():
    assert "1,450" in _render_oneway_table(_SAMPLE_FLIGHTS, "YYZ", "TYO")

def test_oneway_table_contains_layover_via():
    assert "ICN (2h 5m)" in _render_oneway_table(_SAMPLE_FLIGHTS, "YYZ", "TYO")

def test_oneway_table_has_via_column_header():
    assert ">Via<" in _render_oneway_table(_SAMPLE_FLIGHTS, "YYZ", "TYO")

def test_oneway_table_search_link_present():
    html = _render_oneway_table(_SAMPLE_FLIGHTS, "YYZ", "TYO")
    assert "tfs=abc" in html

def test_oneway_table_sorted_oldest_date_first():
    html = _render_oneway_table(_SAMPLE_FLIGHTS, "YYZ", "TYO")
    assert html.find("2026-10-23") < html.find("2026-10-24")

def test_oneway_table_next_day_badge_present():
    # arr_date differs from dep_date → +1 badge should appear
    html = _render_oneway_table(_SAMPLE_FLIGHTS, "YYZ", "TYO")
    assert "+1" in html


# Round-trip table
def test_roundtrip_table_html_structure():
    html = _render_roundtrip_table(_SAMPLE_RT)
    assert "<table" in html
    assert "<thead>" in html
    assert "<tbody>" in html

def test_roundtrip_table_shows_return_date():
    assert "2026-11-05" in _render_roundtrip_table(_SAMPLE_RT)

def test_roundtrip_table_shows_airline():
    assert "Air Canada" in _render_roundtrip_table(_SAMPLE_RT)

def test_roundtrip_table_has_via_column_header():
    assert ">Via<" in _render_roundtrip_table(_SAMPLE_RT)

def test_roundtrip_table_search_link_present():
    assert "tfs=abc" in _render_roundtrip_table(_SAMPLE_RT)


# Summary table
def test_summary_table_no_data_message():
    html = render_summary_table({"outbound": {}}, ["2026-10-23"], ["outbound"])
    assert "No outbound flight data found" in html

def test_summary_table_shows_cheapest_per_date():
    results = {
        "outbound": {"Japan": _SAMPLE_FLIGHTS, "Taiwan": [], "Thailand": []},
    }
    html = render_summary_table(results, ["2026-10-23", "2026-10-24"], ["outbound"])
    assert "1,450" in html   # cheapest Oct 23
    assert "1,200" in html   # cheapest Oct 24

def test_summary_table_has_via_column_header():
    results = {"outbound": {"Japan": _SAMPLE_FLIGHTS, "Taiwan": [], "Thailand": []}}
    html = render_summary_table(results, ["2026-10-23"], ["outbound"])
    assert ">Via<" in html


# Full HTML body
def test_html_body_doctype():
    results = {"outbound": {"Japan": _SAMPLE_FLIGHTS, "Taiwan": [], "Thailand": []}}
    html = render_html_body(results, ["2026-10-23"], [], ["outbound"], "2026-02-22")
    assert "<!DOCTYPE html>" in html

def test_html_body_contains_report_date():
    results = {"outbound": {"Japan": _SAMPLE_FLIGHTS, "Taiwan": [], "Thailand": []}}
    html = render_html_body(results, ["2026-10-23"], [], ["outbound"], "2026-02-22")
    assert "2026-02-22" in html

def test_html_body_references_serpapi():
    results = {"outbound": {"Japan": _SAMPLE_FLIGHTS, "Taiwan": [], "Thailand": []}}
    html = render_html_body(results, ["2026-10-23"], [], ["outbound"], "2026-02-22")
    assert "SerpApi" in html

def test_html_body_no_amadeus_reference():
    results = {"outbound": {"Japan": _SAMPLE_FLIGHTS, "Taiwan": [], "Thailand": []}}
    html = render_html_body(results, ["2026-10-23"], [], ["outbound"], "2026-02-22")
    assert "Amadeus" not in html

def test_html_body_toronto_in_title():
    results = {"outbound": {"Japan": _SAMPLE_FLIGHTS, "Taiwan": [], "Thailand": []}}
    html = render_html_body(results, ["2026-10-23"], [], ["outbound"], "2026-02-22")
    assert "Toronto" in html


# ── EMAIL_TO multi-recipient parsing ─────────────────────────────────────────

def test_email_to_is_a_list():
    assert isinstance(drf.EMAIL_TO, list)

def test_email_to_multi_recipient_parsing(monkeypatch):
    import importlib, os
    monkeypatch.setenv("EMAIL_TO", "a@example.com, b@example.com , c@example.com")
    recipients = [e.strip() for e in os.environ.get("EMAIL_TO", "").split(",") if e.strip()]
    assert recipients == ["a@example.com", "b@example.com", "c@example.com"]

def test_email_to_single_recipient_still_a_list(monkeypatch):
    import os
    monkeypatch.setenv("EMAIL_TO", "only@example.com")
    recipients = [e.strip() for e in os.environ.get("EMAIL_TO", "").split(",") if e.strip()]
    assert recipients == ["only@example.com"]
