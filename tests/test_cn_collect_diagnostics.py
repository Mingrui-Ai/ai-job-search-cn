"""Opt-in structure evidence: fictional pages, no browser or network."""

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jobsearch_cn import beisen, cli, collect, collect_diagnostics as diagnostics, store
from tests.fixtures.collect_personal import example as site

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
URL = site.search_url("示例", "CITY_45")


def snapshot(html="<main>unrecognised structure</main>", *, url=URL, status=200, title="示例列表", responses=()):
    return collect.Snapshot(url, title, html, status, responses)


def listing(ids=("1",)):
    return snapshot('<div class="example-list">' + ''.join(
        f'<a href="/openings/{i}/detail"><span class="example-title">示例开发{i}</span>'
        '<div class="example-location"><span>广州</span></div></a>' for i in ids) + '</div>')


def detail(i="1"):
    return snapshot(f'<div class="example-detail"><div class="example-header">'
                    f'<h1 class="example-title">示例开发{i}</h1></div>'
                    '<h2 class="example-heading">职位描述</h2><div class="example-content">维护示例软件。</div>'
                    '<h2 class="example-heading">职位要求</h2><div class="example-content">掌握 Python。</div></div>',
                    url=site.canonical_url(i), title="示例详情")


class Tab:
    headless = True

    def __init__(self, *pages, before=None):
        self.pages, self.before, self.check = list(pages), before, None
        self.actions, self.closed = [], False

    def check_before_action(self, callback):
        self.check = callback

    def open(self, url, ready):
        if self.check and self.before is not None:
            current, self.before = self.before, None
            self.check(current)
        self.actions.append(("open", url))
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page

    def load_more(self, selectors, ready):
        self.actions.append(("scroll",))
        return self.pages.pop(0)

    def close(self):
        self.closed = True

    def capture(self, patterns):
        pass  # pre-existing responses are supplied in the fictional Snapshot


