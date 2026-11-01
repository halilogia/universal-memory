# 🧠 Universal Memory — Tam Dosyalar ve Mimari Rehberi

> **Sürüm:** v1.2.0  
> **Lisans:** MIT  
> **Durum:** Production / Production-Hardened (Güvenlik Yamalı)  
> **Eşlikçi Doküman:** `UniversalMemory_Tum_Dosyalar_Mimari_Rehberi.pdf`

---

## 1. Giriş ve Çekirdek Felsefe

**Universal Memory**, heterojen yapay zekâ geliştirme ortamlarında (Claude Code, OpenAI Codex, Antigravity, OpenCode, Hermes) ajanların oturumlar boyu edindikleri deneyimleri, kararları, mimari tercihleri ve kullanıcı geri bildirimlerini kalıcı kılan **yerel öncelikli (Local-First)** ve **çift zamanlı (Bi-Temporal)** bir hafıza ve ikinci beyin motorudur.

### Dört Temel İlke
1. **Local-First & Markdown-First:** Tüm bellek kayıtları insan tarafından doğrudan okunabilir, Git ile sürümlenebilir ve Obsidian vault'u ile %100 uyumlu standart Markdown (`.md`) dosyaları olarak saklanır. Hiçbir tescilli ikili veritabanına hapsolmaz.
2. **Bi-Temporal (Çift-Zamanlılık):** Her anı iki eksende izlenir:
   - *Valid Time (Geçerlilik Zamanı):* Olayın veya bilginin gerçek dünyada geçerli olduğu aralık (`valid_from` - `valid_until`).
   - *Transaction/Ingestion Time (İşlenme Zamanı):* Kaydın veritabanına ve kasaya kaydedildiği an (`ingestion_time`).
   Bu sayede sistem geçmişteki herhangi bir commit veya tarihteki hafıza durumunu kusursuz yeniden inşa edebilir (*time-travel queries*).
3. **Fail-Closed Güvenlik & İzolasyon:** Ajanların kendi kendine yetki yükseltmesini engellemek için iki aşamalı onay kapısı vardır: Ajanlar yalnızca `.proposals/` altına öneri bırakabilir. İnsan veya yetkili orkestratör `memory_commit` çağırmadıkça hiçbir kayıt `canonical` (kalıcı hakikat) statüsüne geçemez.
4. **Wikilinks Tabanlı Bilgi Grafiği:** Obsidian çift köşeli ayraç (`[[KAYIT_ID]]`) standardı üzerinden bellekler arasında yönlü bir bilgi ağı (`memory_nodes` ve `memory_edges`) oluşturulur; çelişkiler `[[contradicts: ID]]` bağıyla modellenir.

---

## 2. Mimari Katmanlar ve Sistem Veri Akışı

```
                  ┌────────────────────────────────────────┐
                  │    LLM İstemcileri & Ajan Ekosistemi   │
                  │ (Claude Code, Codex, Antigravity IDE)  │
                  └───────────────────┬────────────────────┘
                                      │ FastMCP (JSON-RPC)
                                      ▼
                  ┌────────────────────────────────────────┐
                  │   server.py (11 Çekirdek MCP Aracı)    │
                  └───────┬────────────────────────┬───────┘
                          │                        │
       Yazma / Öneri      │                        │ Arama / Okuma
                          ▼                        ▼
              ┌──────────────────────┐  ┌──────────────────────┐
              │   memory_engine.py   │  │   memory_index.py    │
              │  (CRUD, Sanitizer,   │  │ (SQLite FTS5, Graph, │
              │  Bi-Temporal Writer) │  │  Fail-Closed Parser) │
              └───────────┬──────────┘  └──────────┬───────────┘
                          │                        │
                          ▼                        ▼
              ┌────────────────────────────────────────────────┐
              │          Obsidian Markdown Kasası              │
              │  (Antigravity/, Claude/, .proposals/, index.db)│
              └────────────────────────────────────────────────┘
```

---

## 3. Tüm Dosyaların Detaylı Rolleri (File-by-File Deep Dive)

