"""Unit tests for audit_logger.py."""
import json
import os
import shutil
import tempfile
import unittest

import audit_logger


class AuditLoggerTest(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="um_audit_test_")
        self.log_file = os.path.join(self.test_dir, "test_audit.jsonl")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_log_tool_event_creates_jsonl(self):
        audit_logger.log_tool_event(
            tool_name="memory_search",
            args={"query": "test query", "project": "TestProj", "limit": 5},
            duration_ms=15.42,
            status="ok",
            summary="len=2",
            custom_filepath=self.log_file
        )

        self.assertTrue(os.path.exists(self.log_file))
        with open(self.log_file, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]

        self.assertEqual(len(lines), 1)
        record = lines[0]
        self.assertEqual(record["tool"], "memory_search")
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["project"], "TestProj")
        self.assertEqual(record["duration_ms"], 15.42)
        self.assertEqual(record["args"]["query"], "test query")
        self.assertEqual(record["summary"], "len=2")
        self.assertIn("ts", record)

    def test_log_sanitization_masks_secrets_and_truncates_long_strings(self):
        long_str = "A" * 500
        audit_logger.log_tool_event(
            tool_name="memory_capture",
            args={
                "project": "SecretProj",
                "api_key": "sk-12345secret",
                "token": "bearer-token-val",
                "nested": {
                    "password": "super-secret-pw",
                    "data": long_str
                }
            },
            duration_ms=4.2,
            status="ok",
            custom_filepath=self.log_file
        )

        with open(self.log_file, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]

        record = lines[0]
        args = record["args"]
        self.assertEqual(args["api_key"], "***MASKED***")
        self.assertEqual(args["token"], "***MASKED***")
        self.assertEqual(args["nested"]["password"], "***MASKED***")
        self.assertTrue(args["nested"]["data"].endswith("chars]"))
        self.assertTrue(len(args["nested"]["data"]) < 400)

    def test_log_error_event(self):
        audit_logger.log_tool_event(
            tool_name="memory_commit",
            args={"project": "ErrProj"},
            duration_ms=8.1,
            status="error",
            error_message="Stale commit detected",
            custom_filepath=self.log_file
        )

        with open(self.log_file, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]

        record = lines[0]
        self.assertEqual(record["status"], "error")
        self.assertEqual(record["error"], "Stale commit detected")

    def test_fail_safe_non_blocking_on_error(self):
        # Even if path is invalid or write fails, log_tool_event must not raise
        invalid_path = os.path.join(self.test_dir, "non_existent_subdir", "deep", "audit.jsonl")
        try:
            audit_logger.log_tool_event(
                tool_name="memory_get",
                args={"id": "foo"},
                duration_ms=1.0,
                custom_filepath=invalid_path
            )
        except Exception as e:
            self.fail(f"log_tool_event raised an exception: {e}")


if __name__ == "__main__":
    unittest.main()