class Evidence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"

    def run_pages(self, *pages, enabled=True, before=None, **options):
        tab = Tab(*pages, before=before)
        opts = collect.make_options("示例", city="广州", site=site, diagnostics=enabled,
                                    batch="sample-batch", max_pages=options.pop("max_pages", 1), **options)
        result = collect.run(tab, opts, self.root, sleep=lambda _: None, clock=lambda: NOW)
        return result, tab

    def read_evidence(self, result):
        diag = result["diagnostics"]
        return Path(diag["html"]).read_bytes(), json.loads(Path(diag["metadata"]).read_text(encoding="utf-8"))

    def test_default_preserves_summary_and_creates_no_diagnostic_directory(self):
        plain, tab = self.run_pages(snapshot(), enabled=False)
        self.assertFalse((self.root / "collect").exists())
        enabled, enabled_tab = self.run_pages(snapshot())
        self.assertEqual(plain, {k: v for k, v in enabled.items() if k != "diagnostics"})
        self.assertNotIn("diagnostics", plain)
        self.assertEqual(tab.actions, enabled_tab.actions)
        self.assertEqual(len(tab.actions), 1)

    def test_exact_existing_snapshot_and_only_permitted_fields_are_saved(self):
        page = snapshot('<main>中文\r\n<script>never_execute()</script></main>', title="实际标题",
                        responses=(collect.Response(URL, 200, "private request", "private response"),))
        result, tab = self.run_pages(page)
        body, meta = self.read_evidence(result)
        self.assertEqual(body, page.html.encode("utf-8"))
        self.assertEqual((meta["url"], meta["title"], meta["http_status"], meta["phase"]),
                         (page.url, page.title, 200, "list"))
        self.assertEqual(meta["original_sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(meta["saved_sha256"], meta["original_sha256"])
        self.assertEqual((meta["saved_bytes"], meta["original_bytes"]), (len(body), len(body)))
        self.assertEqual((result["status"], collect.exit_code(result), result["saved"]), ("page_changed", 4, 0))
        self.assertEqual(result["diagnostics"]["status"], "saved")
        self.assertTrue(result["diagnostics"]["complete"])
        self.assertNotIn("private", json.dumps(meta))
        self.assertEqual(set(meta), {"format", "batch", "recorded_at", "phase", "stop_status", "stop_reason",
                                     "url", "title", "http_status", "encoding", "html_file", "truncated",
                                     "original_bytes", "saved_bytes", "original_sha256", "saved_sha256"})
        self.assertEqual(len(tab.actions), 1)
        self.assertFalse((self.root / "inbox").exists())

    def test_utf8_byte_cap_never_splits_a_character(self):
        page = snapshot("a" * (diagnostics.MAX_HTML_BYTES - 1) + "中🙂tail")
        result, _ = self.run_pages(page)
        body, meta = self.read_evidence(result)
        self.assertEqual(body, b"a" * (diagnostics.MAX_HTML_BYTES - 1))
        self.assertTrue(meta["truncated"])
        self.assertEqual(result["diagnostics"]["status"], "truncated")
        self.assertEqual(meta["original_bytes"], len(page.html.encode("utf-8")))
        self.assertEqual(meta["original_sha256"], hashlib.sha256(page.html.encode("utf-8")).hexdigest())
        self.assertEqual(meta["saved_sha256"], hashlib.sha256(body).hexdigest())

    def test_exact_cap_is_not_truncated(self):
        result, _ = self.run_pages(snapshot("a" * diagnostics.MAX_HTML_BYTES))
        self.assertEqual(result["diagnostics"]["status"], "saved")
        self.assertFalse(self.read_evidence(result)[1]["truncated"])

    def test_success_empty_and_security_stops_never_write(self):
        pages = [snapshot('<div class="example-list"><div class="example-empty">暂无职位</div></div>'),
                 snapshot(status=403), snapshot(status=429), snapshot('<div id="captcha">challenge</div>'),
                 snapshot('<form action="/login">login</form>')]
        for page in pages:
            with self.subTest(html=page.html, status=page.status):
                result, _ = self.run_pages(page)
                self.assertEqual(result["diagnostics"], {"status": "not_applicable"})
                self.assertIn(result["status"], ("done", "needs_user"))
                self.assertFalse((self.root / "collect").exists())

    def test_http_rejection_has_priority_even_if_adapter_says_changed(self):
        with mock.patch.object(site, "page_problem", return_value=("changed", "unknown")):
            result, _ = self.run_pages(snapshot(status=403))
        self.assertEqual((result["status"], collect.exit_code(result)), ("needs_user", 3))
        self.assertEqual(result["diagnostics"]["status"], "not_applicable")
        self.assertFalse((self.root / "collect").exists())

    def test_beisen_data_request_rejection_is_not_persisted(self):
        tenant = beisen.Tenant("example", "new", "示例", ("intern",), (("广州", "4401", "广州市"),),
                               "https://example.zhiye.com/privacy", "2026-11-10")
        opts = collect.make_search_options(beisen.searches(tenant, [], "intern"), diagnostics=True)
        url = "https://example.zhiye.com/intern/jobs"
        for status in (403, 429):
            page = snapshot("<main>unrecognised</main>", url=url,
                            responses=(collect.Response("https://example.zhiye.com/api/jobad/getjobadpagelist",
                                                        status, body="challenge response"),))
            result = collect.run(Tab(page), opts, self.root, sleep=lambda _: None, clock=lambda: NOW)
            self.assertEqual(result["status"], "needs_user")
            self.assertEqual(result["diagnostics"]["status"], "not_applicable")
            self.assertFalse((self.root / "collect").exists())

    def test_detail_failure_preserves_saved_job_and_uses_detail_snapshot(self):
        failed = snapshot("<main>second detail changed</main>", url=site.canonical_url("2"))
        result, tab = self.run_pages(listing(("1", "2")), detail(), failed)
        body, meta = self.read_evidence(result)
        self.assertEqual((result["saved"], meta["phase"], meta["url"]), (1, "detail", failed.url))
        self.assertEqual(body, failed.html.encode())
        self.assertEqual(len(tab.actions), 3)
        saved = self.root / "inbox" / "official" / "sample-batch" / result["files"][0]
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))["format"], collect.INBOX_FORMAT)

    def test_pre_action_stop_saves_fresh_check_not_last_page_or_next_page(self):
        fresh = snapshot("<main>changed during pause</main>", title="新快照")
        original = site.page_problem
        def problem(url, title, root, status):
            return ("changed", "changed during pause") if title == "新快照" else original(url, title, root, status)
        with mock.patch.object(site, "page_problem", side_effect=problem):
            result, tab = self.run_pages(listing(), detail(), before=fresh)
        body, meta = self.read_evidence(result)
        self.assertEqual(body, fresh.html.encode())
        self.assertEqual(meta["phase"], "list")
        self.assertEqual(len(tab.actions), 1)

    def test_repeated_list_no_progress_records_last_loaded_snapshot(self):
        last = listing(); last.html += "<!-- final load -->"
        with mock.patch.object(site, "has_more", return_value=True, create=True):
            result, tab = self.run_pages(listing(), listing(), last, max_pages=3)
        self.assertEqual(self.read_evidence(result)[0], last.html.encode())
        self.assertEqual(len(tab.actions), 3)
        self.assertIn("连续 2 次加载", result["message"])

    def test_no_snapshot_does_not_substitute_a_previous_page(self):
        result, _ = self.run_pages(listing(), collect._Stop("page_changed", "no snapshot"))
        self.assertEqual(result["diagnostics"]["status"], "unavailable")
        self.assertFalse((self.root / "collect").exists())

    def test_same_batch_and_time_get_distinct_directories(self):
        first, _ = self.run_pages(snapshot("first"))
        second, _ = self.run_pages(snapshot("second"))
        self.assertNotEqual(first["diagnostics"]["directory"], second["diagnostics"]["directory"])
        self.assertEqual(self.read_evidence(first)[0], b"first")
        self.assertEqual(self.read_evidence(second)[0], b"second")

    def test_directory_collision_fails_without_overwriting(self):
        with mock.patch.object(diagnostics.uuid, "uuid4", return_value=SimpleNamespace(hex="fixed")):
            first, _ = self.run_pages(snapshot("first"))
            second, _ = self.run_pages(snapshot("second"))
        self.assertEqual(second["diagnostics"]["status"], "failed")
        self.assertEqual(self.read_evidence(first)[0], b"first")
        self.assertEqual(second["saved"], 0)

    def test_metadata_failure_leaves_explicit_incomplete_html(self):
        with mock.patch.object(store, "_write_json", side_effect=OSError("disk full")):
            result, _ = self.run_pages(snapshot())
        diag = result["diagnostics"]
        self.assertEqual((diag["status"], diag["complete"], diag["metadata"]), ("failed", False, None))
        self.assertEqual(diag["partial_files"], ["page.html"])
        self.assertTrue(Path(diag["html"]).is_file())
        self.assertEqual(collect.exit_code(result), 4)
        self.assertIn("找不到岗位卡片", result["message"])

    def test_html_publication_failure_cleans_temp_and_preserves_stop(self):
        with mock.patch.object(diagnostics.os, "link", side_effect=OSError("no hard links")):
            result, tab = self.run_pages(snapshot())
        diag = result["diagnostics"]
        self.assertEqual(diag["status"], "failed")
        self.assertEqual(diag["partial_files"], [])
        self.assertEqual(list(Path(diag["directory"]).iterdir()), [])
        self.assertEqual((len(tab.actions), result["saved"], collect.exit_code(result)), (1, 0, 4))

    def test_concurrent_file_creation_is_not_overwritten(self):
        real_link = os.link
        def collision(source, destination):
            Path(destination).write_bytes(b"prior evidence")
            return real_link(source, destination)
        with mock.patch.object(diagnostics.os, "link", side_effect=collision):
            result, _ = self.run_pages(snapshot())
        diag = result["diagnostics"]
        self.assertEqual(diag["status"], "failed")
        self.assertEqual((Path(diag["directory"]) / "page.html").read_bytes(), b"prior evidence")
        self.assertFalse(list(Path(diag["directory"]).glob(".tmp-*")))

    def test_unsafe_batch_and_oversized_metadata_write_nothing(self):
        for batch, page in (("../outside", snapshot()), ("safe", snapshot(title="x" * diagnostics.MAX_METADATA_BYTES))):
            with self.subTest(batch=batch):
                result = diagnostics.save(self.root, batch, page, phase="list", reason="test", at=NOW)
                self.assertEqual(result["status"], "failed")
                self.assertFalse(self.root.exists())

    def test_folder_link_is_rejected_without_writing_outside(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir(); self.root.mkdir()
        link = self.root / "collect"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            if sys.platform != "win32":
                self.skipTest("directory symlinks are not available")
            import _winapi
            _winapi.CreateJunction(str(outside), str(link))
            self.addCleanup(link.rmdir)
        else:
            self.addCleanup(link.unlink)
        result, _ = self.run_pages(snapshot())
        self.assertEqual(result["diagnostics"]["status"], "failed")
        self.assertEqual(list(outside.iterdir()), [])

    def test_windows_reparse_point_guard_is_used(self):
        original = store._is_link
        with mock.patch.object(store, "_is_link", side_effect=lambda p: p.name == "diagnostics" or original(p)):
            result, _ = self.run_pages(snapshot())
        self.assertEqual(result["diagnostics"]["status"], "failed")
        self.assertFalse((self.root / "collect" / "diagnostics").exists())

    def test_unknown_http_status_is_preserved_as_null(self):
        result, _ = self.run_pages(snapshot(status=None))
        self.assertIsNone(self.read_evidence(result)[1]["http_status"])

    def test_personal_cli_flag_runs_real_collector_and_closes_tab(self):
        for enabled in (False, True):
            argv = ["collect", "fictional", "--query", "示例", "--city", "广州", "--max-pages", "1",
                    "--data-dir", str(self.root)] + (["--diagnostics"] if enabled else [])
            args = cli.build_parser({"fictional": site}).parse_args(argv)
            tab = Tab(snapshot())
            with mock.patch.object(cli.browser, "open_tab", return_value=tab), redirect_stdout(io.StringIO()) as out:
                code = args.handler(args)
            result = json.loads(out.getvalue())
            self.assertEqual(code, 4)
            self.assertEqual("diagnostics" in result, enabled)
            self.assertTrue(tab.closed)

    def test_beisen_cli_forwards_flag_and_keeps_tenant_metadata(self):
        tenant = beisen.Tenant("example", "legacy", "示例", ("intern",), (("广州", "4401", "广州市"),),
                               "https://example.zhiye.com/privacy", "2026-11-10")
        for enabled in (False, True):
            argv = ["collect", "beisen", "--tenant", "example", "--all", "--data-dir", str(self.root)]
            args = cli.build_parser().parse_args(argv + (["--diagnostics"] if enabled else []))
            with mock.patch.object(beisen, "load_tenants", return_value={"example": tenant}), \
                    mock.patch.object(cli, "_collect_run", return_value={"status": "page_changed", "warnings": []}) as run, \
                    redirect_stdout(io.StringIO()) as out:
                code = args.handler(args)
            self.assertEqual(run.call_args.args[0].diagnostics, enabled)
            self.assertEqual(code, 4)
            self.assertEqual(json.loads(out.getvalue())["tenant"]["subdomain"], "example")


if __name__ == "__main__":
    unittest.main()
