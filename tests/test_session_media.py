import base64
import json
import os
import shutil
import tempfile
import unittest

from tests._vault import ROOT  # noqa: F401  (puts repo on sys.path)
import session_media as sm


class SessionMediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="um-media-")
        self.sess = os.path.join(self.tmp, "sess")
        os.makedirs(self.sess)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def jsonl(self, blocks_per_line):
        p = os.path.join(self.tmp, "s.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            for role, blocks in blocks_per_line:
                f.write(json.dumps({"type": role, "message": {"content": blocks}}) + "\n")
        return p

    def test_widget_svg_and_html(self):
        p = self.jsonl([("assistant", [
            {"type": "tool_use", "name": "mcp__visualize__show_widget",
             "input": {"title": "pro_game_ui_pipeline_pafta", "widget_code": '<svg viewBox="0 0 10 10"><rect/></svg>'}},
            {"type": "tool_use", "name": "mcp__visualize__show_widget",
             "input": {"title": "panel/demo", "widget_code": "<div>x</div>"}}])])
        w = sm.archive_session_media("claude", self.sess, jsonl=p)
        names = sorted(os.path.basename(x) for x in w)
        self.assertEqual(names, ["panel_demo.html", "pro_game_ui_pipeline_pafta.svg"])
        with open(os.path.join(self.sess, "media", "pro_game_ui_pipeline_pafta.svg"), encoding="utf-8") as fh:
            svg = fh.read()
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', svg)

    def test_sendfile_image_marker_base64_and_idempotent(self):
        png = os.path.join(self.tmp, "close_anatolia.png")
        shot = os.path.join(self.tmp, "shot.jpg")
        for q, b in ((png, b"PNGDATA"), (shot, b"JPGDATA")):
            with open(q, "wb") as f:
                f.write(b)
        notes = os.path.join(self.tmp, "n.md")
        with open(notes, "w") as fh:
            fh.write("x")
        p = self.jsonl([
            ("assistant", [{"type": "tool_use", "name": "SendUserFile", "input": {"files": [png, notes]}}]),
            ("user", [{"type": "text", "text": "bak [Image: source: %s]" % shot}]),
            ("user", [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                   "data": base64.b64encode(b"INLINE").decode()}}]),
        ])
        first = sm.archive_session_media("claude", self.sess, jsonl=p)
        self.assertEqual(len(first), 3)
        self.assertTrue(os.path.exists(os.path.join(self.sess, "media", "close_anatolia.png")))
        self.assertEqual(sm.archive_session_media("claude", self.sess, jsonl=p), [])

    def test_name_collision_with_different_content(self):
        items = [sm._item("a", ".svg", data=b"1"), sm._item("a", ".svg", data=b"2")]
        w = sm.write_media(self.sess, items)
        self.assertEqual([os.path.basename(x) for x in w], ["a.svg", "a_2.svg"])

    def test_same_bytes_under_other_name_is_skipped(self):
        w = sm.write_media(self.sess, [sm._item("a", ".png", data=b"X"), sm._item("b", ".png", data=b"X")])
        self.assertEqual([os.path.basename(x) for x in w], ["a.png"])

    def test_codex_and_antigravity(self):
        home = os.path.join(self.tmp, "codex")
        os.makedirs(os.path.join(home, "generated_images", "sid1"))
        open(os.path.join(home, "generated_images", "sid1", "exec-1.png"), "wb").write(b"C")
        w = sm.archive_session_media("codex", self.sess, session_id="sid1", codex_home=home)
        self.assertEqual([os.path.basename(x) for x in w], ["exec-1.png"])
        brain = os.path.join(self.tmp, "brain", "cid1")
        os.makedirs(brain)
        open(os.path.join(brain, "media__1.png"), "wb").write(b"A")
        open(os.path.join(brain, "plan.md"), "w").write("m")
        s2 = os.path.join(self.tmp, "s2")
        w = sm.archive_session_media("antigravity", s2, cid="cid1", brain_dir=os.path.join(self.tmp, "brain"))
        self.assertEqual([os.path.basename(x) for x in w], ["media__1.png"])

    def test_missing_inputs_fail_safe(self):
        self.assertEqual(sm.archive_session_media("claude", self.sess, jsonl=os.path.join(self.tmp, "none")), [])
        self.assertEqual(sm.archive_session_media("bilinmeyen", self.sess), [])


if __name__ == "__main__":
    unittest.main()
