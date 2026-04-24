"""Scraper for nvoids.com job listings.

Public API:
    - JobListing, JobDetails dataclasses
    - DEFAULT_KEYWORDS, SEARCH_URL constants
    - decode_cf_email(encoded_hex)
    - fetch_search_results(search_url, timeout)
    - fetch_job_details(job_url, timeout)
    - is_match(title, keywords)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SEARCH_URL = "https://nvoids.com/search_sph.jsp"

DEFAULT_KEYWORDS: list[str] = [
    # core data engineering titles
    "data engineer",
    "dataengineer",  # seen in postings like "Azure DataEngineer"
    "lead data engineer",
    "senior data engineer",
    "sr data engineer",
    "sr. data engineer",
    "principal data engineer",
    "staff data engineer",
    "data engineering",
    "data platform",
    "data pipeline",
    "data warehouse",
    "data lake",
    "lakehouse",
    "analytics engineer",
    "bi engineer",
    "business intelligence engineer",
    # pipeline / ETL
    "etl developer",
    "etl engineer",
    "data integration",
    # tech-stack keywords strongly associated with data engineering roles
    "databricks",
    "snowflake",
    "dbt",
    "pyspark",
    "apache spark",
    "redshift",
    "bigquery",
    "iceberg",
    "hadoop",
    # adjacent roles you asked to include
    "ml engineer",
    "machine learning engineer",
    "mlops",
    "ai/ml",
    "ai-ml",
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Regex for raw email sweep over visible text. Intentionally conservative.
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)

# Regex for a "City, Region, Country" style location line (e.g. "Malvern, Pennsylvania, USA").
_LOCATION_RE = re.compile(
    r"^[A-Za-z][A-Za-z .'\-]+,\s*[A-Za-z][A-Za-z .'\-]+,\s*[A-Za-z]{2,}$"
)


@dataclass
class JobListing:
    job_id: str
    uid: str
    title: str
    location: str
    posted_at: str
    url: str


@dataclass
class JobDetails:
    job_id: str
    title: str
    location: str
    emails: list[str] = field(default_factory=list)
    raw_text: str = ""


def decode_cf_email(encoded_hex: str) -> str:
    """Decode a Cloudflare-obfuscated email hex string.

    Returns the decoded email, or "" if input is empty/invalid.
    """
    if not encoded_hex or len(encoded_hex) < 4 or len(encoded_hex) % 2 != 0:
        return ""
    try:
        key = int(encoded_hex[0:2], 16)
        chars = []
        for i in range(2, len(encoded_hex), 2):
            chars.append(chr(int(encoded_hex[i : i + 2], 16) ^ key))
        return "".join(chars)
    except ValueError:
        return ""


def _extract_query_param(url: str, name: str) -> str:
    try:
        qs = parse_qs(urlparse(url).query)
        vals = qs.get(name) or []
        return vals[0] if vals else ""
    except Exception:
        return ""


def _is_valid_email(candidate: str) -> bool:
    if not candidate or "@" not in candidate:
        return False
    local, _, domain = candidate.partition("@")
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    # domain must have at least one char before and after the last dot
    if domain.startswith(".") or domain.endswith("."):
        return False
    return True


def is_match(title: str, keywords: Iterable[str] = DEFAULT_KEYWORDS) -> bool:
    """Case-insensitive substring match of any keyword in title."""
    if not title:
        return False
    title_lc = title.lower()
    for kw in keywords:
        if kw and kw.lower() in title_lc:
            return True
    return False


def _get(url: str, timeout: float) -> requests.Response:
    resp = requests.get(url, headers=_DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp


# hotlist values on nvoids' search form:
#   "0" = Include Hotlists, "1" = Exclude Hotlists, "2" = Only Hotlists
_HOTLIST_EXCLUDE = "1"


def fetch_search_results(
    search_url: str = SEARCH_URL,
    timeout: float = 20.0,
    search_val: str = "data engineer",
    hotlist: str = _HOTLIST_EXCLUDE,
) -> list[JobListing]:
    """Fetch and parse the main search results table.

    nvoids' search form is a POST; a plain GET returns whatever search string
    the server is currently caching (it appears to be process-global), which
    makes results non-deterministic. Always POST the intended search_val so
    we get a stable, fresh 100-row window matching our keyword.
    """
    data = {"search_val": search_val, "hotlist": hotlist}
    resp = requests.post(
        search_url, data=data, headers=_DEFAULT_HEADERS, timeout=timeout
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return _parse_search_results(soup, base_url=search_url)


def _parse_search_results(soup: BeautifulSoup, base_url: str) -> list[JobListing]:
    listings: list[JobListing] = []

    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 3:
            continue
        # Find anchor pointing to job_details.jsp in any cell (typically first).
        anchor = None
        for cell in cells:
            a = cell.find("a", href=True)
            if a and "job_details.jsp" in a["href"]:
                anchor = a
                break
        if anchor is None:
            continue

        href = anchor["href"]
        absolute_url = urljoin(base_url, href)
        title = anchor.get_text(strip=True)
        job_id = _extract_query_param(absolute_url, "id")
        uid = _extract_query_param(absolute_url, "uid")

        # Heuristic: title cell is the one that contained the anchor; remaining
        # cells (in document order) are location and posted_at.
        title_cell = anchor.find_parent(["td", "th"])
        remaining = [c for c in cells if c is not title_cell]
        location = remaining[0].get_text(" ", strip=True) if len(remaining) >= 1 else ""
        posted_at = remaining[1].get_text(" ", strip=True) if len(remaining) >= 2 else ""

        listings.append(
            JobListing(
                job_id=job_id,
                uid=uid,
                title=title,
                location=location,
                posted_at=posted_at,
                url=absolute_url,
            )
        )

    return listings


def fetch_job_details(job_url: str, timeout: float = 20.0) -> JobDetails:
    """Fetch a job_details.jsp page and extract structured fields + emails."""
    resp = _get(job_url, timeout=timeout)
    soup = BeautifulSoup(resp.text, "html.parser")
    return _parse_job_details(soup, job_url=job_url)


def _parse_job_details(soup: BeautifulSoup, job_url: str) -> JobDetails:
    job_id = _extract_query_param(job_url, "id")
    emails: list[str] = []

    # 1. mailto: links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            addr = href.split(":", 1)[1]
            addr = addr.split("?", 1)[0].strip()
            if addr:
                emails.append(addr)

    # 2. Cloudflare-protected links: /cdn-cgi/l/email-protection#<hex>
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/cdn-cgi/l/email-protection" in href and "#" in href:
            hex_part = href.split("#", 1)[1]
            decoded = decode_cf_email(hex_part)
            if decoded:
                emails.append(decoded)

    # 3. Cloudflare-obfuscated spans
    for span in soup.find_all(class_="__cf_email__"):
        hex_part = span.get("data-cfemail", "")
        decoded = decode_cf_email(hex_part)
        if decoded:
            emails.append(decoded)

    # Remove cloudflare email spans before reading visible text to avoid
    # "[email protected]" placeholder leaking into raw_text regex sweep.
    visible_text = soup.get_text(" ", strip=True)

    # 4. Regex sweep over visible text
    for match in _EMAIL_RE.findall(visible_text):
        emails.append(match)

    # Normalize: lowercase, filter invalid, dedupe preserving order.
    seen: set[str] = set()
    clean_emails: list[str] = []
    for e in emails:
        e_lc = e.strip().lower()
        if not _is_valid_email(e_lc):
            continue
        if e_lc in seen:
            continue
        seen.add(e_lc)
        clean_emails.append(e_lc)

    # Title
    title = ""
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)
    if not title:
        t = soup.find("title")
        if t and t.get_text(strip=True):
            title = t.get_text(strip=True)
    if not title:
        # First table cell with an anchor back to job_details.jsp
        for a in soup.find_all("a", href=True):
            if "job_details.jsp" in a["href"]:
                txt = a.get_text(strip=True)
                if txt:
                    title = txt
                    break

    # Location: look through table cells and text lines for the pattern.
    location = ""
    for cell in soup.find_all(["td", "th", "li", "p", "span", "div"]):
        txt = cell.get_text(" ", strip=True)
        if txt and _LOCATION_RE.match(txt):
            location = txt
            break
    if not location:
        for line in visible_text.splitlines():
            line = line.strip()
            if _LOCATION_RE.match(line):
                location = line
                break

    raw_text = visible_text[:20000]

    return JobDetails(
        job_id=job_id,
        title=title,
        location=location,
        emails=clean_emails,
        raw_text=raw_text,
    )
