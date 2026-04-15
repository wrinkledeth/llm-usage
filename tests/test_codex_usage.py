import unittest

from codex_usage import map_codex_oauth_snapshot, parse_auth_data, resolve_usage_url


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


if __name__ == "__main__":
    unittest.main()
