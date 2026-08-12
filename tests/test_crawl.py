"""Tests for the bulk crawler: the rate-limit stop, the mirror layout, the queue.

Nothing here touches the network.  The fetcher is driven through a fake
``urlopen`` so that the behaviours which only ever fire against a live, unhappy
server -- a 429, a 304, a body that changed underneath us -- are testable at all.
That matters more here than elsewhere in this repo: the rate-limit stop is a
path that must work correctly the *first* time it is ever exercised for real,
because by then the crawl is already in trouble.
"""

from __future__ import annotations

import email.message
import io
import json
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from palimpsest import crawl
from palimpsest.crawl import (
    FLOOR_GA,
    FLOOR_PROBE,
    Item,
    Progress,
    Queue,
    _act_key,
    _fmt_duration,
    _is_done,
    status_markdown,
)
from palimpsest.fetch import (
    Fetcher,
    RateLimited,
    cache_key,
    content_hash,
    ilcs_articles_url,
    public_act_url,
)
from palimpsest.sample import ga_of


def _headers(**pairs: str) -> email.message.Message:
    message = email.message.Message()
    for key, value in pairs.items():
        message[key.replace("_", "-")] = value
    return message


class _FakeResponse:
    def __init__(self, body: str, status: int = 200, **headers: str) -> None:
        self._body = body.encode("utf-8")
        self.status = status
        self.headers = _headers(**headers)

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _http_error(code: int, body: str = "", **headers: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://www.ilga.gov/x", code, "nope", _headers(**headers), io.BytesIO(body.encode())
    )


def _fetcher(tmp: str) -> Fetcher:
    # crawl_delay=0 so the tests do not actually wait; the delay itself is
    # covered by test_fetch.TestRateLimit.
    return Fetcher(tmp, crawl_delay=0.0, verbose=False)


