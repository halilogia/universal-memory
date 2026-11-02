"""Regression coverage for halilogia/universal-memory#1:
Proper cleanup of memory_nodes and memory_edges on note deletion or id change.
"""
import os
from pathlib import Path
from tests._vault import VaultTestCase
import memory_engine
import memory_index


class GraphCleanupOnDeleteTests(VaultTestCase):
    def test_deleted_note_cleans_up_nodes_edges_and_ghost_backlinks(self):
        # 1. Create target note B
        b_rel = "projects/Proj/target_b.md"
        b_content = """---
id: target_b
type: rule
project: Proj
title: Target Note B
status: canonical
tags: []
---
This is target note B.
"""
        self.write_note(b_rel, b_content)

        # 2. Create source note A linking to note B
        a_rel = "projects/Proj/source_a.md"
        a_content = """---
id: source_a
type: decision
project: Proj
title: Source Note A
status: canonical
tags: []
---
Links to [[target_b]].
"""
        self.write_note(a_rel, a_content)
        memory_index.sync_index()

        # Verify initial backlink exists
        b_record = memory_engine.memory_get("target_b")
        self.assertEqual(len(b_record["relations"]["backlinks"]), 1)
        self.assertEqual(b_record["relations"]["backlinks"][0]["source"], "source_a")

        # Verify database rows exist
        a_norm = os.path.normpath(a_rel)
        conn = memory_index.connect()
        try:
            self.assertEqual(len(conn.execute("SELECT id FROM memory_nodes WHERE path = ?", (a_norm,)).fetchall()), 1)
            self.assertEqual(len(conn.execute("SELECT target_id FROM memory_edges WHERE source_id = 'source_a'").fetchall()), 1)
        finally:
            conn.close()

        # 3. Delete source note A from filesystem
        (Path(self.vault) / a_rel).unlink()
        memory_index.sync_index()

        # Verify database rows are pruned
        conn = memory_index.connect()
        try:
            nodes_a = conn.execute("SELECT id FROM memory_nodes WHERE path = ?", (a_norm,)).fetchall()
            edges_a = conn.execute("SELECT target_id FROM memory_edges WHERE source_id = 'source_a'").fetchall()
            self.assertEqual(len(nodes_a), 0, "Deleted note's memory_nodes row must be removed")
            self.assertEqual(len(edges_a), 0, "Deleted note's memory_edges rows must be removed")
        finally:
            conn.close()

        # 4. Verify target note B no longer returns ghost backlink
        b_after = memory_engine.memory_get("target_b")
        self.assertEqual(len(b_after["relations"]["backlinks"]), 0, "Ghost backlink must not be returned after source note deletion")

    def test_note_id_change_cleans_up_old_node_and_edges(self):
        rel = "projects/Proj/dynamic_id.md"
        content_v1 = """---
id: old_id_123
type: decision
project: Proj
title: Dynamic Note
status: canonical
tags: []
---
Links to [[external_target]].
"""
        self.write_note(rel, content_v1)
        memory_index.sync_index()

        conn = memory_index.connect()
        try:
            self.assertEqual(len(conn.execute("SELECT id FROM memory_nodes WHERE id = 'old_id_123'").fetchall()), 1)
            self.assertEqual(len(conn.execute("SELECT target_id FROM memory_edges WHERE source_id = 'old_id_123'").fetchall()), 1)
        finally:
            conn.close()

        # Change frontmatter id
        content_v2 = """---
id: new_id_456
type: decision
project: Proj
title: Dynamic Note
status: canonical
tags: []
---
Links to [[another_target]].
"""
        self.write_note(rel, content_v2)
        memory_index.sync_index()

        conn = memory_index.connect()
        try:
            old_nodes = conn.execute("SELECT id FROM memory_nodes WHERE id = 'old_id_123'").fetchall()
            old_edges = conn.execute("SELECT target_id FROM memory_edges WHERE source_id = 'old_id_123'").fetchall()
            new_nodes = conn.execute("SELECT id FROM memory_nodes WHERE id = 'new_id_456'").fetchall()
            new_edges = conn.execute("SELECT target_id FROM memory_edges WHERE source_id = 'new_id_456'").fetchall()

            self.assertEqual(len(old_nodes), 0, "Old node_id must be pruned from memory_nodes")
            self.assertEqual(len(old_edges), 0, "Old node_id's edges must be pruned from memory_edges")
            self.assertEqual(len(new_nodes), 1, "New node_id must be present in memory_nodes")
            self.assertEqual(len(new_edges), 1, "New node_id's edges must be present in memory_edges")
        finally:
            conn.close()
