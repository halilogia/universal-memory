"""Dağıtım koruması: server.py'nin zorunlu modül listesi repoyla uyumlu kalmalı."""
import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _local_imports(path: Path) -> set:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return {n for n in names if (REPO / f"{n}.py").exists()}


class DeployGuardTest(unittest.TestCase):
    def test_required_modules_cover_every_local_import(self):
        import server

        needed = set()
        for py in REPO.glob("*.py"):
            if not py.name.startswith("test_"):
                needed |= _local_imports(py)
        missing = needed - set(server.REQUIRED_MODULES) - {"server"}
        self.assertFalse(missing, f"server.REQUIRED_MODULES eksik: {sorted(missing)}")

    def test_required_modules_exist_in_repo(self):
        import server

        for name in server.REQUIRED_MODULES:
            self.assertTrue((REPO / f"{name}.py").exists(), name)


if __name__ == "__main__":
    unittest.main()
