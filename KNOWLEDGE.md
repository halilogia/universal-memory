# 🧠 Universal Memory Mühendislik Hafızası (KNOWLEDGE.md)

Bu dosya, Universal Memory projesinin mimari karar kayıtlarını (ADR) ve teknik tuzaklarını (Gotchas) belgeler.

---

## 🏛️ Mimari Karar Kayıtları (ADR)

### [ADR-01] SQLite FTS5 ve Yerel Dosya Hibrit Mimarisi
- **Karar:** Ağır vektör veri tabanları (Chroma, Pinecone) yerine yerel SQLite FTS5 eklentisi ve salt Markdown dosyaları tercih edildi.
- **Gerekçe:** Sıfır arka plan servisi gereksinimi, insan tarafından Obsidian ile okunabilirlik ve mikrosaniye seviyesinde arama hızı.

---

## ⚠️ Kritik Teknik Tuzaklar (Gotchas)

### [GOTCHA-01] SQLite Dosya Kilidi (database is locked)
- **Tuzak:** Birden fazla ajan eşzamanlı hafıza önerisinde bulunduğunda SQLite `busy` hatası verebilir.
- **Çözüm:** SQLite bağlantısında `timeout=15.0` ve WAL modu (`PRAGMA journal_mode=WAL`) etkinleştirilmiştir.
