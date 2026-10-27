"""Shared fixture: an isolated temporary vault wired into memory_engine / memory_index."""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import memory_engine  # noqa: E402
import memory_index  # noqa: E402


class VaultTestCase(unittest.TestCase):
    def setUp(self):
        self._old_root = memory_engine.VAULT_ROOT
        self.vault = tempfile.mkdtemp(prefix="um-vault-")
        memory_engine.VAULT_ROOT = self.vault
        memory_index._last_check = 0.0

    def tearDown(self):
        memory_engine.VAULT_ROOT = self._old_root
        shutil.rmtree(self.vault, ignore_errors=True)

    def write_note(self, rel, text):
        path = os.path.join(self.vault, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        memory_index.sync_index()
        return path
