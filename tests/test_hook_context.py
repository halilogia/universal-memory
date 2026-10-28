import json
import os
import subprocess
import sys
import tempfile

from tests._vault import VaultTestCase, ROOT
import memory_engine
import hook_context

HOOK = os.path.join(ROOT, "hook_context.py")


class HookContextTests(VaultTestCase):
    def setUp(self):
        super().setUp()
        self.state = os.path.join(self.vault, "state.json")
        os.makedirs(os.path.join(self.vault, "projects"), exist_ok=True)

    def seed(self):
        memory_engine.quick_capture("Demo", "kural: Commit oncesi testleri calistir")
        memory_engine.memory_handoff("Demo", "ozet", ["x"], ["README guncelle"])

    def payload(self, cwd, sid="s1", **kw):
        return json.dumps({"session_id": sid, "cwd": cwd, "hook_event_name": "SessionStart", **kw})

    def run_core(self, raw, **kw):
        return hook_context.run(raw, vault_root=self.vault, state_path=self.state, **kw)

    def test_claude_format_header_and_budget(self):
        self.seed()
        out = self.run_core(self.payload("C:/x/Demo"), max_chars=1500)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertTrue(ctx.startswith(hook_context.HEADER))
        self.assertIn("Commit oncesi", ctx)
        self.assertIn("- [ ] README guncelle", ctx)
        self.assertLessEqual(len(ctx), 1500)

    def test_parent_dir_match(self):
        self.seed()
        self.assertIsNotNone(self.run_core(self.payload("C:/x/Demo/src/deep")))

    def test_antigravity_format(self):
        self.seed()
        raw = json.dumps({"conversationId": "c1", "workspacePaths": ["C:/w/demo"]})
        out = self.run_core(raw)
        msg = out["injectSteps"][0]["systemMessage"]["systemMessage"]
        self.assertTrue(msg.startswith(hook_context.HEADER))

    def test_dedupe_same_session_and_compact_reinject(self):
        self.seed()
        raw = self.payload("C:/x/Demo", sid="A")
        self.assertIsNotNone(self.run_core(raw))
        self.assertIsNone(self.run_core(raw))                                   # same session -> silent
        self.assertIsNotNone(self.run_core(self.payload("C:/x/Demo", sid="B")))  # new session
        self.assertIsNotNone(self.run_core(self.payload("C:/x/Demo", sid="A", source="compact")))

    def test_project_not_found(self):
        self.seed()
        self.assertIsNone(self.run_core(self.payload("C:/x/Unknown")))

    def test_empty_vault_and_empty_project(self):
        self.assertIsNone(self.run_core(self.payload("C:/x/Demo")))
        os.makedirs(os.path.join(self.vault, "projects", "Demo"))
        self.assertIsNone(self.run_core(self.payload("C:/x/Demo")))             # folder but no valid cards
        self.assertIsNone(hook_context.run(self.payload("C:/x/Demo"), vault_root=os.path.join(self.vault, "nope")))

    def test_bad_json_raises_in_core(self):
        with self.assertRaises(ValueError):
            self.run_core("{bozuk")

    def _cli(self, stdin, env_extra=None):
        env = dict(os.environ, UNIVERSAL_MEMORY_VAULT=self.vault, UNIVERSAL_MEMORY_HOOK_STATE=self.state)
        env.update(env_extra or {})
        return subprocess.run([sys.executable, HOOK], input=stdin.encode("utf-8"), capture_output=True, env=env, timeout=30)

    def test_cli_fail_open_garbage_and_empty(self):
        for stdin in ("{bozuk", "", "[]", "null", "\x00\xff"):
            r = self._cli(stdin)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, b"")

    def test_cli_fail_open_missing_vault(self):
        r = self._cli(self.payload("C:/x/Demo"), {"UNIVERSAL_MEMORY_VAULT": os.path.join(self.vault, "yok")})
        self.assertEqual((r.returncode, r.stdout), (0, b""))

    def test_cli_end_to_end_and_dedupe(self):
        self.seed()
        r1 = self._cli(self.payload("C:/x/Demo", sid="Z"))
        self.assertEqual(r1.returncode, 0)
        ctx = json.loads(r1.stdout.decode("utf-8"))["hookSpecificOutput"]["additionalContext"]
        self.assertIn(hook_context.HEADER, ctx)
        r2 = self._cli(self.payload("C:/x/Demo", sid="Z"))
        self.assertEqual((r2.returncode, r2.stdout), (0, b""))

    def test_cli_timeout_is_fail_open(self):
        # timeout 0 -> worker cannot finish in time; hook must still exit 0 silently
        env = dict(os.environ, UNIVERSAL_MEMORY_VAULT=self.vault, UNIVERSAL_MEMORY_HOOK_STATE=self.state)
        self.seed()
        r = subprocess.run([sys.executable, HOOK, "--timeout", "0"], input=self.payload("C:/x/Demo", sid="T").encode(),
                           capture_output=True, env=env, timeout=30)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    import unittest
    unittest.main()
