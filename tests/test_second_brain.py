"""Second Brain: memory_ingest (damıt), memory_graph (organize/MOC), memory_express (ifade) + MCP bağlantısı."""
import json
import os
import unittest
from unittest import mock

from tests._vault import VaultTestCase
import memory_engine
import memory_index
import second_brain
import server

ARTICLE = (
    "Progressive summarization is the practice of distilling notes in layers. "
    "The first layer captures the raw source, and the second layer bolds the best passages. "
    "You should always highlight only what you will reuse later. "
    "As the author says, \"a note you never revisit is a note you never wrote at all\". "
    "Notes become useful only when they connect to a project you are working on right now. "
    "Never copy a whole article without distilling it into your own words first. "
    "Distilling notes in layers keeps the cost of revisiting them low over time. "
    "Remember to review the layers every week so the summaries stay fresh and honest. "
    "A good summary lets a stranger understand the source in under thirty seconds. "
    "Bolded passages are the second layer, and highlights are the third layer of the stack."
)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def add(project, rtype, title, content, tags=(), status="canonical"):
    res = memory_engine.memory_propose(project, rtype, title, content, list(tags), _status=status)
    assert res["success"], res
    return res["id"]


class IngestTests(VaultTestCase):
    def test_card_structure_indexing_and_seal(self):
        with mock.patch.object(memory_engine, "_get_git_commit", return_value="abc1234"):
            res = second_brain.ingest("Proj", "Progressive Summarization Notes", ARTICLE, "article", ["pkm"])
        self.assertTrue(res["success"], res)
        self.assertEqual(res["type"], "resource")
        self.assertEqual(res["source_commit"], "abc1234")
        self.assertRegex(res["content_hash"], r"^[0-9a-f]{64}$")
        self.assertIn(os.path.join("projects", "Proj", "resources"), res["filepath"])
        text = read(res["filepath"])
        for needle in ("status: canonical", "source_type: article", "source_commit: abc1234", "type: resource",
                       "## Executive Summary", "## Core Takeaways", "## Key Quotes", "## Kaynak (Ham İçerik)"):
            self.assertIn(needle, text)
        self.assertIn("pkm", res["tags"])
        hits = memory_engine.memory_search("stranger thirty seconds", project="Proj")
        self.assertTrue(hits, "ingested card must be searchable via FTS5")
        got = memory_engine.memory_get(res["id"])
        self.assertEqual(got["status"], "canonical")

    def test_extraction_is_verbatim_and_bounded(self):
        res = second_brain.ingest("Proj", "T", ARTICLE)
        d = second_brain.distill(ARTICLE)
        self.assertTrue(2 <= len(d["summary"]) <= 3)
        self.assertTrue(all(s in ARTICLE for s in d["summary"]))
        self.assertTrue(3 <= len(res["takeaways"]) <= 5)
        self.assertTrue(all(t["text"] in ARTICLE for t in res["takeaways"]))
        self.assertTrue(all(s in ARTICLE for s in res["insights"]))
        self.assertTrue(any(t["action"] for t in res["takeaways"]))
        self.assertEqual(res["quotes"], ["a note you never revisit is a note you never wrote at all"])
        self.assertFalse({t["text"] for t in res["takeaways"]} & set(d["summary"]))

    def test_progressive_layers_in_raw_section(self):
        res = second_brain.ingest("Proj", "T", ARTICLE)
        raw = read(res["filepath"]).split("## Kaynak (Ham İçerik)")[1]
        self.assertIn("**", raw)
        self.assertIn("==a note you never revisit is a note you never wrote at all==", raw)

    def test_duplicate_rejected_and_force(self):
        first = second_brain.ingest("Proj", "T", ARTICLE)
        dup = second_brain.ingest("Proj", "T", ARTICLE)
        self.assertFalse(dup["success"])
        self.assertEqual((dup["error"], dup["duplicate_of"]), ("duplicate", first["id"]))
        forced = second_brain.ingest("Proj", "T", ARTICLE, force=True)
        self.assertTrue(forced["success"])
        self.assertNotEqual(forced["id"], first["id"])

    def test_validation_errors(self):
        self.assertFalse(second_brain.ingest("Proj", "T", "text", "podcast")["success"])
        self.assertFalse(second_brain.ingest("Proj", "T", "   ")["success"])
        self.assertFalse(second_brain.ingest("Proj", "T", "text here ok", save_as="decision")["success"])

    def test_secrets_are_redacted(self):
        key = "sk-" + "a1B2c3D4" * 4
        res = second_brain.ingest("Proj", "Keys", f"The deploy token is {key} and must never be shared with anyone at all.")
        self.assertEqual(res["redacted"], 1)
        text = read(res["filepath"])
        self.assertNotIn(key, text)
        self.assertIn("[REDACTED]", text)

    def test_save_as_lesson_goes_to_lessons(self):
        res = second_brain.ingest("Proj", "Lesson Src", ARTICLE, save_as="lesson")
        self.assertIn(os.path.join("projects", "Proj", "lessons"), res["filepath"])
        self.assertEqual(memory_engine.memory_get(res["id"])["type"], "lesson")

    def test_youtube_transcript_timestamps_and_run_on_captions(self):
        words = " ".join(f"word{i % 7} topic{i % 5}" for i in range(120))   # no punctuation: auto-caption style
        transcript = "00:01 hello and welcome to the channel today\n[00:09] " + words + "\n01:02:03 thanks for watching everybody"
        res = second_brain.ingest("Proj", "Video", transcript, "youtube")
        self.assertTrue(res["success"])
        body = " ".join([res["executive_summary"]] + [t["text"] for t in res["takeaways"]])
        self.assertNotIn("00:01", body)
        self.assertNotIn("01:02:03", body)
        self.assertTrue(all(len(t["text"].split()) <= 45 for t in res["takeaways"]))

    def test_turkish_content(self):
        text = ("Kademeli özetleme notları katmanlar halinde damıtma yöntemidir. "
                "Önemli olan her katmanda yalnızca işe yarayan cümleleri seçmektir. "
                "Notlarını mutlaka haftalık gözden geçirmelisin, aksi halde özetler eskir. "
                "İyi bir özet kaynağı otuz saniyede anlatır.")
        res = second_brain.ingest("Proj", "Kademeli Özetleme", text, "audio_transcript")
        self.assertTrue(res["success"])
        self.assertTrue(res["takeaways"])
        self.assertTrue(memory_engine.memory_search("ozetleme katmanlar", project="Proj"))

    def test_related_notes_linked_on_ingest(self):
        did = add("Proj", "decision", "Layered note distilling", "We adopt progressive summarization layers for distilling notes.",
                  ["pkm", "notes"])
        res = second_brain.ingest("Proj", "Summarization Article", ARTICLE, "article", ["pkm", "notes"])
        self.assertIn(did, res["related"])
        self.assertIn(f"- related_to: [[{did}]]", read(res["filepath"]))

    def test_long_content_truncated(self):
        res = second_brain.ingest("Proj", "Big", ARTICLE + " " + ("filler sentence about nothing in particular. " * 1500))
        self.assertTrue(res["truncated"])
        self.assertIn("kısaltıldı", read(res["filepath"]))


