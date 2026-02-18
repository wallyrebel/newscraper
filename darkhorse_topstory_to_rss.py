#!/usr/bin/env python3
"""
Scrape Darkhorse Press Top Story posts and publish an RSS 2.0 feed.

Designed for scheduled execution (e.g., GitHub Actions) with incremental state.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

# ----------------------------
# Config
# ----------------------------
CATEGORY_URL = "https://darkhorsepressnow.com/category/news/top-story/"
BASE_URL = "https://darkhorsepressnow.com"
FEED_TITLE = "Darkhorse Press - Top Story"
FEED_DESCRIPTION = "Latest Top Story posts from Darkhorse Press."
USER_AGENT = (
    "Mozilla/5.0 (compatible; DarkhorseTopStoryRSSBot/1.0; "
    "+https://github.com/your-org/your-repo)"
)
REQUEST_TIMEOUT = 20
REQUEST_DELAY_SECONDS = 1.0

MAX_PAGES_TO_SCAN = 5
RECENT_TO_INCLUDE = 40
OUTPUT_PATH = Path("docs/darkhorse-top-story.xml")
STATE_PATH = Path("darkhorse-top-story.seen.json")


@dataclass
class PostItem:
    title: str
    link: str
    guid: str
    pub_date: str
    pub_dt_iso: str
    author: str
    summary: str
    image_url: str

    def as_state(self) -> dict[str, str]:
        return {
            "title": self.title,
            "link": self.link,
            "guid": self.guid,
            "pub_date": self.pub_date,
            "pub_dt_iso": self.pub_dt_iso,
            "author": self.author,
            "summary": self.summary,
            "image_url": self.image_url,
        }

    @classmethod
    def from_state(cls, data: dict[str, Any]) -> "PostItem":
        return cls(
            title=str(data.get("title", "")).strip(),
            link=str(data.get("link", "")).strip(),
            guid=str(data.get("guid", data.get("link", ""))).strip(),
            pub_date=str(data.get("pub_date", "")).strip(),
            pub_dt_iso=str(data.get("pub_dt_iso", "")).strip(),
            author=str(data.get("author", "")).strip(),
            summary=str(data.get("summary", "")).strip(),
            image_url=str(data.get("image_url", "")).strip(),
        )


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"seen_urls": [], "items": {}, "last_run_utc": None}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.warning("State file is invalid JSON. Starting with empty state.")
        return {"seen_urls": [], "items": {}, "last_run_utc": None}

    seen_urls = state.get("seen_urls")
    items = state.get("items")
    if not isinstance(seen_urls, list):
        seen_urls = []
    if not isinstance(items, dict):
        items = {}
    return {
        "seen_urls": [str(url) for url in seen_urls],
        "items": items,
        "last_run_utc": state.get("last_run_utc"),
    }


def save_state(path: Path, state: dict[str, Any]) -> None:
    ensure_parent_dir(path)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def request_soup(session: requests.Session, url: str) -> BeautifulSoup | None:
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as exc:
        logging.warning("Failed request for %s: %s", url, exc)
        return None


def normalize_post_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc
    if not netloc:
        return url
    path = parsed.path or "/"
    path = re.sub(r"/+", "/", path)
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return f"{scheme}://{netloc}{path}"


def looks_like_post_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc and "darkhorsepressnow.com" not in parsed.netloc:
        return False
    path = (parsed.path or "").strip("/")
    if not path:
        return False
    if "/category/" in f"/{path}/":
        return False
    if path.startswith("page/") or path.endswith("/page"):
        return False
    if any(path.startswith(prefix) for prefix in ("tag/", "author/", "wp-", "feed")):
        return False
    return len(path.split("/")) >= 2


def extract_post_urls_from_listing(soup: BeautifulSoup, base_url: str = BASE_URL) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    selector_candidates = [
        "article h1 a[href]",
        "article h2 a[href]",
        "article h3 a[href]",
        ".entry-title a[href]",
        ".post-title a[href]",
        ".td-module-title a[href]",
    ]

    a_tags = []
    for selector in selector_candidates:
        a_tags.extend(soup.select(selector))
    if not a_tags:
        a_tags = soup.select("a[href]")

    for a_tag in a_tags:
        href = a_tag.get("href", "").strip()
        if not href:
            continue
        abs_url = urljoin(base_url, href)
        normalized = normalize_post_url(abs_url)
        if not looks_like_post_url(normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)
    return urls


def discover_listing_urls(
    session: requests.Session, category_url: str, max_pages: int
) -> list[str]:
    discovered: list[str] = []
    seen: set[str] = set()
    for page_num in range(1, max_pages + 1):
        page_url = category_url if page_num == 1 else urljoin(category_url, f"page/{page_num}/")
        logging.info("Scanning listing page %s", page_url)
        soup = request_soup(session, page_url)
        if soup is None:
            continue
        page_urls = extract_post_urls_from_listing(soup, base_url=BASE_URL)
        new_urls = [url for url in page_urls if url not in seen]
        if not new_urls:
            if page_num > 1:
                logging.info("No new candidate URLs at page %s; stopping pagination.", page_num)
                break
            continue
        for url in new_urls:
            seen.add(url)
            discovered.append(url)
        time.sleep(REQUEST_DELAY_SECONDS)
    return discovered


def extract_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = " ".join(node.get_text(" ", strip=True).split())
            if text:
                return text
    return ""


def parse_datetime_str(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = date_parser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def extract_publish_datetime(soup: BeautifulSoup) -> datetime:
    for time_tag in soup.select("time"):
        dt_raw = (time_tag.get("datetime") or "").strip()
        dt = parse_datetime_str(dt_raw)
        if dt:
            return dt
        text_dt = parse_datetime_str(time_tag.get_text(" ", strip=True))
        if text_dt:
            return text_dt

    date_text = extract_meta_content(
        soup,
        [
            {"property": "article:published_time"},
            {"name": "article:published_time"},
            {"property": "og:published_time"},
            {"name": "og:published_time"},
        ],
    )
    if not date_text:
        date_text = extract_text(soup, [".entry-date", ".posted-on", ".post-date"])
    if date_text:
        dt = parse_datetime_str(date_text)
        if dt:
            return dt

    return datetime.now(timezone.utc)


def extract_meta_content(soup: BeautifulSoup, attrs: list[dict[str, str]]) -> str:
    for attr in attrs:
        tag = soup.find("meta", attrs=attr)
        if tag:
            content = (tag.get("content") or "").strip()
            if content:
                return content
    return ""


def extract_canonical_url(soup: BeautifulSoup, page_url: str) -> str:
    canonical_tag = soup.find("link", attrs={"rel": "canonical"})
    if canonical_tag:
        href = (canonical_tag.get("href") or "").strip()
        if href:
            return normalize_post_url(urljoin(page_url, href))
    og_url = extract_meta_content(soup, [{"property": "og:url"}])
    if og_url:
        return normalize_post_url(urljoin(page_url, og_url))
    return normalize_post_url(page_url)


def extract_featured_image(soup: BeautifulSoup, page_url: str) -> str:
    image_url = extract_meta_content(
        soup,
        [
            {"property": "og:image"},
            {"name": "og:image"},
            {"property": "twitter:image"},
            {"name": "twitter:image"},
        ],
    )
    if image_url:
        return urljoin(page_url, image_url)

    for selector in [
        "article img.wp-post-image",
        ".post-thumbnail img",
        ".featured-image img",
        ".entry-content figure img",
        "article img",
    ]:
        img = soup.select_one(selector)
        if not img:
            continue
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("srcset", "").split(" ", 1)[0]
        )
        if src:
            return urljoin(page_url, src.strip())
    return ""


def extract_summary(soup: BeautifulSoup) -> str:
    for selector in [
        "article .entry-content p",
        ".post-content p",
        ".entry-content p",
        "article p",
    ]:
        paragraphs = soup.select(selector)
        for p_tag in paragraphs:
            text = " ".join(p_tag.get_text(" ", strip=True).split())
            if len(text) >= 40:
                return text

    body_text = " ".join(soup.get_text(" ", strip=True).split())
    return body_text[:280] if body_text else ""


def extract_author(soup: BeautifulSoup) -> str:
    meta_author = extract_meta_content(soup, [{"name": "author"}, {"property": "article:author"}])
    if meta_author:
        return meta_author
    return extract_text(
        soup,
        [
            ".author-name",
            ".byline .author",
            ".entry-author",
            "[rel='author']",
        ],
    )


def scrape_post(session: requests.Session, url: str) -> PostItem | None:
    soup = request_soup(session, url)
    if soup is None:
        return None

    title = extract_meta_content(
        soup,
        [
            {"property": "og:title"},
            {"name": "twitter:title"},
        ],
    )
    if not title:
        title = extract_text(soup, ["h1.entry-title", "article h1", "h1", "title"])
    if not title:
        title = "Untitled"

    canonical_link = extract_canonical_url(soup, url)
    pub_dt = extract_publish_datetime(soup)
    author = extract_author(soup)
    summary = extract_summary(soup)
    image_url = extract_featured_image(soup, canonical_link)

    return PostItem(
        title=title,
        link=canonical_link,
        guid=canonical_link,
        pub_date=format_datetime(pub_dt),
        pub_dt_iso=pub_dt.isoformat(),
        author=author,
        summary=summary,
        image_url=image_url,
    )


def build_item_description(item: PostItem) -> str:
    parts: list[str] = []
    if item.image_url:
        escaped_image = html.escape(item.image_url, quote=True)
        parts.append(f'<p><img src="{escaped_image}" alt="{html.escape(item.title)}" /></p>')
    if item.summary:
        parts.append(f"<p>{html.escape(item.summary)}</p>")
    return "".join(parts)


def sort_items_newest_first(items: list[PostItem]) -> list[PostItem]:
    def key_fn(item: PostItem) -> tuple[float, str]:
        dt = parse_datetime_str(item.pub_dt_iso)
        ts = dt.timestamp() if dt else 0.0
        return (ts, item.link)

    return sorted(items, key=key_fn, reverse=True)


def indent_xml(elem: ET.Element, level: int = 0) -> None:
    indent = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "  "
        for child in elem:
            indent_xml(child, level + 1)
        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = indent
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = indent


def write_rss(output_path: Path, items: list[PostItem], feed_url: str) -> None:
    ensure_parent_dir(output_path)

    rss = ET.Element(
        "rss",
        {
            "version": "2.0",
            "xmlns:atom": "http://www.w3.org/2005/Atom",
            "xmlns:media": "http://search.yahoo.com/mrss/",
        },
    )
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = FEED_TITLE
    ET.SubElement(channel, "link").text = CATEGORY_URL
    ET.SubElement(channel, "description").text = FEED_DESCRIPTION
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    atom_link = ET.SubElement(channel, "{http://www.w3.org/2005/Atom}link")
    atom_link.set("href", feed_url)
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    for item in items:
        item_el = ET.SubElement(channel, "item")
        ET.SubElement(item_el, "title").text = item.title
        ET.SubElement(item_el, "link").text = item.link
        guid_el = ET.SubElement(item_el, "guid")
        guid_el.text = item.guid
        guid_el.set("isPermaLink", "true")
        ET.SubElement(item_el, "pubDate").text = item.pub_date
        if item.author:
            ET.SubElement(item_el, "author").text = item.author
        ET.SubElement(item_el, "description").text = build_item_description(item)
        if item.image_url:
            media_content = ET.SubElement(item_el, "{http://search.yahoo.com/mrss/}content")
            media_content.set("url", item.image_url)
            media_content.set("medium", "image")

    indent_xml(rss)
    xml_bytes = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    output_path.write_bytes(xml_bytes)


def infer_repo_feed_url(output_path: Path) -> str:
    owner_repo = None
    env_file = Path(".git/config")
    if env_file.exists():
        content = env_file.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"url\s*=\s*https://github\.com/([^/\s]+)/([^/\s]+?)(?:\.git)?\s*$", content, re.M)
        if match:
            owner_repo = (match.group(1), match.group(2))
    if not owner_repo:
        return f"https://<username>.github.io/<repo>/{output_path.name}"
    owner, repo = owner_repo
    return f"https://{owner}.github.io/{repo}/{output_path.name}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape Darkhorse Top Story and build RSS.")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=MAX_PAGES_TO_SCAN,
        help=f"Maximum listing pages to scan (default: {MAX_PAGES_TO_SCAN}).",
    )
    parser.add_argument(
        "--recent",
        type=int,
        default=RECENT_TO_INCLUDE,
        help=f"Number of most recent posts to include in feed (default: {RECENT_TO_INCLUDE}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"RSS output path (default: {OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=STATE_PATH,
        help=f"State file path (default: {STATE_PATH}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run scraper without writing state/feed files.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    state = load_state(args.state)
    seen_urls: set[str] = set(state["seen_urls"])
    state_items: dict[str, Any] = state["items"]

    discovered_urls = discover_listing_urls(session, CATEGORY_URL, max_pages=args.max_pages)
    if not discovered_urls:
        logging.warning("No URLs discovered from listing pages. Existing feed/state will be preserved.")
        return 0

    discovered_urls = [normalize_post_url(url) for url in discovered_urls]
    discovered_urls = list(dict.fromkeys(discovered_urls))

    new_urls = [url for url in discovered_urls if url not in seen_urls]
    logging.info("Discovered %s URLs (%s new)", len(discovered_urls), len(new_urls))

    # Start with cached items so we only fetch what is new.
    item_cache: dict[str, PostItem] = {}
    for link, item_data in state_items.items():
        item_cache[normalize_post_url(link)] = PostItem.from_state(item_data)

    for idx, url in enumerate(new_urls, start=1):
        logging.info("Scraping new post (%s/%s): %s", idx, len(new_urls), url)
        item = scrape_post(session, url)
        if item is None:
            logging.warning("Skipping failed post scrape: %s", url)
            continue
        item_cache[item.link] = item
        time.sleep(REQUEST_DELAY_SECONDS)

    # Build feed items based on current listing order, then sort by publish date.
    ordered_items: list[PostItem] = []
    for url in discovered_urls:
        norm = normalize_post_url(url)
        cached = item_cache.get(norm)
        if cached:
            ordered_items.append(cached)
    ordered_items = sort_items_newest_first(ordered_items)[: max(1, args.recent)]

    if not ordered_items:
        logging.warning("No feed items available after scrape. Existing feed/state will be preserved.")
        return 0

    # Refresh seen URLs with discovered + prior, keeping deterministic order.
    merged_seen_urls = list(dict.fromkeys(discovered_urls + state["seen_urls"]))
    merged_seen_urls = merged_seen_urls[: max(2000, args.recent * 20)]

    new_state_items = {item.link: item.as_state() for item in ordered_items}
    new_state = {
        "seen_urls": merged_seen_urls,
        "items": new_state_items,
        "last_run_utc": datetime.now(timezone.utc).isoformat(),
    }

    feed_url = infer_repo_feed_url(args.output)
    if args.dry_run:
        logging.info("Dry run enabled. Feed would write %s items to %s", len(ordered_items), args.output)
        logging.info("Dry run enabled. State would write to %s", args.state)
        return 0

    write_rss(args.output, ordered_items, feed_url=feed_url)
    save_state(args.state, new_state)
    logging.info("Wrote feed with %s items to %s", len(ordered_items), args.output)
    logging.info("Updated state at %s", args.state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
