"""
Second Brain katmanı (Tiago Forte CODE: Capture, Organize, Distill, Express) — kasanın üstünde, bi-temporal/FTS5 çekirdeğe dokunmadan.

  * ingest()  Damıt:   ham içerik -> Kademeli Özetleme + extract_wisdom benzeri atomik kart (resources/ veya lessons/)
  * graph()   Organize: karar/ders/kaynak arasında ortak etiket+anahtar kelime bağlantıları, MOC (Map of Content)
  * express() İfade:   ADR raporu / sürüm notları / proje brifi

Deterministiktir (frekans tabanlı çıkarımsal özet, gömme/LLM yok). Kartlar normal kasa notlarıdır: frontmatter id/type/
status/source_commit/bi-temporal alanları taşır, `sync_vault()` ile FTS5'e girer, wikilink'ler `memory_edges`'e düşer.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import memory_engine
import memory_index
from bitemporal import now_iso, record_is_valid

SOURCE_TYPES = ("text", "youtube", "article", "audio_transcript")
SAVE_AS = {"resource": "resources", "lesson": "lessons"}
OUTPUT_TYPES = ("adr_report", "release_notes", "project_brief")
RAW_CAP = 20000          # karta yazılan ham içerik üst sınırı (karakter)
KW_TOP = 12              # bir not için tutulan anahtar kelime sayısı
LINK_MIN = 3             # bağlantı eşiği: 2*ortak_etiket + ortak_anahtar_kelime
GRAPH_TYPES = ("decision", "lesson", "resource", "convention")
IGNORE_TAGS = {"quick-capture", "negative"}   # her notta olan etiketler bağlantı üretmesin
_TYPE_LABEL = {"decision": "🏛️ Kararlar", "lesson": "📚 Dersler", "resource": "📥 Kaynaklar", "convention": "📏 Kurallar"}

_STOP: Set[str] = set(memory_index._STOP) | set(
    "gibi daha cok ama fakat ancak veya olarak olan oldugu var yok her hem kadar sonra once ise bunu bunun buna sunu onu "
    "icinde uzerinde bile hic tum ben sen biz siz onlar degil olur olmak etmek yapmak yani zaten sadece simdi nasil neden "
    "hangi butun bence sey the and for are but not you all any can had her was one our out has his how its may who did get "
    "got that this with from they have will what when your there their would about which been were them then than into "
    "just like also some more very over only other these those being could should because while where".split())
_WORD = re.compile(r"[^\W_]{3,}")
_TS = re.compile(r"^\s*[\[(]?\d{1,2}:\d{2}(?::\d{2})?[\])]?\s*[-–]?\s*")
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_QUOTE = re.compile(r"[\"“«]([^\"”»\n]{20,300})[\"”»]")
_CUE = re.compile(r"\b(?:important|key|must|should|need to|needs to|remember|always|never|lesson|tip|mistake|critical|todo|"
                  r"action|make sure|onemli|kritik|mutlaka|gerek|yapmal|lazim|dikkat|asla|hata|ipucu|unutma|ders)")
_ACTION = re.compile(r"\b(?:should|must|need to|needs to|todo|action|always|never|make sure|remember|yapmal|gerek|lazim|"
                     r"mutlaka|unutma|kullan|ekle|kontrol et)")
_SECRET = re.compile(
    r"sk-[A-Za-z0-9_\-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{35}|xox[baprs]-[A-Za-z0-9\-]{10,}"
    r"|(?i:bearer)\s+[A-Za-z0-9._\-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")


# --------------------------------------------------------------------------- text helpers

def _tokens(text: str) -> List[str]:
    return [t for t in _WORD.findall(memory_index.fold(text)) if not t.isdigit() and t not in _STOP]


def _split_sentences(text: str) -> List[str]:
    out: List[str] = []
    seen: Set[str] = set()
    for part in _SENT_SPLIT.split(text):
        s = re.sub(r"^[-*•>#\s]+", "", _TS.sub("", part))
        words = s.split()
        if len(words) < 3:
            continue
        pieces = [" ".join(words[i:i + 30]) for i in range(0, len(words), 30)] if len(words) > 45 else [" ".join(words)]
        for p in pieces:
            if len(p.split()) >= 3 and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def _keywords(title: str, body: str, k: int = KW_TOP) -> List[str]:
    body = re.sub(r"^#.*$|^\s*-\s*[a-z_]+:\s*\[\[.*$", "", body[:8000], flags=re.MULTILINE)
    counts = Counter(_tokens(title) * 3 + _tokens(body))
    return [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def _redact(text: str) -> tuple[str, int]:
    return _SECRET.subn("[REDACTED]", text)


def _one_line(text: str, width: int = 200) -> str:
    t = re.sub(r"^#.*$|^\s*-\s*[a-z_]+:\s*\[\[.*$", "", text or "", flags=re.MULTILINE)
    t = " ".join(re.sub(r"[*_`>=]+", "", t).split())
    return t if len(t) <= width else t[: width - 1].rstrip() + "…"


def _jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def _split_sections(body: str) -> List[tuple[str, str]]:
    """[(temiz başlık, metin)] — başlık: ASCII katlanmış, emoji/noktalama yok (örn. '📋 Özet' -> 'ozet')."""
    parts = re.split(r"^#{2,6}\s+(.*)$", body, flags=re.MULTILINE)
    return [(re.sub(r"[^a-z0-9 ]", "", memory_index.fold(parts[i])).strip(), parts[i + 1].strip())
            for i in range(1, len(parts) - 1, 2)]


def _section(sections: List[tuple[str, str]], *keys: str) -> str:
    for head, text in sections:
        if any(head.startswith(k) for k in keys):
            return text
    return ""


# --------------------------------------------------------------------------- MODÜL 1: damıtma

def distill(content: str) -> Dict[str, Any]:
    """Kademeli özetleme: yürütme özeti, atomik çıkarımlar (aksiyon bayraklı), alıntılar, içgörüler, anahtar kelimeler.
    Her cümle kaynaktan birebir seçilir (uydurma yok); sıralama = terim frekansı x ipucu bonusu."""
    sents = _split_sentences(content)
    n = len(sents)
    if n == 0:
        return {"summary": [], "takeaways": [], "quotes": [], "insights": [], "keywords": [], "l1": []}
    toks = [_tokens(s) for s in sents]
    freq = Counter(t for ts in toks for t in ts)
    score = []
    for i, ts in enumerate(toks):
        base = sum(freq[t] for t in set(ts)) / math.sqrt(len(ts)) if ts else 0.0
        words = len(sents[i].split())
        base *= (1.25 if _CUE.search(memory_index.fold(sents[i])) else 1.0) * (1.1 if i == 0 else 1.0) * (0.5 if words < 6 else 1.0)
        score.append(base)
    order = sorted(range(n), key=lambda i: (-score[i], i))
    used: List[int] = []

    def pick(k: int, lo: int, hi: int, reuse: bool = False) -> List[int]:
        chosen: List[int] = []
        for i in order:
            if len(chosen) >= k:
                break
            if i in chosen or (i in used and not reuse) or not lo <= len(sents[i].split()) <= hi:
                continue
            if any(_jaccard(toks[i], toks[j]) > 0.6 for j in chosen + used):
                continue
            chosen.append(i)
        return chosen

    summary = list(range(n)) if n <= 3 else pick(3 if n >= 8 else 2, 5, 45) or [0]
    used += summary
    take = pick(5 if n >= 15 else 4 if n >= 8 else 3, 4, 45)
    used += take
    if len(take) < min(3, n):      # küçük içerik: özet cümlelerinden tamamla
        take += [i for i in summary if i not in take][: min(3, n) - len(take)]
    quotes = list(dict.fromkeys(m.strip() for m in _QUOTE.findall(content)))[:3]
    insights = pick(max(0, 5 - len(quotes)) if len(quotes) >= 2 else 3, 40, 220)
    used += insights
    return {
        "summary": [sents[i] for i in sorted(summary)],
        "takeaways": [{"text": sents[i], "action": bool(_ACTION.search(memory_index.fold(sents[i])))} for i in sorted(take)],
        "quotes": quotes,
        "insights": [sents[i] for i in sorted(insights)],
        "keywords": _keywords("", content),
        "l1": [sents[i] for i in order[:8]],
    }


def _highlight(raw: str, bold: List[str], mark: List[str]) -> str:
    """Kademeli özetleme katmanları: **kalın** = 1. katman (en iyi cümleler), ==vurgu== = 2. katman (alıntı/içgörü)."""
    for s in bold:
        if s in raw:
            raw = raw.replace(s, f"**{s}**", 1)
    for s in mark:
        if s in raw and f"=={s}==" not in raw:
            raw = raw.replace(s, f"=={s}==", 1)
    return raw


def _clean_tag(t: str) -> str:
    return re.sub(r"[\[\],\r\n]+", "-", str(t)).strip()


def ingest(project: str, title: str, content: str, source_type: str = "text", tags: Optional[List[str]] = None,
           save_as: str = "resource", force: bool = False) -> Dict[str, Any]:
    """Ham içeriği damıtıp atomik Markdown kartı olarak ``projects/<proje>/resources|lessons/`` altına yazar ve indeksler.

    Kart doğrudan canonical yazılır (kullanıcı bilerek içeri aldı), ``source_commit`` ile Git HEAD'e mühürlenir,
    ``content_hash`` ham içeriğin SHA-256'sıdır; aynı içerik tekrar eklenmez (``force`` ile aşılır).
    Gizli anahtar kalıpları ``[REDACTED]`` ile maskelenir."""
    if source_type not in SOURCE_TYPES:
        return {"success": False, "error": f"Invalid source_type '{source_type}'. Allowed: {', '.join(SOURCE_TYPES)}"}
    if save_as not in SAVE_AS:
        return {"success": False, "error": f"Invalid save_as '{save_as}'. Allowed: {', '.join(SAVE_AS)}"}
    raw, redacted = _redact((content or "").strip())
    if not raw:
        return {"success": False, "error": "Empty content"}

    d = distill(raw)
    title, _ = _redact(" ".join((title or "").split()))
    if not title:
        title = (d["summary"][0] if d["summary"] else raw)[:70].strip() or "Untitled"
    digest = hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()
    user_tags = [_clean_tag(t) for t in (tags or []) if _clean_tag(t)]
    have = {memory_index.fold(t) for t in user_tags}
    all_tags = user_tags + [k for k in _keywords(title, raw)[:3] if k not in have]

    related = _related_ids(project, set(memory_index.fold(t) for t in all_tags), set(_keywords(title, raw)))
    slug = re.sub(r"[^a-z0-9]+", "-", memory_index.fold(title)).strip("-")[:35] or "item"
    rec_id = f"{save_as}-{slug}-{digest[:8]}"
    target_dir = memory_engine._safe_project_dir(project, SAVE_AS[save_as])
    ingestion = now_iso()
    head = memory_engine._get_git_commit(project) or ""

    shown = raw[:RAW_CAP]
    body = _highlight(shown, d["l1"], d["quotes"] + d["insights"])
    if len(raw) > RAW_CAP:
        body += f"\n\n_(ham içerik {len(raw)} karakterden {RAW_CAP} karaktere kısaltıldı)_"

    def render(rid: str) -> str:
        out = [
            "---", f"id: {rid}", f"type: {save_as}", f"project: {project}", f"title: {title}", "status: canonical",
            f"source_type: {source_type}", f"source_commit: {head}", f"content_hash: {digest}",
            "distilled_by: extractive-v1", "tags: [" + ", ".join(all_tags) + "]",
            f"created_at: {datetime.now().isoformat()}", f"ingestion_time: {ingestion}", f"valid_from: {ingestion}",
            "valid_until:", f"source_event_time: {ingestion}", "superseded_by:", "---", "", f"# {title}", "",
            "## Executive Summary", " ".join(d["summary"]), "", "## Core Takeaways",
        ]
        out += [("- [ ] " if t["action"] else "- ") + t["text"] for t in d["takeaways"]]
        if d["quotes"]:
            out += ["", "## Key Quotes"] + [f"> {q}" for q in d["quotes"]]
        if d["insights"]:
            out += ["", "## Extracted Insights"] + [f"- 💡 {s}" for s in d["insights"]]
        if related:
            out += ["", "## İlişkili Notlar"] + [f"- related_to: [[{r}]]" for r in related]
        out += ["", "## Kaynak (Ham İçerik)", body, ""]
        return "\n".join(out)

    target = os.path.join(target_dir, f"{rec_id.upper()}.md")
    try:
        with open(target, "x", encoding="utf-8") as f:
            f.write(render(rec_id))
    except FileExistsError:
        if not force:
            return {"success": False, "error": "duplicate", "duplicate_of": rec_id}
        rec_id = f"{rec_id}-{datetime.now().strftime('%H%M%S%f')}"
        target = os.path.join(target_dir, f"{rec_id.upper()}.md")
        with open(target, "x", encoding="utf-8") as f:
            f.write(render(rec_id))
    memory_engine.sync_vault()
    return {
        "success": True, "id": rec_id, "type": save_as, "filepath": target, "status": "canonical",
        "source_type": source_type, "source_commit": head, "content_hash": digest, "tags": all_tags,
        "executive_summary": " ".join(d["summary"]), "takeaways": d["takeaways"], "quotes": d["quotes"],
        "insights": d["insights"], "related": related, "redacted": redacted, "truncated": len(raw) > RAW_CAP,
    }


# --------------------------------------------------------------------------- kasa okuma

def _parse_tags(value: str) -> List[str]:
    return [t.strip() for t in (value or "").strip("[]").split(",") if t.strip()]


def _read_body(rel: str) -> str:
    try:
        with open(os.path.join(memory_index._vault_root(), rel), "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except OSError:
        return ""
    _, n = memory_index._split_frontmatter(lines)
    return "\n".join(lines[n:]).strip()


def _load(project: str, types: tuple, include_superseded: bool = False, as_of: Optional[str] = None) -> List[Dict[str, Any]]:
    """Projenin ``types`` türündeki kayıtları. Varsayılan: yalnız geçerli (canonical/proposal); geçersizler ``include_superseded`` ile."""
    memory_index.ensure_fresh()
    conn = memory_index.connect()
    try:
        pnorm = memory_index._norm_project(project)
        rows = [r for t in types for r in conn.execute("SELECT * FROM files WHERE pnorm = ? AND rtype = ?", (pnorm, t))]
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        status = (r["status"] or "canonical").lower()
        if status not in ("canonical", "proposal", "superseded", "invalidated"):
            continue
        valid = record_is_valid(r, as_of) and status in ("canonical", "proposal")
        if not valid and not include_superseded:
            continue
        out.append({
            "id": r["rid"] or r["path"].replace(os.sep, "/").removesuffix(".md"), "type": r["rtype"], "title": r["title"],
            "status": status if valid else "superseded", "date": r["date"] or "", "created_at": r["created_at"] or "",
            "path": r["path"], "tags": _parse_tags(r["tags"]), "superseded_by": r["superseded_by"] or "",
            "commit": r["source_commit"] or "", "body": _read_body(r["path"]),
        })
    out.sort(key=lambda n: (n["date"], n["created_at"], n["id"]))
    return out


def _match_topic(nodes: List[Dict[str, Any]], topic: Optional[str]) -> List[Dict[str, Any]]:
    """Konunun tüm kelimelerini içerenler; yoksa herhangi birini içerenler."""
    qt = set(re.findall(r"[^\W_]{2,}", memory_index.fold(topic or "")))
    if not qt:
        return nodes
    vocab = [(n, set(re.findall(r"[^\W_]{2,}", memory_index.fold(f"{n['title']} {' '.join(n['tags'])} {n['body'][:20000]}"))))
             for n in nodes]
    allm = [n for n, v in vocab if qt <= v]
    return allm or [n for n, v in vocab if qt & v]


# --------------------------------------------------------------------------- MODÜL 2: graf + MOC

def _score_pair(tags_a: Set[str], kw_a: Set[str], tags_b: Set[str], kw_b: Set[str]) -> tuple[int, List[str]]:
    st = (tags_a & tags_b) - IGNORE_TAGS
    sk = (kw_a & kw_b) - st
    return 2 * len(st) + len(sk), sorted(st) + sorted(sk)


def _related_ids(project: str, tags: Set[str], kw: Set[str], limit: int = 5) -> List[str]:
    """Yeni kart için mevcut notlar arasından en ilgili olanlar (ingest sırasında çift yönlü bağ için)."""
    scored = []
    for n in _load(project, GRAPH_TYPES):
        s, _ = _score_pair(tags, kw, {memory_index.fold(t) for t in n["tags"]}, set(_keywords(n["title"], n["body"])))
        if s >= LINK_MIN:
            scored.append((-s, n["id"]))
    return [i for _, i in sorted(scored)[:limit]]


def build_graph(project: str, topic: Optional[str] = None) -> Dict[str, Any]:
    """Düğümler (karar/ders/kaynak/kural), çıkarımsal + açık (wikilink) bağlantılar, kümeler, yalnız notlar."""
    nodes = _load(project, GRAPH_TYPES)
    for n in nodes:
        n["tagset"] = {memory_index.fold(t) for t in n["tags"]}
        n["kw"] = set(_keywords(n["title"], n["body"]))
    ids = {n["id"] for n in nodes}
    links: Dict[tuple, Dict[str, Any]] = {}
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            score, shared = _score_pair(a["tagset"], a["kw"], b["tagset"], b["kw"])
            if score >= LINK_MIN:
                links[tuple(sorted((a["id"], b["id"])))] = {"source": a["id"], "target": b["id"], "score": score,
                                                           "shared": shared, "kind": "inferred", "relations": []}
    conn = memory_index.connect()
    try:
        edges = conn.execute("SELECT source_id, target_id, relation FROM memory_edges").fetchall()
    finally:
        conn.close()
    for e in edges:
        s, t = e["source_id"], e["target_id"]
        if s in ids and t in ids and s != t:
            link = links.setdefault(tuple(sorted((s, t))), {"source": s, "target": t, "score": 0, "shared": [],
                                                           "kind": "explicit", "relations": []})
            if e["relation"] not in link["relations"]:
                link["relations"].append(e["relation"])
            if link["kind"] == "inferred":
                link["kind"] = "both"

    scope = nodes
    if topic:
        seeds = {n["id"] for n in _match_topic(nodes, topic)}
        keep = set(seeds)
        for lk in links.values():
            if lk["source"] in seeds or lk["target"] in seeds:
                keep |= {lk["source"], lk["target"]}
        scope = [n for n in nodes if n["id"] in keep]
        links = {k: v for k, v in links.items() if v["source"] in keep and v["target"] in keep}

    adj: Dict[str, Set[str]] = {n["id"]: set() for n in scope}
    for lk in links.values():
        adj[lk["source"]].add(lk["target"])
        adj[lk["target"]].add(lk["source"])
    by_id = {n["id"]: n for n in scope}
    seen: Set[str] = set()
    clusters: List[Dict[str, Any]] = []
    for n in scope:
        if n["id"] in seen or not adj[n["id"]]:
            continue
        comp, stack = [], [n["id"]]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.append(cur)
            stack.extend(adj[cur] - seen)
        terms = Counter(s for lk in links.values() if lk["source"] in comp for s in lk["shared"])
        label = sorted(terms.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if terms else "ilişkili notlar"
        clusters.append({"label": label, "ids": sorted(comp, key=lambda i: (by_id[i]["type"], by_id[i]["date"], i))})
    clusters.sort(key=lambda c: (-len(c["ids"]), c["label"]))
    orphans = [n["id"] for n in scope if not adj[n["id"]]]
    return {"nodes": scope, "links": list(links.values()), "adj": adj, "clusters": clusters, "orphans": orphans}


def graph(project: str, topic: Optional[str] = None) -> Dict[str, Any]:
    g = build_graph(project, topic)
    nodes, adj = g["nodes"], g["adj"]
    if not nodes:
        return {"success": False, "error": f"No decision/lesson/resource records for project '{project}'"
                + (f" matching topic '{topic}'" if topic else "")}
    by_id = {n["id"]: n for n in nodes}
    name = f"{topic} · {project}" if topic else project
    md = [f"# 🗺️ MOC — {name}",
          f"> {len(nodes)} not · {len(g['links'])} bağlantı · {len(g['clusters'])} küme · {len(g['orphans'])} bağlantısız not", ""]
    hubs = sorted((i for i in adj if adj[i]), key=lambda i: (-len(adj[i]), i))[:5]
    if hubs:
        md += ["## 🧭 Merkez Notlar (Hubs)"] + [f"- [[{i}]] — {by_id[i]['title']} · {len(adj[i])} bağlantı" for i in hubs] + [""]
    for c in g["clusters"]:
        md.append(f"## 🧩 Küme: {c['label']}")
        for rtype in GRAPH_TYPES:
            members = [i for i in c["ids"] if by_id[i]["type"] == rtype]
            if not members:
                continue
            md.append(f"### {_TYPE_LABEL[rtype]}")
            for i in members:
                md.append(f"- [[{i}]] — {by_id[i]['title']}")
                md.append("  - ↔ " + " · ".join(f"[[{j}]]" for j in sorted(adj[i])[:6]))
        md.append("")
    if g["orphans"]:
        md += ["## 🏝️ Bağlantısız Notlar", "> Ortak etiket/anahtar kelime yok; bağlamak için etiket ekle veya `[[...]]` ver."]
        md += [f"- [[{i}]] — {by_id[i]['title']} ({by_id[i]['type']})" for i in g["orphans"]]
    return {
        "success": True, "project": project, "topic": topic, "markdown": "\n".join(md).rstrip() + "\n",
        "nodes": [{"id": n["id"], "type": n["type"], "title": n["title"], "status": n["status"], "tags": n["tags"],
                   "keywords": sorted(n["kw"]), "degree": len(adj[n["id"]])} for n in nodes],
        "links": g["links"], "clusters": g["clusters"], "orphans": g["orphans"],
    }


# --------------------------------------------------------------------------- MODÜL 3: ifade (express)

def _head(project: str) -> str:
    return memory_engine._get_git_commit(project) or "—"


def _adr_status(n: Dict[str, Any]) -> str:
    if n["status"] == "superseded":
        return f"Superseded by [[{n['superseded_by']}]]" if n["superseded_by"] else "Superseded"
    return "Proposed" if n["status"] == "proposal" else "Accepted"


def _adr_report(project: str, topic: Optional[str]) -> Dict[str, Any]:
    decisions = _match_topic(_load(project, ("decision",), include_superseded=True), topic)
    if not decisions:
        return {"success": False, "error": f"No decision records for project '{project}'" + (f" matching '{topic}'" if topic else "")}
    g = build_graph(project)
    by_id = {n["id"]: n for n in g["nodes"]}
    counts = Counter(_adr_status(d).split()[0] for d in decisions)
    md = [f"# ADR Raporu — {project}" + (f" · {topic}" if topic else ""),
          f"> {len(decisions)} karar ({counts['Accepted']} kabul, {counts['Proposed']} önerilen, {counts['Superseded']} geçersiz) "
          f"· Git: `{_head(project)}` · {datetime.now().strftime('%Y-%m-%d')}", "", "## İçindekiler"]
    md += [f"- ADR-{i:03d}: [[{d['id']}]] — {d['title']} ({_adr_status(d).split()[0]})" for i, d in enumerate(decisions, 1)]
    for i, d in enumerate(decisions, 1):
        rel = [(m.group(1).lower(), m.group(2).strip()) for m in
               (memory_index._TYPED_EDGE_RE.match(l) for l in d["body"].split("\n")) if m]
        body = "\n".join(l for l in d["body"].split("\n") if not memory_index._TYPED_EDGE_RE.match(l))
        body = re.sub(r"\A#\s+.*\n", "", body.strip()).strip()
        sec = _split_sections(body)
        ctx, dec, cons = _section(sec, "context", "baglam"), _section(sec, "decision", "karar"), _section(sec, "consequence", "sonuc")
        md += ["", "---", f"## ADR-{i:03d}: {d['title']}", f"- **Kimlik:** [[{d['id']}]]", f"- **Durum:** {_adr_status(d)}",
               f"- **Tarih:** {d['date']}", f"- **Etiketler:** {', '.join(d['tags']) or '—'}", f"- **Git:** `{d['commit'] or '—'}`"]
        if rel:
            md.append("- **İlişkiler:** " + ", ".join(f"{r}: [[{t}]]" for r, t in rel))
        md += ["", "### Bağlam", ctx or "_Belirtilmemiş._", "", "### Karar", dec or body or "_Belirtilmemiş._"]
        if cons:
            md += ["", "### Sonuçlar", cons]
        links = [by_id[j] for j in sorted(g["adj"].get(d["id"], ())) if by_id[j]["type"] in ("lesson", "resource")]
        if links:
            md += ["", "### İlişkili Dersler / Kaynaklar"] + [f"- [[{x['id']}]] — {x['title']}" for x in links]
    return {"markdown": "\n".join(md) + "\n", "sources": [d["id"] for d in decisions], "counts": dict(counts)}


def _release_notes(project: str, topic: Optional[str], since: Optional[str]) -> Dict[str, Any]:
    def recent(n: Dict[str, Any]) -> bool:
        return not since or n["date"] >= since[:10]

    decisions = [n for n in _match_topic(_load(project, ("decision",), include_superseded=True), topic) if recent(n)]
    lessons = [n for n in _match_topic(_load(project, ("lesson",)), topic) if recent(n)]
    resources = [n for n in _match_topic(_load(project, ("resource",)), topic) if recent(n)]
    handoffs_all = _load(project, ("handoff",))
    handoffs = [h for h in handoffs_all if recent(h)]
    if not (decisions or lessons or handoffs or resources):
        return {"success": False, "error": f"No records for project '{project}' in the requested window"}
    live = [d for d in decisions if d["status"] != "superseded"]
    md = [f"# Sürüm Notları — {project}" + (f" · {topic}" if topic else ""),
          f"> {datetime.now().strftime('%Y-%m-%d')} · Git: `{_head(project)}`" + (f" · {since[:10]} sonrası" if since else ""), ""]
    if live:
        md += ["## 🏛️ Mimari Kararlar"] + [f"- **{d['title']}** ([[{d['id']}]]) — {_one_line(_section(_split_sections(d['body']), 'decision', 'karar') or d['body'], 160)}" for d in live] + [""]
    if lessons:
        md.append("## 📚 Öğrenilen Dersler")
        md += [("- ⚠️ **Denendi, çalışmadı:** " if "negative" in d["tags"] else "- ") + f"{d['title']} ([[{d['id']}]])" for d in lessons] + [""]
    replaced = [d for d in decisions if d["status"] == "superseded"]
    if replaced:
        md += ["## 🔁 Geçersiz Kılınanlar"] + [f"- {d['title']} → [[{d['superseded_by']}]]" if d["superseded_by"] else f"- {d['title']}" for d in replaced] + [""]
    if resources:
        md += ["## 📥 Eklenen Kaynaklar"] + [f"- {d['title']} ([[{d['id']}]])" for d in resources] + [""]
    done = [(h["date"], _one_line(_section(_split_sections(h["body"]), "ozet"), 240)) for h in handoffs]
    if any(s for _, s in done):
        md += ["## ✅ Tamamlananlar (Handoff Özetleri)"] + [f"- {d} — {s}" for d, s in done if s] + [""]
    tasks = re.findall(r"^\s*-\s*\[ \]\s*(.+)$", handoffs_all[-1]["body"], flags=re.MULTILINE) if handoffs_all else []
    if tasks:
        md += ["## ⏳ Açık İşler"] + [f"- [ ] {t.strip()}" for t in tasks] + [""]
    return {"markdown": "\n".join(md).rstrip() + "\n",
            "sources": [n["id"] for n in decisions + lessons + resources + handoffs],
            "counts": {"decisions": len(live), "lessons": len(lessons), "superseded": len(replaced),
                       "resources": len(resources), "handoffs": len(handoffs)}}


def _project_brief(project: str, topic: Optional[str]) -> Dict[str, Any]:
    def pick(rtype: str) -> List[Dict[str, Any]]:
        return _match_topic(_load(project, (rtype,)), topic)

    conventions, decisions, lessons, resources = pick("convention"), pick("decision"), pick("lesson"), pick("resource")
    handoffs = _load(project, ("handoff",))
    if not (conventions or decisions or lessons or resources or handoffs):
        return {"success": False, "error": f"No records for project '{project}'"}
    md = [f"# Proje Brifi — {project}" + (f" · {topic}" if topic else ""),
          f"> {datetime.now().strftime('%Y-%m-%d')} · Git: `{_head(project)}` · {len(conventions)} kural · {len(decisions)} karar "
          f"· {len(lessons)} ders · {len(resources)} kaynak", ""]
    tasks: List[str] = []
    if handoffs:
        last = handoffs[-1]
        sec = _split_sections(last["body"])
        summary = _one_line(_section(sec, "ozet"), 400)
        tasks = re.findall(r"^\s*-\s*\[ \]\s*(.+)$", last["body"], flags=re.MULTILINE)
        if summary:
            md += [f"## 🎯 Güncel Durum ({last['date']})", summary, ""]

    def block(title: str, items: List[Dict[str, Any]], key: tuple = ()) -> None:
        if items:
            md.append(title)
            for n in items:
                text = _one_line(_section(_split_sections(n["body"]), *key) or n["body"], 180) if key or n["body"] else ""
                md.append(f"- **{n['title']}** ([[{n['id']}]])" + (f": {text}" if text and text != n["title"] else ""))
            md.append("")

    block("## 📏 Kurallar", conventions)
    block("## 🏛️ Aktif Kararlar", decisions, ("decision", "karar"))
    block("## ⚠️ Denendi, Çalışmadı", [n for n in lessons if "negative" in n["tags"]])
    block("## 📚 Dersler", [n for n in lessons if "negative" not in n["tags"]])
    block("## 📥 Kaynaklar", resources, ("executive summary",))
    if tasks:
        md += ["## ⏳ Açık İşler"] + [f"- [ ] {t.strip()}" for t in tasks] + [""]
    g = build_graph(project, topic)
    hubs = sorted((i for i in g["adj"] if g["adj"][i]), key=lambda i: (-len(g["adj"][i]), i))[:3]
    if g["clusters"]:
        by_id = {n["id"]: n for n in g["nodes"]}
        md += ["## 🧭 Bilgi Haritası", "- Kümeler: " + ", ".join(f"{c['label']} ({len(c['ids'])})" for c in g["clusters"][:5])]
        md += ["- Merkez notlar: " + ", ".join(f"[[{i}]]" for i in hubs)] if hubs else []
        md += [f"- Bağlantısız not: {len(g['orphans'])}", ""] if by_id else []
    return {"markdown": "\n".join(md).rstrip() + "\n",
            "sources": [n["id"] for n in conventions + decisions + lessons + resources],
            "counts": {"conventions": len(conventions), "decisions": len(decisions), "lessons": len(lessons),
                       "resources": len(resources), "handoffs": len(handoffs), "open_tasks": len(tasks)}}


def express(project: str, output_type: str = "adr_report", topic: Optional[str] = None,
            since: Optional[str] = None) -> Dict[str, Any]:
    """Kayıtlı kararlar/dersler/handoff'lardan insan ve geliştirici için derlenmiş çıktı (Markdown)."""
    if output_type not in OUTPUT_TYPES:
        return {"success": False, "error": f"Invalid output_type '{output_type}'. Allowed: {', '.join(OUTPUT_TYPES)}"}
    if output_type == "adr_report":
        res = _adr_report(project, topic)
    elif output_type == "release_notes":
        res = _release_notes(project, topic, since)
    else:
        res = _project_brief(project, topic)
    if res.get("success") is False:
        return res
    return {"success": True, "output_type": output_type, "project": project, "topic": topic,
            "source_commit": _head(project), **res}
