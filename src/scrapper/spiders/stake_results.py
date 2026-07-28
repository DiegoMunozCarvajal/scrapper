"""
Spider para Stake.com.co — resultados de tenis vía widget Kambi (websbkt.com).

NOTA: El widget Kambi en Stake SOLO sirve eventos próximos (odds activas).
NO incluye resultados/partidos finalizados. Los eventos sin odds (main_odds.main
vacío) son partidos suspendidos o sin betting abierto, no finalizados.

Para resultados reales, usar tennis_results_scraper.py (tennisexplorer.com).
Este spider es un esqueleto que extrae eventos sin odds — puede o no tener
información de ganador según cambios futuros del API Kambi.

NO modifica el spider stake.py — es un spider independiente.

Uso:
  scrapy crawl stake_results -a sport=tennis -o results.json
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

# ── Tournament → surface mapping ──────────────────────
# Kambi widget doesn't expose surface — every tournament defaults to "hard".
# Keys match Kambi tournament_name field exactly as scraped from Stake.com.co.
# Sources: ITF, Tennis Europe, CoreTennis, ATP/WTA tour websites.

TOURNAMENT_SURFACE_MAP: dict[str, str] = {
    # Grand Slams
    "ATP Tour. Wimbledon": "grass",
    "WTA Tour. Wimbledon": "grass",
    "ATP Tour. Roland Garros": "clay",
    "WTA Tour. Roland Garros": "clay",
    "ATP Tour. US Open": "hard",
    "WTA Tour. US Open": "hard",
    "ATP Tour. Australian Open": "hard",
    "WTA Tour. Australian Open": "hard",
    # ATP Tour
    "ATP Tour. Eastbourne": "grass",
    "ATP Tour. Eastbourne. Doubles": "grass",
    "ATP Tour. Mallorca": "grass",
    "ATP Tour. Mallorca. Doubles": "grass",
    "ATP Tour. Queen's": "grass",
    "ATP Tour. Halle": "grass",
    "ATP Tour. Stuttgart": "grass",
    "ATP Tour. 's-Hertogenbosch": "grass",
    # WTA Tour
    "WTA Tour. Eastbourne": "grass",
    "WTA Tour. Eastbourne. Doubles": "grass",
    "WTA Tour. Bad Homburg": "grass",
    "WTA Tour. Bad Homburg. Doubles": "grass",
    "WTA Tour. Berlin": "grass",
    "WTA Tour. Nottingham": "grass",
    "WTA Tour. Birmingham": "grass",
    "WTA Tour. 's-Hertogenbosch": "grass",
    # ATP Challenger Tour
    "ATP Challenger Tour. Piracicaba": "clay",
    "ATP Challenger Tour. Piracicaba. Doubles": "clay",
    "ATP Challenger Tour. Plovdiv": "clay",
    "ATP Challenger Tour. Targu Mures": "clay",
    # ITF Men
    "ITF. Men. Alkmaar": "clay",
    "ITF. Men. Bakio": "hard",
    "ITF. Men. Bergamo": "clay",
    "ITF. Men. Brussels": "hard",
    "ITF. Men. Claremont": "hard",
    "ITF. Men. Kamen": "clay",
    "ITF. Men. Kursumlijska Banja": "clay",
    "ITF. Men. Monastir": "hard",
    "ITF. Men. Tanger": "clay",
    "ITF. Men. Wuning": "hard",
    # ITF Women
    "ITF. Women. Alkmaar": "clay",
    "ITF. Women. Asuncion": "clay",
    "ITF. Women. Claremont": "hard",
    "ITF. Women. Galati": "clay",
    "ITF. Women. Gdansk": "clay",
    "ITF. Women. Maanshan": "hard",
    "ITF. Women. Monastir": "hard",
    "ITF. Women. Palma del Rio": "hard",
    "ITF. Women. Rome": "clay",
    "ITF. Women. Sapporo": "hard",
    "ITF. Women. Taipei": "hard",
}

SURFACE_KEYWORDS = {
    "clay": ["clay", "tierra", "arcilla"],
    "grass": ["grass", "cesped", "césped", "hierba", "lawn"],
    "hard": ["hard", "dura", "duro", "cemento", "concrete"],
    "carpet": ["carpet", "moqueta", "sintetica", "sintética"],
}


def _detect_surface(text: str) -> str:
    """Detect surface from tournament name or match text.

    Resolution order:
      1. Exact match in TOURNAMENT_SURFACE_MAP (uses tournament name)
      2. Keyword detection in combined text
      3. Default: "hard"
    """
    # 1. Check tournament map (text is "tournament player_a player_b")
    for tour_name in TOURNAMENT_SURFACE_MAP:
        if tour_name in text:
            return TOURNAMENT_SURFACE_MAP[tour_name]

    # 2. Keyword fallback
    combined = text.lower()
    for surface, keywords in SURFACE_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return surface
    return "hard"


# ── Extracción de resultados vía Playwright standalone ─────────────


async def extract_tennis_results(limit: int = 50) -> list[dict]:
    """
    Navega a /deportes/tennis con Playwright standalone.
    Captura events-by-path.json vía response listener PASIVO.
    Extrae partidos finalizados (con ganador/perdedor) en vez de odds activas.

    Retorna lista de dicts con:
      {event_id, player_a, player_b, winner, loser, tournament,
       match_date, surface, scores, status}
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
            results = _parse_kambi_results(events_data[0], limit)

        await browser.close()

    return results


