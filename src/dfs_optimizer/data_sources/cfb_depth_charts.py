from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urljoin, urlparse

import requests


CFB_DEPTH_CHART_INDEX_URL = "https://www.ourlads.com/ncaa-football-depth-charts/"
TEAM_NAME_ALIASES = {
    "BYU": "Brigham Young",
    "UCF": "Central Florida",
    "SMU": "Southern Methodist",
    "USC": "Southern California",
    "UTSA": "Texas San Antonio",
}


@dataclass(frozen=True, slots=True)
class CFBDepthChartEntry:
    team: str
    name: str
    position: str
    depth: int
    reserve: bool = False


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.current_href: str | None = None
        self.current_text: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag.casefold() == "a":
            self.current_href = dict(attrs).get("href")
            self.current_text = []

    def handle_data(self, data) -> None:
        if self.current_href is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag) -> None:
        if tag.casefold() == "a" and self.current_href is not None:
            self.anchors.append((
                self.current_href,
                " ".join("".join(self.current_text).split()),
            ))
            self.current_href = None
            self.current_text = []


class _DepthTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.row: list[dict[str, object]] | None = None
        self.cell: dict[str, object] | None = None
        self.rows: list[list[dict[str, object]]] = []

    def handle_starttag(self, tag, attrs) -> None:
        tag = tag.casefold()
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = {"text": [], "href": None}
        elif tag == "a" and self.cell is not None:
            self.cell["href"] = dict(attrs).get("href")

    def handle_data(self, data) -> None:
        if self.cell is not None:
            self.cell["text"].append(data)

    def handle_endtag(self, tag) -> None:
        tag = tag.casefold()
        if tag in {"td", "th"} and self.cell is not None:
            self.cell["text"] = " ".join("".join(self.cell["text"]).split())
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None


def fetch_cfb_depth_charts(
    team_names: tuple[tuple[str, str], ...], *, timeout: float = 20
) -> tuple[CFBDepthChartEntry, ...]:
    """Download current Ourlads charts for the requested salary-file teams."""
    try:
        index = requests.get(
            CFB_DEPTH_CHART_INDEX_URL,
            headers={"User-Agent": "dfs-optimizer/0.1 depth-chart client"},
            timeout=timeout,
        )
        index.raise_for_status()
    except requests.RequestException as exc:
        raise OSError(f"could not download college depth-chart index: {exc}") from exc
    links = _depth_chart_links(index.text)
    team_urls = {
        abbreviation: _match_team_url(
            abbreviation,
            TEAM_NAME_ALIASES.get(abbreviation.upper(), school),
            links,
        )
        for abbreviation, school in team_names
    }
    team_urls = {team: url for team, url in team_urls.items() if url}
    entries: list[CFBDepthChartEntry] = []

    def load(team: str, url: str) -> tuple[CFBDepthChartEntry, ...]:
        response = requests.get(
            url,
            headers={"User-Agent": "dfs-optimizer/0.1 depth-chart client"},
            timeout=timeout,
        )
        response.raise_for_status()
        return parse_cfb_depth_chart(response.text, team)

    with ThreadPoolExecutor(max_workers=min(8, len(team_urls) or 1)) as executor:
        futures = {
            executor.submit(load, team, url): team
            for team, url in team_urls.items()
        }
        for future in as_completed(futures):
            try:
                entries.extend(future.result())
            except requests.RequestException:
                continue
    return tuple(sorted(
        entries, key=lambda item: (item.team, item.position, item.depth, item.name)
    ))


def parse_cfb_depth_chart(
    content: str, team: str
) -> tuple[CFBDepthChartEntry, ...]:
    parser = _DepthTableParser()
    parser.feed(content)
    entries: dict[tuple[str, str], CFBDepthChartEntry] = {}
    for row in parser.rows:
        if not row:
            continue
        raw_position = str(row[0]["text"]).strip().upper()
        position = "WR" if raw_position.startswith("WR") else raw_position
        reserve = position == "RES"
        if position not in {"QB", "RB", "WR", "TE", "RES"}:
            continue
        for depth, index in enumerate(range(2, len(row), 2), start=1):
            href = str(row[index].get("href") or "")
            name = _player_name(href, str(row[index]["text"]))
            if not name:
                continue
            key = (position, _normalize(name))
            current = entries.get(key)
            if current is None or depth < current.depth:
                entries[key] = CFBDepthChartEntry(
                    team.upper(), name, position, depth, reserve=reserve
                )
    return tuple(entries.values())


def _depth_chart_links(content: str) -> tuple[tuple[str, str, str], ...]:
    parser = _AnchorParser()
    parser.feed(content)
    links = []
    for href, label in parser.anchors:
        if "depth-chart.aspx" not in href.casefold():
            continue
        url = urljoin(CFB_DEPTH_CHART_INDEX_URL, href)
        slug = (parse_qs(urlparse(url).query).get("s") or [""])[0]
        if slug:
            links.append((url, slug, label))
    return tuple(dict.fromkeys(links))


def _match_team_url(
    abbreviation: str, school: str, links: tuple[tuple[str, str, str], ...]
) -> str | None:
    targets = {_normalize(abbreviation), _normalize(school)} - {""}
    ranked = []
    for url, slug, label in links:
        values = {_normalize(slug), _normalize(label)} - {""}
        exact = bool(targets & values)
        prefix = any(
            target.startswith(value) or value.startswith(target)
            for target in targets for value in values
        )
        if exact or prefix:
            ranked.append((0 if exact else 1, min(
                abs(len(target) - len(value))
                for target in targets for value in values
            ), url))
    if not ranked:
        return None
    ranked.sort()
    best = ranked[0][:2]
    winners = {url for score, distance, url in ranked if (score, distance) == best}
    return next(iter(winners)) if len(winners) == 1 else None


def _player_name(href: str, fallback: str) -> str:
    match = re.search(r"/player/([^/]+)/\d+", href, re.IGNORECASE)
    if match:
        return match.group(1).replace("-", " ")
    return re.split(
        r"\s+(?:RS|FR|SO|JR|SR|GR)(?:/TR)?(?:\s|$)", fallback, maxsplit=1
    )[0].strip()


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())
