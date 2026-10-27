import unittest

from tests._vault import VaultTestCase
import conflict_resolver as cr
import memory_engine


class ClassifyTests(unittest.TestCase):
    def test_identical_is_duplicate(self):
        sim = cr.similarity("Log seviyesi", "Uretimde log seviyesi INFO olmali", ["log"],
                            "Log seviyesi", "Uretimde log seviyesi INFO olmali", ["log"])
        self.assertGreaterEqual(sim, cr.DUPLICATE_THRESHOLD)
        self.assertEqual(cr.classify("Log seviyesi", "Uretimde log seviyesi INFO olmali",
                                     "Log seviyesi", "Uretimde log seviyesi INFO olmali", sim), "duplicate")

    def test_unrelated(self):
        sim = cr.similarity("Renk paleti", "Mavi tonlar", [], "Veritabani", "Postgres indeks", [])
        self.assertEqual(cr.classify("Renk paleti", "Mavi tonlar", "Veritabani", "Postgres indeks", sim), "unrelated")

    def test_negation_flip_is_contradiction(self):
        verdict = cr.classify("Debug log", "Uretimde debug log acik tutulmali", "Debug log",
                              "Uretimde debug log acik tutulmamali asla", 0.5)
        self.assertEqual(verdict, "contradiction")

    def test_replacement_cue_is_update(self):
        verdict = cr.classify("Depolama", "Artik Postgres kullanilacak depolama icin", "Depolama",
                              "SQLite kullanilacak depolama icin", 0.5)
        self.assertEqual(verdict, "update")

    def test_turkish_folding(self):
        a = cr._tokens("ÇALIŞMADI şeker")
        self.assertIn("calismadi", a)
        self.assertIn("seker", a)


class ProposeFlowTests(VaultTestCase):
    def test_duplicate_is_rejected_then_forced(self):
        first = memory_engine.memory_propose("Demo", "decision", "Log seviyesi", "Uretimde log seviyesi INFO olmali", ["log"])
        self.assertTrue(first["success"])
        dup = memory_engine.memory_propose("Demo", "decision", "Log seviyesi", "Uretimde log seviyesi INFO olmali", ["log"])
        self.assertFalse(dup["success"])
        self.assertEqual(dup["error"], "duplicate")
        self.assertEqual(dup["duplicate_of"], first["id"])
        forced = memory_engine.memory_propose("Demo", "decision", "Log seviyesi", "Uretimde log seviyesi INFO olmali", ["log"], force=True)
        self.assertTrue(forced["success"])

    def test_other_project_not_compared(self):
        memory_engine.memory_propose("Demo", "decision", "Log seviyesi", "Uretimde log seviyesi INFO olmali", ["log"])
        other = memory_engine.memory_propose("Baska", "decision", "Log seviyesi", "Uretimde log seviyesi INFO olmali", ["log"])
        self.assertTrue(other["success"])

    def test_contradiction_linked_and_superseded_on_commit(self):
        old = memory_engine.memory_propose("Demo", "convention", "Debug log", "Uretimde debug log acik tutulmali", ["log"])
        memory_engine.memory_commit(old["id"])
        new = memory_engine.memory_propose("Demo", "convention", "Debug log",
                                           "Uretimde debug log acik tutulmamali asla", ["log"])
        self.assertTrue(new["success"], new)
        self.assertEqual(new["conflict_action"], "supersede_candidates")
        self.assertEqual(new["contradicts"], [old["id"]])
        # still valid until the new one is committed
        self.assertEqual(memory_engine.memory_get(old["id"])["status"], "canonical")
        res = memory_engine.memory_commit(new["id"])
        self.assertEqual(res["superseded"], [old["id"]])
        old_rec = memory_engine.memory_get(old["id"])
        self.assertEqual(old_rec["status"], "superseded")
        self.assertEqual(old_rec["superseded_by"], new["id"])

    def test_superseded_record_no_longer_a_candidate(self):
        old = memory_engine.memory_propose("Demo", "decision", "Depolama", "SQLite kullanilacak depolama", ["db"])
        memory_engine.memory_commit(old["id"])
        new = memory_engine.memory_propose("Demo", "decision", "Depolama", "Artik Postgres kullanilacak depolama", ["db"])
        memory_engine.memory_commit(new["id"])
        res = cr.analyze("Demo", "decision", "Depolama", "SQLite kullanilacak depolama", ["db"])
        self.assertNotIn(old["id"], [c["id"] for c in res["candidates"]])

    def test_quick_capture_supersedes_canonical(self):
        a = memory_engine.quick_capture("Demo", "karar: Uretimde debug log acik tutulmali")
        self.assertTrue(a["success"], a)
        b = memory_engine.quick_capture("Demo", "karar: Uretimde debug log acik tutulmamali asla")
        self.assertTrue(b["success"], b)
        self.assertEqual(b["superseded"], [a["id"]])
        self.assertEqual(memory_engine.memory_get(a["id"])["status"], "superseded")


if __name__ == "__main__":
    unittest.main()
