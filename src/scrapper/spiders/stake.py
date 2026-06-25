"""
Spider para Stake.com.co — odds de tenis vía widget Kambi (websbkt.com).

Usa Playwright standalone (no scrapy-playwright) porque el widget Kambi
no carga correctamente bajo scrapy-playwright y `page.route()` rompe la
inicialización del widget.

Uso:
  scrapy crawl stake -a sport=tennis -a limit=30 -o odds.json
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

import scrapy
from dotenv import load_dotenv

from ..items import OddsItem

# ── Configuración ────────────────────────────────────
_env_path = Path.home() / "dev/personal/scraper/.env"
load_dotenv(_env_path)

BOGOTA_GEO = {"latitude": 4.7110, "longitude": -74.0721}
TENNIS_URL = "https://stake.com.co/deportes/tennis"

SURFACE_KEYWORDS = {
    "clay": ["clay", "tierra", "arcilla"],
    "grass": ["grass", "cesped", "césped", "hierba", "lawn"],
    "hard": ["hard", "dura", "duro", "cemento", "concrete"],
    "carpet": ["carpet", "moqueta", "sintetica", "sintética"],
}


def _detect_surface(text: str) -> str:
    combined = text.lower()
    for surface, keywords in SURFACE_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return surface
    return "hard"


# ── Extracción vía Playwright standalone ─────────────


async def _extract_tennis_odds_standalone(limit: int = 30) -> list[dict]:
    """
    Navega a /deportes/tennis con Playwright standalone.
    Captura events-by-path.json vía response listener PASIVO.
    """
    from playwright.async_api import async_playwright

    results = []
    events_data = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="es-CO",
            timezone_id="America/Bogota",
            geolocation=BOGOTA_GEO,
        )
        page = await context.new_page()

        async def _on_response(response):
            url = response.url
            if "events-by-path" in url and "tennis" in url:
                try:
                    body = await response.text()
                    events_data.append(json.loads(body))
                except (json.JSONDecodeError, Exception):
                    pass

        page.on("response", _on_response)

        await page.goto(TENNIS_URL, wait_until="domcontentloaded", timeout=60000)

        for _ in range(15):
            await page.wait_for_timeout(2000)
            if events_data:
                break

        if events_data:
            results = _parse_kambi_events(events_data[0], limit)

        await browser.close()

    return results


def _parse_kambi_events(data: dict, limit: int = 30) -> list[dict]:
    """
    Parsea events-by-path.json → dicts con odds moneyline.

    Estructura de events-by-path.json:
      {events: [{
        id, sport_name, tournament_name, date_start, outright,
        teams: {home, away},
        main_odds: {main: {oddId: {team_name, odd_value, filter_id, team_side}}}
      }]}
    """
    items = []
    events_list = data.get("events", [])
    if not isinstance(events_list, list):
        return items

    for evt in events_list:
        if not isinstance(evt, dict):
            continue
        if evt.get("sport_name") != "tennis":
            continue
        if evt.get("outright"):
            continue

        player_a = (evt.get("teams") or {}).get("home", "").strip()
        player_b = (evt.get("teams") or {}).get("away", "").strip()
        if not player_a or not player_b:
            continue

        main_odds = (evt.get("main_odds") or {}).get("main", {})
        if not isinstance(main_odds, dict):
            continue

        odds_a = None
        odds_b = None
        for odd in main_odds.values():
            if not isinstance(odd, dict):
                continue
            if odd.get("filter_id") != 1:
                continue
            value = odd.get("odd_value")
            if value is None:
                continue
            side = odd.get("team_side")
            if side == 1:
                odds_a = float(value)
            elif side == 2:
                odds_b = float(value)

        if odds_a is None or odds_b is None:
            continue

        tournament = evt.get("tournament_name", "unknown")
        match_date = (evt.get("date_start") or "")[:10] or datetime.now().strftime("%Y-%m-%d")
        surface = _detect_surface(f"{tournament} {player_a} {player_b}")
        event_id = str(evt.get("id", ""))

        items.append(
            {
                "event_id": event_id,
                "player_a": player_a,
                "player_b": player_b,
                "odds_a": odds_a,
                "odds_b": odds_b,
                "tournament": str(tournament),
                "match_date": match_date,
                "surface": surface,
            }
        )

        if len(items) >= limit:
            break

    return items


# ── Spider ────────────────────────────────────────────


class StakeSpider(scrapy.Spider):
    name = "stake"
    site = "stake"

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 4,
        "ROBOTSTXT_OBEY": False,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sport = getattr(self, "sport", "tennis")
        self.league = getattr(self, "league", None)
        self.limit = int(getattr(self, "limit", "30"))
        self.region = getattr(self, "region", "colombia")
        self.logger.info(
            "Stake spider: sport=%s limit=%d region=%s",
            self.sport,
            self.limit,
            self.region,
        )

    async def start(self):
        """Ejecuta extracción vía Playwright standalone."""
        self.logger.info("Starting Playwright standalone extraction...")
        raw_items = await _extract_tennis_odds_standalone(limit=self.limit)
        self.logger.info("Extracted %d raw items", len(raw_items))

        for ri in raw_items:
            match_slug = (
                f"{ri['player_a'].lower().replace(' ', '-')}"
                f"-vs-{ri['player_b'].lower().replace(' ', '-')}"
                f"-{ri['match_date']}"
            )
            yield OddsItem(
                site=f"stake_{self.region}",
                sport=self.sport,
                league=self.league or "unknown",
                tournament=ri["tournament"],
                match_date=ri["match_date"],
                title=f"{ri['player_a']} vs {ri['player_b']}",
                player_a=ri["player_a"],
                player_b=ri["player_b"],
                odds_a=ri["odds_a"],
                odds_b=ri["odds_b"],
                surface=ri["surface"],
                market_type="moneyline",
                url=f"{TENNIS_URL}#match={match_slug}",
                metadata={
                    "region": self.region,
                    "scraped_via": "kambi_events_by_path",
                    "event_id": ri["event_id"],
                },
            )
