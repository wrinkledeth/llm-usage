import json
import pathlib
import tempfile
import unittest
from unittest import mock

from codex_usage import (
    CodexCredentials,
    _CodexRPCClient,
    _resolve_codex_executable,
    map_codex_oauth_snapshot,
    map_codex_rpc_snapshot,
    parse_auth_data,
    resolve_usage_url,
    save_credentials,
)


class CodexUsageTests(unittest.TestCase):
    def test_parse_auth_data_supports_snake_case_tokens(self):
        creds = parse_auth_data(
            b"""
            {
              "tokens": {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "id_token": "id-token",
                "account_id": "account-123"
              },
              "last_refresh": "2025-12-20T12:34:56Z"
            }
            """
        )

        self.assertEqual(creds.access_token, "access-token")
        self.assertEqual(creds.refresh_token, "refresh-token")
        self.assertEqual(creds.id_token, "id-token")
        self.assertEqual(creds.account_id, "account-123")
        self.assertIsNotNone(creds.last_refresh)

    def test_parse_auth_data_supports_legacy_camel_case_tokens(self):
        creds = parse_auth_data(
            b"""
            {
              "tokens": {
                "accessToken": "access-token",
                "refreshToken": "refresh-token",
                "idToken": "id-token",
                "accountId": "account-123"
              }
            }
            """
        )

        self.assertEqual(creds.access_token, "access-token")
        self.assertEqual(creds.refresh_token, "refresh-token")
        self.assertEqual(creds.account_id, "account-123")

    def test_resolve_usage_url_defaults_to_backend_api(self):
        self.assertEqual(
            resolve_usage_url({}, None),
            "https://chatgpt.com/backend-api/wham/usage",
        )

    def test_resolve_usage_url_honors_non_backend_config(self):
        config = 'chatgpt_base_url = "https://example.com"\n'
        self.assertEqual(
            resolve_usage_url({}, config),
            "https://example.com/api/codex/usage",
        )

    def test_map_codex_oauth_snapshot_splits_session_and_weekly(self):
        snapshot = map_codex_oauth_snapshot(
            {
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 22,
                        "reset_at": 1766948068,
                        "limit_window_seconds": 18000,
                    },
                    "secondary_window": {
                        "used_percent": 43,
                        "reset_at": 1767407914,
                        "limit_window_seconds": 604800,
                    },
                },
                "credits": {
                    "has_credits": True,
                    "unlimited": False,
                    "balance": "150.0",
                },
            }
        )

        self.assertEqual(snapshot.session.percent, 22.0)
        self.assertEqual(snapshot.weekly.percent, 43.0)
        self.assertEqual(snapshot.credits.balance, 150.0)

    def test_map_codex_oauth_snapshot_treats_weekly_only_window_as_weekly(self):
        snapshot = map_codex_oauth_snapshot(
            {
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 7,
                        "reset_at": 1775468693,
                        "limit_window_seconds": 604800,
                    },
                    "secondary_window": None,
                }
            }
        )

        self.assertIsNone(snapshot.session)
        self.assertEqual(snapshot.weekly.percent, 7.0)

    def test_map_codex_oauth_snapshot_splits_five_day_long_window(self):
        snapshot = map_codex_oauth_snapshot(
            {
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 22,
                        "reset_at": 1766948068,
                        "limit_window_seconds": 18000,
                    },
                    "secondary_window": {
                        "used_percent": 43,
                        "reset_at": 1767370312,
                        "limit_window_seconds": 5 * 24 * 60 * 60,
                    },
                }
            }
        )

        self.assertEqual(snapshot.session.percent, 22.0)
        self.assertEqual(snapshot.weekly.percent, 43.0)
        self.assertEqual(snapshot.weekly.window_seconds, 5 * 24 * 60 * 60)

    def test_map_codex_oauth_snapshot_treats_five_day_only_window_as_weekly(self):
        snapshot = map_codex_oauth_snapshot(
            {
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 7,
                        "reset_at": 1775295893,
                        "limit_window_seconds": 5 * 24 * 60 * 60,
                    },
                    "secondary_window": None,
                }
            }
        )

        self.assertIsNone(snapshot.session)
        self.assertEqual(snapshot.weekly.percent, 7.0)
        self.assertEqual(snapshot.weekly.window_seconds, 5 * 24 * 60 * 60)

    def test_map_codex_oauth_snapshot_keeps_window_with_missing_duration(self):
        snapshot = map_codex_oauth_snapshot(
            {
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 22,
                        "reset_at": 1766948068,
                        "limit_window_seconds": 18000,
                    },
                    "secondary_window": {
                        "used_percent": 43,
                        "reset_at": 1767407914,
                    },
                }
            }
        )

        self.assertEqual(snapshot.session.percent, 22.0)
        self.assertEqual(snapshot.weekly.percent, 43.0)
        self.assertIsNone(snapshot.weekly.window_seconds)

    def test_map_codex_oauth_snapshot_orders_reversed_windows_by_duration(self):
        snapshot = map_codex_oauth_snapshot(
            {
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 43,
                        "reset_at": 1767407914,
                        "limit_window_seconds": 604800,
                    },
                    "secondary_window": {
                        "used_percent": 22,
                        "reset_at": 1766948068,
                        "limit_window_seconds": 18000,
                    },
                }
            }
        )

        self.assertEqual(snapshot.session.percent, 22.0)
        self.assertEqual(snapshot.weekly.percent, 43.0)

    def test_map_codex_rpc_snapshot_prefers_canonical_codex_bucket(self):
        snapshot = map_codex_rpc_snapshot(
            {},
            {
                "rateLimits": {
                    "primary": {"usedPercent": 91, "windowDurationMins": 300},
                    "secondary": {"usedPercent": 92, "windowDurationMins": 10080},
                },
                "rateLimitsByLimitId": {
                    "codex": {
                        "primary": {"usedPercent": 31, "windowDurationMins": 300},
                        "secondary": {"usedPercent": 42, "windowDurationMins": 10080},
                    },
                    "codex_other": {
                        "primary": {"usedPercent": 77, "windowDurationMins": 60},
                    },
                },
            },
        )

        self.assertEqual(snapshot.session.percent, 31.0)
        self.assertEqual(snapshot.weekly.percent, 42.0)

    def test_rpc_request_omits_params_for_parameterless_method(self):
        client = _CodexRPCClient.__new__(_CodexRPCClient)
        client._next_id = 1
        client._send = mock.Mock()
        client._read_message = mock.Mock(return_value={"id": 1, "result": {}})

        self.assertEqual(client.request("account/rateLimits/read"), {})
        client._send.assert_called_once_with(
            {"id": 1, "method": "account/rateLimits/read"}
        )

    @mock.patch("codex_usage.shutil.which", return_value="/custom/bin/codex")
    def test_resolve_codex_executable_uses_configured_path(self, _which):
        self.assertEqual(
            _resolve_codex_executable(
                {"PATH": "/custom/bin", "CODEX_CLI_PATH": "codex"}
            ),
            "/custom/bin/codex",
        )

    def test_save_credentials_preserves_unknown_token_fields(self):
        with tempfile.TemporaryDirectory() as codex_home:
            auth_path = pathlib.Path(codex_home) / "auth.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "auth_mode": "chatgpt",
                        "tokens": {
                            "access_token": "old-access",
                            "refresh_token": "old-refresh",
                            "future_token_field": "keep-me",
                        },
                    }
                )
            )
            save_credentials(
                CodexCredentials(
                    access_token="new-access",
                    refresh_token="new-refresh",
                    id_token=None,
                    account_id=None,
                    last_refresh=None,
                ),
                {"CODEX_HOME": codex_home},
            )

            saved = json.loads(auth_path.read_text())
            self.assertEqual(saved["tokens"]["access_token"], "new-access")
            self.assertEqual(saved["tokens"]["future_token_field"], "keep-me")


if __name__ == "__main__":
    unittest.main()
