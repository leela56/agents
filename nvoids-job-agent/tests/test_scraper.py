"""Unit tests for app.scraper. Pure HTML/string-level tests — no network IO."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.scraper import (
    DEFAULT_KEYWORDS,
    decode_cf_email,
    fetch_job_details,
    fetch_search_results,
    is_match,
)


# Known Cloudflare-obfuscated email hex (shape-only assertions).
CF_HEX = "6715060d120c0615121504550427000a060e0b4904080a"


def test_decode_cf_email_known():
    decoded = decode_cf_email(CF_HEX)
    assert isinstance(decoded, str)
    assert "@" in decoded
    local, _, domain = decoded.partition("@")
    assert local, "local part should be non-empty"
    assert "." in domain, "domain should contain at least one dot"
    after_dot = domain.rsplit(".", 1)[-1]
    assert len(after_dot) >= 2


def test_decode_cf_email_empty():
    assert decode_cf_email("") == ""
    # Also: malformed short string should not blow up
    assert decode_cf_email("a") == ""


def test_is_match_positive_negative():
    assert is_match("AWS Data Engineer - Malvern, PA") is True
    assert is_match("Java Solution Architect") is False
    assert is_match("Senior Databricks Engineer") is True
    # Empty inputs
    assert is_match("") is False
    # Uses default keywords when none provided
    assert is_match("ETL Developer needed") is True
    # Custom keywords
    assert is_match("Python Guru", keywords=["python"]) is True


def _mock_response(html: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.text = html
    resp.status_code = status
    resp.raise_for_status = MagicMock()
    return resp


SEARCH_HTML = """
<html><body>
<table>
  <tr><th>Title</th><th>Location</th><th>Posted</th></tr>
  <tr>
    <td><a href="job_details.jsp?id=3321105&amp;uid=d8837e4d006148d2b644f3bacb44a4dc">Senior Data Engineer</a></td>
    <td>Malvern, Pennsylvania, USA</td>
    <td>10:05 PM 23-Apr-26</td>
  </tr>
  <tr>
    <td>Some footer text</td>
    <td>Nowhere</td>
    <td>--</td>
  </tr>
</table>
</body></html>
"""


def test_parse_search_results_from_html():
    with patch("app.scraper.requests.get", return_value=_mock_response(SEARCH_HTML)):
        results = fetch_search_results()

    assert len(results) == 1
    r = results[0]
    assert r.job_id == "3321105"
    assert r.uid == "d8837e4d006148d2b644f3bacb44a4dc"
    assert r.title == "Senior Data Engineer"
    assert r.location == "Malvern, Pennsylvania, USA"
    assert r.posted_at == "10:05 PM 23-Apr-26"
    assert r.url.endswith(
        "job_details.jsp?id=3321105&uid=d8837e4d006148d2b644f3bacb44a4dc"
    )
    assert r.url.startswith("http")


DETAILS_HTML = f"""
<html><head><title>Senior Data Engineer</title></head><body>
<h1>Senior Data Engineer</h1>
<table>
  <tr><td>Location</td><td>Malvern, Pennsylvania, USA</td></tr>
</table>
<p>Contact us:</p>
<a href="mailto:Hello@Example.com">Hello@Example.com</a>
<a href="/cdn-cgi/l/email-protection#{CF_HEX}">[email&nbsp;protected]</a>
<span class="__cf_email__" data-cfemail="{CF_HEX}">[email&nbsp;protected]</span>
<p>Also reach recruiter@corp.io for details.</p>
</body></html>
"""


def test_parse_job_details_with_cf_email():
    url = "https://nvoids.com/job_details.jsp?id=3321105&uid=abc123"
    with patch("app.scraper.requests.get", return_value=_mock_response(DETAILS_HTML)):
        details = fetch_job_details(url)

    assert details.job_id == "3321105"
    assert details.title == "Senior Data Engineer"
    assert details.location == "Malvern, Pennsylvania, USA"

    assert len(details.emails) >= 2
    for e in details.emails:
        assert e == e.lower(), f"email {e!r} not lowercased"
        assert "@" in e
        _, _, domain = e.partition("@")
        assert "." in domain

    # mailto email normalized to lowercase
    assert "hello@example.com" in details.emails
    # regex-swept fallback email also captured
    assert "recruiter@corp.io" in details.emails

    # raw_text populated and bounded
    assert details.raw_text
    assert len(details.raw_text) <= 20000


def test_default_keywords_exposed():
    # Sanity: module exposes keyword list for downstream use
    assert "data engineer" in DEFAULT_KEYWORDS
    assert "databricks" in DEFAULT_KEYWORDS
