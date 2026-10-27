import os
import tempfile
import unittest

from tests._vault import VaultTestCase, ROOT
import memory_engine
import context_injector

import sys
sys.path.insert(0, os.path.join(ROOT, "distillation"))
import worker  # noqa: E402

TRANSCRIPT = """\
## Kullanıcı [10:00]
Redis ile denedik ama çalışmadı, bağlantı havuzu tükendi.
## Asistan [10:05]
- Karar verdik: oturum deposu için SQLite kullanılacak.
- Her zaman testleri commit öncesi çalıştır.
- [ ] README güncellenecek
TODO: CI boru hattını ekle
We decided to use WAL mode.
The approach failed on Windows paths.
```
failed in code block should still not crash
```
"""


class DistillTests(unittest.TestCase):
    def test_extracts_negative_decisions_rules_tasks(self):
        d = worker.DeterministicExtractor.extract(TRANSCRIPT)
        self.assertTrue(any("Redis" in x for x in d["failed_approaches"]))
        self.assertTrue(any("Windows" in x for x in d["failed_approaches"]))
        self.assertTrue(any("SQLite" in x for x in d["decisions"]))
        self.assertTrue(any("WAL" in x for x in d["decisions"]))
        self.assertTrue(any("commit öncesi" in x for x in d["rules"]))
        self.assertIn("README güncellenecek", d["unresolved_tasks"])
        self.assertTrue(any("CI" in t for t in d["unresolved_tasks"]))

    def test_pipeline_without_model_and_merge_dedup(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(TRANSCRIPT)
        try:
            out = worker.run_pipeline(f.name, "Demo", use_model=False)
        finally:
            os.unlink(f.name)
        self.assertTrue(out["failed_approaches"])
        self.assertEqual(worker._merge(["a b"], ["A  B", "c", ""]), ["a b", "c"])

    def test_model_failure_is_non_fatal(self):
        orig = worker.subprocess.run
        worker.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("opencode"))
        try:
            self.assertIsNone(worker.OpenCodeDistiller.distill("Demo", "x"))
        finally:
            worker.subprocess.run = orig

    def test_submit_uses_prefixes(self):
        calls = []
        worker.submit({"project": "P", "decisions": ["d1"], "rules": ["r1"], "failed_approaches": ["f1"]},
                      capture=lambda p, t, tags=None: calls.append(t) or {"success": True, "id": t})
        self.assertEqual(calls, ["karar: d1", "kural: r1", "olmadı: f1"])


class CaptureAndContextTests(VaultTestCase):
    def test_capture_prefix_routing(self):
        n = memory_engine.quick_capture("Demo", "olmadı: FTS ile dedup çok yavaş kaldı")
        self.assertTrue(n["success"])
        rec = memory_engine.memory_get(n["id"])
        self.assertEqual(rec["type"], "lesson")
        self.assertIn("negative", rec["tags"])
        self.assertEqual(rec["status"], "canonical")
        k = memory_engine.quick_capture("Demo", "kural: Commit mesajına emoji ekleme")
        self.assertEqual(memory_engine.memory_get(k["id"])["type"], "convention")
        self.assertFalse(memory_engine.quick_capture("Demo", "   ")["success"])
        self.assertFalse(memory_engine.quick_capture("Demo", "karar:  ")["success"])

    def test_context_only_valid_and_within_budget(self):
        a = memory_engine.quick_capture("Demo", "karar: Uretimde debug log acik tutulmali")
        b = memory_engine.quick_capture("Demo", "karar: Uretimde debug log acik tutulmamali asla")
        memory_engine.quick_capture("Demo", "kural: Commit oncesi testleri calistir")
        memory_engine.quick_capture("Demo", "olmadı: Redis baglanti havuzu tukendi")
        memory_engine.memory_handoff("Demo", "ozet", ["x"], ["README guncelle"])
        res = context_injector.build_context("Demo", "debug log", max_chars=2000)
        ids = [c["id"] for c in res["cards"]]
        self.assertIn(b["id"], ids)
        self.assertNotIn(a["id"], ids)               # invalidated -> never injected
        self.assertIn("KURALLAR", res["text"])
        self.assertIn("ÇALIŞMADI", res["text"])
        self.assertIn("- [ ] README guncelle", res["text"])
        self.assertLessEqual(len(res["text"]), 2000)

    def test_context_budget_is_hard_limit(self):
        for i in range(30):
            memory_engine.quick_capture("Demo", f"kural: bambaska kural numarasi {i} " + "uzun " * 30 + f"benzersiz{i}x")
        res = context_injector.build_context("Demo", "", max_chars=500)
        self.assertLessEqual(len(res["text"]), 500)

    def test_time_travel_context(self):
        a = memory_engine.quick_capture("Demo", "karar: Uretimde debug log acik tutulmali")
        memory_engine.quick_capture("Demo", "karar: Uretimde debug log acik tutulmamali asla")
        past = context_injector.build_context("Demo", "debug", as_of="2000-01-01")
        self.assertEqual(past["cards"], [])           # nothing existed yet
        self.assertTrue(a["success"])

    def test_agent_scope_filter(self):
        memory_engine.memory_propose("Demo", "convention", "Ajan A kurali", "yalniz ajan a icin ozel ayar", ["x"],
                                     agent_id="A", _status="canonical")
        memory_engine.memory_propose("Demo", "convention", "Ortak kural", "herkes icin gecerli genel ilke", ["y"],
                                     _status="canonical")
        titles = lambda aid: {c["title"] for c in context_injector.build_context("Demo", "", agent_id=aid)["cards"]}
        self.assertEqual(titles("A"), {"Ajan A kurali", "Ortak kural"})
        self.assertEqual(titles("B"), {"Ortak kural"})

    def test_inject_prompt_prefix(self):
        memory_engine.quick_capture("Demo", "kural: Commit oncesi testleri calistir")
        out = context_injector.inject_prompt("testleri calistir", "Demo")
        self.assertTrue(out.startswith("# HAFIZA BAĞLAMI — Demo"))
        self.assertTrue(out.endswith("testleri calistir"))


if __name__ == "__main__":
    unittest.main()