class GraphTests(VaultTestCase):
    def _seed(self):
        self.d1 = add("Proj", "decision", "Use SQLite FTS5 index", "Full text search over vault notes with BM25 ranking.", ["search", "sqlite"])
        self.l1 = add("Proj", "lesson", "FTS5 tokenizer folds Turkish", "Unicode tokenizer needs manual folding for Turkish search.", ["search", "turkish"])
        self.r1 = second_brain.ingest("Proj", "BM25 ranking explained", "BM25 ranking weighs term frequency against document length. "
                                      "Search engines like SQLite FTS5 expose bm25 scoring directly. "
                                      "Tune the ranking weights per column when the title matters more.", "article", ["search"])["id"]
        self.o1 = add("Proj", "decision", "Pick Godot for prototypes", "Godot scenes iterate faster than Unity for tiny games.", ["gamedev"])

    def test_links_clusters_and_orphans(self):
        self._seed()
        res = second_brain.graph("Proj")
        self.assertTrue(res["success"])
        pairs = {frozenset((l["source"], l["target"])) for l in res["links"]}
        self.assertIn(frozenset((self.d1, self.l1)), pairs)
        self.assertIn(frozenset((self.d1, self.r1)), pairs)
        self.assertIn(self.o1, res["orphans"])
        md = res["markdown"]
        self.assertIn("# 🗺️ MOC — Proj", md)
        for rid in (self.d1, self.l1, self.r1):
            self.assertIn(f"[[{rid}]]", md)
        self.assertIn("## 🏝️ Bağlantısız Notlar", md)
        self.assertTrue(res["clusters"])
        by_id = {n["id"]: n for n in res["nodes"]}
        self.assertGreaterEqual(by_id[self.d1]["degree"], 2)

    def test_topic_filter_includes_neighbors_only(self):
        self._seed()
        res = second_brain.graph("Proj", "godot")
        self.assertEqual([n["id"] for n in res["nodes"]], [self.o1])
        res = second_brain.graph("Proj", "turkish")
        ids = {n["id"] for n in res["nodes"]}
        self.assertIn(self.l1, ids)
        self.assertIn(self.d1, ids)          # komşu
        self.assertNotIn(self.o1, ids)
        self.assertIn("turkish", res["markdown"].split("\n")[0])

    def test_superseded_records_are_excluded(self):
        self._seed()
        new = add("Proj", "decision", "Use SQLite FTS5 with hybrid vectors", "Add vector scoring next to BM25 search ranking.", ["search", "sqlite"])
        memory_engine.memory_supersede(self.d1, new)
        ids = {n["id"] for n in second_brain.graph("Proj")["nodes"]}
        self.assertIn(new, ids)
        self.assertNotIn(self.d1, ids)

    def test_explicit_wikilink_creates_link(self):
        a = add("Proj", "decision", "Alpha apples", "Apples are red fruit grown in orchards.", ["fruit"])
        b = add("Proj", "lesson", "Quantum routers", "Packet switching differs from circuit design entirely.", ["net"])
        path = memory_engine.memory_get(b)["filepath"]
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n- depends_on: [[{a}]]\n")
        memory_index.sync_index()
        link = second_brain.graph("Proj")["links"][0]
        self.assertEqual({link["source"], link["target"]}, {a, b})
        self.assertEqual((link["kind"], link["relations"]), ("explicit", ["depends_on"]))

    def test_unknown_project(self):
        res = second_brain.graph("Nope")
        self.assertFalse(res["success"])


