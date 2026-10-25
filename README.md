# 🧠 Universal Memory MCP: Git-Tarzı Yapay Zeka Bellek Kütüphanesi

> **Antigravity, Claude Code ve OpenAI Codex için ortak, kalıcı, Git-bağlantılı ve anlık Obsidian hafıza motoru.**

Universal Memory, yapay zeka ajanlarının oturumlar arasında hafızasını kaybetmesini önleyen, kararları ve devir notlarını Git commit hash'lerine mühürleyen ve **SQLite FTS5 BM25** ile milisaniyeler içinde arama yapan hafif ve güçlü bir bellek mimarisidir.

---

## 🏛️ Mimari Genel Bakış (Architecture)

```
┌────────────────────────────────────────────────────────────────────────┐
│               Yapay Zeka Ajanları (AI Agents)                          │
│   🔵 Antigravity (Lider)  |  🟠 Claude Code (İnşa)  |  🟢 Codex (Hız) │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ JSON-RPC 2.0 (stdio)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             Universal Memory MCP Server (server.py)                    │
│   • memory_search   • memory_get   • memory_propose                    │
│   • memory_commit   • memory_handoff                                   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
         ┌──────────────────────────┴──────────────────────────┐
         ▼                                                     ▼
┌─────────────────────────────────┐   ┌──────────────────────────────────┐
│  Obsidian Kasa (Markdown / Git) │   │ SQLite FTS5 Arama Motoru         │
│  • Otomatik Sohbet Transkripti  │   │ (.index/memory_v2.sqlite)        │
│  • projects/<proje>/decisions/  │◄──┤ • Türkçe harf katlama (ç->c vb.) │
│  • projects/<proje>/lessons/    │   │ • Mesaj düzeyinde indeksleme     │
│  • projects/<proje>/handoffs/   │   │ • Git commit bayatlık uyarısı    │
└─────────────────────────────────┘   └──────────────────────────────────┘
```

---

## 📂 Obsidian Kasa Dizin Yapısı (Vault Layout)

Universal Memory, tüm verileri standart Markdown formatında ve insan-okunabilir şekilde saklar:

```text
~/Desktop/GitHub/obsidian/
├── .index/
│   └── memory_v2.sqlite                # FTS5 arama veri tabanı (otomatik üretilir)
│
├── GrandStrategy3D/                    # Otomatik Arşivlenen Sohbetler (Günlük / Oturum)
│   ├── [2026-10-21]_GrandStrategy3D/
│   │   ├── DEV_LOG.md
│   │   └── 2026-10-21.md               # Transkript (## SPEAKER [SAAT] başlıkları)
│   └── ...
│
└── projects/                           # 🏛️ Yapısal Mimari Bellek (Universal Memory)
    └── GrandStrategy3D/
        ├── decisions/                  # Mimari Kararlar (DECISION-*.md)
        ├── lessons/                    # Öğrenilen Dersler & Hata Çözümleri (LESSON-*.md)
        └── handoffs/                   # Oturum Devir Notları (HANDOFF-*.md)
```

---

## 🛠️ Araç Rehberi (Tool Reference)

Universal Memory 5 temel araç sunar. Bu araçlar Git benzeri bir yaşam döngüsüyle çalışır:

### 1. `memory_search` (Arama)
Obsidian kasasındaki tüm sohbetleri ve yapısal notları **mesaj düzeyinde** arar.
- **Özellikler:** 
  - Türkçe harf duyarlıdır (`ç->c, ı->i, ş->s, ö->o, ü->u, ğ->g`). Arama terimi "Kor Saat" yazılsa bile "Kör Saat" ile eşleşir.
  - Önce tüm kelimelerin geçtiği sonuçları (`AND`), yetmezse herhangi bir kelimenin geçtiği sonuçları (`OR`) getirir.
  - Otomatik taze tutulur (kasa değiştiğinde 15 saniyede bir cheap-check yapar).
- **Parametreler:**
  - `query` (string, zorunlu): Aranacak anahtar kelimeler. Tam ifade için `"çift tırnak"` kullanılır.
  - `project` (string, opsiyonel): Proje filtresi (`GrandStrategy3D`, `GravityGuard` vb.).
  - `limit` (integer, varsayılan: 5): Dönecek sonuç sayısı.
- **Dönen Sonuç Örneği:**
  ```json
  {
    "id": "GrandStrategy3D/.../2026-10-21.md#124",
    "project": "GrandStrategy3D",
    "speaker": "CLAUDE CODE (ASİSTAN)",
    "when": "2026-10-21 14:35:10",
    "snippet": "...harita LOD geçişlerinde ==InstancedMesh== kullanıldı...",
    "match_line": 124,
    "source_commit": "a3f81c2",
    "stale_warning": false
  }
  ```

---