def _parse_kambi_results(data: dict, limit: int = 50) -> list[dict]:
    """
    Parsea events-by-path.json → dicts con resultados (ganador/perdedor).

    Busca eventos con state=CLOSED o que tengan scores/resultados.
    A diferencia de _parse_kambi_events (odds), este extrae ganadores.

    Estructura esperada de events-by-path.json:
      {events: [{
        id, sport_name, tournament_name, date_start, outright,
        state,  # "CLOSED" para finalizados
        teams: {home, away},
        main_odds: {...} o null para finalizados,
        scores: {home: 2, away: 0} o similar
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

        # Determinar si el evento está finalizado
        state = evt.get("state", "")
        event_status = evt.get("status", "") or evt.get("eventStatus", "")

        # Buscar ganador de múltiples fuentes posibles
        winner = _extract_winner(evt, player_a, player_b)
        if not winner:
            # Evento sin resultado — saltar (no es un resultado)
            continue

        loser = player_b if winner == player_a else player_a

        date_start = evt.get("date_start") or ""
        tournament = evt.get("tournament_name", "unknown")
        match_date = date_start[:10] if date_start else datetime.now().strftime("%Y-%m-%d")
        surface = _detect_surface(f"{tournament} {player_a} {player_b}")
        event_id = str(evt.get("id", ""))

        # Extraer scores si están disponibles
        scores = _extract_scores(evt)

        items.append(
            {
                "event_id": event_id,
                "player_a": player_a,
                "player_b": player_b,
                "winner": winner,
                "loser": loser,
                "tournament": str(tournament),
                "match_date": match_date,
                "surface": surface,
                "scores": scores,
                "status": state or event_status or "closed",
            }
        )

        if len(items) >= limit:
            break

    return items


def _extract_winner(evt: dict, player_a: str, player_b: str) -> str | None:
    """
    Extrae el ganador de un evento Kambi.

    Prueba múltiples campos (Kambi puede usar distintos nombres):
    - event.result.home/away con valores
    - event.scores con name + score
    - event.winner_name
    - main_odds null + state CLOSED + algún campo de resultado
    """
    # 1. Campo 'result' directo: {home: 2, away: 1}
    result = evt.get("result", {})
    if isinstance(result, dict):
        home_score = result.get("home", 0) or 0
        away_score = result.get("away", 0) or 0
        try:
            home_score = int(home_score)
            away_score = int(away_score)
            if home_score > away_score:
                return player_a
            elif away_score > home_score:
                return player_b
        except (ValueError, TypeError):
            pass

    # 2. Campo 'scores': [{name: "Player A", score: 2}, {name: "Player B", score: 1}]
    scores = evt.get("scores")
    if isinstance(scores, list) and len(scores) >= 2:
        try:
            s0 = int(scores[0].get("score", 0))
            s1 = int(scores[1].get("score", 0))
            if s0 > s1:
                return scores[0].get("name", player_a)
            elif s1 > s0:
                return scores[1].get("name", player_b)
        except (ValueError, TypeError):
            pass

    # 3. Campo 'winner' o 'winner_name' directo
    winner_name = evt.get("winner") or evt.get("winner_name") or ""
    if winner_name:
        winner_lower = winner_name.lower().strip()
        if winner_lower in player_a.lower() or player_a.lower() in winner_lower:
            return player_a
        if winner_lower in player_b.lower() or player_b.lower() in winner_lower:
            return player_b

    # 4. Campo 'settled': true + 'outcome' o 'winning_side'
    if evt.get("settled") or evt.get("state") == "CLOSED":
        outcome = evt.get("outcome") or evt.get("winning_side") or ""
        if outcome:
            outcome = str(outcome).lower()
            if "home" in outcome:
                return player_a
            if "away" in outcome:
                return player_b

    return None


def _extract_scores(evt: dict) -> dict | None:
    """Extrae scores del evento si están disponibles."""
    # Kambi puede tener scores en varios formatos
    scores = evt.get("scores")
    if isinstance(scores, list):
        try:
            return {
                "home": scores[0].get("score", 0),
                "away": scores[1].get("score", 0),
            }
        except (IndexError, KeyError, TypeError):
            pass

    result = evt.get("result", {})
    if isinstance(result, dict) and ("home" in result or "away" in result):
        return {"home": result.get("home", 0), "away": result.get("away", 0)}

    return None


# ── Spider ────────────────────────────────────────────


class StakeResultsSpider(scrapy.Spider):
    name = "stake_results"
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
        self.limit = int(getattr(self, "limit", "50"))
        self.region = getattr(self, "region", "colombia")
        self.logger.info(
            "StakeResults spider: sport=%s limit=%d region=%s",
            self.sport,
            self.limit,
            self.region,
        )

    async def start(self):
        """Ejecuta extracción de resultados vía Playwright standalone."""
        self.logger.info("Starting Playwright results extraction...")
        raw_items = await extract_tennis_results(limit=self.limit)
        self.logger.info("Extracted %d result items", len(raw_items))

        for ri in raw_items:
            match_slug = (
                f"{ri['player_a'].lower().replace(' ', '-')}"
                f"-vs-{ri['player_b'].lower().replace(' ', '-')}"
                f"-{ri['match_date']}"
            )
            yield OddsItem(
                site=f"stake_{self.region}_results",
                sport=self.sport,
                league=self.league or "unknown",
                tournament=ri["tournament"],
                match_date=ri["match_date"],
                commence_time=ri.get("match_date", ""),
                title=f"{ri['player_a']} vs {ri['player_b']}",
                player_a=ri["player_a"],
                player_b=ri["player_b"],
                odds_a=1.0,  # Resultados no tienen odds
                odds_b=1.0,
                surface=ri["surface"],
                market_type="results",
                url=f"{TENNIS_URL}#match={match_slug}",
                metadata={
                    "region": self.region,
                    "scraped_via": "kambi_results",
                    "event_id": ri["event_id"],
                    "winner": ri["winner"],
                    "loser": ri["loser"],
                    "scores": ri.get("scores"),
                    "status": ri.get("status", ""),
                },
            )