class ExpressTests(VaultTestCase):
    def _seed(self):
        self.old = add("Proj", "decision", "Use polling for sync", "## Bağlam\nWebhooks are not reachable.\n## Karar\nPoll every minute.\n## Sonuçlar\nHigher latency.", ["sync"])
        self.new = add("Proj", "decision", "Use webhooks for sync", "## Context\nTunnel is available now.\n## Decision\nSwitch to webhooks.", ["sync"])
        memory_engine.memory_supersede(self.old, self.new)
        self.les = add("Proj", "lesson", "Retry sync with backoff", "Webhooks endpoints for sync fail often so retry with exponential backoff.", ["sync", "negative"])
        self.conv = add("Proj", "convention", "Commit small and often", "Keep every commit under one concern at a time.", [])
        memory_engine.memory_handoff("Proj", "Sync layer shipped and verified.", ["Webhooks"], ["Write retry docs", "Add metrics"])

    def test_adr_report(self):
        self._seed()
        res = second_brain.express("Proj", "adr_report")
        self.assertTrue(res["success"])
        md = res["markdown"]
        self.assertIn("# ADR Raporu — Proj", md)
        self.assertEqual(res["counts"], {"Superseded": 1, "Accepted": 1})
        self.assertIn(f"Superseded by [[{self.new}]]", md)
        self.assertIn("- **Durum:** Accepted", md)
        self.assertIn("### Bağlam\nWebhooks are not reachable.", md)
        self.assertIn("### Karar\nSwitch to webhooks.", md)
        self.assertIn("### Sonuçlar\nHigher latency.", md)
        self.assertIn("### İlişkili Dersler / Kaynaklar", md)
        self.assertEqual(sorted(res["sources"]), sorted([self.old, self.new]))
        self.assertLess(md.index("ADR-001: Use polling"), md.index("ADR-002: Use webhooks"))

    def test_release_notes(self):
        self._seed()
        res = second_brain.express("Proj", "release_notes")
        md = res["markdown"]
        self.assertIn("## 🏛️ Mimari Kararlar", md)
        self.assertIn("Use webhooks for sync", md)
        self.assertIn("## 🔁 Geçersiz Kılınanlar", md)
        self.assertIn(f"Use polling for sync → [[{self.new}]]", md)
        self.assertIn("## 📚 Öğrenilen Dersler", md)
        self.assertIn("⚠️ **Denendi, çalışmadı:** Retry sync with backoff", md)
        self.assertIn("Sync layer shipped and verified.", md)
        self.assertIn("- [ ] Write retry docs", md)
        self.assertEqual(res["counts"]["handoffs"], 1)
        future = second_brain.express("Proj", "release_notes", since="2999-01-01")
        self.assertFalse(future["success"])

    def test_project_brief(self):
        self._seed()
        res = second_brain.express("Proj", "project_brief")
        md = res["markdown"]
        for needle in ("# Proje Brifi — Proj", "## 📏 Kurallar", "Commit small and often", "## 🏛️ Aktif Kararlar",
                       "Switch to webhooks.", "## ⚠️ Denendi, Çalışmadı", "## ⏳ Açık İşler", "- [ ] Add metrics",
                       "Sync layer shipped and verified."):
            self.assertIn(needle, md)
        self.assertNotIn("Use polling for sync", md)          # geçersiz karar brifte yok
        self.assertEqual(res["counts"]["open_tasks"], 2)

    def test_topic_filter_and_errors(self):
        self._seed()
        add("Proj", "decision", "Pick Godot for prototypes", "Godot scenes iterate faster than Unity for tiny games.", ["gamedev"])
        res = second_brain.express("Proj", "project_brief", topic="godot")
        self.assertIn("Pick Godot", res["markdown"])
        self.assertNotIn("webhooks", res["markdown"])
        self.assertFalse(second_brain.express("Proj", "slides")["success"])
        self.assertFalse(second_brain.express("Empty", "adr_report")["success"])
        self.assertFalse(second_brain.express("Empty", "project_brief")["success"])


