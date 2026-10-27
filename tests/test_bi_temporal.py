import unittest

from tests._vault import VaultTestCase
import bitemporal
import memory_engine


class TimeLogicTests(unittest.TestCase):
    def test_open_window_is_valid(self):
        self.assertTrue(bitemporal.is_valid_at("", "", "2030-01-01"))

    def test_window_bounds_half_open(self):
        self.assertFalse(bitemporal.is_valid_at("2026-01-01", "2026-06-01", "2025-12-31"))
        self.assertTrue(bitemporal.is_valid_at("2026-01-01", "2026-06-01", "2026-01-01"))
        self.assertTrue(bitemporal.is_valid_at("2026-01-01", "2026-06-01", "2026-05-31T23:59:59"))
        self.assertFalse(bitemporal.is_valid_at("2026-01-01", "2026-06-01", "2026-06-01"))

    def test_garbage_timestamps_are_open(self):
        self.assertIsNone(bitemporal.parse_ts("not-a-date"))
        self.assertIsNone(bitemporal.parse_ts("null"))
        self.assertTrue(bitemporal.is_valid_at("garbage", "", None))

    def test_aware_timestamps_normalised(self):
        self.assertIsNotNone(bitemporal.parse_ts("2026-01-01T10:00:00Z"))

    def test_record_without_end_but_superseded_is_invalid(self):
        self.assertFalse(bitemporal.record_is_valid({"valid_until": "", "status": "superseded"}))
        self.assertFalse(bitemporal.record_is_valid({"valid_until": "", "status": "canonical", "superseded_by": "x"}))
        self.assertTrue(bitemporal.record_is_valid({"valid_until": "", "status": "canonical"}))


class SupersedeTests(VaultTestCase):
    def _propose(self, title, content, **kw):
        res = memory_engine.memory_propose("Demo", "decision", title, content, ["db"], **kw)
        self.assertTrue(res["success"], res)
        return res["id"]

    def test_propose_writes_temporal_fields(self):
        rid = self._propose("Veritabani secimi", "SQLite kullaniyoruz, tek dosya yeterli.", agent_id="claude", run_id="r1")
        rec = memory_engine.memory_get(rid)
        self.assertTrue(rec["ingestion_time"])
        self.assertEqual(rec["valid_from"], rec["ingestion_time"])
        self.assertEqual(rec["valid_until"], "")
        self.assertEqual((rec["agent_id"], rec["run_id"]), ("claude", "r1"))

    def test_supersede_keeps_history_and_links(self):
        old = self._propose("Veritabani secimi", "SQLite kullaniyoruz, tek dosya yeterli.")
        new = self._propose("Sunucu tarafi depolama", "Postgres kullanilacak, cok kullanicili erisim gerekiyor.", force=True)
        res = memory_engine.memory_supersede(old, new, "2026-10-01T00:00:00")
        self.assertTrue(res["success"], res)

        old_rec = memory_engine.memory_get(old)
        self.assertEqual(old_rec["superseded_by"], new)
        self.assertEqual(old_rec["valid_until"], "2026-10-01T00:00:00")
        self.assertEqual(old_rec["status"], "superseded")
        new_rels = memory_engine.memory_get(new)["relations"]["outgoing"]
        self.assertIn({"target": old, "relation": "supersedes"}, new_rels)
        # the old file still exists (never deleted)
        self.assertIn("SQLite", old_rec["content"])

    def test_time_travel_search(self):
        old = self._propose("Cache stratejisi", "Redis onbellek kullaniyoruz uretimde.", valid_from="2026-09-01T00:00:00")
        new = self._propose("Onbellek yeni", "Memcached yerine gecildi hizli onbellek katmani.", force=True)
        memory_engine.memory_supersede(old, new, "2026-10-01T00:00:00")

        def ids(**kw):
            return {r["id"] for r in memory_engine.memory_search("onbellek", **kw)}

        now_hits = {i.split("#")[0] for i in ids()}
        self.assertFalse(any("REDIS" in i.upper() or old.upper() in i.upper() for i in now_hits))
        past = " ".join(ids(as_of="2026-09-15", include_invalid=False))
        self.assertIn(old.upper(), past.upper())
        hist = " ".join(ids(include_invalid=True))
        self.assertIn(old.upper(), hist.upper())

    def test_cannot_supersede_twice_or_self(self):
        a = self._propose("Bir", "alfa beta gama delta kararı")
        b = self._propose("Iki", "tamamen farkli bir konu hakkinda not", force=True)
        c = self._propose("Uc", "ucuncu bambaska icerik burada", force=True)
        self.assertFalse(memory_engine.memory_supersede(a, a)["success"])
        self.assertTrue(memory_engine.memory_supersede(a, b)["success"])
        self.assertFalse(memory_engine.memory_supersede(a, c)["success"])
        self.assertFalse(memory_engine.memory_supersede("yok-boyle-id", b)["success"])

    def test_set_frontmatter_preserves_body(self):
        path = self.write_note("projects/Demo/x.md", "---\nid: x\nstatus: canonical\n---\n\n# T\nbody ---\n")
        bitemporal.set_frontmatter(path, {"status": "superseded", "valid_until": "2026-01-01"})
        with open(path, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("status: superseded", text)
        self.assertIn("valid_until: 2026-01-01", text)
        self.assertTrue(text.endswith("body ---\n"))


if __name__ == "__main__":
    unittest.main()
