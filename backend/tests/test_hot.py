"""Heat analysis must tolerate malformed model fields without losing valid results."""
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1] / "app"
package = types.ModuleType("_hot_tests")
package.__path__ = [str(ROOT)]
modules = {name: types.ModuleType(f"_hot_tests.{name}") for name in ("config", "db", "llm", "notify", "ns")}
config, db, llm, notify, ns = (modules[name] for name in ("config", "db", "llm", "notify", "ns"))
config.CATEGORIES = {"tech": "技术"}
ns.Client = Mock()
with patch.dict(sys.modules, {package.__name__: package, **{m.__name__: m for m in modules.values()}}):
    spec = importlib.util.spec_from_file_location("_hot_tests.hot", ROOT / "hot.py")
    hot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hot)


class HotTests(unittest.TestCase):
    def setUp(self):
        config.get = lambda: {"hot": {"categories": [], "top_n": 10}}
        config.now = lambda: datetime(2026, 11, 3, 21, 0)
        config.now_str = lambda: "2026-11-03 21:00:00"
        db.q = Mock(return_value=[{"post_id": pid, "title": f"title {pid}", "category": "tech"}
                                  for pid in (1, 2, 3, 123)])
        db.ex = Mock()
        llm.model = lambda: "test-model"
        llm.chat_json = Mock()
        notify.send = Mock()
        self.ctx = types.SimpleNamespace(log=Mock(), summary="")

    def analyze(self, keywords, summary="summary", win="1h"):
        llm.chat_json.return_value = {"keywords": keywords, "summary": summary}
        hot.analyze(self.ctx, win)
        return json.loads(db.ex.call_args.args[1][3])

    def test_scalar_post_id_saves_a_complete_snapshot(self):
        kws = self.analyze([{"word": "DMIT 补货", "heat": 80, "count": 1, "post_ids": 123}])
        self.assertEqual(kws, [{"word": "DMIT 补货", "heat": 80, "count": 1, "post_ids": [123]}])
        self.assertEqual(db.ex.call_args.args[1][:3], ("1h", "2026-11-03 21:00:00", 4))
        self.assertIn("1 个关键词", self.ctx.summary)
        notify.send.assert_not_called()

    def test_string_id_is_not_split_into_digits(self):
        kws = self.analyze([{"word": "DMIT", "post_ids": "123"}])
        self.assertEqual(kws[0]["post_ids"], [123])
        self.assertEqual(kws[0]["count"], 1)

    def test_null_missing_and_wrong_id_containers_preserve_valid_keywords(self):
        for value in (None, {}, {"id": 123}, False, 1.5):
            with self.subTest(value=value):
                kws = self.analyze([{"word": "DMIT", "post_ids": value, "count": "2"},
                                    {"word": "Cloudflare", "post_ids": [1]}])
                self.assertEqual(kws[0]["post_ids"], [])
                self.assertEqual(kws[0]["count"], 2)
                self.assertEqual(kws[1]["post_ids"], [1])
        self.assertEqual(self.analyze([{"word": "DMIT"}])[0]["post_ids"], [])

    def test_ids_are_deduplicated_and_limited_to_input_posts(self):
        kws = self.analyze([{"word": "DMIT", "count": 999,
                             "post_ids": [123, "123", " 2 ", 999, True, 1.9, None, [], "²", "1.0"]}])
        self.assertEqual(kws[0]["post_ids"], [123, 2])
        self.assertEqual(kws[0]["count"], 2)

    def test_bad_entries_and_numbers_do_not_discard_valid_results(self):
        kws = self.analyze([None, 42, "bad", {}, {"word": []}, {"word": " "},
                             {"word": "bad fields", "heat": "unknown", "count": {}},
                             {"word": "high", "heat": "150", "count": 999},
                             {"word": "low", "heat": -2, "count": -5}])
        self.assertEqual([k["word"] for k in kws], ["high", "bad fields", "low"])
        self.assertEqual([k["heat"] for k in kws], [100, 0, 0])
        self.assertEqual([k["count"] for k in kws], [4, 0, 0])
        for value in (None, [], {}, float("inf"), float("nan"), True):
            with self.subTest(value=value):
                kws = self.analyze([{"word": "DMIT", "heat": value, "count": value}])
                self.assertEqual((kws[0]["heat"], kws[0]["count"]), (0, 0))

    def test_unusable_response_does_not_replace_previous_snapshot(self):
        for out in (None, [], 42, {}, {"keywords": None}, {"keywords": {}}, {"keywords": [None, 42]}):
            with self.subTest(out=out):
                db.ex.reset_mock()
                llm.chat_json.return_value = out
                with self.assertRaisesRegex(ValueError, "LLM 热度结果格式错误"):
                    hot.analyze(self.ctx, "1h")
                db.ex.assert_not_called()

    def test_legitimate_empty_keywords_and_daily_summary_still_work(self):
        self.assertEqual(self.analyze([]), [])
        self.analyze([{"word": "DMIT", "heat": 80, "post_ids": [123]}], win="24h")
        self.assertEqual(notify.send.call_args.args, ("hot", "NodeSeek 今日热点（4 帖）\n1. DMIT  ·  1 帖\n\nsummary"))
        self.analyze([], summary=None)
        self.assertEqual(db.ex.call_args.args[1][4], "")

    def test_top_n_applies_to_valid_keywords_sorted_by_heat(self):
        config.get = lambda: {"hot": {"categories": [], "top_n": 1}}
        kws = self.analyze([None, {"word": "low", "heat": 2}, {"word": "high", "heat": 99}])
        self.assertEqual([k["word"] for k in kws], ["high"])


if __name__ == "__main__":
    unittest.main()
