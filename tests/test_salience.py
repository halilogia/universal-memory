"""
Unit tests for Universal Memory Salience & Recall Counter:
1. Hit counter increment (direct, memory_get, memory_search)
2. 90-day exponential decay formula: S(t) = sum(w_i * 2^(- (t - t_i) / H))
3. Verified golden priority (maintains superiority even when cooled down)
4. Backward compatibility (default values: 0, None, 0.0, False)
5. MCP Server tool integration (memory_search, memory_get, memory_propose)
"""
import json
import math
import os
import unittest
from datetime import datetime, timedelta, timezone

from tests._vault import VaultTestCase
import memory_engine
import memory_index
import server


class MemorySalienceTests(VaultTestCase):
    def test_direct_hit_counter_and_salience(self):
        eid = "ProjectAlpha/2026-11-02.md#15"
        
        # Initial state: no recall events
        initial_sal = memory_index.get_salience(eid)
        self.assertEqual(initial_sal["hit_count"], 0)
        self.assertIsNone(initial_sal["last_accessed"])
        self.assertEqual(initial_sal["salience_score"], 0.0)
        self.assertFalse(initial_sal["verified_golden"])

        # Record first recall event
        t1 = datetime(2026, 11, 2, 10, 0, 0, tzinfo=timezone.utc)
        sal1 = memory_index.record_recall_event(eid, weight=1.0, timestamp=t1)
        self.assertEqual(sal1["hit_count"], 1)
        self.assertEqual(sal1["last_accessed"], t1.isoformat())
        self.assertAlmostEqual(sal1["salience_score"], 1.0, places=4)
        self.assertFalse(sal1["verified_golden"])

        # Record second recall event immediately
        sal2 = memory_index.record_recall_event(eid, weight=1.0, timestamp=t1)
        self.assertEqual(sal2["hit_count"], 2)
        self.assertAlmostEqual(sal2["salience_score"], 2.0, places=4)

        # Record third recall event with custom weight
        sal3 = memory_index.record_recall_event(eid, weight=2.5, timestamp=t1)
        self.assertEqual(sal3["hit_count"], 3)
        self.assertAlmostEqual(sal3["salience_score"], 4.5, places=4)

    def test_exponential_decay_formula_90_days(self):
        # 1. Direct mathematical calculation check
        # S = w * 2^(-dt / H) where H = 90 days = 7,776,000 seconds
        day_seconds = 86400.0
        self.assertAlmostEqual(memory_index.calculate_decay(1.0, 0), 1.0, places=6)
        self.assertAlmostEqual(memory_index.calculate_decay(1.0, 45 * day_seconds), 2.0 ** -0.5, places=6)
        self.assertAlmostEqual(memory_index.calculate_decay(1.0, 90 * day_seconds), 0.5, places=6)
        self.assertAlmostEqual(memory_index.calculate_decay(1.0, 180 * day_seconds), 0.25, places=6)
        self.assertAlmostEqual(memory_index.calculate_decay(1.0, 270 * day_seconds), 0.125, places=6)
        self.assertAlmostEqual(memory_index.calculate_decay(2.0, 90 * day_seconds), 1.0, places=6)

        # 2. Sequential multi-event decay over time using get_salience(..., as_of=...)
        eid = "Test/DecayDoc.md#1"
        t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        # Event 1 at t0
        memory_index.record_recall_event(eid, weight=1.0, timestamp=t0)
        
        # Evaluate at t0: score = 1.0
        sal_t0 = memory_index.get_salience(eid, as_of=t0)
        self.assertAlmostEqual(sal_t0["salience_score"], 1.0, places=4)
        
        # Evaluate at t0 + 90 days: score = 0.5
        t_90 = t0 + timedelta(days=90)
        sal_t90 = memory_index.get_salience(eid, as_of=t_90)
        self.assertAlmostEqual(sal_t90["salience_score"], 0.5, places=4)
        self.assertEqual(sal_t90["hit_count"], 1)

        # Event 2 at t0 + 90 days (w = 1.0)
        memory_index.record_recall_event(eid, weight=1.0, timestamp=t_90)
        sal_after_e2 = memory_index.get_salience(eid, as_of=t_90)
        # Score = 0.5 (decayed event 1) + 1.0 (fresh event 2) = 1.5
        self.assertEqual(sal_after_e2["hit_count"], 2)
        self.assertAlmostEqual(sal_after_e2["salience_score"], 1.5, places=4)

        # Evaluate at t0 + 180 days (90 days after event 2):
        # Event 1 decayed by 180 days -> 0.25
        # Event 2 decayed by 90 days  -> 0.50
        # Total = 0.75
        t_180 = t0 + timedelta(days=180)
        sal_t180 = memory_index.get_salience(eid, as_of=t_180)
        self.assertAlmostEqual(sal_t180["salience_score"], 0.75, places=4)

        # Evaluate at t0 + 270 days:
        # Total = 0.75 * 0.5 = 0.375
        t_270 = t0 + timedelta(days=270)
        sal_t270 = memory_index.get_salience(eid, as_of=t_270)
        self.assertAlmostEqual(sal_t270["salience_score"], 0.375, places=4)

    def test_memory_get_increments_hit_counter_and_salience(self):
        note_content = (
            "---\n"
            "id: decision-salience-cache\n"
            "type: decision\n"
            "title: Salience Caching Protocol\n"
            "status: canonical\n"
            "---\n"
            "## Architecture Details\n"
            "Caching memory salience prevents expensive repeated scans.\n"
        )
        rel_path = "ProjectAlpha/salience_decision.md"
        self.write_note(rel_path, note_content)

        # Initial get -> hit_count becomes 1
        rec1 = memory_index.get("decision-salience-cache")
        self.assertIsNotNone(rec1)
        self.assertEqual(rec1["hit_count"], 1)
        self.assertIsNotNone(rec1["last_accessed"])
        self.assertGreater(rec1["salience_score"], 0.0)
        self.assertFalse(rec1["verified_golden"])

        # Second get -> hit_count becomes 2
        rec2 = memory_index.get("decision-salience-cache")
        self.assertIsNotNone(rec2)
        self.assertEqual(rec2["hit_count"], 2)
        self.assertGreater(rec2["salience_score"], rec1["salience_score"])

        # Third get via file path with line anchor
        rec3 = memory_index.get(f"{rel_path}#7")
        self.assertIsNotNone(rec3)
        self.assertIn("hit_count", rec3)
        self.assertGreaterEqual(rec3["hit_count"], 1)

    def test_memory_search_increments_hit_counter(self):
        note_content = (
            "Line 1: Header\n"
            "## USER [14:00]\n"
            "QuantumSalienceSearch unique query keyword\n"
            "## ASSISTANT [14:01]\n"
            "Quantum salience heat map algorithm response\n"
        )
        rel_path = "ProjectAlpha/quantum_search.md"
        self.write_note(rel_path, note_content)

        # Before search: chunk has 0 hits
        cid = f"{rel_path}#2"
        self.assertEqual(memory_index.get_salience(cid)["hit_count"], 0)

        # First search -> retrieves chunk and records recall
        res1 = memory_index.search("QuantumSalienceSearch")
        self.assertTrue(len(res1) > 0)
        top1 = res1[0]
        self.assertEqual(top1["hit_count"], 1)
        self.assertIsNotNone(top1["last_accessed"])
        self.assertGreater(top1["salience_score"], 0.0)
        self.assertFalse(top1["verified_golden"])

        # Second search -> hit_count becomes 2
        res2 = memory_index.search("QuantumSalienceSearch")
        self.assertTrue(len(res2) > 0)
        top2 = res2[0]
        self.assertEqual(top2["hit_count"], 2)
        self.assertGreater(top2["salience_score"], top1["salience_score"])

    def test_verified_golden_priority_over_hot_cooled_records(self):
        # Note A: verified_golden: true in frontmatter
        note_golden = (
            "---\n"
            "id: golden-doc-arch\n"
            "title: Database Architecture Guidelines\n"
            "verified_golden: true\n"
            "status: canonical\n"
            "---\n"
            "## Golden Core Principle\n"
            "Always use strict ACID compliance for transactional ledgers.\n"
        )
        # Note B: regular note, not golden
        note_regular = (
            "---\n"
            "id: regular-doc-arch\n"
            "title: Database Architecture Guidelines Temporary Note\n"
            "verified_golden: false\n"
            "status: canonical\n"
            "---\n"
            "## Temporary Draft\n"
            "Transactional ledgers draft notes.\n"
        )
        path_golden = "Projects/golden_arch.md"
        path_regular = "Projects/regular_arch.md"
        self.write_note(path_golden, note_golden)
        self.write_note(path_regular, note_regular)

        # Frontmatter takes 6 lines, so heading chunk starts at line 7
        chunk_a_id = f"{path_golden}#7"
        chunk_b_id = f"{path_regular}#7"

        # Check that frontmatter parsed verified_golden correctly
        sal_g = memory_index.get_salience(chunk_a_id)
        self.assertTrue(sal_g["verified_golden"])
        sal_r = memory_index.get_salience(chunk_b_id)
        self.assertFalse(sal_r["verified_golden"])

        # Simulate:
        # Note B is very hot today (15 recall events today -> salience ~15.0)
        now_dt = datetime.now(timezone.utc)
        for _ in range(15):
            memory_index.record_recall_event(chunk_b_id, weight=1.0, timestamp=now_dt)

        # Note A was accessed 360 days ago (4 half-lives = 2^-4 = 0.0625, completely cooled down)
        old_dt = now_dt - timedelta(days=360)
        memory_index.record_recall_event(chunk_a_id, weight=1.0, timestamp=old_dt)

        # Verify raw salience scores
        score_b = memory_index.get_salience(chunk_b_id)["salience_score"]
        score_a = memory_index.get_salience(chunk_a_id)["salience_score"]
        self.assertGreater(score_b, 10.0)
        self.assertLess(score_a, 0.1)

        # 1. Search with order_by="relevance" (default BM25):
        # Verified golden MUST maintain superiority over the much hotter regular note!
        results_rel = memory_index.search("Database Architecture Guidelines", order_by="relevance")
        self.assertGreaterEqual(len(results_rel), 2)
        self.assertTrue(results_rel[0]["verified_golden"])
        self.assertIn("golden_arch.md", results_rel[0]["path"])

        # 2. Search with order_by="salience":
        # Verified golden MUST still maintain superiority over regular notes!
        results_sal = memory_index.search("Database Architecture Guidelines", order_by="salience")
        self.assertGreaterEqual(len(results_sal), 2)
        self.assertTrue(results_sal[0]["verified_golden"])
        self.assertIn("golden_arch.md", results_sal[0]["path"])

        # 3. Test programmatic set_verified_golden
        # If we promote Note B to golden as well:
        memory_index.set_verified_golden(chunk_b_id, golden=True)
        # Now both are golden, and Note B has higher salience score, so Note B should rank first among goldens
        results_both_golden = memory_index.search("Database Architecture Guidelines", order_by="salience")
        self.assertEqual(results_both_golden[0]["id"], chunk_b_id)

        # Unmark Note B
        memory_index.set_verified_golden(chunk_b_id, golden=False)
        results_demoted = memory_index.search("Database Architecture Guidelines", order_by="salience")
        self.assertTrue(results_demoted[0]["verified_golden"])
        self.assertIn("golden_arch.md", results_demoted[0]["path"])

    def test_backward_compatibility_defaults(self):
        note_content = (
            "Plain note header\n"
            "## Content\n"
            "Normal plain note with default properties.\n"
        )
        self.write_note("Normal/note1.md", note_content)

        # 1. Check get_salience defaults
        sal = memory_index.get_salience("Normal/note1.md#2")
        self.assertEqual(sal["hit_count"], 0)
        self.assertIsNone(sal["last_accessed"])
        self.assertEqual(sal["salience_score"], 0.0)
        self.assertFalse(sal["verified_golden"])

        # 2. Check search result fields
        res = memory_index.search("default properties")
        self.assertEqual(len(res), 1)
        item = res[0]
        self.assertIn("hit_count", item)
        self.assertIn("last_accessed", item)
        self.assertIn("salience_score", item)
        self.assertIn("verified_golden", item)
        self.assertFalse(item["verified_golden"])

    def test_mcp_server_full_flow(self):
        # 1. Propose note with verified_golden = True via server
        prop_req = {
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": "memory_propose",
                "arguments": {
                    "project": "GoldenServerProject",
                    "type": "decision",
                    "title": "Universal Salience Architecture",
                    "content": "Salience score ranking and recall tracking verified.",
                    "tags": ["salience", "mcp"],
                    "verified_golden": True
                }
            }
        }
        prop_resp = server.handle_request(prop_req)
        prop_data = json.loads(prop_resp["result"]["content"][0]["text"])
        self.assertTrue(prop_data["success"])
        rid = prop_data["id"]

        # Ensure index updated
        memory_index.sync_index()

        # 2. memory_get via MCP server
        get_req = {
            "method": "tools/call",
            "id": 2,
            "params": {
                "name": "memory_get",
                "arguments": {
                    "record_id": rid
                }
            }
        }
        get_resp = server.handle_request(get_req)
        get_data = json.loads(get_resp["result"]["content"][0]["text"])
        self.assertEqual(get_data["hit_count"], 1)
        self.assertIsNotNone(get_data["last_accessed"])
        self.assertGreater(get_data["salience_score"], 0.0)
        self.assertTrue(get_data["verified_golden"])

        # 3. memory_search via MCP server with order_by="salience"
        search_req = {
            "method": "tools/call",
            "id": 3,
            "params": {
                "name": "memory_search",
                "arguments": {
                    "query": "Universal Salience Architecture",
                    "order_by": "salience"
                }
            }
        }
        search_resp = server.handle_request(search_req)
        search_results = json.loads(search_resp["result"]["content"][0]["text"])
        self.assertTrue(len(search_results) > 0)
        first_hit = search_results[0]
        self.assertIn("hit_count", first_hit)
        self.assertIn("last_accessed", first_hit)
        self.assertIn("salience_score", first_hit)
        self.assertIn("verified_golden", first_hit)
        self.assertTrue(first_hit["verified_golden"])


if __name__ == "__main__":
    unittest.main()
