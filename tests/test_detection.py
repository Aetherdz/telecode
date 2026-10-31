import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from telegram_bridge import detection


class DetectionTests(unittest.TestCase):
    def test_nine_cards_and_manual_capability_distinction(self):
        with mock.patch.object(detection.setup_cli, "discover", return_value=(False, None, True)):
            result = detection.cards()
        self.assertEqual(len(result), 9)
        self.assertTrue(all("detected" in item and "verified" in item for item in result))
        self.assertFalse(result[-1]["verified"])
        self.assertEqual(result[-1]["capability"], "manual")
        self.assertFalse(result[0]["detected"])

    def test_home_browse_only_immediate_directories_and_reject_links(self):
        with tempfile.TemporaryDirectory(dir=pathlib.Path.home()) as temp:
            root = pathlib.Path(temp)
            (root / "project").mkdir()
            outside = pathlib.Path.home().parent
            try:
                (root / "escape").symlink_to(outside, target_is_directory=True)
            except OSError:
                pass
            rows = detection.browse_directories(root)
            self.assertEqual([row["name"] for row in rows], ["project"])
            self.assertTrue(pathlib.Path(rows[0]["path"]).is_relative_to(root))

    def test_sessions_metadata_only_bounded_and_max_three(self):
        with tempfile.TemporaryDirectory(dir=pathlib.Path.home()) as temp:
            home = pathlib.Path(temp)
            directory = home / ".local/share/opencode/storage/session"
            directory.mkdir(parents=True)
            for i in range(5):
                (directory / f"{i}.json").write_text(json.dumps({
                    "id": f"ses{i}", "title": f"Title {i}", "directory": str(home),
                    "time": {"updated": i}, "messages": ["secret prompt"]
                }))
            rows = detection.recent_sessions(home)
            self.assertEqual([row["id"] for row in rows], ["ses4", "ses3", "ses2"])
            self.assertTrue(all("messages" not in row for row in rows))

    def test_sessions_reject_traversal_symlink_and_oversized_metadata(self):
        with tempfile.TemporaryDirectory(dir=pathlib.Path.home()) as temp:
            home = pathlib.Path(temp)
            directory = home / ".local/share/opencode/storage/session"
            directory.mkdir(parents=True)
            (directory / "ok.json").write_text(json.dumps({
                "id": "ses-ok", "title": "api_key=should-not-leak", "directory": str(home),
                "time": {"updated": 4}, "messages": ["private prompt"]
            }))
            (directory / "large.json").write_bytes(b" " * (detection.MAX_METADATA_BYTES + 1))
            outside = home.parent / (home.name + "-outside.json")
            outside.write_text(json.dumps({"id": "ses-outside", "title": "outside"}))
            try:
                (directory / "link.json").symlink_to(outside)
            except OSError:
                pass
            rows = detection.recent_sessions(home)
            self.assertEqual(len(rows), 1)
            self.assertNotIn("should-not-leak", rows[0]["title"])
            self.assertNotIn("messages", rows[0])

    def test_cards_follow_only_documented_hosts_and_manual_is_unverified(self):
        documented = {"opencode", "claude", "codex", "cursor", "gemini", "cline", "roo", "q"}
        with mock.patch.object(detection.setup_cli, "discover", return_value=(True, None, True)):
            rows = detection.cards()
        self.assertEqual({row["key"] for row in rows[:-1]}, documented)
        self.assertTrue(all(row["detected"] for row in rows[:-1]))
        self.assertFalse(rows[-1]["verified"])


if __name__ == "__main__":
    unittest.main()
