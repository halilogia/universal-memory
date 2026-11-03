"""Unit tests for compact_output.py."""
import json
import unittest

import compact_output

HIT = {
    "id": "GravityGuard/[2026-11-03]_x/2026-11-03.md#227",
    "project": "GravityGuard", "type": "note", "title": "x", "agent": "", "session": "",
    "speaker": "3. Token optimizasyonu tamamlandı mı  Analizler tamam uygulama yarım",
    "when": "2026-11-03", "via": "kelime", "cos": None, "snippet": "a  b\n" * 200,
    "match_line": 227, "path": "C:\\vault\\x.md", "status": "proposal",
    "valid_from": "", "valid_until": "", "superseded_by": "", "source_commit": "",
    "head_commit": None, "stale_warning": False, "hit_count": 1,
    "last_accessed": "2026-11-03T13:30:38", "salience_score": 1.0, "verified_golden": False,
}


class CompactOutputTest(unittest.TestCase):
    def test_hit_keeps_only_useful_fields(self):
        out = compact_output.compact_hit(HIT)
        self.assertEqual(set(out), {"id", "when", "snippet"})
        self.assertLessEqual(len(out["snippet"]), compact_output.SNIPPET_MAX)

    def test_signals_and_context_survive(self):
        hit = dict(HIT, agent="Codex", speaker="KULLANICI", stale_warning=True,
                   status="invalidated", context="ctx")
        out = compact_output.compact_hit(hit)
        for key in ("agent", "speaker", "stale_warning", "status", "context"):
            self.assertIn(key, out)

    def test_compact_is_much_smaller_than_verbose(self):
        res = [HIT] * 5
        lean = compact_output.render_search(res)
        full = compact_output.render_search(res, verbose=True)
        self.assertLess(len(lean), len(full) * 0.35)
        self.assertEqual(json.loads(full), res)

    def test_record_drops_empty_and_counters(self):
        rec = {"id": "a", "content": "body", "tags": "", "hit_count": 3, "salience_score": 1.0,
               "relations": {"outgoing": [], "backlinks": []},
               "validity": {"status": "unknown", "reason": "x"}, "status": "proposal"}
        out = json.loads(compact_output.render_record(rec))
        self.assertEqual(out, {"id": "a", "content": "body", "status": "proposal"})

    def test_non_list_search_result_passes_through(self):
        self.assertEqual(compact_output.compact_search({"error": "x"}), {"error": "x"})


if __name__ == "__main__":
    unittest.main()
