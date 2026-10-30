# 📋 Universal Memory Görev Takibi (TASKS.md)

---

## 🚀 Aktif Sprint (v1.2)
- [x] **SessionStart Otomatik Bağlam Enjeksiyonu:** `hook_context.py`, fail-open mimari ve 11 test (41/41 test OK).
- [x] **Bitemporal & Çelişki Yönetimi:** `bitemporal.py` ve `conflict_resolver.py` ile zaman damgalı/çelişki takipli hafıza.
- [x] **Core Docs Standardizasyonu:** Temel repo dokümantasyonu.
- [x] **Second Brain (CODE):** `memory_ingest`, `memory_graph`, `memory_express` + 23 test (69/69).
- [ ] **Hibrit Arama:** FTS5 BM25 puanlaması ile semantik benzerlik entegrasyonu.
- [ ] **Sohbet Analizi & Otomatik Özetleme:** Ajan sohbetlerinden otomatik karar çıkarma ve onay zinciri.

---

## ⏳ Backlog
- [ ] Obsidian eklentisi (Community Plugin) paketlemesi
- [ ] Bellek yaşlandırma ve önemsiz kayıtları arşivleme algoritması

---

## ✅ Tamamlananlar (v1.0)
- [x] FastMCP stdio arayüzü
- [x] İki aşamalı commit mekanizması
- [x] SQLite FTS5 tablo yapılandırması
- [x] Markdown dışa aktarımı
