"""Read-only RSS retries are bounded and never replay account writes."""
from datetime import timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, call, patch
from xml.etree.ElementTree import ParseError

from curl_cffi.requests.exceptions import ConnectionError, DNSError, HTTPError, Timeout


ROOT = Path(__file__).resolve().parents[1] / "app"
package = types.ModuleType("_rss_tests")
package.__path__ = [str(ROOT)]
modules = {name: types.ModuleType(f"_rss_tests.{name}") for name in ("config", "db", "security")}
config, db, security = (modules[name] for name in ("config", "db", "security"))
security.encrypt = security.decrypt = lambda text: text
config.TZ = timezone.utc
config.now_str = lambda: "2026-11-03 21:00:00"
with patch.dict(sys.modules, {package.__name__: package, **{m.__name__: m for m in modules.values()}}):
    spec = importlib.util.spec_from_file_location("_rss_tests.ns", ROOT / "ns.py")
    ns = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ns)


URL = "https://rss.nodeseek.com/"
FEED = """<rss version="2.0"><channel><item><title>DMIT</title>
<link>https://www.nodeseek.com/post-123-1</link><category>技术</category>
</item></channel></rss>"""


class RssTests(unittest.TestCase):
    def setUp(self):
        self.client = ns.Client.__new__(ns.Client)
        self.client.log = Mock()
        self.client.request = Mock()
        self.sleep = patch.object(ns.time, "sleep").start()
        self.addCleanup(patch.stopall)

    def response(self, status=200, text=FEED):
        response = Mock(status_code=status, text=text)
        if status >= 400:
            response.raise_for_status.side_effect = HTTPError(f"HTTP {status}")
        return response

    def test_success_parses_feed_without_retrying(self):
        self.client.request.return_value = self.response()
        self.assertEqual(self.client.rss(URL)[0]["post_id"], 123)
        self.client.request.assert_called_once_with("GET", URL, timeout=15)
        self.sleep.assert_not_called()

    def test_timeout_retries_and_recovers(self):
        self.client.request.side_effect = [Timeout("timed out", 28), self.response()]
        self.assertEqual(self.client.rss(URL)[0]["post_id"], 123)
        self.assertEqual(self.client.request.call_count, 2)
        self.sleep.assert_called_once_with(1)
        self.assertIn("第 2/3 次", self.client.log.call_args.args[0])

    def test_connection_and_dns_failures_can_recover(self):
        self.client.request.side_effect = [ConnectionError("connect", 7), DNSError("dns", 6), self.response()]
        self.assertEqual(self.client.rss(URL)[0]["post_id"], 123)
        self.assertEqual(self.client.request.call_count, 3)
        self.assertEqual(self.sleep.call_args_list, [call(1), call(2)])

    def test_exhausted_timeout_fails_clearly_after_three_attempts(self):
        failure = Timeout("timed out", 28)
        self.client.request.side_effect = failure
        with self.assertRaisesRegex(ns.NSError, "连续 3 次超时或连接失败") as caught:
            self.client.rss(URL)
        self.assertIs(caught.exception.__cause__, failure)
        self.assertEqual(self.client.request.call_count, 3)
        self.assertEqual(self.sleep.call_args_list, [call(1), call(2)])

    def test_transient_http_error_retries_and_recovers(self):
        self.client.request.side_effect = [self.response(502), self.response()]
        self.assertEqual(self.client.rss(URL)[0]["post_id"], 123)
        self.sleep.assert_called_once_with(1)

    def test_exhausted_http_error_is_not_treated_as_an_empty_feed(self):
        self.client.request.return_value = self.response(503)
        with self.assertRaisesRegex(ns.NSError, "HTTP 503.*3 次"):
            self.client.rss(URL)
        self.assertEqual(self.client.request.call_count, 3)

    def test_permanent_http_errors_are_not_retried_or_parsed(self):
        for status in (401, 403, 404, 429):
            with self.subTest(status=status):
                self.client.request.reset_mock()
                self.client.request.return_value = self.response(status)
                with self.assertRaises(HTTPError):
                    self.client.rss(URL)
                self.client.request.assert_called_once()
        self.sleep.assert_not_called()

    def test_cloudflare_and_parse_errors_are_not_retried(self):
        self.client.request.side_effect = ns.CFBlocked("challenge")
        with self.assertRaises(ns.CFBlocked):
            self.client.rss(URL)
        self.client.request.assert_called_once()
        self.client.request.reset_mock(side_effect=True)
        self.client.request.return_value = self.response(text="not XML")
        with self.assertRaises(ParseError):
            self.client.rss(URL)
        self.client.request.assert_called_once()
        self.sleep.assert_not_called()

    def transport(self):
        client = ns.Client.__new__(ns.Client)
        client.base = "https://www.nodeseek.com"
        client.ua = "test-agent"
        client.s = Mock()
        client.s.request.return_value = self.response()
        client._auth_session = Mock(return_value=(client.s, client.ua))
        client._blocked = Mock(return_value=False)
        return client

    def test_normal_request_timeout_is_unchanged_and_rss_can_override_it(self):
        client = self.transport()
        client.request("GET", "/")
        self.assertEqual(client.s.request.call_args.kwargs["timeout"], 30)
        client.request("GET", URL, timeout=15)
        self.assertEqual(client.s.request.call_args.kwargs["timeout"], 15)

    def test_write_timeout_does_not_replay_the_request(self):
        client = self.transport()
        client.s.request.side_effect = Timeout("response unknown", 28)
        with self.assertRaises(Timeout):
            client.request("POST", "/example-write", auth=True, data="body")
        client.s.request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
