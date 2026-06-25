"""
Spider para Pinnacle — odds de referencia (sharp book).

Pinnacle es el gold standard de odds "justas". Scrapeamos sus cuotas
para usarlas como referencia contra las de Stake.

Uso:
  scrapy crawl pinnacle -a sport=tennis -a limit=30 -o pinnacle_odds.json
"""

import json
import re
from datetime import datetime

import scrapy
from scrapy import Request
from scrapy_playwright.page import PageMethod

from ..items import OddsItem


def _build_match_url(base_url: str, player_a: str, player_b: str) -> str:
    """Construye URL única por partido para evitar colisiones de dedup."""
    slug = (
        f"{player_a.lower().replace(' ', '-')}"
        f"-vs-{player_b.lower().replace(' ', '-')}"
        f"-{datetime.now().strftime('%Y%m%d')}"
    )
    return f"{base_url}#match={slug}"


def _match_odds_to_player(player_name: str, odds_by_name: dict[str, float]) -> float:
    """Busca odds para un jugador por nombre. Sin match → 0.0 (no positional fallback)."""
    if not player_name:
        return 0.0
    pn = player_name.lower().strip()
    # Exact match
    if player_name in odds_by_name:
        return odds_by_name[player_name]
    # Case-insensitive exact
    for name, odds in odds_by_name.items():
        if name.lower().strip() == pn:
            return odds
    # Substring bidirectional — only if outcome name has no spread number
    import re

    for name, odds in odds_by_name.items():
        nl = name.lower().strip()
        if re.search(r"[+-]\d+\.?\d*", nl):
            continue  # skip handicap names like "Djokovic +2.5"
        if pn in nl or nl in pn:
            return odds
    return 0.0


