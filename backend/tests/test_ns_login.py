"""Regression tests for false-positive browser logins and expired write sessions.

Run: python -m unittest discover -s backend/tests -v
All settings, browser operations, and HTTP requests are isolated from real accounts.
"""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1] / "app"
package = types.ModuleType("_login_tests")
package.__path__ = [str(ROOT)]
config = types.ModuleType("_login_tests.config")
db = types.ModuleType("_login_tests.db")
security = types.ModuleType("_login_tests.security")
security.encrypt = lambda text: text
security.decrypt = lambda text: text
with patch.dict(sys.modules, {
    package.__name__: package, config.__name__: config,
    db.__name__: db, security.__name__: security,
}):
    spec = importlib.util.spec_from_file_location("_login_tests.ns", ROOT / "ns.py")
    ns = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ns)


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.settings = {}
        db.get_setting = lambda key, default=None: self.settings.get(key, default)
        db.set_setting = self.settings.__setitem__
        db.DATA_DIR = Path("isolated-test-browser-profile")
        config.get = lambda: {"ns": {
            "base": "https://www.nodeseek.com", "auto_cf": True,
            "username": "test-user", "password_enc": "test-password",
        }}
        config.now_str = lambda: "2026-10-28 00:00:00"
        self.client = ns.Client(log=Mock())
        self.addCleanup(self.client.s.close)

    def verified(self):
        ns._save_session({"auth": "test-session"}, "test-agent")

    def response(self, code=200, data=None):
        response = Mock(status_code=code)
        response.json.return_value = data
        session = Mock()
        session.get.return_value = response
        return session

    def browser(self, *, verification=False, error="", url="https://www.nodeseek.com/board"):
        sb = Mock()
        sb.execute_script.side_effect = lambda source: "" if source == ns.MARK_LOGIN_FORM else "test-agent"
        sb.get_current_url.return_value = url
        sb.is_element_visible.return_value = verification
        sb.find_elements.return_value = [Mock(text=error)] if error else []
        sb.driver.get_cookies.return_value = [{"name": "cf_clearance", "value": "test-clearance"}]
        manager = Mock()
        manager.__enter__ = Mock(return_value=sb)
        manager.__exit__ = Mock(return_value=False)
        selenium = types.ModuleType("seleniumbase")
        selenium.SB = Mock(return_value=manager)
        return sb, selenium

    def test_legacy_cf_only_session_is_not_shown_as_logged_in(self):
        self.settings["ns_session"] = json.dumps({
            "cookies": {"cf_clearance": "test", "colorscheme": "dark"}, "at": "old",
        })
        self.assertEqual(ns.session_info(), {"has_session": False, "logged_in_at": None})

    def test_verified_session_is_shown_as_logged_in(self):
        self.verified()
        self.assertEqual(ns.session_info(), {"has_session": True, "logged_in_at": "2026-10-28 00:00:00"})

    def test_readonly_auth_probe_accepts_zero_unread(self):
        session = self.response(data={"success": True, "unreadCount": 0})
        with patch.object(self.client, "_new_session", return_value=session):
            self.assertTrue(self.client._verify_login({"auth": "test"}, "test-agent"))
        self.assertEqual(session.get.call_args.args[0], "https://www.nodeseek.com/api/notification/unread-count")
        self.assertEqual(session.get.call_args.kwargs["headers"]["User-Agent"], "test-agent")
        session.close.assert_called_once()

    def test_auth_probe_rejects_anonymous_and_unrelated_success(self):
        for code, data in [(500, {"success": False, "message": "USER NOT FOUND"}),
                           (200, {"success": False, "message": "USER NOT FOUND"}),
                           (200, {"success": True}), (403, {}), (200, []),
                           (200, {"success": "false", "unreadCount": 0})]:
            with self.subTest(code=code, data=data):
                session = self.response(code=code, data=data)
                with patch.object(self.client, "_new_session", return_value=session):
                    self.assertFalse(self.client._verify_login({"cf_clearance": "test"}, "test-agent"))
                session.close.assert_called_once()

    def test_auth_probe_rejects_html(self):
        session = self.response()
        session.get.return_value.json.side_effect = ValueError("not json")
        with patch.object(self.client, "_new_session", return_value=session):
            self.assertFalse(self.client._verify_login({"auth": "test"}, "test-agent"))

    def test_auth_probe_closes_session_on_network_error(self):
        session = self.response()
        session.get.side_effect = TimeoutError("test timeout")
        with patch.object(self.client, "_new_session", return_value=session):
            with self.assertRaises(TimeoutError):
                self.client._verify_login({"auth": "test"}, "test-agent")
        session.close.assert_called_once()

    def test_redirect_without_verified_auth_never_saves_success(self):
        self.verified()
        sb, selenium = self.browser()
        with patch.dict(sys.modules, {"seleniumbase": selenium}), \
             patch.object(self.client, "_verify_login", return_value=False) as verify, \
             patch.object(ns.time, "monotonic", side_effect=[0, 1, 1, 1, 46]), \
             patch.object(ns, "_save_session") as save:
            with self.assertRaisesRegex(ns.LoginError, "未取得有效"):
                self.client.login()
        verify.assert_called_once()
        save.assert_not_called()
        self.assertFalse(ns.session_info()["has_session"])
        self.assertIsNone(self.client._auth)
        self.assertNotIn(("登录成功",), [call.args for call in self.client.log.call_args_list])

    def test_browser_login_saves_only_after_exported_session_verified(self):
        sb, selenium = self.browser()
        sb.driver.get_cookies.return_value.append({"name": "auth", "value": "test-session"})
        with patch.dict(sys.modules, {"seleniumbase": selenium}), \
             patch.object(self.client, "_verify_login", return_value=True) as verify:
            self.client.login()
        verify.assert_called_once_with({"cf_clearance": "test-clearance", "auth": "test-session"}, "test-agent")
        self.assertTrue(ns.session_info()["has_session"])
        self.assertEqual(self.settings["cf_session"]["cookies"], {"cf_clearance": "test-clearance"})
        self.client._auth[0].close()

    def test_redirect_to_email_verification_is_not_a_success(self):
        _, selenium = self.browser(verification=True)
        with patch.dict(sys.modules, {"seleniumbase": selenium}), \
             patch.object(self.client, "_verify_login") as verify, \
             patch.object(ns, "_save_session") as save:
            with self.assertRaisesRegex(ns.LoginError, "邮箱验证码"):
                self.client.login()
        verify.assert_not_called()
        save.assert_not_called()

    def test_email_signin_page_is_detected_before_waiting_for_password(self):
        sb, selenium = self.browser(url="https://www.nodeseek.com/emailSignIn.html")
        with patch.dict(sys.modules, {"seleniumbase": selenium}), \
             patch.object(self.client, "_verify_login") as verify:
            with self.assertRaisesRegex(ns.LoginError, "邮箱动态验证"):
                self.client.login()
        sb.wait_for_element_visible.assert_not_called()
        verify.assert_not_called()
        self.assertFalse(ns.session_info()["has_session"])

    def test_redirect_to_email_signin_page_is_not_a_success(self):
        sb, selenium = self.browser()
        sb.get_current_url.side_effect = [
            "https://www.nodeseek.com/signIn.html", "https://www.nodeseek.com/emailSignIn.html",
        ]
        with patch.dict(sys.modules, {"seleniumbase": selenium}), \
             patch.object(self.client, "_verify_login") as verify:
            with self.assertRaisesRegex(ns.LoginError, "邮箱动态验证"):
                self.client.login()
        verify.assert_not_called()
        self.assertFalse(ns.session_info()["has_session"])

    def test_english_email_code_selector_is_checked(self):
        sb = Mock()
        sb.get_current_url.return_value = "https://www.nodeseek.com/verify"
        sb.is_element_visible.side_effect = lambda selector: "validation code" in selector
        self.assertTrue(ns._requires_email_verification(sb))

    def test_login_waits_for_authenticated_cookies_after_redirect(self):
        sb, selenium = self.browser()
        sb.driver.get_cookies.side_effect = [
            [{"name": "cf_clearance", "value": "test-clearance"}],
            [{"name": "cf_clearance", "value": "test-clearance"}, {"name": "auth", "value": "test-session"}],
        ]
        with patch.dict(sys.modules, {"seleniumbase": selenium}), \
             patch.object(ns.time, "monotonic", side_effect=[0, 1, 1, 1, 5, 5]), \
             patch.object(self.client, "_verify_login", side_effect=[False, True]) as verify:
            self.client.login()
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(ns._load_session()["cookies"]["auth"], "test-session")
        self.client._auth[0].close()

    def test_signin_url_case_does_not_count_as_login(self):
        _, selenium = self.browser(error="wrong password", url="https://www.nodeseek.com/SIGNIN.html")
        with patch.dict(sys.modules, {"seleniumbase": selenium}), \
             patch.object(self.client, "_verify_login") as verify:
            with self.assertRaisesRegex(ns.LoginError, "wrong password"):
                self.client.login()
        verify.assert_not_called()

    def test_legacy_cookie_session_requires_login_before_write(self):
        self.settings["ns_session"] = json.dumps({"cookies": {"cf_clearance": "test"}})
        with patch.object(self.client, "login") as login, \
             patch.object(self.client, "api", return_value=(200, {"success": True, "message": "ok"})):
            self.assertEqual(self.client._write("/test", None, "/"), (True, "ok"))
        login.assert_called_once()

    def test_user_not_found_reauthenticates_and_retries_once(self):
        for status, message in [(200, "USER NOT FOUND"), (500, "USER NOT FOUND"), (404, "user_not_found")]:
            with self.subTest(status=status, message=message):
                self.verified()
                self.client._auth = (Mock(), "stale-agent")
                def relogin():
                    self.assertIsNone(self.client._auth)
                    self.assertFalse(ns.session_info()["has_session"])
                    self.verified()
                with patch.object(self.client, "login", side_effect=relogin) as login, \
                     patch.object(self.client, "api", side_effect=[
                         (status, {"success": False, "message": message}),
                         (200, {"success": True, "message": "ok"}),
                     ]) as api:
                    self.assertEqual(self.client._write("/test", None, "/"), (True, "ok"))
                login.assert_called_once()
                self.assertEqual(api.call_count, 2)

    def test_second_auth_failure_invalidates_session_without_retry_loop(self):
        self.verified()
        with patch.object(self.client, "login", side_effect=self.verified) as login, \
             patch.object(self.client, "api", return_value=(500, {"success": False, "message": "USER NOT FOUND"})) as api:
            self.assertEqual(self.client._write("/test", None, "/"), (False, "USER NOT FOUND"))
        login.assert_called_once()
        self.assertEqual(api.call_count, 2)
        self.assertFalse(ns.session_info()["has_session"])

    def test_unrelated_write_failure_does_not_retry(self):
        self.verified()
        with patch.object(self.client, "login") as login, \
             patch.object(self.client, "api", return_value=(400, {"success": False, "message": "invalid content"})) as api:
            self.assertEqual(self.client._write("/test", None, "/"), (False, "invalid content"))
        login.assert_not_called()
        api.assert_called_once()


if __name__ == "__main__":
    unittest.main()