class ServerWiringTests(VaultTestCase):
    def _call(self, name, args):
        req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
        return server.handle_request(req)["result"]["content"][0]["text"]

    def test_tools_listed_and_schema_files_in_sync(self):
        names = {t["name"] for t in server.TOOLS}
        self.assertTrue({"memory_ingest", "memory_graph", "memory_express"} <= names)
        schema_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schemas")
        for t in server.TOOLS:
            if t["name"] in ("memory_ingest", "memory_graph", "memory_express"):
                with open(os.path.join(schema_dir, t["name"] + ".json"), encoding="utf-8") as f:
                    sch = json.load(f)
                self.assertEqual(sch["parameters"], t["inputSchema"], t["name"])
                self.assertEqual(sch["description"], t["description"])

    def test_required_modules_include_second_brain(self):
        self.assertIn("second_brain", server.REQUIRED_MODULES)

    def test_end_to_end_over_mcp(self):
        out = json.loads(self._call("memory_ingest", {"project": "Proj", "title": "Layers", "content": ARTICLE,
                                                      "source_type": "article", "tags": ["pkm"]}))
        self.assertTrue(out["success"])
        add("Proj", "decision", "Adopt layered notes", "Distilling notes in layers is now our standard practice.", ["pkm"])
        moc = self._call("memory_graph", {"project": "Proj", "topic": "layers"})
        self.assertIn("# 🗺️ MOC", moc)
        self.assertIn(f"[[{out['id']}]]", moc)
        brief = self._call("memory_express", {"project": "Proj", "output_type": "project_brief"})
        self.assertIn("# Proje Brifi — Proj", brief)
        self.assertIn("Adopt layered notes", brief)
        err = self._call("memory_express", {"project": "Proj", "output_type": "bogus"})
        self.assertIn("Invalid output_type", err)


if __name__ == "__main__":
    unittest.main()
