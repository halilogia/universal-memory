"""
Unit tests for the 3 friction improvements:
1. memory_get(id) #line compatibility and alias support
2. memory_search surround / context_lines support
3. memory_search order_by ("time_asc" | "time_desc") support
"""
import json
import unittest

from tests._vault import VaultTestCase
import memory_engine
import memory_index
import server


class FrictionImprovementsTests(VaultTestCase):
    def test_memory_get_id_alias_and_line_anchors(self):
        note_content = (
            "Line 1: Header\n"
            "## USER [10:00]\n"
            "Line 3: Soru icerigi\n"
            "## ASSISTANT [10:01]\n"
            "Line 5: Cevap icerigi\n"
            "Line 6: Detaylar\n"
        )
        rel_path = "ProjectA/2026-10-28.md"
        self.write_note(rel_path, note_content)

        # 1. Direct memory_index.get with path#line
        rec = memory_index.get(f"{rel_path}#3")
        self.assertIsNotNone(rec)
        self.assertIn("Line 3: Soru icerigi", rec["content"])

        # 2. Test with line range path#3:5
        rec_range = memory_index.get(f"{rel_path}#3:5")
        self.assertIsNotNone(rec_range)
        self.assertEqual(rec_range["lines"], "3-5")
        self.assertIn("Line 3: Soru icerigi", rec_range["content"])
        self.assertIn("Line 5: Cevap icerigi", rec_range["content"])

        # 3. Test with surround parameter
        rec_surr = memory_index.get(f"{rel_path}#3:4", surround=1)
        self.assertIsNotNone(rec_surr)
        self.assertEqual(rec_surr["lines"], "2-5")

        # 4. Test MCP server handle_request using {"id": "..."} instead of record_id
        req = {
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": "memory_get",
                "arguments": {
                    "id": f"{rel_path}#3"
                }
            }
        }
        resp = server.handle_request(req)
        raw_text = resp["result"]["content"][0]["text"]
        self.assertNotIn("Hata: Hafıza kaydı bulunamadı: ''", raw_text)
        parsed = json.loads(raw_text)
        self.assertIn("Line 3: Soru icerigi", parsed["content"])

    def test_memory_search_surround_context(self):
        note_content = (
            "Line 1: Baslangic\n"
            "## USER [12:00]\n"
            "Line 3: Ajan mimarisi nasil calisir?\n"
            "Line 4: Ek soru detaylari\n"
            "## ASSISTANT [12:00]\n"
            "Line 6: Ajan mimarisi 3 fazli calisir.\n"
            "Line 7: Faz 1, Faz 2, Faz 3.\n"
            "Line 8: Bitis satiri.\n"
        )
        rel_path = "Demo/architecture.md"
        self.write_note(rel_path, note_content)

        # Default search has no 'context' field
        res_default = memory_engine.memory_search("mimarisi nasil calisir")
        self.assertTrue(len(res_default) > 0)
        self.assertNotIn("context", res_default[0])

        # Search with surround=2 includes 'context' with surrounding lines
        res_surr = memory_engine.memory_search("mimarisi nasil calisir", surround=2)
        self.assertTrue(len(res_surr) > 0)
        hit = res_surr[0]
        self.assertIn("context", hit)
        self.assertIn("context_range", hit)
        self.assertIn("Line 6: Ajan mimarisi 3 fazli calisir.", hit["context"])

        # Test context_lines alias via server MCP call
        req = {
            "method": "tools/call",
            "id": 2,
            "params": {
                "name": "memory_search",
                "arguments": {
                    "query": "mimarisi nasil calisir",
                    "context_lines": 3
                }
            }
        }
        resp = server.handle_request(req)
        hits = json.loads(resp["result"]["content"][0]["text"])
        self.assertTrue(len(hits) > 0)
        self.assertIn("context", hits[0])
        self.assertIn("Line 6: Ajan mimarisi 3 fazli calisir.", hits[0]["context"])

    def test_memory_search_chronological_order(self):
        # Create 3 notes across different dates
        self.write_note("Chron/2026-08-01.md", "## USER [10:00]\nAgustos baslangic calismasi radar.")
        self.write_note("Chron/2026-09-01.md", "## USER [10:00]\nEylul orta calismasi radar.")
        self.write_note("Chron/2026-10-01.md", "## USER [10:00]\nEkim son calismasi radar.")

        # 1. order_by="time_asc" (earliest first)
        res_asc = memory_engine.memory_search("radar", order_by="time_asc", limit=10)
        self.assertEqual(len(res_asc), 3)
        dates_asc = [r["when"][:10] for r in res_asc]
        self.assertEqual(dates_asc, ["2026-08-01", "2026-09-01", "2026-10-01"])

        # 2. order_by="time_desc" (latest first)
        res_desc = memory_engine.memory_search("radar", order_by="time_desc", limit=10)
        self.assertEqual(len(res_desc), 3)
        dates_desc = [r["when"][:10] for r in res_desc]
        self.assertEqual(dates_desc, ["2026-10-01", "2026-09-01", "2026-08-01"])

        # 3. Test MCP server parameter
        req = {
            "method": "tools/call",
            "id": 3,
            "params": {
                "name": "memory_search",
                "arguments": {
                    "query": "radar",
                    "order_by": "time_asc"
                }
            }
        }
        resp = server.handle_request(req)
        hits = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual([h["when"][:10] for h in hits], ["2026-08-01", "2026-09-01", "2026-10-01"])


if __name__ == "__main__":
    unittest.main()
