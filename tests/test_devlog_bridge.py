#!/usr/bin/env python3
"""
Unit tests for devlog_bridge module in universal-memory.
"""

import os
import json
import shutil
import tempfile
import unittest

from devlog_bridge import (
    devlog_roots,
    parse_devlog_content,
    devlog_list,
    devlog_get,
    devlog_check_session,
    _fallback_parse_yaml,
)


class TestDevLogBridge(unittest.TestCase):
    def setUp(self):
        self.old_vault = os.environ.get("OBSIDIAN_VAULT_PATH")
        self.old_repo = os.environ.get("DEVLOG_REPO_PATH")
        self.temp_dir = tempfile.mkdtemp(prefix="um_devlog_test_")
        self.vault_dir = os.path.join(self.temp_dir, "obsidian")
        os.environ["OBSIDIAN_VAULT_PATH"] = self.vault_dir
        os.environ["DEVLOG_REPO_PATH"] = self.temp_dir
        self.p_devlogs = os.path.join(self.vault_dir, "projects", "myproject", "devlogs")
        os.makedirs(self.p_devlogs, exist_ok=True)

        # Create sample devlog markdown
        self.sample_md = """---
schemaVersion: 2
id: "myproject-2026-11-02-entry1"
project: "MyProject"
occurredOn: "2026-11-02"
dayNumber: 2
entryNumber: 1
headline: "Test DevLog Headline"
summary: "Test DevLog Summary in plain language"
tags:
  - "testing"
  - "minimalism"
verification:
  status: "verified"
---

## 🎯 1. Problem ve Hedef
Plain language problem explanation.

## ✅ 2. Tamamlanan İşler
- Feature A added.

<details><summary>🔍 Teknik Detaylar</summary>
git diff +10 -0
</details>

## 📚 6. Kaynaklar ve Atıflar (References)
[^1]: [Test / Doğrulama] npm test passed.
"""
        self.sample_file = os.path.join(self.p_devlogs, "2026-11-02-devlog1.md")
        with open(self.sample_file, "w", encoding="utf-8") as f:
            f.write(self.sample_md)

    def tearDown(self):
        if self.old_vault is None:
            os.environ.pop("OBSIDIAN_VAULT_PATH", None)
        else:
            os.environ["OBSIDIAN_VAULT_PATH"] = self.old_vault
        if self.old_repo is None:
            os.environ.pop("DEVLOG_REPO_PATH", None)
        else:
            os.environ["DEVLOG_REPO_PATH"] = self.old_repo
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_devlog_content(self):
        meta, body = parse_devlog_content(self.sample_md)
        self.assertEqual(meta.get("id"), "myproject-2026-11-02-entry1")
        self.assertEqual(meta.get("project"), "MyProject")
        self.assertEqual(meta.get("dayNumber"), 2)
        self.assertIn("🎯 1. Problem ve Hedef", body)

    def test_fallback_yaml_parser(self):
        raw = """
id: "simple-id"
project: "TestProj"
dayNumber: 5
tags:
  - alpha
  - beta
"""
        parsed = _fallback_parse_yaml(raw)
        self.assertEqual(parsed.get("id"), "simple-id")
        self.assertEqual(parsed.get("project"), "TestProj")
        self.assertEqual(parsed.get("dayNumber"), 5)
        self.assertEqual(parsed.get("tags"), ["alpha", "beta"])

    def test_devlog_roots_discovery(self):
        roots = devlog_roots(vault=self.vault_dir)
        self.assertIn(self.p_devlogs, roots)

    def test_devlog_list_and_filters(self):
        entries = devlog_list(project="myproject")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], "myproject-2026-11-02-entry1")
        self.assertEqual(entries[0]["verificationStatus"], "verified")

        # Filter by non-existing project
        empty = devlog_list(project="otherproject")
        self.assertEqual(len(empty), 0)

        # Filter by tag
        tagged = devlog_list(tag="minimalism")
        self.assertEqual(len(tagged), 1)
        not_tagged = devlog_list(tag="nonexistent")
        self.assertEqual(len(not_tagged), 0)

    def test_devlog_get(self):
        # By ID
        entry = devlog_get("myproject-2026-11-02-entry1")
        self.assertEqual(entry["id"], "myproject-2026-11-02-entry1")
        self.assertIn("Plain language problem explanation", entry["body"])

        # By file path
        by_path = devlog_get(self.sample_file)
        self.assertEqual(by_path["id"], "myproject-2026-11-02-entry1")

        # Missing
        missing = devlog_get("nonexistent-entry-id")
        self.assertIn("error", missing)

    def test_devlog_check_session_lifecycle(self):
        # Test NEW session
        res_new = devlog_check_session("cid-unknown-123")
        self.assertEqual(res_new["status"], "NEW")

        # Create temporary ledger file
        ledger_file = os.path.join(self.temp_dir, ".analysis_ledger.json")
        ledger_data = {
            "sess-1": {
                "conversationId": "sess-1",
                "lastAnalyzedMessageCount": 2,
                "analyzedAt": "2026-11-02T12:00:00Z",
                "devlogId": "myproject-2026-11-02-entry1"
            }
        }
        with open(ledger_file, "w", encoding="utf-8") as f:
            json.dump(ledger_data, f)

        # Create temporary transcript with 2 messages
        transcript = os.path.join(self.temp_dir, "transcript.jsonl")
        with open(transcript, "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "m1", "content": "hello"}) + "\n")
            f.write(json.dumps({"id": "m2", "content": "world"}) + "\n")

        # Monkeypatch _resolve_ledger_path
        import devlog_bridge
        orig_resolve = devlog_bridge._resolve_ledger_path
        devlog_bridge._resolve_ledger_path = lambda: ledger_file

        try:
            # Check UP_TO_DATE (2 messages recorded, 2 in transcript)
            res_up = devlog_check_session("sess-1", transcript_path=transcript)
            self.assertEqual(res_up["status"], "UP_TO_DATE")
            self.assertEqual(res_up["totalMessages"], 2)

            # Append 1 message -> DELTA (3 messages now)
            with open(transcript, "a", encoding="utf-8") as f:
                f.write(json.dumps({"id": "m3", "content": "new delta message"}) + "\n")

            res_delta = devlog_check_session("sess-1", transcript_path=transcript)
            self.assertEqual(res_delta["status"], "DELTA")
            self.assertEqual(res_delta["newMessages"], 1)
            self.assertEqual(res_delta["totalMessages"], 3)
        finally:
            devlog_bridge._resolve_ledger_path = orig_resolve


if __name__ == "__main__":
    unittest.main()