class TestRateLimitStopsTheCrawl(unittest.TestCase):
    """The single most important behaviour in the module.

    Being blocked from ilga.gov is unrecoverable -- there is no second source --
    so a throttling signal must abort rather than retry, and must be
    distinguishable from an ordinary failure.
    """

    def test_429_and_503_raise_immediately_without_retrying(self):
        for status in (429, 503, 509):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                fetcher = _fetcher(tmp)
                opener = mock.Mock(side_effect=_http_error(status))
                with (
                    mock.patch("palimpsest.fetch.urllib.request.urlopen", opener),
                    self.assertRaises(RateLimited) as caught,
                ):
                    fetcher.get(public_act_url("103-0565"), retries=3)
                # One attempt, not three: the retry loop must not run.
                self.assertEqual(opener.call_count, 1)
                self.assertEqual(caught.exception.status, status)

    def test_rate_limited_is_not_a_fetcherror_so_it_cannot_be_swallowed(self):
        from palimpsest.fetch import FetchError

        self.assertFalse(issubclass(RateLimited, FetchError))

    def test_a_retry_after_header_on_any_status_counts_as_throttling(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            error = _http_error(500, retry_after="120")
            with (
                mock.patch("palimpsest.fetch.urllib.request.urlopen", side_effect=error),
                self.assertRaises(RateLimited) as caught,
            ):
                fetcher.get(public_act_url("103-0565"))
            self.assertEqual(caught.exception.retry_after, "120")

    def test_a_403_that_says_it_is_a_block_counts_as_throttling(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            error = _http_error(403, "Access denied: automated traffic detected")
            with (
                mock.patch("palimpsest.fetch.urllib.request.urlopen", side_effect=error),
                self.assertRaises(RateLimited),
            ):
                fetcher.get(public_act_url("103-0565"))

    def test_an_ordinary_500_still_retries_and_then_fails_normally(self):
        from palimpsest.fetch import FetchError

        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            opener = mock.Mock(side_effect=_http_error(500))
            with (
                mock.patch("palimpsest.fetch.urllib.request.urlopen", opener),
                self.assertRaises(FetchError),
            ):
                fetcher.get(public_act_url("103-0565"), retries=2)
            self.assertEqual(opener.call_count, 2)

    def test_the_run_loop_lets_rate_limited_escape(self):
        """``run`` catches FetchError but must never catch RateLimited."""
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            queue = Queue(built_at=time.time(), items=[_pa_item("103-0565")])
            with (
                mock.patch("palimpsest.fetch.urllib.request.urlopen", side_effect=_http_error(429)),
                self.assertRaises(RateLimited),
            ):
                crawl.run(
                    fetcher,
                    queue,
                    deadline=time.time() + 60,
                    status_paths=[Path(tmp) / "status.md"],
                    queue_path=Path(tmp) / "queue.json",
                    stop_file=Path(tmp) / "STOP",
                )
            # The status file is written before the exception leaves, so the
            # abort is on the record rather than only in a traceback.
            self.assertIn("RATE LIMITED", (Path(tmp) / "status.md").read_text(encoding="utf-8"))


def _pa_item(number: str, tier: int = 0) -> Item:
    return Item(
        kind=crawl.KIND_PUBLIC_ACT,
        url=public_act_url(number),
        tier=tier,
        label=f"P.A. {number}",
        pa_number=number,
    )


class TestContentAddressedMirror(unittest.TestCase):
    def test_a_body_is_stored_under_its_hash_and_the_meta_points_at_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            url = public_act_url("103-0565")
            with mock.patch(
                "palimpsest.fetch.urllib.request.urlopen",
                return_value=_FakeResponse("AN ACT concerning elections."),
            ):
                response = fetcher.get(url)
            expected = content_hash("AN ACT concerning elections.")
            self.assertEqual(response.sha256, expected)
            self.assertTrue((Path(tmp) / "objects" / expected[:2] / expected).exists())
            meta = json.loads((Path(tmp) / (cache_key(url) + ".json")).read_text())
            self.assertEqual(meta["sha256"], expected)

    def test_two_urls_with_identical_bytes_share_one_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            with mock.patch(
                "palimpsest.fetch.urllib.request.urlopen",
                return_value=_FakeResponse("identical"),
            ):
                fetcher.get(public_act_url("103-0565"))
                fetcher.get(public_act_url("103-0566"))
            objects = list((Path(tmp) / "objects").rglob("*"))
            self.assertEqual(len([o for o in objects if o.is_file()]), 1)

    def test_a_legacy_dot_body_cache_entry_is_still_served(self):
        """An existing 119 MB cache predates the object store. It must not re-fetch."""
        with tempfile.TemporaryDirectory() as tmp:
            url = public_act_url("103-0565")
            (Path(tmp) / (cache_key(url) + ".body")).write_text("legacy body", encoding="utf-8")
            (Path(tmp) / (cache_key(url) + ".json")).write_text('{"status": 200}', encoding="utf-8")
            fetcher = Fetcher(tmp, offline=True, verbose=False)
            response = fetcher.get(url)
            self.assertEqual(response.body, "legacy body")
            self.assertTrue(response.from_cache)

    def test_a_changed_body_is_detected_by_hash_on_revalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            url = public_act_url("103-0565")
            with mock.patch(
                "palimpsest.fetch.urllib.request.urlopen", return_value=_FakeResponse("first")
            ):
                first = fetcher.get(url)
            self.assertFalse(first.changed)
            with mock.patch(
                "palimpsest.fetch.urllib.request.urlopen", return_value=_FakeResponse("second")
            ):
                second = fetcher.get(url, revalidate=True)
            self.assertTrue(second.changed)
            self.assertEqual(second.body, "second")


class TestConditionalGet(unittest.TestCase):
    def test_a_stored_etag_goes_back_out_as_if_none_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            url = public_act_url("103-0565")
            with mock.patch(
                "palimpsest.fetch.urllib.request.urlopen",
                return_value=_FakeResponse("body", ETag='"abc"', Last_Modified="Mon, 1 Jan 2024"),
            ):
                fetcher.get(url)

            opener = mock.Mock(side_effect=_http_error(304))
            with mock.patch("palimpsest.fetch.urllib.request.urlopen", opener):
                response = fetcher.get(url, revalidate=True)

            sent = opener.call_args[0][0]
            self.assertEqual(sent.get_header("If-none-match"), '"abc"')
            self.assertEqual(sent.get_header("If-modified-since"), "Mon, 1 Jan 2024")
            self.assertTrue(response.revalidated)
            self.assertEqual(response.body, "body")

    def test_the_first_pass_does_not_revalidate_a_cached_page_at_all(self):
        """A page already in the mirror costs zero requests unless asked."""
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            url = public_act_url("103-0565")
            with mock.patch(
                "palimpsest.fetch.urllib.request.urlopen", return_value=_FakeResponse("body")
            ):
                fetcher.get(url)
            opener = mock.Mock()
            with mock.patch("palimpsest.fetch.urllib.request.urlopen", opener):
                fetcher.get(url)
            opener.assert_not_called()


class TestQueue(unittest.TestCase):
    def test_act_key_parses_the_index_label(self):
        self.assertEqual(_act_key("10 ILCS 5/ Election Code."), ("10", "5"))
        self.assertEqual(_act_key("820 ILCS 305/ Workers' Compensation Act."), ("820", "305"))
        self.assertIsNone(_act_key("Some heading with no citation"))

    def test_a_queue_round_trips_through_json(self):
        queue = Queue(
            built_at=1.0,
            items=[_pa_item("103-0565"), Item(crawl.KIND_ILCS_ACT, "", 2, "5 ILCS 70/", "79", "2")],
            skipped_below_floor=456,
            sample_sections=4600,
            chapters=68,
        )
        restored = Queue.from_json(queue.to_json())
        self.assertEqual(restored.items, queue.items)
        self.assertEqual(restored.skipped_below_floor, 456)
        self.assertEqual(restored.sample_sections, 4600)

    def test_the_cache_is_the_ledger_for_resumability(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            item = _pa_item("103-0565")
            self.assertFalse(_is_done(fetcher, item))
            with mock.patch(
                "palimpsest.fetch.urllib.request.urlopen", return_value=_FakeResponse("body")
            ):
                fetcher.get(item.url)
            self.assertTrue(_is_done(fetcher, item))

    def test_an_ilcs_act_is_done_when_its_articles_page_is_mirrored(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            item = Item(crawl.KIND_ILCS_ACT, "", 2, "5 ILCS 70/", act_id="79", chapter_id="2")
            self.assertFalse(_is_done(fetcher, item))
            with mock.patch(
                "palimpsest.fetch.urllib.request.urlopen", return_value=_FakeResponse("<html>")
            ):
                fetcher.get(ilcs_articles_url("79", "2"))
            self.assertTrue(_is_done(fetcher, item))

    def test_a_resumed_run_skips_mirrored_items_without_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            items = [_pa_item("103-0565"), _pa_item("103-0566")]
            with mock.patch(
                "palimpsest.fetch.urllib.request.urlopen", return_value=_FakeResponse("body")
            ):
                fetcher.get(items[0].url)

            opener = mock.Mock(return_value=_FakeResponse("body"))
            with mock.patch("palimpsest.fetch.urllib.request.urlopen", opener):
                progress = crawl.run(
                    fetcher,
                    Queue(built_at=time.time(), items=items),
                    deadline=time.time() + 60,
                    status_paths=[Path(tmp) / "s.md"],
                    queue_path=Path(tmp) / "q.json",
                    stop_file=Path(tmp) / "STOP",
                )
            self.assertEqual(progress.done, 2)
            self.assertEqual(progress.cached, 1)
            self.assertEqual(opener.call_count, 1)
            self.assertEqual(progress.stopped_because, "the queue was drained")


class TestStopConditions(unittest.TestCase):
    def test_an_expired_deadline_stops_the_run_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            opener = mock.Mock(return_value=_FakeResponse("body"))
            with mock.patch("palimpsest.fetch.urllib.request.urlopen", opener):
                progress = crawl.run(
                    fetcher,
                    Queue(built_at=time.time(), items=[_pa_item("103-0565")]),
                    deadline=time.time() - 1,  # already spent
                    status_paths=[Path(tmp) / "s.md"],
                    queue_path=Path(tmp) / "q.json",
                    stop_file=Path(tmp) / "STOP",
                )
            opener.assert_not_called()
            self.assertIn("four-hour fetch budget", progress.stopped_because)

    def test_a_stop_file_stops_the_run_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            stop = Path(tmp) / "STOP-CRAWL"
            stop.write_text("")
            fetcher = _fetcher(tmp)
            opener = mock.Mock(return_value=_FakeResponse("body"))
            with mock.patch("palimpsest.fetch.urllib.request.urlopen", opener):
                progress = crawl.run(
                    fetcher,
                    Queue(built_at=time.time(), items=[_pa_item("103-0565")]),
                    deadline=time.time() + 60,
                    status_paths=[Path(tmp) / "s.md"],
                    queue_path=Path(tmp) / "q.json",
                    stop_file=stop,
                )
            opener.assert_not_called()
            self.assertIn("stop file", progress.stopped_because)


class TestCorpusFloor(unittest.TestCase):
    def test_the_probe_straddles_the_floor_in_both_directions(self):
        below = [pa for pa in FLOOR_PROBE if ga_of(pa) < FLOOR_GA]
        at_or_above = [pa for pa in FLOOR_PROBE if ga_of(pa) >= FLOOR_GA]
        self.assertTrue(below, "nothing below the floor: a moved floor would go unnoticed")
        self.assertTrue(at_or_above, "nothing above the floor: a broken fetch would go unnoticed")

    def test_the_probe_is_small_enough_to_be_free(self):
        # Ten requests is under two minutes of a four-hour budget.
        self.assertLessEqual(len(FLOOR_PROBE), 12)

    def test_the_probe_result_is_read_off_the_mirror_not_a_run_counter(self):
        """A resumed run, or a report generated after the crawl exited, must
        still see a probe that is sitting complete on disk. Deriving it from a
        counter turned a real measurement into "has not run"."""
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            self.assertEqual(crawl.probe_floor(fetcher), (0, []))

            body = "AN ACT concerning government. " + "x" * 1000
            placeholder = "<b>Document: 090-0001 is not currently available.</b>"
            for pa in FLOOR_PROBE:
                text = body if ga_of(pa) >= FLOOR_GA else placeholder
                with mock.patch(
                    "palimpsest.fetch.urllib.request.urlopen",
                    return_value=_FakeResponse(text),
                ):
                    fetcher.get(public_act_url(pa))

            # A brand new Fetcher: nothing in memory, everything on disk.
            probed, disagreements = crawl.probe_floor(_fetcher(tmp))
            self.assertEqual(probed, len(FLOOR_PROBE))
            self.assertEqual(disagreements, [])

    def test_a_pre_floor_act_that_returns_text_is_flagged_as_a_moved_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            with mock.patch(
                "palimpsest.fetch.urllib.request.urlopen",
                return_value=_FakeResponse("AN ACT of 2001. " + "x" * 1000),
            ):
                fetcher.get(public_act_url("092-0001"))
            probed, disagreements = crawl.probe_floor(fetcher)
            self.assertEqual(probed, 1)
            self.assertIn("092-0001", disagreements[0])


class TestStatusFile(unittest.TestCase):
    def _status(self, floor=None, **kwargs) -> str:
        progress = Progress(started=time.time() - 600, total=1000, **kwargs)
        queue = Queue(built_at=0.0, skipped_below_floor=456, sample_sections=4600)
        return status_markdown(progress, queue, deadline=time.time() + 3600, floor=floor)

    def test_it_reports_the_four_numbers_the_brief_asks_for(self):
        text = self._status(done=250, requests=200)
        for expected in ("Remaining", "Network requests", "Observed rate", "ETA"):
            self.assertIn(expected, text)

    def test_the_checkable_ceiling_is_reported_apart_from_the_mirrored_count(self):
        """Mirroring a section is not the same as being able to check it.

        45 % of the sample Acts' sections name a source Act that is not
        published, so quoting the mirrored count as the oracle's reach would
        overstate it by nearly a factor of two.
        """
        progress = Progress(started=time.time() - 60, total=10, done=4, requests=4)
        queue = Queue(
            built_at=0.0,
            sample_sections=4600,
            sample_checkable=2540,
            sample_below_floor=1798,
            sample_no_public_act=262,
        )
        text = status_markdown(progress, queue, deadline=time.time() + 60)
        self.assertIn("4,600", text)
        self.assertIn("2,540", text)
        self.assertIn("1,798", text)
        self.assertIn("never checkable", text)

    def test_a_deliberate_skip_is_disclosed_rather_than_folded_into_the_counts(self):
        """A crawl that silently drops work reads as complete when it is not."""
        text = self._status(done=250, requests=200)
        self.assertIn("456", text)
        self.assertIn("not silently folded into them", text)

    def test_a_moved_corpus_floor_is_reported_loudly(self):
        text = self._status(done=1, requests=1, floor=(10, ["092-0001 available"]))
        self.assertIn("disagrees with the recorded floor", text)
        self.assertIn("092-0001", text)

    def test_an_unmoved_floor_says_so_only_once_the_probe_has_actually_run(self):
        self.assertIn("it held", self._status(done=1, requests=1, floor=(10, [])))

    def test_an_unrun_probe_is_not_reported_as_a_clean_measurement(self):
        """ "The probe found nothing" and "the probe has not run" are the same
        empty list. Reporting the second as the first claims a measurement that
        never happened."""
        text = self._status(done=1, requests=1, floor=(0, []))
        self.assertIn("has not run", text)
        self.assertIn("previously recorded", text)
        self.assertNotIn("it held", text)

    def test_the_rate_is_seconds_per_request_not_requests_per_second(self):
        progress = Progress(started=time.time() - 100, total=10, done=10, requests=10)
        self.assertAlmostEqual(progress.rate, 10.0, places=0)


class TestResumeInstructions(unittest.TestCase):
    """The brief asks the status file to carry the *exact* resume command."""

    def _status(self) -> str:
        progress = Progress(started=time.time() - 60, total=10, done=4, requests=4)
        return status_markdown(progress, Queue(built_at=0.0), deadline=time.time() + 60)

    def test_the_status_file_carries_a_runnable_resume_command(self):
        text = self._status()
        self.assertIn("palimpsest.crawl", text)
        self.assertIn("--cache", text)
        self.assertIn("--status", text)

    def test_the_resume_command_omits_rebuild_queue(self):
        """Passing --rebuild-queue would restart the job, not resume it."""
        self.assertNotIn("--rebuild-queue", crawl.RESUME_COMMAND)
        self.assertIn("deliberately **not**", self._status())

    def test_the_clean_stop_mechanism_is_documented(self):
        self.assertIn("STOP-CRAWL", self._status())


class TestTierBreakdown(unittest.TestCase):
    def test_it_counts_done_and_total_per_tier_against_the_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = _fetcher(tmp)
            items = [_pa_item("103-0565", 0), _pa_item("103-0566", 0), _pa_item("103-0567", 4)]
            with mock.patch(
                "palimpsest.fetch.urllib.request.urlopen", return_value=_FakeResponse("body")
            ):
                fetcher.get(items[0].url)
            breakdown = crawl.tier_breakdown(fetcher, Queue(built_at=0.0, items=items))
            self.assertEqual(breakdown, [(0, 1, 2), (4, 0, 1)])

    def test_every_tier_it_can_emit_has_a_human_name(self):
        for tier in (0, 1, 2, 3, 4):
            self.assertIn(tier, crawl.TIER_NAMES)

    def test_the_breakdown_reaches_the_status_file(self):
        progress = Progress(started=time.time() - 60, total=3, done=1, requests=1)
        text = status_markdown(
            progress, Queue(built_at=0.0), time.time() + 60, breakdown=[(0, 1, 2), (3, 0, 1)]
        )
        self.assertIn("What remains, by tier", text)
        self.assertIn(crawl.TIER_NAMES[0], text)
        self.assertIn(crawl.TIER_NAMES[3], text)


class TestFormatting(unittest.TestCase):
    def test_durations_read_as_english(self):
        self.assertEqual(_fmt_duration(45), "45s")
        self.assertEqual(_fmt_duration(125), "2m 5s")
        self.assertEqual(_fmt_duration(7300), "2h 1m")
        self.assertEqual(_fmt_duration(-5), "0s")


if __name__ == "__main__":
    unittest.main()
