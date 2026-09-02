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
* **stops dead** on any response that resembles rate limiting, rather than
  retrying into it (see :class:`RateLimited`).

Re-verified against the live ``robots.txt`` on 2026-08-12 before the bulk crawl:
byte-for-byte the same policy, same ``Crawl-delay: 10``, same four disallowed
paths.

The cache is a build artifact.  It is gitignored and must never be committed:
this repository distributes code, not a mirror of the state's statutes.

**Storage layout.**  Bodies are content-addressed: a body is written once to
``cache/objects/<first two hex>/<sha256>`` and the URL-keyed ``<key>.json``
metadata file points at it.  Two URLs serving identical bytes therefore cost one
copy on disk, and re-fetching a page whose content has not changed is detectable
without diffing -- the hash is the identity.  Metadata written before this
change stored the body beside it as ``<key>.body``; that layout is still read,
so an existing cache keeps working and is not re-fetched.
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


RATE_LIMIT_STATUSES = frozenset({429, 503, 509})
"""Statuses treated as "the server is asking us to stop".

429 and 503 are the explicit ones.  509 (Bandwidth Limit Exceeded) is
non-standard but means the same thing where it is served.  403 is handled
separately in :meth:`Fetcher.get`, because ilga.gov uses it for ordinary
authorisation too -- it counts as rate limiting only when the response carries a
``Retry-After`` header or a body that says so.
"""


class DisallowedURL(ValueError):
    """Raised when a URL would violate robots.txt or leave the allowed hosts."""


class FetchError(RuntimeError):
    """A network fetch failed after retries."""


class RateLimited(RuntimeError):
    """The server signalled rate limiting, throttling, or a block.

    This is deliberately **not** a subclass of :class:`FetchError`, and nothing
    in this codebase may catch it to retry.  ilga.gov is the only source of this
    data; there is no second publisher to fall back to and no way to earn back
    goodwill once it is spent.  A crawler that backs off and tries again is
    optimising for finishing the run, when the thing actually at risk is
    continued access.  So the rule is: one throttling signal ends the crawl,
    the queue is left resumable, and a human decides what happens next.
    """

    def __init__(self, url: str, status: int, retry_after: str | None = None) -> None:
        self.url = url
        self.status = status
        self.retry_after = retry_after
        detail = f" (Retry-After: {retry_after})" if retry_after else ""
        super().__init__(
            f"ilga.gov returned HTTP {status} for {url}{detail} -- "
            "this resembles rate limiting, so the crawl stops here rather than retrying"
        )


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


