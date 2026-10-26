# 🏛️ Universal Memory Mimarisi (ARCHITECTURE.md)

Universal Memory; Antigravity, Claude Code ve Codex arasında paylaşılan, Git-benzeri iki aşamalı (propose/commit) çalışan kalıcı yapay zeka hafıza motorudur.

---

## 🧩 Katmanlar ve Bileşenler

```
universal-memory/
├── server.py           # Model Context Protocol (MCP) sunucusu (stdio üzerinden JSON-RPC)
├── memory_engine.py    # İki aşamalı öneri/onay döngüsü (propose, commit, handoff)
├── memory_index.py     # SQLite FTS5 tam metin araması ve Obsidian Markdown senkronizasyonu
├── distillation/       # Oturum sonu bilgi damıtma ve özetleme algoritmaları
└── schemas/            # Bellek kayıtları ve metadata JSON şemaları
```

---

## ⚡ İki Aşamalı Hafıza Döngüsü (Two-Phase Commit)

```mermaid
sequenceDiagram
    participant Agent as Yapay Zeka Ajanı (Antigravity/Claude)
    participant Engine as Memory Engine
    participant SQLite as SQLite FTS5 Deposu
    participant Vault as Obsidian Vault (.md)

    Agent->>Engine: memory_propose(title, content, tags)
    Engine-->>Agent: proposal_id & diff önizleme
    Note over Agent,Engine: Ajan veya İnsan doğrulaması
    Agent->>Engine: memory_commit(proposal_id)
    Engine->>SQLite: Atomik transaction kaydı
    Engine->>Vault: Markdown dosyası olarak diske yaz
    Engine-->>Agent: Onaylandı ve dizine eklendi (status: OK)
```

---

## 🛡️ Dokunulmaz Kurallar
1. **İki Aşamalı Yazma Güvencesi:** Ajanlar doğrudan kalıcı hafızaya körlemesine yazamaz; önce `propose` ile teklif edilir, doğrulandıktan sonra `commit` edilir.
2. **Kişisel Veri ve Gizlilik:** API anahtarları, şifreler ve oturum tokenları bellek indeksine kaydedilemez.
