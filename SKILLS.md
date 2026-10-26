# 📜 SKILLS.md — Universal Memory Geliştirici & Ajan Standartları

Bu doküman, Universal Memory projesinde çalışan ajanlar ve geliştiriciler için mimari standartları ve DoD kriterlerini tanımlar.

---

## 🎯 Temel İlkeler ve Sınırlar

- **Platform:** Python 3.10+, SQLite 3 (FTS5).
- **Hafıza Bütünlüğü:** Doğrulanmamış veriler asla kalıcı depoya taşınamaz.
- **200 Satır Kuralı:** Dokümantasyon 200 satırı aşamaz.

---

## ✅ Tamamlanma Kriteri (Definition of Done)

1. `pytest` testleri hatasız tamamlanmalı.
2. `TASKS.md` güncellenmeli.
3. Pre-Push kapısı doğrulanarak commit alınıp GitHub'a push edilmeli.
