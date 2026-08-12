import datetime as dt
import json
import pathlib
import subprocess
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from claude_usage import (
    CLAUDE_USAGE_ARGS,
    ClaudeUsageError,
    _resolve_claude_executable,
    load_claude_cli_snapshot,
    parse_claude_usage_text,
)


USAGE_TEXT = """You are currently using your subscription to power your Claude Code usage

Current session: 26% used \u00b7 resets Aug 11 at 11:19pm (America/New_York)
Current week (all models): 80% used \u00b7 resets Aug 12 at 4:59am (America/New_York)
"""


class ClaudeUsageTests(unittest.TestCase):
    def test_parse_claude_usage_text_builds_both_windows(self):
        now = dt.datetime(2026, 8, 12, 3, 11, tzinfo=dt.timezone.utc)

        snapshot = parse_claude_usage_text(USAGE_TEXT, now=now)

        self.assertEqual(snapshot.session.percent, 26.0)
        self.assertEqual(snapshot.session.window_seconds, 5 * 60 * 60)
        self.assertEqual(
            snapshot.session.resets_at,
            dt.datetime(2026, 8, 11, 23, 19, tzinfo=ZoneInfo("America/New_York")),
        )
        self.assertEqual(snapshot.weekly.percent, 80.0)
        self.assertEqual(snapshot.weekly.window_seconds, 7 * 24 * 60 * 60)
        self.assertEqual(
            snapshot.weekly.resets_at,
            dt.datetime(2026, 8, 12, 4, 59, tzinfo=ZoneInfo("America/New_York")),
        )

    def test_parse_claude_usage_text_handles_year_rollover(self):
        usage_text = """Current session: 1% used - resets Dec 31 at 11pm (UTC)
Current week: 2% used - resets Jan 2 at 3am (UTC)
"""
        now = dt.datetime(2026, 12, 31, 20, 0, tzinfo=dt.timezone.utc)

        snapshot = parse_claude_usage_text(usage_text, now=now)

        self.assertEqual(snapshot.session.resets_at.year, 2026)
        self.assertEqual(snapshot.weekly.resets_at.year, 2027)

    def test_parse_claude_usage_text_rejects_missing_window(self):
        with self.assertRaisesRegex(ClaudeUsageError, "unexpected /usage format"):
            parse_claude_usage_text("Current session: 12% used")

    @mock.patch("claude_usage.subprocess.run")
    @mock.patch("claude_usage._resolve_claude_executable", return_value="/bin/claude")
    def test_load_claude_cli_snapshot_runs_zero_token_usage_command(
        self,
        resolve_executable,
        run,
    ):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"is_error": False, "result": USAGE_TEXT}),
            stderr="",
        )
        env = {"HOME": "/Users/test", "PATH": "/bin"}
        now = dt.datetime(2026, 8, 12, 3, 11, tzinfo=dt.timezone.utc)

        snapshot = load_claude_cli_snapshot(env=env, now=now)

        self.assertEqual(snapshot.weekly.percent, 80.0)
        expected_env = {**env, "USER": mock.ANY, "LOGNAME": mock.ANY}
        resolve_executable.assert_called_once_with(expected_env)
        self.assertEqual(run.call_args.args[0], ["/bin/claude", *CLAUDE_USAGE_ARGS])
        self.assertEqual(run.call_args.kwargs["env"], expected_env)

    @mock.patch("claude_usage.subprocess.run")
    @mock.patch("claude_usage._resolve_claude_executable", return_value="/bin/claude")
    def test_load_claude_cli_snapshot_reports_cli_failure(
        self,
        _resolve_executable,
        run,
    ):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="not authenticated",
        )

        with self.assertRaisesRegex(ClaudeUsageError, "not authenticated"):
            load_claude_cli_snapshot(env={"PATH": "/bin"})

    @mock.patch("claude_usage.shutil.which", return_value=None)
    def test_resolve_claude_executable_uses_local_bin_fallback(self, _which):
        with mock.patch.object(pathlib.Path, "is_file", return_value=True), mock.patch(
            "claude_usage.os.access",
            return_value=True,
        ):
            executable = _resolve_claude_executable(
                {"HOME": "/Users/test", "PATH": "/usr/bin"}
            )

        self.assertEqual(executable, "/opt/homebrew/bin/claude")


if __name__ == "__main__":
    unittest.main()
