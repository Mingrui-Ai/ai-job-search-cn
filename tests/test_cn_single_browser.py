"""Opt-in real Chrome tests against ephemeral loopback HTTP fixtures only.

Run with JOBSEARCH_CN_LOCAL_BROWSER_TESTS=1 in an environment with Playwright
and Chrome already installed. Never installs software or contacts a real portal.
The public CLI still rejects HTTP/localhost; these tests exercise the internal
browser transport after the separately tested strict URL admission boundary.
"""

import json
import os
import re
import threading
import unittest
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from jobsearch_cn import browser, robots_policy


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with self.server.lock:
            self.server.hits[self.path] += 1
            self.server.agents.append(self.headers.get("User-Agent"))
        status, body, location = 200, b"<main>Fictional detail only</main>", None
        if self.path == "/robots.txt":
            status = self.server.robots_status
            body = b"User-agent: *\nDisallow:\n"
            if 300 <= status < 400:
                location = self.server.redirect_target
        elif self.path.startswith("/detail/redirect-"):
            status = int(self.path.rsplit("-", 1)[1])
            location = self.server.redirect_target
        elif self.path == "/detail/js":
            body += b"<script>location.href='/target'</script>"
        elif self.path == "/detail/meta":
            body += b"<meta http-equiv='refresh' content='0; url=/target'>"
        elif self.path == "/detail/popup":
            body += b"<script>window.open('/target', '_blank')</script>"
        elif self.path == "/detail/iframe":
            body += b"<iframe src='/target'></iframe>"
        elif self.path == "/detail/reload":
            body += b"<script>location.reload()</script>"
        elif self.path == "/detail/history":
            body += b"<script>history.pushState({}, '', '/changed')</script>"
        elif self.path == "/detail/delayed":
            body += b"<script>setTimeout(()=>location.href='/target', 50)</script>"
        elif self.path == "/detail/late403":
            body += b"<script>setTimeout(()=>fetch('/data403'), 50)</script>"
        elif self.path == "/detail/api":
            body += b"<script>fetch('/api/detail')</script>"
        elif self.path == "/data403":
            status, body = 403, b"denied"
        elif self.path == "/api/detail":
            body = json.dumps({"Code": 200, "Data": {"Name": "Fictional"}}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8" if self.path == "/robots.txt"
                         else "application/json" if self.path == "/api/detail" else "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if location:
            self.send_header("Location", location)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # expected for aborted navigation

    def log_message(self, *args):
        pass


def server():
    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    instance.daemon_threads = True
    instance.hits, instance.agents, instance.lock = Counter(), [], threading.Lock()
    instance.robots_status = 200
    instance.base = f"http://127.0.0.1:{instance.server_port}"
    instance.redirect_target = instance.base + "/target"
    worker = threading.Thread(target=instance.serve_forever, daemon=True)
    worker.start()
    return instance, worker


@unittest.skipUnless(os.environ.get("JOBSEARCH_CN_LOCAL_BROWSER_TESTS") == "1",
                     "opt-in: installed Chrome + fictional loopback server")
class LocalBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.worker = server()
        cls.other, cls.other_worker = server()
        # A different port is a different origin. A redirect must not reach it.
        cls.server.redirect_target = cls.other.base + "/target"

    @classmethod
    def tearDownClass(cls):
        for instance, worker in ((cls.server, cls.worker), (cls.other, cls.other_worker)):
            instance.shutdown()
            instance.server_close()
            worker.join(timeout=5)

    def setUp(self):
        for instance in (self.server, self.other):
            instance.hits.clear()
            instance.agents.clear()
            instance.robots_status = 200

    def read(self, suffix, *, capture=False, robots=True):
        url = self.server.base + "/detail/" + suffix
        tab = browser.open_single_tab()
        if capture:
            tab.capture([re.compile(r"^/api/detail$")])
        try:
            if robots:
                body, status, error = tab.read_robots(url)
                policy = robots_policy.decide(url, body, status, checked_at="2026-11-10T00:00:00+08:00", error=error)
                self.assertEqual(policy["status"], "allowed")
            with mock.patch.object(browser, "READY_TIMEOUT_MS", 600), mock.patch.object(browser, "SETTLE_S", 0.2):
                tab.open_single(url, ["main"])
        finally:
            snapshot, reason = tab.freeze_and_close()
        self.assertTrue(tab._closed)
        return snapshot, reason

    def test_success_is_one_document_and_readable_after_close(self):
        snapshot, reason = self.read("ok")
        self.assertIsNone(reason)
        self.assertIn("Fictional detail", snapshot.html)
        self.assertEqual(self.server.hits["/detail/ok"], 1)
        self.assertEqual(self.server.hits["/robots.txt"], 1)
        self.assertTrue(all(agent == robots_policy.USER_AGENT for agent in self.server.agents))

    def test_30x_never_reaches_location_even_on_another_origin(self):
        for status in (301, 302, 307, 308):
            with self.subTest(status=status):
                _, reason = self.read(f"redirect-{status}")
                self.assertIsNotNone(reason)
                self.assertEqual(self.server.hits[f"/detail/redirect-{status}"], 1)
                self.assertEqual(self.other.hits["/target"], 0)

    def test_scripts_meta_popup_iframe_reload_and_delayed_navigation_do_not_send(self):
        for kind in ("js", "meta", "popup", "iframe", "reload", "delayed"):
            with self.subTest(kind=kind):
                _, reason = self.read(kind)
                self.assertIsNotNone(reason)
                self.assertEqual(self.server.hits[f"/detail/{kind}"], 1)
                self.assertEqual(self.server.hits["/target"], 0)

    def test_history_change_is_not_silently_accepted(self):
        _, reason = self.read("history")
        self.assertIsNotNone(reason)
        self.assertEqual(self.server.hits["/changed"], 0)

    def test_late_denied_response_is_kept_through_context_close(self):
        _, reason = self.read("late403")
        self.assertIn("403", reason)
        self.assertEqual(self.server.hits["/data403"], 1)

    def test_page_initiated_api_is_passively_captured(self):
        snapshot, reason = self.read("api", capture=True)
        self.assertIsNone(reason)
        self.assertEqual(self.server.hits["/api/detail"], 1)
        self.assertEqual(len(snapshot.responses), 1)
        self.assertEqual(json.loads(snapshot.responses[0].body)["Code"], 200)

    def test_robots_redirect_is_not_followed_and_has_no_detail_request(self):
        self.server.robots_status = 302
        tab = browser.open_single_tab()
        try:
            url = self.server.base + "/detail/ok"
            body, status, error = tab.read_robots(url)
            result = robots_policy.decide(url, body, status, checked_at="2026-11-10T00:00:00+08:00", error=error)
        finally:
            tab.freeze_and_close()
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(self.server.hits["/robots.txt"], 1)
        self.assertEqual(self.server.hits["/detail/ok"], 0)
        self.assertEqual(self.other.hits["/target"], 0)


if __name__ == "__main__":
    unittest.main()
