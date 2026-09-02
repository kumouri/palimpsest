"""A polite, cached fetcher for ilga.gov.

The constraints implemented here are not suggestions; they are read directly off
`https://www.ilga.gov/robots.txt` (verified 2026-08-11):

    User-agent: *
    Disallow: /account
    Disallow: /admin
    Disallow: /search
    Disallow: /api
    Crawl-delay: 10

So this module:

* refuses, in code, to construct a request against a disallowed path -- ``/search``
  and ``/api`` in particular, which are the two an ingest pipeline would be tempted
  to use.  Enumeration goes through the chapter/act index pages instead.
* sleeps so that no two *network* requests leave this machine less than
  ``CRAWL_DELAY`` seconds apart.  The clock is stored on disk, so the delay is
  honoured across separate runs of the program too, not merely within one process.
* sends an identifying User-Agent with a contact URL.
* caches every response body on disk keyed by URL, so a re-run costs zero fetches.

The cache is a build artifact.  It is gitignored and must never be committed:
this repository distributes code, not a mirror of the state's statutes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CRAWL_DELAY = 10.0
"""Seconds between network requests. From robots.txt. Do not lower this."""

USER_AGENT = (
    "palimpsest-oracle/0.1 (+https://github.com/kumouri/palimpsest; "
    "statutory reconstruction research; respects robots.txt Crawl-delay: 10)"
)

DISALLOWED_PREFIXES = ("/account", "/admin", "/search", "/api")
"""Path prefixes robots.txt disallows for all agents. Matched case-insensitively."""

ALLOWED_HOSTS = ("ilga.gov", "www.ilga.gov")

DEFAULT_CACHE = Path(os.environ.get("PALIMPSEST_CACHE", "cache"))


class DisallowedURL(ValueError):
    """Raised when a URL would violate robots.txt or leave the allowed hosts."""


class FetchError(RuntimeError):
    """A network fetch failed after retries."""


def check_url(url: str) -> str:
    """Validate a URL against robots.txt and the host allowlist.

    Returns the URL unchanged if it is fetchable; raises :class:`DisallowedURL`
    otherwise.  Exposed separately from :func:`Fetcher.get` so tests can assert
    the policy without touching the network.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise DisallowedURL(f"not an http(s) URL: {url!r}")
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise DisallowedURL(f"host {host!r} is not in the allowlist {ALLOWED_HOSTS}")
    path = parts.path.lower()
    for bad in DISALLOWED_PREFIXES:
        if path == bad or path.startswith(bad + "/") or path.startswith(bad + "."):
            raise DisallowedURL(f"robots.txt disallows {bad!r} for all agents; refusing {url!r}")
    return url


