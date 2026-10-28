#!/usr/bin/env python3
"""Repo -> MCP'nin çalıştığı kopya senkronu.

MCP, repodan değil ~/.gemini/mcp/universal-memory/ klasöründen çalışır. Repoya yeni
bir .py eklendiğinde buraya da taşınmazsa "No module named ..." hatası çıkar.

  python tools/sync_deploy.py            # yalnızca farkları listeler (çıkış kodu 1: fark var)
  python tools/sync_deploy.py --apply    # eksik/farklı dosyaları kopyalar, eskileri backups/ altına yedekler

Yalnızca repodaki dosyalar kopyalanır; çalışma kopyasındaki ek dosyalara dokunulmaz.
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = Path.home() / ".gemini" / "mcp" / "universal-memory"


def repo_files() -> list[Path]:
    files = [p for p in REPO.glob("*.py") if not p.name.startswith("test_")]
    files += [p for p in (REPO / "distillation").glob("*.py")] if (REPO / "distillation").is_dir() else []
    return sorted(files)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="farkları kopyala")
    ap.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = ap.parse_args()

    target = args.target
    if not target.is_dir():
        print(f"Hedef klasör yok: {target}", file=sys.stderr)
        return 2

    stamp = time.strftime("%Y%m%d-%H%M%S")
    drift = []
    for src in repo_files():
        rel = src.relative_to(REPO)
        dst = target / rel
        if not dst.exists():
            drift.append((rel, "EKSİK"))
        elif dst.read_bytes() != src.read_bytes():
            drift.append((rel, "FARKLI"))
        else:
            continue
        if args.apply:
            if dst.exists():
                backup = target / "backups" / stamp / rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    if not drift:
        print("Senkron: fark yok.")
        return 0
    for rel, why in drift:
        print(f"{why:7} {rel}" + ("  -> kopyalandı" if args.apply else ""))
    return 0 if args.apply else 1


if __name__ == "__main__":
    sys.exit(main())
