"""Bounded handoff lifecycle and HTTP authentication, without a real account."""
import importlib.util
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1] / "app"
package = types.ModuleType("_handoff_tests")
package.__path__ = [str(ROOT)]
with patch.dict(sys.modules, {package.__name__: package}):
    from importlib import import_module
    flows = import_module("_handoff_tests.login_flow")
    routes = import_module("_handoff_tests.login_routes")


class FlowTests(unittest.TestCase):
    def test_duplicate_start_reuses_browser_and_cancellation_cleans_memory(self):
        manager = flows.LoginManager()
        ready = threading.Event()
        def run(flow):
            flow.picture(b"private-frame", 100, 80)
            flow.manual("manual required")
            flow.enqueue({"kind": "text", "text": "private-code"})
            ready.set()
            flow.stop.wait(2)
            flow.check()
        first = manager.start(run)
        self.assertTrue(ready.wait(2))
        self.assertIs(manager.start(lambda f: self.fail("second browser")), first)
        public = str(first.public())
        self.assertNotIn("private-frame", public)
        self.assertNotIn("private-code", public)
        manager.cancel(first.id)
        self.assertTrue(first.done.wait(2))
        self.assertEqual(first.phase, "canceled")
        self.assertIsNone(first.frame)
        self.assertFalse(first.inputs)

    def test_timeout_and_worker_failure_do_not_become_success(self):
        manager = flows.LoginManager()
        def expire(flow):
            flow.manual("wait")
            flow.deadline = time.time() - 1
            flow.check()
        flow = manager.start(expire)
        self.assertTrue(flow.done.wait(2))
        self.assertEqual(flow.phase, "expired")
        def fail(flow):
            raise RuntimeError("secret-which-must-not-appear")
        flow = manager.start(fail)
        self.assertTrue(flow.done.wait(2))
        self.assertEqual(flow.phase, "error")
        self.assertNotIn("secret-which-must-not-appear", str(flow.public()))

    def test_only_safe_bounded_inputs_and_active_screens_are_accepted(self):
        flow = flows.LoginFlow()
        flow.picture(b"frame", 100, 80)
        with self.assertRaises(ValueError):
            flow.enqueue({"kind": "click", "x": 1, "y": 1})
        flow.manual("wait")
        for invalid in [
            {"kind": "click", "x": -1, "y": 0}, {"kind": "click", "x": 100, "y": 0},
            {"kind": "click", "x": True, "y": 0}, {"kind": "text", "text": "a\nb"},
            {"kind": "text", "text": "a" * 257}, {"kind": "key", "key": "F12"},
            {"kind": "scroll", "delta": 100}, {"kind": "eval", "text": "alert(1)"},
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                flow.enqueue(invalid)
        for _ in range(32):
            flow.enqueue({"kind": "key", "key": "Tab"})
        with self.assertRaises(ValueError):
            flow.enqueue({"kind": "key", "key": "Tab"})
        self.assertEqual(len(flow.take_inputs()), 32)
        flow.stop.set()
        with self.assertRaises(flows.FlowStopped):
            flow.enqueue({"kind": "text", "text": "123456"})


class RouteTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        def auth(request: Request):
            if request.cookies.get("session") != "signed-test-cookie":
                raise HTTPException(401)
        self.manager = flows.LoginManager()
        self.manager.current = self.flow = flows.LoginFlow()
        self.flow.picture(b"jpeg-for-test", 100, 80)
        self.flow.manual("manual required")
        self.patcher = patch.object(flows, "manager", self.manager)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        routes.install(app, auth, lambda: self.flow.public())
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.url = f"/api/ns/login/{self.flow.id}"

    def authenticated(self):
        self.client.cookies.set("session", "signed-test-cookie")

    def test_every_endpoint_requires_panel_authentication(self):
        for method, path, body in [
            ("GET", "/api/ns/login/status", None), ("POST", "/api/ns/login/start", {}),
            ("GET", self.url + "/screen", None), ("POST", self.url + "/input", {"kind": "key", "key": "Tab"}),
            ("POST", self.url + "/cancel", {}),
        ]:
            kwargs = {"json": body} if body is not None else {}
            with self.subTest(path=path):
                self.assertEqual(self.client.request(method, path, **kwargs).status_code, 401)

    def test_cross_origin_input_and_start_are_rejected(self):
        self.authenticated()
        for path in [self.url + "/input", self.url + "/cancel", "/api/ns/login/start"]:
            self.assertEqual(self.client.post(path, json={}, headers={"Origin": "https://attacker.invalid"}).status_code, 403)

    def test_current_screen_is_private_and_old_or_canceled_flow_unusable(self):
        self.authenticated()
        response = self.client.get(self.url + "/screen")
        self.assertEqual(response.content, b"jpeg-for-test")
        self.assertIn("no-store", response.headers["cache-control"])
        self.assertEqual(response.headers["cross-origin-resource-policy"], "same-origin")
        self.assertEqual(self.client.get("/api/ns/login/old-id/screen").status_code, 404)
        self.assertEqual(self.client.post(self.url + "/cancel").status_code, 200)
        self.assertEqual(self.client.get(self.url + "/screen").status_code, 409)
        self.assertEqual(self.client.post(self.url + "/input", json={"kind": "text", "text": "123456"}).status_code, 409)

    def test_input_is_queued_and_status_has_no_screen_or_secrets(self):
        self.authenticated()
        response = self.client.post(self.url + "/input", json={"kind": "text", "text": "private-code"}, headers={"Origin": "http://testserver"})
        self.assertEqual(response.status_code, 200)
        status = self.client.get("/api/ns/login/status")
        self.assertNotIn("private-code", status.text)
        self.assertNotIn("jpeg-for-test", status.text)
        self.assertIn("no-store", status.headers["cache-control"])
        self.assertEqual(self.flow.take_inputs(), [{"kind": "text", "text": "private-code"}])


if __name__ == "__main__":
    unittest.main()
