import copy
import json

import pytest
from scrapy import Request
from scrapy.http import TextResponse

from scrapper.spiders.pinnacle import PinnacleSpider
from scrapper.spiders.stake import StakeSpider, _parse_kambi_events


def _response(url: str, body: str) -> TextResponse:
    request = Request(url)
    return TextResponse(url, body=body.encode(), encoding="utf-8", request=request)


async def _collect_async(async_iterable):
    return [item async for item in async_iterable]


# ── Stake spider tests (Kambi events-by-path.json schema) ──

_KAMBI_TENNIS_EVENT = {
    "id": 123456789,
    "sport_name": "tennis",
    "tournament_name": "ATP Tour. Mallorca",
    "date_start": "2026-06-25T10:00:00Z",
    "outright": False,
    "teams": {"home": "Jack Draper", "away": "Ugo Humbert"},
    "main_odds": {
        "main": {
            "odd1": {
                "team_name": "Jack Draper",
                "odd_value": 1.80,
                "filter_id": 1,
                "team_side": 1,
            },
            "odd2": {
                "team_name": "Ugo Humbert",
                "odd_value": 2.00,
                "filter_id": 1,
                "team_side": 2,
            },
        }
    },
}


def test_stake_parse_kambi_extracts_moneyline_odds():
    """_parse_kambi_events extracts moneyline odds from Kambi JSON."""
    data = {"events": [_KAMBI_TENNIS_EVENT]}
    items = _parse_kambi_events(data, limit=10)

    assert len(items) == 1
    assert items[0]["player_a"] == "Jack Draper"
    assert items[0]["player_b"] == "Ugo Humbert"
    assert items[0]["odds_a"] == 1.80
    assert items[0]["odds_b"] == 2.00
    assert items[0]["tournament"] == "ATP Tour. Mallorca"
    assert items[0]["surface"] in ("clay", "grass", "hard", "carpet")
    # commence_time must be full ISO datetime, match_date date-only
    assert items[0]["commence_time"] == "2026-06-25T10:00:00Z", (
        "commence_time must be full ISO from date_start"
    )
    assert items[0]["match_date"] == "2026-06-25", "match_date must be date-only ([:10])"


def test_stake_parse_kambi_skips_non_tennis():
    """Events with sport_name != 'tennis' are skipped."""
    event = copy.deepcopy(_KAMBI_TENNIS_EVENT)
    event["sport_name"] = "soccer"
    data = {"events": [event]}
    items = _parse_kambi_events(data, limit=10)
    assert len(items) == 0


def test_stake_parse_kambi_skips_outright():
    """Outright (tournament winner) events are skipped."""
    event = copy.deepcopy(_KAMBI_TENNIS_EVENT)
    event["outright"] = True
    data = {"events": [event]}
    items = _parse_kambi_events(data, limit=10)
    assert len(items) == 0


def test_stake_parse_kambi_skips_handicap_filter():
    """Odds with filter_id != 1 (handicaps, totals, etc.) are excluded."""
    event = copy.deepcopy(_KAMBI_TENNIS_EVENT)
    # Replace moneyline odds with handicap odds (filter_id=3)
    event["main_odds"]["main"] = {
        "odd1": {"team_name": "Jack Draper", "odd_value": 1.90, "filter_id": 3, "team_side": 1},
        "odd2": {"team_name": "Ugo Humbert", "odd_value": 1.90, "filter_id": 3, "team_side": 2},
    }
    data = {"events": [event]}
    items = _parse_kambi_events(data, limit=10)
    assert len(items) == 0


def test_stake_parse_kambi_respects_limit():
    """Only returns up to `limit` items."""
    events = []
    for i in range(20):
        e = copy.deepcopy(_KAMBI_TENNIS_EVENT)
        e["id"] = 1000 + i
        events.append(e)
    data = {"events": events}
    items = _parse_kambi_events(data, limit=5)
    assert len(items) == 5


def test_stake_spider_has_start_method():
    """StakeSpider exposes start() for standalone Playwright extraction."""
    spider = StakeSpider()
    assert hasattr(spider, "start"), "StakeSpider must expose start()"
    import inspect

    assert inspect.ismethod(spider.start) or inspect.iscoroutinefunction(spider.start), (
        "start() must be callable"
    )


def test_stake_parse_kambi_handles_empty_data():
    """Gracefully handles empty/malformed data."""
    assert _parse_kambi_events({}, limit=10) == []
    assert _parse_kambi_events({"events": []}, limit=10) == []
    assert _parse_kambi_events({"events": None}, limit=10) == []
    assert _parse_kambi_events({"events": [{"sport_name": "tennis"}]}, limit=10) == []


# ── Pinnacle spider tests (unchanged) ──


@pytest.mark.asyncio
async def test_pinnacle_parse_yields_items_from_inline_json():
    spider = PinnacleSpider()
    payload = {
        "events": [
            {
                "name": "Test Open",
                "participants": [{"name": "Player One"}, {"name": "Player Two"}],
                "markets": [
                    {
                        "outcomes": [
                            {"name": "Player One", "price": 1.9},
                            {"name": "Player Two", "price": 2.0},
                        ]
                    }
                ],
            }
        ]
    }
    html = f"<html><script>window.__DATA__ = {json.dumps(payload)};</script></html>"
    response = _response("https://www.pinnacle.com/en/tennis", html)

    items = await _collect_async(spider.parse(response))

    assert len(items) == 1
    assert items[0]["player_a"] == "Player One"
    assert items[0]["player_b"] == "Player Two"
    assert items[0]["odds_a"] == 1.9
    assert items[0]["odds_b"] == 2.0


def test_pinnacle_rejects_handicap_outcome_names():
    """Handicap names like 'Djokovic +2.5' should not match player 'Djokovic'."""
    from scrapper.spiders.pinnacle import _match_odds_to_player

    odds_map = {
        "Djokovic +2.5": 1.90,
        "Alcaraz -2.5": 1.95,
        "Djokovic": 1.80,
        "Alcaraz": 2.00,
    }
    # Should match the clean name, not the handicap line
    result = _match_odds_to_player("Djokovic", odds_map)
    assert result == 1.80, f"Expected 1.80 (clean), got {result}"

    # "Djokovic" alone should NOT match "Djokovic +2.5"
    odds_map_no_clean = {"Djokovic +2.5": 1.90, "Alcaraz -2.5": 1.95}
    result2 = _match_odds_to_player("Djokovic", odds_map_no_clean)
    assert result2 == 0.0, f"Handicap should not match, got {result2}"


def test_pinnacle_skips_total_games_markets():
    """Markets named 'Total Games' should not yield items."""
    spider = PinnacleSpider()
    payload = {
        "events": [
            {
                "name": "Test Open",
                "participants": [{"name": "Player One"}, {"name": "Player Two"}],
                "markets": [
                    {
                        "name": "Total Games",
                        "outcomes": [
                            {"name": "Over 22.5", "price": 1.90},
                            {"name": "Under 22.5", "price": 1.90},
                        ],
                    }
                ],
            }
        ]
    }
    html = f"<html><script>window.__DATA__ = {json.dumps(payload)};</script></html>"
    response = _response("https://www.pinnacle.com/en/tennis", html)

    import asyncio

    items = asyncio.run(_collect_async(spider.parse(response)))

    # Should NOT yield moneyline items from Total Games market
    assert len(items) == 0, f"Total Games should be skipped, got {len(items)} items"
