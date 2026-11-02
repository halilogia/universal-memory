"""Cross-project context contracts using an isolated vault and real index."""
from unittest.mock import patch

from tests._vault import VaultTestCase
import context_injector as ctx
import server


class CrossProjectContextTests(VaultTestCase):
    def note(self, name, project="Alpha", title="SQLite", body="database", **fields):
        metadata = dict(project=project, type="lesson", title=title, id=name,
                        status="canonical", date="2026-01-01", valid_from="2020-01-01")
        metadata.update(fields)
        self.write_note(f"{project}/lessons/{name}.md", "---\n" + "\n".join(
            f"{key}: {value}" for key, value in metadata.items()) + "\n---\n" + body)

    def ids(self, project="Alpha", query="sqlite", **kw):
        return {c["id"] for c in ctx.build_context(project, query, **kw)["cards"]}

    def test_named_project_global_and_relevant_foreign(self):
        self.note("local", title="Local rule")
        self.note("global", "global", title="Shared rule")
        self.note("foreign", "Beta", title="SQLite connections")
        self.note("unrelated", "Beta", title="Graphics")
        self.assertEqual(self.ids(), {"local", "global", "foreign"})
        self.assertEqual(self.ids(include_global=False), {"local"})
        self.assertEqual(self.ids(query=""), {"local", "global"})

    def test_all_aliases_and_provenance(self):
        self.note("alpha")
        self.note("beta", "Beta")
        self.note("global", "global")
        for project in ("all", "*", " ALL "):
            with self.subTest(project=project):
                self.assertEqual(self.ids(project, "", include_global=False), {"alpha", "beta", "global"})
        self.assertEqual({c["project"] for c in ctx.build_context("all")["cards"]},
                         {"Alpha", "Beta", "global"})

    def test_cross_project_validity_status_and_agent_filters(self):
        self.note("valid", "Beta")
        self.note("expired", "Beta", valid_until="2021-01-01")
        self.note("superseded", "Beta", superseded_by="valid")
        self.note("proposal", "Beta", status="proposal")
        self.note("private", "Beta", agent_id="other")
        self.note("future", "Beta", valid_from="2099-01-01")
        self.assertEqual(self.ids(agent_id="mine"), {"valid"})
        self.assertEqual(self.ids(agent_id="mine", include_proposals=True), {"valid", "proposal"})
        self.assertEqual(self.ids(agent_id="mine", as_of="2019-01-01"), set())

    def test_handoffs_stay_in_named_project(self):
        self.note("local-task", type="handoff", body="- [ ] Local work")
        self.note("foreign-task", "Beta", type="handoff", date="2026-02-01", body="- [ ] Foreign work")
        text = ctx.build_context("Alpha")["text"]
        self.assertIn("Local work", text)
        self.assertNotIn("Foreign work", text)
        self.assertNotIn("work", ctx.build_context("all")["text"])

    def test_scoring_frequency_title_recency_and_negative(self):
        row = {"rtype": "lesson", "title": "", "tags": "[]"}
        score = lambda body, rank=0: ctx._score(row, body, {"sqlite"}, rank)
        self.assertGreater(score("sqlite sqlite"), score("sqlite"))
        self.assertGreater(score("sqlite"), score("sqlite", 10))
        title_row = dict(row, title="SQLite")
        self.assertEqual(ctx._score(title_row, "", {"sqlite"}, 0), score("sqlite sqlite sqlite"))
        negative = dict(row, tags='["negative"]')
        self.assertGreater(ctx._score(negative, "sqlite", {"sqlite"}, 0), score("sqlite"))
        self.assertEqual(ctx._score(dict(row, tags='["not-negative"]'), "sqlite", {"sqlite"}, 0), score("sqlite"))
        self.assertGreater(score("sqlite"), ctx._score(negative, "unrelated", {"sqlite"}, 0))
        self.assertEqual(score("sqlite " * 12), score("sqlite " * 100))

    def test_verification_keywords_force_and_budget(self):
        for query in ("DOĞRULAMA!", "verification", "review", "kural", "test"):
            with self.subTest(query=query):
                self.assertTrue(ctx.build_context("Alpha", query)["text"].endswith(ctx.VERIFICATION_TEMPLATE))
        self.assertNotIn("Evidence Checklist", ctx.build_context("Alpha", "contest")["text"])
        self.assertTrue(ctx.build_context("Alpha", inject_verification_template=True)["text"].endswith(ctx.VERIFICATION_TEMPLATE))
        with self.assertRaises(ValueError):
            ctx.build_context("Alpha", "test", max_chars=20)
        for budget in (0, 1, 30, 150):
            pack = ctx.build_context("Alpha", max_chars=budget)
            self.assertLessEqual(pack["chars"], budget)
        for invalid in ({"max_chars": -1}, {"card_chars": 0}):
            with self.assertRaises(ValueError):
                ctx.build_context("Alpha", **invalid)

    def test_budget_prefers_relevance_and_preserves_whole_cards_and_template(self):
        self.note("weak", title="Unrelated", body="x" * 200)
        self.note("strong", "Beta", title="SQLite", body="sqlite " * 50)
        budget = len(ctx.VERIFICATION_TEMPLATE) + 360
        pack = ctx.build_context("Alpha", "sqlite", max_chars=budget, inject_verification_template=True)
        self.assertEqual([c["id"] for c in pack["cards"]], ["strong"])
        self.assertLessEqual(pack["chars"], budget)
        self.assertEqual(pack["chars"], len(pack["text"]))
        self.assertIn(pack["cards"][0]["text"], pack["text"])
        self.assertTrue(pack["text"].endswith(ctx.VERIFICATION_TEMPLATE))

    def test_mcp_schema_and_forwarding(self):
        schema = next(t for t in server.TOOLS if t["name"] == "memory_context")["inputSchema"]
        self.assertTrue(schema["properties"]["include_global"]["default"])
        with patch.object(ctx, "build_context", return_value={"text": "context"}) as build:
            with patch.object(server.audit_logger, "log_tool_event"):
                response = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "memory_context", "arguments": {"project": "*",
                        "include_global": False, "inject_verification_template": True}}})
        build.assert_called_once_with("*", "", 3000, None, "", include_global=False,
                                      inject_verification_template=True)
        self.assertEqual(response["result"]["content"][0]["text"], "context")