def content_hash(text: str) -> str:
    """The sha256 of a body, as stored. This is the object's identity."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Response:
    url: str
    status: int
    body: str
    from_cache: bool
    sha256: str | None = None
    """Content address of the body. ``None`` only for legacy cache entries
    written before the object store existed and not yet re-fetched."""
    revalidated: bool = False
    """True when the server answered 304 Not Modified: a network round trip
    happened, the bytes did not change, and nothing was rewritten."""
    changed: bool = False
    """True when a network fetch produced a body whose hash differs from the
    one previously cached for this URL. The whole point of a conditional,
    content-addressed refresh is that this is cheap to know."""


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
        self.objects_dir = self.cache_dir / "objects"
        self.fetched = 0
        self.served_from_cache = 0
        self.revalidated = 0
        self.changed = 0

    # -- content-addressed storage ----------------------------------------

    def _object_path(self, sha: str) -> Path:
        return self.objects_dir / sha[:2] / sha

    def _meta_path(self, url: str) -> Path:
        return self.cache_dir / (cache_key(url) + ".json")

    def _legacy_body_path(self, url: str) -> Path:
        return self.cache_dir / (cache_key(url) + ".body")

    def _read_meta(self, url: str) -> dict | None:
        try:
            return json.loads(self._meta_path(url).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _read_body(self, url: str, meta: dict) -> str | None:
        """Body for a cached entry, from either storage layout.

        The legacy ``<key>.body`` file wins when present so that a cache built
        before the object store is served without a re-fetch.
        """
        legacy = self._legacy_body_path(url)
        if legacy.exists():
            try:
                return legacy.read_text(encoding="utf-8")
            except OSError:
                return None
        sha = meta.get("sha256")
        if not sha:
            # A 404 or an unavailable-document placeholder is stored as an
            # empty body with no object; that is a real cached answer.
            return "" if meta.get("status") == 404 else None
        try:
            return self._object_path(sha).read_text(encoding="utf-8")
        except OSError:
            return None

    def _store(self, url: str, *, status: int, text: str, headers: dict[str, str]) -> str:
        """Write a body to the object store and its metadata beside the URL key.

        Returns the content hash.  Writing the object before the metadata means
        a crash between the two leaves an unreferenced object (harmless, and
        re-used on the next fetch of the same bytes) rather than metadata
        pointing at a body that is not there.
        """
        sha = content_hash(text)
        path = self._object_path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)
        meta = {
            "url": url,
            "status": status,
            "sha256": sha,
            "bytes": len(text),
            "fetched_at": time.time(),
            "validated_at": time.time(),
        }
        if etag := headers.get("ETag"):
            meta["etag"] = etag
        if last_modified := headers.get("Last-Modified"):
            meta["last_modified"] = last_modified
        self._meta_path(url).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return sha

    def _touch_validated(self, url: str, meta: dict) -> None:
        """Record that a 304 confirmed the cached copy is still current."""
        meta["validated_at"] = time.time()
        try:
            self._meta_path(url).write_text(json.dumps(meta, indent=2), encoding="utf-8")
        except OSError:
            pass

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

    def get(self, url: str, *, retries: int = 3, revalidate: bool = False) -> Response:
        """Fetch ``url``, serving from cache when possible.

        ``revalidate=True`` turns a cache hit into a **conditional** GET: the
        stored ``ETag`` / ``Last-Modified`` go out as ``If-None-Match`` /
        ``If-Modified-Since``, and a 304 costs one round trip and no bytes.
        This is the refresh path -- the first pass over the corpus leaves
        ``revalidate`` off, because a page already in the cache does not need
        re-asking at all.

        Raises :class:`RateLimited` immediately, without retrying, on any
        response that looks like throttling.
        """
        check_url(url)
        meta = self._read_meta(url)
        cached_body = self._read_body(url, meta) if meta is not None else None
        have_cache = meta is not None and cached_body is not None

        if have_cache and not revalidate:
            self.served_from_cache += 1
            return Response(
                url=url,
                status=meta["status"],
                body=cached_body,
                from_cache=True,
                sha256=meta.get("sha256"),
            )
        if self.offline:
            raise FetchError(f"offline and {url} is not cached")

        conditional: dict[str, str] = {}
        if have_cache:
            if etag := meta.get("etag"):
                conditional["If-None-Match"] = etag
            if last_modified := meta.get("last_modified"):
                conditional["If-Modified-Since"] = last_modified

        last_error: Exception | None = None
        for attempt in range(retries):
            self._wait_turn()
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **conditional})
            try:
                if self.verbose:
                    print(f"    [fetch] {url}", flush=True)
                with urllib.request.urlopen(request, timeout=60) as resp:
                    raw = resp.read()
                    status = resp.status
                    headers = dict(resp.headers.items())
                self._stamp()
                text = raw.decode("utf-8", errors="replace").lstrip("﻿")
                previous = meta.get("sha256") if meta else None
                sha = self._store(url, status=status, text=text, headers=headers)
                self.fetched += 1
                changed = previous is not None and previous != sha
                if changed:
                    self.changed += 1
                return Response(
                    url=url,
                    status=status,
                    body=text,
                    from_cache=False,
                    sha256=sha,
                    changed=changed,
                )
            except urllib.error.HTTPError as exc:
                self._stamp()
                if _is_rate_limiting(exc):
                    # Deliberately raised out of the retry loop, not into it.
                    raise RateLimited(
                        url, exc.code, exc.headers.get("Retry-After") if exc.headers else None
                    ) from exc
                if exc.code == 304 and have_cache:
                    # The cached copy is still current. No bytes moved.
                    self._touch_validated(url, meta)
                    self.revalidated += 1
                    return Response(
                        url=url,
                        status=meta["status"],
                        body=cached_body,
                        from_cache=True,
                        sha256=meta.get("sha256"),
                        revalidated=True,
                    )
                if exc.code == 404:
                    # A 404 is a real, cacheable answer -- some DocNames simply
                    # do not exist.  Caching it keeps re-runs from re-asking.
                    self._store(url, status=404, text="", headers={})
                    self.fetched += 1
                    return Response(
                        url=url, status=404, body="", from_cache=False, sha256=content_hash("")
                    )
                last_error = exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self._stamp()
                last_error = exc
            if self.verbose:
                print(f"    [retry {attempt + 1}/{retries}] {last_error}", flush=True)
            if attempt + 1 < retries:
                time.sleep(min(30.0, self.crawl_delay * (attempt + 1)))
        raise FetchError(f"{url}: {last_error}")


_RATE_LIMIT_BODY_RE = re.compile(
    r"rate[ -]?limit|too many requests|slow down|temporarily blocked|access denied", re.I
)


def _is_rate_limiting(exc: urllib.error.HTTPError) -> bool:
    """Does this error response mean "stop crawling"?

    Errs towards yes.  A false positive costs one aborted run that resumes
    exactly where it stopped; a false negative costs the project its only data
    source.  Those are not symmetric, so the test is not symmetric either.
    """
    if exc.code in RATE_LIMIT_STATUSES:
        return True
    if exc.headers is not None and exc.headers.get("Retry-After"):
        return True
    if exc.code == 403:
        # 403 is ambiguous on its own. Read a little of the body to see whether
        # it is an authorisation refusal or a bot block.
        try:
            body = exc.read(4096).decode("utf-8", errors="replace")
        except Exception:
            return True  # cannot tell: assume the expensive-to-be-wrong case
        return bool(_RATE_LIMIT_BODY_RE.search(body))
    return False


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