### 3.1 `server.py` — FastMCP Protokol Sunucusu
- **Sorumluluk:** Universal Memory'yi dış dünyaya açan ana giriş noktasıdır. FastMCP kütüphanesi üzerinden stdio tabanlı JSON-RPC protokolü sunar.
- **11 Çekirdek MCP Aracı:**
  1. `memory_search`: SQLite FTS5 tam metin araması, stemming, kronolojik sıralama (`order_by`), çok satırlı bağlam (`surround`).
  2. `memory_get`: Belirli bir kaydı ID veya yol ile alma; önbellek, geçerlilik uyarısı ve giden/gelen wikilink ağını getirir.
  3. `memory_propose`: İnsan onayına sunulacak yeni bir hipotez, kural veya karar önerisi oluşturur (`.proposals/`).
  4. `memory_capture`: Doğrudan kanonik hafızaya yazılan hızlı ve yüksek güvenilirlikli kayıt oluşturur.
  5. `memory_supersede`: Eski veya geçersizleşen bir kaydı yeni bir kayıtla çift zamanlı olarak geçersiz kılar (`valid_until` ve `superseded_by`).
  6. `memory_context`: Oturum başında ajana enjekte edilecek proje bağlam paketini derler.
  7. `memory_commit`: İnsan onayıyla `.proposals/` altındaki bir öneriyi `canonical` statüsüne yükseltir.
  8. `memory_handoff`: Ajan oturumunun devir teslim özetini kalıcılaştırır.
  9. `memory_ingest`: İkinci beyin C.O.D.E. boru hattına ham not/oturum aktarımı yapar.
  10. `memory_graph`: Bilgi grafiğinde komşuluk, çelişki ve ilişki sorguları yürütür.
  11. `memory_express`: Bağlantılı bellek kümelerinden yeni sentez ve mimari içgörüler türetir.

### 3.2 `memory_engine.py` — Çekirdek Hafıza Motoru
- **Sorumluluk:** Dosya oluşturma, atomik yazma, çakışma kontrolü ve güvenlik süzgeci.
- **Güvenlik Mimarisi (v1.2 Yaması):**
  - `_clean_field()`: `title`, `project` ve `tags` alanlarındaki tüm satır sonlarını (``, `
`) regex ile temizler.
  - `_safe_str()`: String alanları JSON/YAML uyumlu güvenli serileştirmeye tabi tutar.
  - Ajanlardan gelen kontrolsüz metinlerin frontmatter'ı erkenden kapatması (`
