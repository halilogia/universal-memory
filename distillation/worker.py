"""
Universal Memory Distillation Worker (Hafıza Fabrikası)
Transkriptlerden deterministik ve serbest model (OpenCode / Ollama) ile:
1. Akıllı Başlık (Smart Title)
2. Açık / Yarım Kalan Görevler (- [ ] Unresolved Tasks)
3. Alınan Kararlar ve Dersler (Decisions & Lessons)
4. Başarısız Denemeler ve Negatif Bilgi (Failed Approaches)
çıkarır ve Proposal Kuyruğuna (Proposal Queue) teslim eder.
"""

import os
import re
import sys
import json
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional

VAULT_ROOT = os.environ.get("UNIVERSAL_MEMORY_VAULT", os.path.expanduser(r"C:\Users\Halil Emre\Desktop\GitHub\obsidian"))


class DeterministicExtractor:
    """Katman 1: Sıfır model maliyetiyle regex ve kural tabanlı çıkarım."""

    TASK_PATTERN = re.compile(r"^\s*-\s*\[ \]\s*(.+)$", re.MULTILINE)
    TODO_PATTERN = re.compile(r"(?:TODO|FIXME|EKSİK):\s*(.+)$", re.IGNORECASE | re.MULTILINE)
    COMMIT_PATTERN = re.compile(r"\b([0-9a-f]{7,40})\b")
    FILE_PATH_PATTERN = re.compile(r"(?:`|'|\")([a-zA-Z0-9_\-/\\]+\.[a-zA-Z0-9]{1,6})(?:`|'|\")")

    @classmethod
    def extract(cls, text: str) -> Dict[str, Any]:
        tasks = cls.TASK_PATTERN.findall(text)
        todos = cls.TODO_PATTERN.findall(text)
        all_tasks = list(dict.fromkeys(tasks + todos))

        # Files mentioned
        files = list(dict.fromkeys([
            f for f in cls.FILE_PATH_PATTERN.findall(text)
            if "/" in f or "\\" in f or f.endswith((".py", ".ts", ".js", ".gd", ".json", ".md", ".shader"))
        ]))[:20]

        return {
            "unresolved_tasks": all_tasks,
            "mentioned_files": files,
            "task_count": len(all_tasks)
        }


class OpenCodeDistiller:
    """Katman 2: OpenCode / yerel model ile semantik çıkarım ve akıllı başlık üretici."""

    SYSTEM_PROMPT = """Sen bir Kıdemli Yazılım Mimarı ve Bilgi Çıkarıcısısın (Knowledge Distiller).
Verilen sohbet transkriptini analiz et ve SADECE aşağıdaki JSON formatında geçerli bir yanıt dön.
Asla markdown formatı veya ek yorum ekleme, sadece saf JSON döndür.

{
  "smart_title": "Projenin ve çözülen asıl mühendislik konusunun 4-7 kelimelik profesyonel başlığı",
  "summary": "Oturumda yapılanların 2 cümlelik teknik özeti",
  "decisions": ["Alınan kesin mimari kararlar"],
  "failed_approaches": ["Denenip çalışmayan veya performansı düşüren yaklaşımlar (Negatif Bilgi)"],
  "unresolved_tasks": ["Açıkta kalan, sonraki oturumlara ertelenen görevler"]
}"""

    @classmethod
    def distill(cls, project: str, raw_text: str, model: Optional[str] = None) -> Optional[Dict[str, Any]]:
        # Sample text: first 2000 chars and last 2000 chars to save context
        clean_text = raw_text.strip()
        if len(clean_text) > 4000:
            sample = clean_text[:2000] + "\n\n...[ara mesajlar atlandı]...\n\n" + clean_text[-2000:]
        else:
            sample = clean_text

        prompt = f"Proje: {project}\n\nTranskript:\n{sample}"

        # Attempt to run opencode run non-interactively
        cmd = ["opencode", "run", "--prompt", f"{cls.SYSTEM_PROMPT}\n\n{prompt}"]
        if model:
            cmd.extend(["--model", model])

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
                errors="replace"
            )
            out = res.stdout.strip()
            # Find json block in output
            m = re.search(r"\{[\s\S]*\}", out)
            if m:
                return json.loads(m.group(0))
        except Exception:
            pass

        return None


def run_pipeline(file_path: str, project: str) -> Dict[str, Any]:
    """Katman 1 ve 2'yi birleştirip damıtılmış hafıza çıktısı üretir."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    det = DeterministicExtractor.extract(text)
    semantic = OpenCodeDistiller.distill(project, text)

    combined_tasks = det["unresolved_tasks"]
    smart_title = f"{project} Oturumu"
    summary = "Transkript incelendi."
    decisions = []
    failed = []

    if semantic:
        smart_title = semantic.get("smart_title") or smart_title
        summary = semantic.get("summary") or summary
        decisions = semantic.get("decisions") or []
        failed = semantic.get("failed_approaches") or []
        for t in semantic.get("unresolved_tasks", []):
            if t not in combined_tasks:
                combined_tasks.append(t)

    return {
        "source_file": file_path,
        "project": project,
        "smart_title": smart_title,
        "summary": summary,
        "decisions": decisions,
        "failed_approaches": failed,
        "unresolved_tasks": combined_tasks,
        "mentioned_files": det["mentioned_files"],
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = sys.argv[1]
        proj = sys.argv[2] if len(sys.argv) > 2 else "General"
        print(json.dumps(run_pipeline(path, proj), ensure_ascii=False, indent=2))
    else:
        print("Kullanım: python worker.py <transkript_yolu.md> [proje_adi]")