### 2. `memory_get` (Tam Metin Çekme)
Arama sonucundaki bir kaydın veya belirli bir satır aralığının tam metnini okur.
- **Parametreler:**
  - `record_id` (string): `memory_search` tarafından dönen `id` (örn: `GrandStrategy3D/.../2026-10-21.md#120:150` veya `decision-uniform-buffer`).

---

### 3. `memory_propose` (Yeni Karar/Ders Taslağı Oluşturma)
Bir ajan yeni bir mimari çözüm, hata çözümü veya optimizasyon keşfettiğinde bunu **`proposal` (taslak)** olarak kaydeder.
- **Nereye Kaydeder?**
  - Sohbet dosyasının üstüne EKLEMEZ!
  - `obsidian/projects/<proje>/decisions/` veya `lessons/` altında **yeni bir bağımsız `.md` dosyası** oluşturur.
  - O anki repo HEAD Git hash'ini (`source_commit`) frontmatter'a mühürler.
- **Dosya Formatı:**
  ```markdown
  ---
  id: decision-batched-mesh-lods
  type: decision
  project: GrandStrategy3D
  title: BatchedMesh ile Harita LOD Optimizasyonu
  status: proposal
  source_commit: e7a912c
  tags: [graphics, threejs, lod]
  created_at: 2026-10-23T23:30:00
  ---
  # BatchedMesh ile Harita LOD Optimizasyonu
  İl sınırları instanced mesh yerine tek bir batched mesh altında birleştirildi...
  ```

---

### 4. `memory_commit` (Kararı Onaylama & Kanunlaştırma)
Önerilen bir kararı (`status: proposal`) inceleyip onaylayarak **resmi standart (`status: canonical`)** haline getirir.
- **Ne Yapar?**
  - İlgili markdown dosyasını açar.
  - `status: proposal` satırını `status: canonical` olarak değiştirir.
  - FTS5 arama veri tabanını anında günceller.
  - Artık gelecekteki aramalarda bu not en güvenilir referans kuralı olarak gelir.

---

### 5. `memory_handoff` (Oturum Devir Teslimi)
Bir çalışma seansı bittiğinde veya görev başka bir ajana/oturumuna devredilirken kullanılır.
- **Nereye Kaydeder?**
  - `obsidian/projects/<proje>/handoffs/HANDOFF-<tarih-saat>.md` dosyası oluşturur.
- **İçerik:**
  - **Özet:** Oturumda nelerin yapıldığı.
  - **Alınan Kararlar:** Mimaride kesinleşen maddeler.
  - **Açık İşler:** Bir sonraki oturumun doğrudan başlayacağı `- [ ]` görev listesi.
- **Yeni Oturum Başlarken:**
  Yeni gelen ajan ilk iş `memory_get` ile en son `HANDOFF` dosyasını okur; bağlam kaybı yaşamadan açık maddelerden çalışmaya devam eder.

---

## 🔒 Git-Commit Bayatlık Uyarısı (Stale Warning)

Universal Memory, kod deposunun Git geçmişi ile Obsidian hafızasını senkron tutar:
1. Bir karar alındığında o anki `git rev-parse --short HEAD` (örn: `8f12d4a`) nota kaydedilir.
2. Ajan gelecekte bu kararı aradığında, sistem projenin güncel `HEAD` commit'ini kontrol eder.
3. Eğer kod değişmiş ve dosya güncellenmemişse, çıktıya `stale_warning: true` eklenir:
   > *"Dikkat: Bu karar 8f12d4a commit'inde alınmış, fakat repo şu an b49c71e commit'inde. Kod değişmiş olabilir, kontrol et!"*

---

## ⚡ Kurulum ve Çalıştırma

Universal Memory standart Python 3 stdio JSON-RPC sunucusudur (sıfır harici bağımlılık, sadece Python yerleşik kütüphaneleri):

```bash
# Doğrudan test çalıştırması
python -X utf8 server.py
```

### Ortam Değişkeni (Opsiyonel)
Varsayılan olarak `UNIVERSAL_MEMORY_VAULT` ortam değişkeniyle Obsidian kasanızın yolunu belirtebilirsiniz:
```bash
# Windows
set UNIVERSAL_MEMORY_VAULT=C:\Users\Kullanici\Obsidian\Kasam

# Linux / macOS
export UNIVERSAL_MEMORY_VAULT=~/obsidian
```
*(Belirtilmezse varsayılan yerel Obsidian kasası otomatik algılanır).*

### `mcp_config.json` Yapılandırması (Antigravity / Claude Code / Codex)
```json
{
  "mcpServers": {
    "universal-memory": {
      "command": "python",
      "args": [
        "-X",
        "utf8",
        "C:\\Users\\Halil Emre\\Desktop\\GitHub\\Public\\universal-memory\\server.py"
      ],
      "env": {
        "UNIVERSAL_MEMORY_VAULT": "C:\\Users\\Halil Emre\\Desktop\\GitHub\\obsidian"
      }
    }
  }
}
```
