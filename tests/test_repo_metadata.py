import os
import pathlib
import tempfile
import unittest

from repo_metadata import parse_github_repo, resolve_github_repo


class RepoMetadataTests(unittest.TestCase):
    def test_parse_github_repo_supports_https_urls(self):
        self.assertEqual(
            parse_github_repo("https://github.com/example/codex-claude-bar.git"),
            "example/codex-claude-bar",
        )

    def test_parse_github_repo_supports_ssh_urls(self):
        self.assertEqual(
            parse_github_repo("git@github.com:example/codex-claude-bar.git"),
            "example/codex-claude-bar",
        )

    def test_resolve_github_repo_prefers_env_override(self):
        self.assertEqual(
            resolve_github_repo(env={"CLAUDE_BAR_GITHUB_REPO": "you/custom-repo"}),
            "you/custom-repo",
        )

    def test_resolve_github_repo_falls_back_when_no_git_repo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(
                resolve_github_repo(
                    repo_root=pathlib.Path(temp_dir),
                    env={},
                    default="fallback/repo",
                ),
                "fallback/repo",
            )


if __name__ == "__main__":
    unittest.main()
