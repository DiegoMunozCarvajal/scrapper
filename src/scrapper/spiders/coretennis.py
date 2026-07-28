"""
Spider for CoreTennis.net — historical tennis match results.

Covers ATP, WTA, Challenger, ITF Futures ($15K/$25K), and Juniors.
4.3M+ matches, 216K+ player profiles.

Usage:
  scrapy crawl coretennis -a players="Max Basing,Rafael Jodar" -o results.csv
  scrapy crawl coretennis -a player_ids="106921,218360" -o results.csv
"""

import re
from datetime import datetime, timezone

import scrapy

from ..items import TennisMatchItem

BASE_URL = "https://www.coretennis.net"
SEARCH_URL = f"{BASE_URL}/majic/pageServer/0n0100000a/en/Search-Players.html"

SURFACE_CLASS_MAP = {
    "plSurf1": "clay",
    "plSurf2": "hard",
    "plSurf3": "grass",
    "plSurf4": "carpet",
}

SURFACE_TEXT_MAP = {
    "clay": "clay",
    "hard": "hard",
    "indoor hard": "hard",
    "grass": "grass",
    "carpet": "carpet",
    "indoor": "hard",
}

CATEGORY_LEVEL_MAP = {
    "grand slam": "A",
    "atp": "A",
    "wta": "A",
    "challenger": "C",
    "ch": "C",
    "itf": "S",
    "futures": "S",
    "m25": "S",
    "m15": "S",
    "w25": "S",
    "w15": "S",
    "j": "J",
    "junior": "J",
    "j60": "J",
    "j30": "J",
    "j100": "J",
    "j200": "J",
    "j300": "J",
    "j500": "J",
}


def _clean_name(name: str) -> str:
    """Remove country code suffix: 'Max Basing(GBR)' → 'Max Basing'."""
    return re.sub(r"\s*\([A-Z]{3}\)\s*$", "", name).strip()


MONTH_MAP = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def _extract_surface(tourn_sel) -> str:
    """Extract surface from CSS classes then text fallback."""
    classes = (tourn_sel.attrib.get("class", "") or "").split()
    for cls in classes:
        if cls in SURFACE_CLASS_MAP:
            return SURFACE_CLASS_MAP[cls]
    text = " ".join(tourn_sel.css("::text").getall()).lower()
    for keyword, surface in SURFACE_TEXT_MAP.items():
        if keyword in text:
            return surface
    return "hard"


def _extract_category_level(category_text: str) -> str:
    for keyword, level in CATEGORY_LEVEL_MAP.items():
        if keyword in category_text.strip().lower():
            return level
    return "S"


def _parse_date_range(dates_text: str) -> int:
    """Parse 'Jun 08 Jun 13' → MMDD int."""
    if not dates_text:
        return 0
    parts = dates_text.split()
    if len(parts) < 2:
        return 0
    month_str = parts[0][:3].title()
    try:
        day = int(re.search(r"(\d+)", parts[1]).group(1))
    except (ValueError, AttributeError):
        return 0
    month = MONTH_MAP.get(month_str, 1)
    return month * 100 + day


def _parse_score(score_text: str) -> str:
    score = score_text.strip()
    score = re.sub(r"\((\d+)\)", r"-\1", score)
    if re.match(r"^\d{2}(\s+\d{2})*$", score):
        parts = []
        digits = score.replace(" ", "")
        for i in range(0, len(digits), 2):
            pair = digits[i : i + 2]
            if len(pair) == 2:
                parts.append(f"{pair[0]}-{pair[1]}")
        if parts:
            score = " ".join(parts)
    return score