---
`) veya sahte `status: canonical` enjekte etmesi kesin olarak engellenmiştir.
- **Fonksiyonlar:** `memory_propose()`, `memory_capture()`, `memory_commit()`, `memory_supersede()`, `check_validity()`.

### 3.3 `memory_index.py` — SQLite FTS5 & Bilgi Grafiği İndeksleyicisi
- **Sorumluluk:** Kasa dosyalarını izler, SQLite `index.db` içinde tam metin arama ve grafik tablolarını günceller.
- **Fail-Closed Parser (v1.2 Yaması):**
  - `_split_frontmatter()`: Frontmatter bloklarını katı kurallarla ayrıştırır. Yinelenen `status:` anahtarlarında ilk değeri korur veya reddeder.
  - `_file_meta()`: Bir dosyada `status` alanı eksikse, varsayılan değer **`proposal`** olarak atanır. Asla en yetkili durum olan `canonical` atanmaz!
- **Tablolar:**
  - `files`: Dosya meta verileri, mtime, valid_from/until, ingestion_time, status.
  - `files_fts`: SQLite FTS5 tam metin arama sanal tablosu.
  - `memory_nodes` & `memory_edges`: Wikilink ilişkileri (`supports`, `contradicts`, `supersedes`).

### 3.4 `second_brain.py` — C.O.D.E. Metodolojisi & İkinci Beyin
- **Sorumluluk:** Tiago Forte'un *Building a Second Brain* (C.O.D.E. - Capture, Organize, Distill, Express) yaklaşımını yapay zekâya uygular.
- **Bileşenler:**
  - *Distill:* Ham oturum kayıtlarından mimari dersler ve kararlar damıtır.
  - *Express:* Dağınık notları birleştirerek üst seviye sentez raporları ve yol haritaları üretir.

### 3.5 `bitemporal.py` — Çift Zamanlılık Mantığı
- **Sorumluluk:** Hafızanın zaman boyutundaki mutasyonlarını matematiksel olarak yönetir.
- **Zaman Boyutları:**
  - `valid_from` & `valid_until`: Gerçek dünyadaki geçerlilik penceresi.
  - `ingestion_time` & `source_event_time`: Sisteme kaydedilme anı.
- Bu yapı, *"Bu kural 25 Ekim'de geçerli miydi?"* veya *"Bu commit atıldığında model ne biliyordu?"* sorularının yanıtlanmasını sağlar.

### 3.6 `conflict_resolver.py` — Çelişki ve Uyuşmazlık Çözücü
- **Sorumluluk:** Farklı oturumlarda veya farklı ajanlar tarafından üretilen çelişkili bellek kayıtlarını tespit eder.
- Çelişen kayıtları `[[contradicts: ID]]` etiketiyle işaretler; insan onayına sunulacak çözümü hazırlar.

### 3.7 `context_injector.py` & `hook_context.py` — Oturum Başlangıç Enjektörü
- **Sorumluluk:** Claude Code, Codex ve Antigravity'nin `SessionStart` yaşam döngüsüne entegre olur.
- Ajan çalışmaya başladığında projenin en güncel kanonik kararlarını ve mimari kurallarını çeker, prompt penceresini şişirmeden ajanın zihnine enjekte eder.

### 3.8 `session_media.py` — Medya ve Görsel Arşivleyici
- **Sorumluluk:** Ajanların çalışma esnasında ürettiği ekran görüntülerini, UI çizimlerini, SVG diyagramlarını ve grafikleri oturum kimliği ile ilişkilendirerek kasanın yanındaki medya dizininde arşivler.

### 3.9 `tools/sync_deploy.py` — Dağıtım ve Senkronizasyon
- **Sorumluluk:** Geliştirme ortamında yapılan kod ve modül değişikliklerini çalışan MCP sunucusu çalışma zamanına senkronize eder; modül kaymalarını (module drift) engeller.

### 3.10 `tests/` — Test ve Güvenlik Suiti
- **Kapsam:** 80'den fazla otomatik test.
- `test_frontmatter_injection.py`: Frontmatter manipülasyonu, yetki atlatma ve satır sonu enjeksiyonlarının önlendiğini doğrulayan katı güvenlik regresyon testleri.
- `test_v2_friction_improvements.py`: Arama ve getirme ergonomisi testleri.

---

## 4. Güvenlik Vaka Analizi: Matt Abate Bildirimi & Privilege Escalation Yaması

1 Kasım 2026 tarihinde geliştirici Matt Abate tarafından sorumlu bildirimle (`mabate13@gmail.com`) iletilen açık:
- **Zafiyet:** `memory_propose` f-string içinde `title` ve `tags` alanlarını raw yazarken, `memory_index` parser'ı ilk `---` gördüğünde bloğu kapatıyordu ve `status` bulunamayınca varsayılanı `canonical` yapıyordu.
- **Etki:** Bir ajan saldırgan metin içeren bir başlık göndererek insan onayını atlatabiliyor ve öneriyi doğrudan doğrulanmış kanonik hafıza yapabiliyordu.
- **Kalıcı Düzeltme (Commit `94537f9`):**
  1. Girdilerdeki tüm satır sonları temizlendi (`re.sub`).
  2. Parser'a **Fail-Closed** ilkesi getirildi: Eksik veya hatalı status durumunda kayıt daima en düşük yetkili seviye olan `proposal` kalır.
  3. Tekrarlanan anahtarlar reddedildi.
  4. 80/80 test ile doğrulandı.

---

## 5. Dizin Hiyerarşisi (Obsidian Vault Standardı)

```
obsidian/
├── Antigravity/         # Antigravity IDE oturumları ve hafıza kayıtları
├── Claude/              # Claude Code oturumları ve kararları
├── Codex/               # OpenAI Codex oturumları ve çalışma notları
├── .proposals/          # Henüz onaylanmamış hafıza önerileri (İzole)
└── index.db             # SQLite FTS5 ve Graph veritabanı (Otomatik)
```

---

## 6. Sürekli Dokümantasyon Protokolü
Bu doküman ve eşlikçi `UniversalMemory_Tum_Dosyalar_Mimari_Rehberi.pdf` dosyası, repodaki her mimari ve dosya değişikliğinde `tools/update_architecture_pdf.py` ile sürekli güncellenir.
