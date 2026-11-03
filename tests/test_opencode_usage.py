import datetime as dt
import json
import pathlib
import tempfile
import unittest

from opencode_usage import (
    OpenCodeAuthNotFoundError,
    OpenCodeUsageError,
    load_api_key,
    map_usage_snapshot,
    parse_api_key,
)

SAMPLE_RESPONSE = {
    "usage": {
        "rolling": {"status": "ok", "percent": 12.5, "resetsAt": "2026-11-04T01:09:32.000Z"},
        "weekly": {"status": "ok", "percent": 40, "resetsAt": "2026-11-09T00:00:00.000Z"},
        "monthly": {"status": "ok", "percent": 3, "resetsAt": "2026-12-03T19:57:07.000Z"},
    }
}


class ParseApiKeyTests(unittest.TestCase):
    def test_pi_auth_entry(self):
        self.assertEqual(parse_api_key({"opencode-go": {"type": "api_key", "key": " sk-pi "}}), "sk-pi")

    def test_opencode_auth_entry(self):
        self.assertEqual(parse_api_key({"opencode-go": {"type": "api", "key": "sk-oc"}}), "sk-oc")

    def test_ignores_other_providers_and_oauth(self):
        self.assertIsNone(parse_api_key({"openai": {"type": "api_key", "key": "x"}}))
        self.assertIsNone(parse_api_key({"opencode-go": {"type": "oauth", "access": "x"}}))
        self.assertIsNone(parse_api_key([]))


class LoadApiKeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel: str, data: dict):
        path = self.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def test_env_var_wins(self):
        self._write(".pi/agent/auth.json", {"opencode-go": {"type": "api_key", "key": "from-pi"}})
        env = {"HOME": str(self.home), "OPENCODE_API_KEY": "from-env"}
        self.assertEqual(load_api_key(env), "from-env")

    def test_pi_before_opencode(self):
        self._write(".pi/agent/auth.json", {"opencode-go": {"type": "api_key", "key": "from-pi"}})
        self._write(".local/share/opencode/auth.json", {"opencode-go": {"type": "api", "key": "from-oc"}})
        self.assertEqual(load_api_key({"HOME": str(self.home)}), "from-pi")

    def test_falls_back_to_opencode_and_skips_bad_json(self):
        (self.home / ".pi/agent").mkdir(parents=True)
        (self.home / ".pi/agent/auth.json").write_text("{not json")
        self._write(".local/share/opencode/auth.json", {"opencode-go": {"type": "api", "key": "from-oc"}})
        self.assertEqual(load_api_key({"HOME": str(self.home)}), "from-oc")

    def test_missing_everywhere(self):
        with self.assertRaises(OpenCodeAuthNotFoundError):
            load_api_key({"HOME": str(self.home)})


class MapUsageSnapshotTests(unittest.TestCase):
    def test_maps_three_windows(self):
        snap = map_usage_snapshot(SAMPLE_RESPONSE)
        self.assertEqual(snap.provider_id, "opencode")
        self.assertEqual(snap.session.percent, 12.5)
        self.assertEqual(snap.session.window_seconds, 5 * 3600)
        self.assertEqual(snap.session.resets_at, dt.datetime(2026, 11, 4, 1, 9, 32, tzinfo=dt.timezone.utc))
        self.assertEqual(snap.weekly.percent, 40)
        self.assertEqual(snap.monthly.percent, 3)
        self.assertTrue(snap.has_any_usage)
        self.assertIsNone(snap.error)

    def test_used_and_limit_fallback(self):
        snap = map_usage_snapshot({"usage": {"rolling": {"used": 3, "limit": 12}}})
        self.assertEqual(snap.session.percent, 25)
        self.assertIsNone(snap.weekly)
        self.assertIsNone(snap.monthly)

    def test_missing_rolling_raises(self):
        with self.assertRaises(OpenCodeUsageError):
            map_usage_snapshot({"usage": {}})


if __name__ == "__main__":
    unittest.main()