class CoreTennisSpider(scrapy.Spider):
    name = "coretennis"
    site = "coretennis"

    custom_settings = {
        "CONCURRENT_REQUESTS": 2,
        "DOWNLOAD_DELAY": 1.5,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "ROBOTSTXT_OBEY": False,
    }

    def start_requests(self):
        players_str = getattr(self, "players", None)
        player_ids_str = getattr(self, "player_ids", None)

        if player_ids_str:
            for pid in player_ids_str.split(","):
                pid = pid.strip()
                if pid.isdigit():
                    url = f"{BASE_URL}/tennis-player/player/{pid}/results.html"
                    yield scrapy.Request(
                        url,
                        callback=self.parse_results,
                        meta={"player_id": int(pid), "player_name": f"id-{pid}"},
                    )

        if players_str:
            for name in players_str.split(","):
                name = name.strip()
                if name:
                    # CoreTennis search is single-word only — use last name
                    search_term = name.split()[-1] if " " in name else name
                    search_url = f"{SEARCH_URL}?search=1&pln={search_term}"
                    yield scrapy.Request(
                        search_url,
                        callback=self.parse_search,
                        meta={"search_name": name, "search_term": search_term},
                    )

    def parse_search(self, response):
        name = response.meta["search_name"]
        search_term = response.meta.get("search_term", name)
        # CoreTennis search returns multiple players. Find best match by slug.
        all_links = response.css('a[href*="/tennis-player/"][href*="/profile.html"]')
        name_lower = name.lower()
        best_href = None
        for link in all_links:
            href = link.attrib.get("href", "")
            slug_match = re.search(r"/tennis-player/([^/]+)/(\d+)/", href)
            if slug_match:
                slug = slug_match.group(1).replace("-", " ")
                if slug == name_lower:
                    best_href = href
                    break
                if not best_href:
                    slug_words = set(slug.split())
                    name_words = set(name_lower.split())
                    if slug_words & name_words:
                        best_href = href

        if best_href:
            match = re.search(r"/tennis-player/([^/]+)/(\d+)/", best_href)
            if match:
                slug, pid = match.group(1), int(match.group(2))
                results_url = f"{BASE_URL}/tennis-player/{slug}/{pid}/results.html"
                yield scrapy.Request(
                    results_url,
                    callback=self.parse_results,
                    meta={"player_id": pid, "player_name": name},
                )
        else:
            self.logger.warning("Player not found: %s (searched: %s)", name, search_term)

    def parse_results(self, response):
        player_id = response.meta["player_id"]
        player_name = response.meta.get("player_name", "")

        # Parse displayed player name if not provided
        if not player_name or player_name.startswith("id-"):
            h1 = response.css("div.ppHeader h1")
            if h1:
                # Get text WITHOUT the country span
                name_parts = h1[0].xpath("text()").getall()
                name_text = " ".join(name_parts).strip()
                player_name = re.sub(r"\s*Results\s*", "", name_text).strip()
                player_name = _clean_name(player_name)

        # Year tabs → year number mapping
        year_by_div = {}
        for tab_link in response.css("ul.shadetabs li a[rel]"):
            rel = tab_link.attrib.get("rel", "")
            m = re.match(r"yearContent(\d{4})", rel)
            if m:
                year_by_div[rel] = int(m.group(1))

        year_divs = response.css('div[id^="yearContent"]')
        if not year_divs:
            self.logger.warning("No year data for player %d (%s)", player_id, player_name)
            return

        for year_div in year_divs:
            div_id = year_div.attrib.get("id", "")
            div_year_match = re.match(r"yearContent(\d{4})", div_id)
            if not div_year_match:
                continue
            year = int(div_year_match.group(1))

            for tourn_div in year_div.css("div.plTourn"):
                head = tourn_div.css("div.pprHead")
                if not head:
                    continue

                plm2 = head[0].css("div.plM2")
                if not plm2:
                    continue

                plm2_el = plm2[0]

                # Tournament name from link
                tourn_link = plm2_el.css("a")
                tourn_name = tourn_link[0].css("::text").get("").strip() if tourn_link else ""

                # Category + surface from text
                full_text = " ".join(plm2_el.css("::text").getall()).strip()
                surface = _extract_surface(tourn_div)
                category = ""

                text_parts = full_text.split(" - ")
                for part in text_parts:
                    part_lower = part.strip().lower()
                    if part_lower in SURFACE_TEXT_MAP:
                        surface = SURFACE_TEXT_MAP[part_lower]
                    elif any(
                        kw in part_lower
                        for kw in [
                            "boys",
                            "girls",
                            "junior",
                            "atp",
                            "wta",
                            "challenger",
                            "itf",
                            "futures",
                            "m25",
                            "m15",
                            "w25",
                            "w15",
                            "j60",
                            "j30",
                            "j100",
                            "j200",
                            "j300",
                            "j500",
                            "grand slam",
                        ]
                    ):
                        category = part.strip()

                tourney_level = _extract_category_level(category)

                # Date
                dates_div = head[0].css("div.plM1")
                dates_text = (
                    " ".join(dates_div[0].css("::text").getall()).strip() if dates_div else ""
                )
                mmdd = _parse_date_range(dates_text)
                tourney_date = year * 10000 + mmdd if mmdd else year * 10000 + 101

                # Match rows
                for row in tourn_div.css("div.pprRow"):
                    opp_div = row.css("div.plM2")
                    result_divs = row.css("div.plM4")
                    score_div = row.css("div.plM3")
                    round_div = row.css("div.plM1")

                    if not result_divs or not opp_div:
                        continue

                    result_text = ""
                    for rd in result_divs:
                        txt = (rd.css("::text").get("") or "").strip()
                        if txt in ("W", "L"):
                            result_text = txt
                            break

                    opp_link = opp_div[0].css("a")
                    opponent_name = (
                        _clean_name((opp_link[0].css("::text").get("") or "").strip())
                        if opp_link
                        else ""
                    )

                    score_text = (
                        (score_div[0].css("::text").get("") or "").strip() if score_div else ""
                    )
                    round_text = (
                        (round_div[0].css("::text").get("") or "").strip() if round_div else ""
                    )

                    if not opponent_name or not result_text:
                        continue
                    if score_text.lower() in ("w/o", "walkover"):
                        continue

                    score = _parse_score(score_text)

                    if result_text == "W":
                        winner_name = player_name
                        loser_name = opponent_name
                    else:
                        winner_name = opponent_name
                        loser_name = player_name

                    is_gs = "grand slam" in tourn_name.lower() or "grand slam" in category.lower()
                    best_of = 5 if is_gs else 3

                    yield TennisMatchItem(
                        url=f"{response.url}?match={tourney_date}-{round_text}-{loser_name.replace(' ', '-').lower()}",
                        title=f"{winner_name} vs {loser_name}",
                        winner_name=winner_name,
                        loser_name=loser_name,
                        score=score,
                        surface=surface,
                        tourney_date=tourney_date,
                        tourney_level=tourney_level,
                        tourney_name=tourn_name or category,
                        round=round_text,
                        best_of=best_of,
                        source_url=response.url,
                    )