class PinnacleSpider(scrapy.Spider):
    name = "pinnacle"
    site = "pinnacle"

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 3,
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "ROBOTSTXT_OBEY": False,
        "USER_AGENT": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }

    BASE_URL = "https://www.pinnacle.com"

    SPORT_PATHS = {
        "tennis": "/en/tennis/matchups",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sport = getattr(self, "sport", "tennis")
        self.limit = int(getattr(self, "limit", "30"))
        sport_path = self.SPORT_PATHS.get(self.sport, f"/en/{self.sport}")
        self.start_url = f"{self.BASE_URL}{sport_path}"

    def start_requests(self):
        yield Request(
            url=self.start_url,
            callback=self.parse,
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "playwright_page_methods": [
                    PageMethod("wait_for_load_state", "networkidle"),
                    PageMethod("wait_for_timeout", 4000),
                ],
            },
        )

    async def parse(self, response):
        page = response.meta.get("playwright_page")
        items = []
        try:
            # Estrategia 1: Buscar data en scripts inline
            scripts = response.css("script::text").getall()
            for script in scripts:
                for key in (
                    "__NEXT_DATA__",
                    "window.__DATA__",
                    "window.__INITIAL__",
                ):
                    if key in script:
                        try:
                            match = re.search(
                                rf"{re.escape(key)}\s*=\s*(\{{.*\}});",
                                script,
                                re.DOTALL,
                            )
                            if not match:
                                match = re.search(r'(\{.*"events".*\})', script, re.DOTALL)
                            if match:
                                data = json.loads(match.group(1))
                                extracted = self._walk_json(data)
                                items.extend(extracted)
                        except (json.JSONDecodeError, Exception) as e:
                            self.logger.debug("JSON parse failed for key %s: %s", key, e)

            # Estrategia 2: Parsear HTML
            if not items:
                event_blocks = response.css(
                    '[class*="event"], [class*="matchup"], [class*="matchup-row"]'
                )
                for block in event_blocks:
                    text = " ".join(block.css("::text").getall())
                    nums = re.findall(r"(\d+\.\d{2,3})", text)
                    if len(nums) >= 2:
                        names = re.findall(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", text)
                        if len(names) >= 2:
                            items.append(
                                OddsItem(
                                    site="pinnacle",
                                    sport=self.sport,
                                    league="unknown",
                                    tournament="unknown",
                                    match_date=datetime.now().strftime("%Y-%m-%d"),
                                    title=f"{names[0]} vs {names[1]}",
                                    player_a=names[0],
                                    player_b=names[1],
                                    odds_a=float(nums[0]),
                                    odds_b=float(nums[1]),
                                    surface="hard",
                                    market_type="moneyline",
                                    url=_build_match_url(
                                        self.start_url,
                                        names[0],
                                        names[1],
                                    ),
                                    metadata={"scraped_via": "html_parse"},
                                )
                            )

            # Estrategia 3: Fallback regex
            if not items:
                self.logger.warning("No items found. Consider enabling LLM fallback.")
                items = self._text_regex_fallback(response)
        finally:
            if page:
                await page.close()

        self.logger.info("Extracted %d items from Pinnacle", len(items))
        for item in items[: self.limit]:
            yield item

    def _walk_json(self, data, depth=0):
        """Recorre JSON buscando eventos con odds emparejadas por nombre."""
        if depth > 6:
            return []
        items = []
        if isinstance(data, dict):
            if "events" in data and isinstance(data["events"], list):
                for event in data["events"]:
                    if not isinstance(event, dict):
                        continue

                    # Extraer participantes
                    names = []
                    for p in event.get("participants", []):
                        if isinstance(p, dict):
                            names.append(p.get("name", ""))
                        elif isinstance(p, str):
                            names.append(p)

                    # Extraer odds emparejadas por nombre — solo H2H/moneyline
                    odds_by_name = {}
                    for m in event.get("markets", []):
                        if not isinstance(m, dict):
                            continue
                        market_name = str(m.get("name", m.get("marketName", ""))).lower()
                        # Skip non-H2H markets (totals, handicaps, etc.)
                        skip_keywords = [
                            "total",
                            "over",
                            "under",
                            "handicap",
                            "spread",
                            "asian",
                            "games",
                            "sets",
                            "points",
                            "correct score",
                            "set betting",
                            "tie break",
                            "game handicap",
                        ]
                        if any(kw in market_name for kw in skip_keywords):
                            continue
                        for o in m.get("selections", m.get("outcomes", [])):
                            if isinstance(o, dict):
                                o_name = o.get("name", o.get("label", ""))
                                o_price = o.get("price", o.get("odds", 0))
                                if o_name and o_price:
                                    odds_by_name[str(o_name)] = float(o_price)

                    if len(names) >= 2 and len(odds_by_name) >= 2:
                        # Solo emparejar si hay match por nombre (nunca caer a posición)
                        a_odds = _match_odds_to_player(names[0], odds_by_name)
                        b_odds = _match_odds_to_player(names[1], odds_by_name)
                        if not a_odds or not b_odds:
                            continue  # skip — sin match confiable
                        items.append(
                            OddsItem(
                                site="pinnacle",
                                sport=self.sport,
                                league=event.get("league", event.get("tournament", "unknown")),
                                tournament=event.get("name", event.get("title", "unknown")),
                                match_date=event.get(
                                    "startTime",
                                    datetime.now().strftime("%Y-%m-%d"),
                                ),
                                title=f"{names[0]} vs {names[1]}",
                                player_a=names[0],
                                player_b=names[1],
                                odds_a=float(a_odds),
                                odds_b=float(b_odds),
                                surface="hard",
                                market_type="moneyline",
                                url=_build_match_url(self.start_url, names[0], names[1]),
                                metadata={"scraped_via": "json_walk"},
                            )
                        )
            for v in data.values():
                items.extend(self._walk_json(v, depth + 1))
        elif isinstance(data, list) and depth < 5:
            for item in data:
                items.extend(self._walk_json(item, depth + 1))
        return items

    def _text_regex_fallback(self, response):
        items = []
        text = " ".join(t.strip() for t in response.css("body::text").getall() if t.strip())
        pattern = re.compile(
            r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\.\'-]{3,40}?)\s+(\d+\.\d{2,3})\s+"
            r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\.\'-]{3,40}?)\s+(\d+\.\d{2,3})"
        )
        for match in pattern.finditer(text):
            a, oa, b, ob = (
                match.group(1),
                float(match.group(2)),
                match.group(3),
                float(match.group(4)),
            )
            if 1.01 <= oa <= 50.0 and 1.01 <= ob <= 50.0:
                items.append(
                    OddsItem(
                        site="pinnacle",
                        sport=self.sport,
                        league="unknown",
                        tournament="unknown",
                        match_date=datetime.now().strftime("%Y-%m-%d"),
                        title=f"{a.strip()} vs {b.strip()}",
                        player_a=a.strip(),
                        player_b=b.strip(),
                        odds_a=oa,
                        odds_b=ob,
                        surface="hard",
                        market_type="moneyline",
                        url=_build_match_url(self.start_url, a.strip(), b.strip()),
                        metadata={"scraped_via": "text_regex"},
                    )
                )
        return items
