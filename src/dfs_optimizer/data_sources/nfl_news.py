from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
import json
import re
import unicodedata
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import requests

from dfs_optimizer.data_sources.nfl_props import NFL_TEAM_NAMES
from dfs_optimizer.models import Slate


@dataclass(frozen=True, slots=True)
class NFLNewsCandidate:
    team: str
    title: str
    source: str
    url: str
    published_at: str | None
    matched_players: tuple[str, ...]
    topics: tuple[str, ...]


def fetch_nfl_news_candidates(
    slate: Slate,
    *,
    days: int = 7,
    timeout: float = 10,
) -> tuple[NFLNewsCandidate, ...]:
    """Collect recent, attributed headlines for slate teams and match players.

    Headlines are review candidates, not model inputs. This intentionally does
    not infer a workload change from media wording without human confirmation.
    """
    teams = sorted(slate.teams)
    players_by_team = {
        team: tuple(player.name for player in slate.players if player.team == team)
        for team in teams
    }

    def fetch(team: str):
        team_name = NFL_TEAM_NAMES.get(team, team)
        query = quote_plus(
            f'"{team_name}" (coach OR injury OR practice OR workload OR snaps) when:{days}d'
        )
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        response = requests.get(
            url,
            headers={"User-Agent": "dfs-optimizer/0.1"},
            timeout=timeout,
        )
        response.raise_for_status()
        return team, response.content

    feeds = []
    with ThreadPoolExecutor(max_workers=min(6, len(teams) or 1)) as executor:
        pending = {executor.submit(fetch, team): team for team in teams}
        for future in as_completed(pending):
            try:
                feeds.append(future.result())
            except requests.RequestException:
                continue

    candidates = []
    seen = set()
    for team, content in feeds:
        try:
            items = ET.fromstring(content).findall("./channel/item")
        except ET.ParseError:
            continue
        for item in items:
            title = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            if not title or not url or url in seen:
                continue
            matches = tuple(
                name for name in players_by_team[team]
                if _player_mentioned(name, title)
            )
            if not matches:
                continue
            topics = _topics(title)
            if not topics:
                continue
            source_node = item.find("source")
            source = (
                (source_node.text or "").strip()
                if source_node is not None else "Unknown source"
            )
            published = _published(item.findtext("pubDate"))
            candidates.append(NFLNewsCandidate(
                team=team,
                title=title,
                source=source,
                url=url,
                published_at=published,
                matched_players=matches,
                topics=topics,
            ))
            seen.add(url)
    return tuple(sorted(candidates, key=lambda item: item.published_at or "", reverse=True))


def nfl_news_snapshot(candidates: tuple[NFLNewsCandidate, ...]) -> bytes:
    return (json.dumps([asdict(item) for item in candidates], indent=2) + "\n").encode()


def _player_mentioned(name: str, text: str) -> bool:
    normalized_name = _normalize(name)
    normalized_text = _normalize(text)
    parts = normalized_name.split()
    if normalized_name in normalized_text:
        return True
    # Headlines commonly omit suffixes and occasionally use only a distinctive
    # surname. Require at least four letters to avoid weak matches such as Hall.
    surname = next((part for part in reversed(parts) if part not in {"jr", "ii", "iii", "iv"}), "")
    return len(surname) >= 5 and re.search(rf"\b{re.escape(surname)}\b", normalized_text) is not None


def _topics(title: str) -> tuple[str, ...]:
    text = title.lower()
    groups = {
        "injury": ("injury", "injured", "questionable", "doubtful", "out", "practice"),
        "return": ("return", "activated", "cleared", "back in"),
        "role": ("workload", "snaps", "starter", "committee", "role", "carries", "targets"),
        "coach": ("coach", "says", "said", "expects", "plans"),
    }
    return tuple(label for label, words in groups.items() if any(word in text for word in words))


def _published(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return value.strip() or None


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
