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

VAULT_ROOT = os.environ.get("UNIVERSAL_MEMORY_VAULT", os.path.expanduser("~/Desktop/GitHub/obsidian"))


class DeterministicExtractor:
    """Katman 1: Sıfır model maliyetiyle regex ve kural tabanlı çıkarım."""

    TASK_PATTERN = re.compile(r"^\s*-\s*\[ \]\s*(.+)$", re.MULTILINE)
    TODO_PATTERN = re.compile(r"(?:TODO|FIXME|EKSİK):\s*(.+)$", re.IGNORECASE | re.MULTILINE)
    COMMIT_PATTERN = re.compile(r"\b([0-9a-f]{7,40})\b")
    FILE_PATH_PATTERN = re.compile(r"(?:`|'|\")([a-zA-Z0-9_\-/\\]+\.[a-zA-Z0-9]{1,6})(?:`|'|\")")

    # Negative knowledge (tried and failed), durable decisions and standing rules; TR + EN, matched per line.
    NEGATIVE_PATTERN = re.compile(
        r"(çalışmadı|calismadi|işe yaramadı|ise yaramadi|olmadı|başarısız|basarisiz|vazgeçtik|vazgectik|geri aldık|geri aldik|"
        r"sorun çıkardı|sorun cikardi|didn'?t work|doesn'?t work|did not work|does not work|failed|reverted|rolled back|"
        r"dead end|not viable|abandon(?:ed)?|gave up on)", re.IGNORECASE)
    DECISION_PATTERN = re.compile(
        r"(karar verdik|karar verildi|kararlaştırdık|kararlastirdik|karar:|bundan sonra|artık .{2,60} kullan|"
        r"decided to|we decided|the decision is|we will use|going with|switching to|from now on|chosen approach)", re.IGNORECASE)
    RULE_PATTERN = re.compile(
        r"(her zaman|asla |kural:|yasak(?:tır)?\b|zorunlu|\balways\b|\bnever\b|must not|\bmust\b always|rule:)", re.IGNORECASE)
    _NOISE = re.compile(r"^\s*(```|\||#{1,6}\s*$|>\s*$)")

    @classmethod
    def _lines(cls, text: str, pattern: "re.Pattern[str]", limit: int = 15) -> List[str]:
        out: List[str] = []
        for raw in text.splitlines():
            line = re.sub(r"^\s*(?:[-*>]+|\d+[.)])\s*(?:\[[ xX]\]\s*)?", "", raw).strip()
            line = re.sub(r"\*\*|__|`", "", line)
            if not (12 <= len(line) <= 400) or cls._NOISE.match(raw) or not pattern.search(line):
                continue
            if line not in out:
                out.append(line)
            if len(out) >= limit:
                break
        return out

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
            "task_count": len(all_tasks),
            "failed_approaches": cls._lines(text, cls.NEGATIVE_PATTERN),
            "decisions": cls._lines(text, cls.DECISION_PATTERN),
            "rules": cls._lines(text, cls.RULE_PATTERN),
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

        # Attempt to run opencode non-interactively (message is positional: ``opencode run [message..]``)
        cmd = ["opencode", "run"]
        if model:
            cmd.extend(["--model", model])
        cmd.append(f"{cls.SYSTEM_PROMPT}\n\n{prompt}")

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


def _merge(base: List[str], extra: List[Any]) -> List[str]:
    """Order-preserving union; model output is coerced to str and near-duplicates (case/space) are dropped."""
    seen = {" ".join(x.lower().split()) for x in base}
    for item in extra or []:
        item = str(item).strip()
        key = " ".join(item.lower().split())
        if item and key not in seen:
            base.append(item)
            seen.add(key)
    return base


def run_pipeline(file_path: str, project: str, use_model: bool = True) -> Dict[str, Any]:
    """Katman 1 ve 2'yi birleştirip damıtılmış hafıza çıktısı üretir (negatif bilgi, kararlar, kurallar, açık işler)."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    det = DeterministicExtractor.extract(text)
    semantic = OpenCodeDistiller.distill(project, text) if use_model else None

    combined_tasks = det["unresolved_tasks"]
    smart_title = f"{project} Oturumu"
    summary = "Transkript incelendi."
    decisions = list(det["decisions"])
    failed = list(det["failed_approaches"])

    if semantic:
        smart_title = semantic.get("smart_title") or smart_title
        summary = semantic.get("summary") or summary
        decisions = _merge(decisions, semantic.get("decisions") or [])
        failed = _merge(failed, semantic.get("failed_approaches") or [])
        combined_tasks = _merge(combined_tasks, semantic.get("unresolved_tasks") or [])

    return {
        "source_file": file_path,
        "project": project,
        "smart_title": smart_title,
        "summary": summary,
        "decisions": decisions,
        "failed_approaches": failed,
        "rules": det["rules"],
        "unresolved_tasks": combined_tasks,
        "mentioned_files": det["mentioned_files"],
        "timestamp": datetime.now().isoformat()
    }


def submit(distilled: Dict[str, Any], capture: Any = None) -> Dict[str, Any]:
    """Send distilled items to memory via quick_capture (conflict-checked, deduplicated).
    Decisions -> ``karar:``, rules -> ``kural:``, failed approaches -> ``olmadı:``. Returns counts + per-item results."""
    if capture is None:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import memory_engine
        capture = memory_engine.quick_capture
    project = distilled["project"]
    results: List[Dict[str, Any]] = []
    for key, prefix in (("decisions", "karar"), ("rules", "kural"), ("failed_approaches", "olmadı")):
        for item in distilled.get(key, []):
            res = capture(project, f"{prefix}: {item}", tags=["distilled"])
            results.append({"kind": key, "text": item, "success": res.get("success", False),
                            "duplicate_of": res.get("duplicate_of"), "id": res.get("id")})
    return {
        "captured": sum(1 for r in results if r["success"]),
        "duplicates": sum(1 for r in results if r["duplicate_of"] and not r["success"]),
        "results": results,
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = sys.argv[1]
        proj = sys.argv[2] if len(sys.argv) > 2 else "General"
        flags = set(sys.argv[3:])
        out = run_pipeline(path, proj, use_model="--no-model" not in flags)
        if "--submit" in flags:
            out["submitted"] = submit(out)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("Kullanım: python worker.py <transkript_yolu.md> [proje_adi] [--no-model] [--submit]")