def cache_key(url: str) -> str:
    """Stable on-disk key for a URL. Readable prefix + hash, so a cache
    directory can be eyeballed without being ambiguous."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    tail = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1] or "index"
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in tail)[:48]
    return f"{safe}.{digest}"


@dataclass
class Response:
    url: str
    status: int
    body: str
    from_cache: bool


class Fetcher:
    """Cached, rate-limited HTTP GET against ilga.gov."""

    def __init__(
        self,
        cache_dir: Path | str = DEFAULT_CACHE,
        *,
        crawl_delay: float = CRAWL_DELAY,
        offline: bool = False,
        verbose: bool = True,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.crawl_delay = crawl_delay
        self.offline = offline
        self.verbose = verbose
        self._clock = self.cache_dir / ".last-fetch"
        self.fetched = 0
        self.served_from_cache = 0

    # -- rate limiting ----------------------------------------------------

    def _wait_turn(self) -> None:
        """Block until ``crawl_delay`` has elapsed since the last network fetch.

        The timestamp lives on disk so that two runs started back to back still
        honour the delay between them.
        """
        try:
            last = float(self._clock.read_text())
        except (OSError, ValueError):
            last = 0.0
        remaining = self.crawl_delay - (time.time() - last)
        if remaining > 0:
            if self.verbose:
                print(f"    [crawl-delay] sleeping {remaining:.1f}s", flush=True)
            time.sleep(remaining)

    def _stamp(self) -> None:
        try:
            self._clock.write_text(str(time.time()))
        except OSError:
            pass

    # -- fetching ---------------------------------------------------------

    def get(self, url: str, *, retries: int = 3) -> Response:
        check_url(url)
        body_path = self.cache_dir / (cache_key(url) + ".body")
        meta_path = self.cache_dir / (cache_key(url) + ".json")
        if body_path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.served_from_cache += 1
            return Response(
                url=url,
                status=meta["status"],
                body=body_path.read_text(encoding="utf-8"),
                from_cache=True,
            )
        if self.offline:
            raise FetchError(f"offline and {url} is not cached")

        last_error: Exception | None = None
        for attempt in range(retries):
            self._wait_turn()
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                if self.verbose:
                    print(f"    [fetch] {url}", flush=True)
                with urllib.request.urlopen(request, timeout=60) as resp:
                    raw = resp.read()
                    status = resp.status
                self._stamp()
                text = raw.decode("utf-8", errors="replace").lstrip("﻿")
                meta = {"url": url, "status": status, "fetched_at": time.time()}
                body_path.write_text(text, encoding="utf-8")
                meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                self.fetched += 1
                return Response(url=url, status=status, body=text, from_cache=False)
            except urllib.error.HTTPError as exc:
                self._stamp()
                if exc.code == 404:
                    # A 404 is a real, cacheable answer -- some DocNames simply
                    # do not exist.  Caching it keeps re-runs from re-asking.
                    text = ""
                    meta = {"url": url, "status": 404, "fetched_at": time.time()}
                    body_path.write_text(text, encoding="utf-8")
                    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                    self.fetched += 1
                    return Response(url=url, status=404, body="", from_cache=False)
                last_error = exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self._stamp()
                last_error = exc
            if self.verbose:
                print(f"    [retry {attempt + 1}/{retries}] {last_error}", flush=True)
            time.sleep(min(30.0, self.crawl_delay * (attempt + 1)))
        raise FetchError(f"{url}: {last_error}")


_SOFT_404_RE = re.compile(r"Document:\s*[0-9A-Za-z\-]+\s*is not currently available", re.I)


def is_soft_404(body: str) -> bool:
    """True if the page is ilga.gov's "not currently available" placeholder.

    Public Acts from before roughly the 90th General Assembly are not online.
    Asking for one does **not** return 404 -- it returns **HTTP 200** with a
    128-byte body reading ``Document: 86-0451 is not currently available.``  A
    crawler that trusts the status code records a successful fetch of an empty
    Act and then reports "the Act does not contain this section", which
    misattributes a corpus-coverage floor as a parser failure.  This is the
    difference between "we cannot see it" and "we looked and it was not there",
    and the two must never be counted in the same bucket.
    """
    return bool(_SOFT_404_RE.search(body))


# -- URL builders -------------------------------------------------------------
#
# All of these live under paths robots.txt permits.  None of them touch /search
# or /api.


def ilcs_section_url(doc_name: str) -> str:
    """Static document route for one compiled ILCS section.

    ``doc_name`` is ILGA's own key: 4-digit chapter + 5-digit act + ``K`` +
    section number, e.g. ``000500700K4`` for 5 ILCS 70/4.
    """
    return f"https://www.ilga.gov/documents/legislation/ilcs/documents/{doc_name}.htm"


def public_act_url(pa_number: str) -> str:
    """Printer-friendly HTML for a Public Act, e.g. ``103-0565``."""
    return f"https://www.ilga.gov/Legislation/PublicActs/PrinterFriendly/{pa_number}"


def ilcs_articles_url(act_id: str | int, chapter_id: str | int = 0) -> str:
    """Index of articles/sections within one ILCS Act (enumeration entry point)."""
    return (
        f"https://www.ilga.gov/Legislation/ILCS/Articles" f"?ActID={act_id}&ChapterID={chapter_id}"
    )


def ilcs_acts_url(chapter_id: str | int) -> str:
    """Index of Acts within one ILCS chapter."""
    return f"https://www.ilga.gov/Legislation/ILCS/Acts?ChapterID={chapter_id}"
