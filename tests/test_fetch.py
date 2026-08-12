"""Tests for the fetcher's robots.txt policy and its cache.

None of these touch the network. The point of the first class is that the
robots.txt constraints are enforced *in code* and are therefore testable, rather
than living in a comment that a future change can quietly violate.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from palimpsest.fetch import (
    CRAWL_DELAY,
    USER_AGENT,
    DisallowedURL,
    Fetcher,
    FetchError,
    cache_key,
    check_url,
    ilcs_articles_url,
    ilcs_section_url,
    is_soft_404,
    public_act_url,
)


class TestRobotsPolicy(unittest.TestCase):
    def test_search_and_api_are_refused(self):
        # robots.txt: 'Disallow: /search' and 'Disallow: /api' for User-agent: *
        for url in (
            "https://www.ilga.gov/search",
            "https://www.ilga.gov/search?q=election",
            "https://www.ilga.gov/api/legislation",
            "https://ilga.gov/API/Something",
            "https://www.ilga.gov/admin/panel",
            "https://www.ilga.gov/account/login",
        ):
            with self.subTest(url=url), self.assertRaises(DisallowedURL):
                check_url(url)

    def test_the_routes_the_pipeline_actually_uses_are_allowed(self):
        for url in (
            ilcs_section_url("000500700K4"),
            public_act_url("103-0565"),
            ilcs_articles_url(79, 2),
            "https://www.ilga.gov/Legislation/ILCS/Chapters",
            "https://www.ilga.gov/legislation/ILCS/details?ActID=170&ChapAct=FullText",
        ):
            with self.subTest(url=url):
                self.assertEqual(check_url(url), url)

    def test_other_hosts_are_refused(self):
        for url in ("https://example.com/statutes", "https://lrb.ilga.gov/x.pdf"):
            with self.subTest(url=url), self.assertRaises(DisallowedURL):
                check_url(url)

    def test_non_http_schemes_are_refused(self):
        with self.assertRaises(DisallowedURL):
            check_url("file:///etc/passwd")

    def test_a_path_merely_starting_with_the_same_letters_is_allowed(self):
        # '/searchable-thing' is not '/search'.
        self.assertTrue(check_url("https://www.ilga.gov/searchable"))

    def test_crawl_delay_is_the_robots_value(self):
        self.assertEqual(CRAWL_DELAY, 10.0)

    def test_user_agent_identifies_the_project_and_a_contact(self):
        self.assertIn("palimpsest", USER_AGENT)
        self.assertIn("https://", USER_AGENT)


class TestSoft404(unittest.TestCase):
    def test_the_not_available_placeholder_is_detected(self):
        body = (
            '<title>Public Acts - 96-0542</title>\r\n<div translate="no">\r\n'
            "    <b>Document: 96-0542 is not currently available.</b><br>\r\n</div>"
        )
        self.assertTrue(is_soft_404(body))

    def test_a_real_act_is_not_a_soft_404(self):
        self.assertFalse(is_soft_404("<b>Public Act 103-0565</b> AN ACT concerning"))


class TestCache(unittest.TestCase):
    def test_cache_key_is_stable_and_distinct(self):
        a = cache_key("https://www.ilga.gov/x/1")
        self.assertEqual(a, cache_key("https://www.ilga.gov/x/1"))
        self.assertNotEqual(a, cache_key("https://www.ilga.gov/x/2"))

    def test_cache_key_is_a_safe_filename(self):
        key = cache_key("https://www.ilga.gov/legislation/ILCS/details?A=1&B=2/3")
        self.assertNotIn("/", key)
        self.assertNotIn("?", key)
        self.assertNotIn("&", key)

    def test_offline_fetcher_serves_a_cached_body_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            url = public_act_url("103-0565")
            fetcher = Fetcher(tmp, offline=True, verbose=False)
            body_path = Path(tmp) / (cache_key(url) + ".body")
            meta_path = Path(tmp) / (cache_key(url) + ".json")
            body_path.write_text("AN ACT concerning local government.", encoding="utf-8")
            meta_path.write_text('{"status": 200}', encoding="utf-8")

            resp = fetcher.get(url)
            self.assertTrue(resp.from_cache)
            self.assertEqual(resp.status, 200)
            self.assertIn("AN ACT", resp.body)
            self.assertEqual(fetcher.fetched, 0)
            self.assertEqual(fetcher.served_from_cache, 1)

    def test_offline_fetcher_refuses_to_invent_an_uncached_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = Fetcher(tmp, offline=True, verbose=False)
            with self.assertRaises(FetchError):
                fetcher.get(public_act_url("104-0001"))

    def test_offline_fetcher_still_enforces_robots(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = Fetcher(tmp, offline=True, verbose=False)
            with self.assertRaises(DisallowedURL):
                fetcher.get("https://www.ilga.gov/api/acts")


class TestRateLimit(unittest.TestCase):
    def test_the_delay_clock_persists_on_disk_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Fetcher(tmp, crawl_delay=0.2, verbose=False)
            first._stamp()
            stamped = float((Path(tmp) / ".last-fetch").read_text())
            self.assertLess(abs(stamped - time.time()), 5)

            # A brand new Fetcher over the same cache must wait out the delay
            # left by the previous one, not start from zero.
            started = time.monotonic()
            Fetcher(tmp, crawl_delay=0.2, verbose=False)._wait_turn()
            self.assertGreater(time.monotonic() - started, 0.05)


class TestUrlBuilders(unittest.TestCase):
    def test_section_url_uses_the_static_document_route(self):
        self.assertEqual(
            ilcs_section_url("000500700K4"),
            "https://www.ilga.gov/documents/legislation/ilcs/documents/000500700K4.htm",
        )

    def test_public_act_url(self):
        self.assertTrue(public_act_url("103-0565").endswith("/PrinterFriendly/103-0565"))


if __name__ == "__main__":
    unittest.main()
