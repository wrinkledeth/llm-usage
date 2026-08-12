import hashlib
import json
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

from claude_cookie import (
    _MacCookieSource,
    _cookie_is_expired,
    _decrypt_chromium_cookie,
    _find_macos_session_cookie,
    _ordered_profile_dirs,
    get_claude_session_cookie,
)


class ClaudeCookieTests(unittest.TestCase):
    def test_ordered_profile_dirs_prefers_last_used_then_active_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            (root / "Profile 1").mkdir()
            (root / "Profile 15").mkdir()
            (root / "Default").mkdir()
            (root / "Local State").write_text(
                json.dumps(
                    {
                        "profile": {
                            "last_used": "Profile 15",
                            "info_cache": {
                                "Profile 1": {"active_time": 20},
                                "Profile 15": {"active_time": 10},
                            },
                        }
                    }
                )
            )

            ordered = _ordered_profile_dirs(root)

            self.assertEqual(
                [path.name for path in ordered[:3]],
                ["Profile 15", "Profile 1", "Default"],
            )

    def test_find_macos_session_cookie_reads_last_used_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            (root / "Local State").write_text(
                json.dumps(
                    {
                        "profile": {
                            "last_used": "Profile 15",
                            "info_cache": {
                                "Profile 1": {"active_time": 20},
                                "Profile 15": {"active_time": 10},
                            },
                        }
                    }
                )
            )
            self._write_cookie_db(root / "Profile 1" / "Cookies", "old-session")
            self._write_cookie_db(root / "Profile 15" / "Cookies", "active-session")
            source = _MacCookieSource((), "unused", "unused")

            self.assertEqual(
                _find_macos_session_cookie(source, root),
                ("sessionKey", "active-session"),
            )

    def test_find_macos_session_cookie_skips_expired_cookie(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            self._write_cookie_db(
                root / "Default" / "Cookies",
                "expired-session",
                expires_utc=1,
            )
            self._write_cookie_db(root / "Profile 1" / "Cookies", "valid-session")
            source = _MacCookieSource((), "unused", "unused")

            self.assertEqual(
                _find_macos_session_cookie(source, root),
                ("sessionKey", "valid-session"),
            )

    def test_decrypt_chromium_cookie_removes_host_digest(self):
        host = ".claude.ai"
        plaintext = hashlib.sha256(host.encode()).digest() + b"session-value"
        with mock.patch(
            "claude_cookie._common_crypto_decrypt",
            return_value=plaintext,
        ):
            value = _decrypt_chromium_cookie(host, b"v10ciphertext", b"key")

        self.assertEqual(value, "session-value")

    @mock.patch("claude_cookie.rookiepy.firefox")
    def test_get_claude_session_cookie_retains_rookiepy_fallback(self, firefox):
        firefox.return_value = [
            {
                "name": "sessionKey",
                "value": "firefox-session",
            }
        ]

        self.assertEqual(
            get_claude_session_cookie("firefox"),
            ("sessionKey", "firefox-session"),
        )

    def test_cookie_is_expired_treats_session_cookie_as_valid(self):
        self.assertFalse(_cookie_is_expired(0))
        self.assertTrue(_cookie_is_expired(1))

    def _write_cookie_db(
        self,
        path: pathlib.Path,
        value: str,
        expires_utc: int = 0,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute(
                """
                CREATE TABLE cookies (
                    host_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    value TEXT NOT NULL,
                    encrypted_value BLOB NOT NULL,
                    expires_utc INTEGER NOT NULL,
                    last_access_utc INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO cookies (
                    host_key,
                    name,
                    value,
                    encrypted_value,
                    expires_utc,
                    last_access_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (".claude.ai", "sessionKey", value, b"", expires_utc, 1),
            )


if __name__ == "__main__":
    unittest.main()
