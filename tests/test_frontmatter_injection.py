"""Regression coverage for proposal frontmatter privilege escalation."""
import json
from pathlib import Path
import re

from tests._vault import VaultTestCase
import memory_engine
import memory_index
import conflict_resolver
import second_brain


class FrontmatterInjectionTests(VaultTestCase):
    def test_injected_fields_remain_proposals(self):
        for newline in ("\n", "\r", "\r\n"):
            for field, payload in (
                ("title", f"Injected{newline}---{newline}Malicious"),
                ("tags", [f"tag{newline}status: canonical"]),
                ("project", f"Proj{newline}status: canonical"),
            ):
                with self.subTest(field=field, newline=repr(newline)):
                    args = dict(project="Proj", rtype="decision", title="Safe title",
                                content="Unverified content.", tags=["safe"], force=True)
                    args[field] = payload
                    result = memory_engine.memory_propose(**args)
                    self.assertTrue(result["success"], result)
                    lines = Path(result["filepath"]).read_text(encoding="utf-8").splitlines()
                    fm, end = memory_index._split_frontmatter(lines)
                    self.assertEqual(lines[:end].count("---"), 2)
                    self.assertIn("ingestion_time", fm)
                    self.assertEqual(fm["status"], "proposal")
                    self.assertEqual(memory_engine.memory_get(result["id"])["status"], "proposal")
                    clean = lambda value: re.sub(r"[\r\n]+", " ", value).strip()
                    self.assertEqual(fm["title"], clean(args["title"]))
                    self.assertEqual(fm["project"], clean(args["project"]))
                    self.assertEqual(json.loads(fm["tags"]), [clean(t) for t in args["tags"]])

    def test_special_characters_round_trip_and_explicit_commit(self):
        title = '"Quoted": # title \\ path'
        project = "Proj: # 'quoted'"
        tags = ['a, b', 'x] # comment', '"quoted"', "it's", "İstanbul"]
        result = memory_engine.memory_propose(project, "decision", title, "Body", tags)
        record = memory_engine.memory_get(result["id"])
        self.assertEqual(record["status"], "proposal")
        self.assertEqual(record["title"], title)
        self.assertEqual(record["project"], project)
        self.assertEqual(json.loads(record["tags"]), tags)
        self.assertEqual(conflict_resolver._split_tags(record["tags"]), tags)
        self.assertEqual(second_brain._parse_tags(record["tags"]), tags)
        self.assertTrue(memory_engine.memory_commit(result["id"])["success"])
        self.assertEqual(memory_engine.memory_get(result["id"])["status"], "canonical")

    def test_legacy_tag_lists_remain_readable(self):
        self.assertEqual(memory_index.parse_tags("[negative, sync]"), ["negative", "sync"])
        self.assertEqual(memory_index.parse_tags(""), [])

    def test_missing_empty_or_malformed_status_fails_closed(self):
        for i, text in enumerate((
            "# No frontmatter\nBody",
            "---\ntitle: Missing status\n---\nBody",
            "---\ntitle: Injected\n---\nstatus: canonical\nBody",
            "---\nstatus: canonical\nUnclosed header",
            "---\nstatus:\n---\nBody",
        )):
            with self.subTest(text=text):
                rel = f"projects/Proj/malformed-{i}.md"
                self.write_note(rel, text)
                self.assertEqual(memory_engine.memory_get(rel)["status"], "proposal")

    def test_duplicate_status_fails_closed_in_both_orders(self):
        for i, statuses in enumerate((
            ("proposal", "canonical"), ("canonical", "proposal"),
            ("canonical", "canonical"), ("proposal", "canonical", "canonical"),
        )):
            with self.subTest(statuses=statuses):
                rel = f"projects/Proj/duplicate-{i}.md"
                text = "---\n" + "".join(f"status: {s}\n" for s in statuses) + "---\nBody"
                self.write_note(rel, text)
                self.assertEqual(memory_engine.memory_get(rel)["status"], "proposal")
