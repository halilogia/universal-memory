#!/usr/bin/env python3
"""
Universal Memory — Tam Dosyalar ve Mimari Rehberi Oluşturucu ve Senkronizasyon Aracı.
ReportLab ile profesyonel Türkçe uyumlu PDF ve eşlikçi Markdown Wiki dokümanı üretir.
"""
import os
import sys
import shutil
from pathlib import Path

# UTF-8 stdout
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = REPO_ROOT / "UniversalMemory_Tum_Dosyalar_Mimari_Rehberi.pdf"
DOCS_DIR = REPO_ROOT / "docs"
MD_PATH = DOCS_DIR / "UniversalMemory_Tum_Dosyalar_Mimari_Rehberi.md"
OBSIDIAN_DIR = Path(os.path.expanduser("~")) / "Desktop" / "GitHub" / "obsidian" / "projects" / "universal-memory"
OBSIDIAN_MD = OBSIDIAN_DIR / "UniversalMemory_Tum_Dosyalar_Mimari_Rehberi.md"
DESKTOP_LNK = Path(os.path.expanduser("~")) / "Desktop" / "UniversalMemory_Tum_Dosyalar_Mimari_Rehberi.lnk"

# Markdown içeriği
WIKI_CONTENT = """# 🧠 Universal Memory — Tam Dosyalar ve Mimari Rehberi

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
  - `_clean_field()`: `title`, `project` ve `tags` alanlarındaki tüm satır sonlarını (`\r`, `\n`) regex ile temizler.
  - `_safe_str()`: String alanları JSON/YAML uyumlu güvenli serileştirmeye tabi tutar.
  - Ajanlardan gelen kontrolsüz metinlerin frontmatter'ı erkenden kapatması (`\n---\n`) veya sahte `status: canonical` enjekte etmesi kesin olarak engellenmiştir.
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
"""

def generate_pdf():
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
        )
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as err:
        print(f"[HATA] ReportLab kütüphanesi eksik: {err}", file=sys.stderr)
        return False

    # Font Kaydı (Segoe UI - %100 Türkçe desteği)
    font_regular = "SegoeUI"
    font_bold = "SegoeUI-Bold"
    try:
        pdfmetrics.registerFont(TTFont('SegoeUI', 'C:/Windows/Fonts/segoeui.ttf'))
        pdfmetrics.registerFont(TTFont('SegoeUI-Bold', 'C:/Windows/Fonts/segoeuib.ttf'))
    except Exception as fe:
        print(f"[UYARI] SegoeUI yüklenemedi, Helvetica kullanılacak: {fe}", file=sys.stderr)
        font_regular = "Helvetica"
        font_bold = "Helvetica-Bold"

    # Sayfa Numaralandırıcı Canvas
    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            num_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.draw_page_decorations(num_pages)
                super().showPage()
            super().save()

        def draw_page_decorations(self, page_count):
            if self._pageNumber == 1:
                return  # Kapak sayfasında üst/alt bilgi çizme
            
            self.saveState()
            self.setFont(font_regular, 8)
            self.setFillColor(colors.HexColor('#64748b'))
            
            # Üstbilgi
            self.drawString(44, 805, "Universal Memory v1.2 — Tüm Dosyalar ve Mimari Rehberi")
            self.setStrokeColor(colors.HexColor('#e2e8f0'))
            self.setLineWidth(0.5)
            self.line(44, 798, 551, 798)
            
            # Altbilgi
            self.line(44, 45, 551, 45)
            self.drawString(44, 32, "Gizli & Proje İçi Dokümantasyon · Local-First, Bi-Temporal Memory Engine")
            self.drawRightString(551, 32, f"Sayfa {self._pageNumber} / {page_count}")
            self.restoreState()

    # Stiller
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=24,
        leading=30,
        textColor=colors.HexColor('#0f172a'),
        alignment=0,
        spaceAfter=10
    )
    
    subtitle_style = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName=font_regular,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#475569'),
        alignment=0,
        spaceAfter=25
    )

    h1_style = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Heading1'],
        fontName=font_bold,
        fontSize=15,
        leading=19,
        textColor=colors.HexColor('#1e3a8a'),
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'Heading2_Custom',
        parent=styles['Heading2'],
        fontName=font_bold,
        fontSize=11.5,
        leading=15,
        textColor=colors.HexColor('#0f766e'),
        spaceBefore=10,
        spaceAfter=5,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'Body_Custom',
        parent=styles['BodyText'],
        fontName=font_regular,
        fontSize=9,
        leading=13.5,
        textColor=colors.HexColor('#334155'),
        spaceAfter=6
    )

    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        parent=styles['Normal'],
        fontName=font_regular,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#334155'),
        leftIndent=14,
        firstLineIndent=-10,
        spaceAfter=3
    )

    code_style = ParagraphStyle(
        'Code_Custom',
        parent=styles['Code'],
        fontName='Courier',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#0f172a')
    )

    table_text = ParagraphStyle(
        'TableText',
        parent=styles['Normal'],
        fontName=font_regular,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#1e293b')
    )

    table_header = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName=font_bold,
        fontSize=8.5,
        leading=11.5,
        textColor=colors.white
    )

    story = []

    # ================= KAPAK BÖLÜMÜ =================
    story.append(Spacer(1, 40))
    story.append(Paragraph("UNIVERSAL MEMORY", ParagraphStyle('SuperTitle', fontName=font_bold, fontSize=11, textColor=colors.HexColor('#2563eb'), spaceAfter=5)))
    story.append(Paragraph("Tam Dosyalar ve Mimari Rehberi", title_style))
    story.append(Paragraph("Çoklu Ajan ve İkinci Beyin Kalıcı Hafıza Motoru — Kapsamlı Teknik Referans ve Güvenlik Vaka İncelemesi", subtitle_style))
    
    meta_table_data = [
        [Paragraph("<b>Sürüm:</b> v1.2.0 (Production)", table_text), Paragraph("<b>Tarih:</b> 1 Kasım 2026", table_text)],
        [Paragraph("<b>Mimari:</b> Local-First, Bi-Temporal, Fail-Closed", table_text), Paragraph("<b>Protokol:</b> FastMCP (JSON-RPC) stdio", table_text)],
        [Paragraph("<b>Desteklenen Ajanlar:</b> Claude Code, OpenAI Codex, Antigravity", table_text), Paragraph("<b>Depolama:</b> Obsidian Markdown + SQLite FTS5", table_text)],
    ]
    t_meta = Table(meta_table_data, colWidths=[250, 250])
    t_meta.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#cbd5e1'), spaceAfter=15))

    # ================= 1. GİRİŞ VE VİZYON =================
    story.append(Paragraph("1. Giriş, Vizyon ve Çekirdek Felsefe", h1_style))
    story.append(Paragraph(
        "<b>Universal Memory</b>, modern yapay zekâ geliştirme ortamlarında çalışan otonom ajanların (Claude Code, OpenAI Codex, Antigravity vb.) "
        "oturumlar boyunca edindikleri tecrübeleri, mimari kuralları ve kullanıcı tercihlerini kaybetmeden birbirine aktarmasını sağlayan "
        "yerel öncelikli (Local-First) bir hafıza motorudur.", body_style
    ))
    story.append(Paragraph(
        "Geleneksel vektör veritabanları (Vector DB) opak gömme vektörleri (opaque embeddings) kullanarak hafızayı insan denetiminden uzaklaştırırken, "
        "Universal Memory tüm kayıtları şeffaf, Git ile sürümlenebilir ve Obsidian vault'u içinde doğrudan düzenlenebilir saf Markdown dosyaları olarak saklar.", body_style
    ))
    
    story.append(Paragraph("Dört Temel Tasarım Sütunu:", h2_style))
    story.append(Paragraph("• <b>Local-First & Markdown-First:</b> Veriler kullanıcının yerel makinesinde durur. Her kayıt bir <code>.md</code> dosyasıdır.", bullet_style))
    story.append(Paragraph("• <b>Bi-Temporal (Çift-Zamanlılık):</b> Valid Time (gerçek dünyada geçerli olunan süre) ve Ingestion Time (kaydedilme anı) bağımsız izlenir.", bullet_style))
    story.append(Paragraph("• <b>Fail-Closed Güvenlik:</b> Ajanlar doğrudan kalıcı hafıza yazamaz; öneriler <code>.proposals/</code> altında izole edilir ve açık insan onayı (<code>memory_commit</code>) gerektirir.", bullet_style))
    story.append(Paragraph("• <b>Wikilinks Tabanlı Bilgi Grafiği:</b> Kayıtlar arası ilişkiler (<code>[[KAYIT_ID]]</code>, <code>[[contradicts: ID]]</code>) yönlü bir bilgi ağı oluşturur.", bullet_style))

    story.append(Spacer(1, 10))

    # ================= 2. MİMARİ VE VERİ AKIŞI =================
    story.append(Paragraph("2. Mimari Katmanlar ve Sistem Veri Akışı", h1_style))
    story.append(Paragraph(
        "Universal Memory altı bağımsız katmandan meydana gelir:", body_style
    ))

    layers_data = [
        [Paragraph("Katman", table_header), Paragraph("Sorumlu Modül", table_header), Paragraph("Temel Görevi", table_header)],
        [Paragraph("1. Protokol & MCP", table_text), Paragraph("<code>server.py</code>", table_text), Paragraph("FastMCP stdio tabanlı 11 çekirdek aracın sunumu ve JSON-RPC iletişimi.", table_text)],
        [Paragraph("2. Motor & CRUD", table_text), Paragraph("<code>memory_engine.py</code>", table_text), Paragraph("Atomik dosya oluşturma, çift-zamanlı yazma, güvenli serileştirme.", table_text)],
        [Paragraph("3. İndeks & Grafik", table_text), Paragraph("<code>memory_index.py</code>", table_text), Paragraph("SQLite FTS5 tam metin araması, düğüm/kenar tablosu, Fail-Closed parser.", table_text)],
        [Paragraph("4. İkinci Beyin", table_text), Paragraph("<code>second_brain.py</code>", table_text), Paragraph("Tiago Forte C.O.D.E. (Capture, Organize, Distill, Express) işleme hattı.", table_text)],
        [Paragraph("5. Zaman & Çatışma", table_text), Paragraph("<code>bitemporal.py</code><br/><code>conflict_resolver.py</code>", table_text), Paragraph("Zaman yolculuğu sorguları, çelişen iddiaların tespiti ve çözümü.", table_text)],
        [Paragraph("6. Enjeksiyon & Medya", table_text), Paragraph("<code>context_injector.py</code><br/><code>session_media.py</code>", table_text), Paragraph("SessionStart kancasıyla dinamik bağlam enjeksiyonu ve görsel arşivleme.", table_text)]
    ]
    t_layers = Table(layers_data, colWidths=[90, 110, 300])
    t_layers.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e293b')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_layers)

    story.append(PageBreak())

    # ================= 3. TÜM DOSYALARIN TEKNİK İNCELEMESİ =================
    story.append(Paragraph("3. Tüm Kaynak Dosyaların Detaylı Rolleri (File-by-File)", h1_style))
    story.append(Paragraph(
        "Universal Memory reposundaki her kaynak dosya katı sorumluluk ayrımı (Single Responsibility) ilkesiyle inşa edilmiştir:", body_style
    ))

    # server.py
    story.append(Paragraph("3.1 <code>server.py</code> — FastMCP Protokol Sunucusu (22.9 KB)", h2_style))
    story.append(Paragraph(
        "FastMCP çerçevesini kullanarak istemci ajanlara (Claude, Codex, Antigravity) 11 adet yüksek seviyeli hafıza aracı sunar. "
        "Her araç gelen argümanları doğrular, kütüphane çağrılarını yürütür ve sonucu JSON/Markdown formatında döndürür. "
        "Ayrıca stdio akışında log kirliliğini önlemek için stderr yönlendirmesi ve hata izolasyonu uygular.", body_style
    ))

    # memory_engine.py
    story.append(Paragraph("3.2 <code>memory_engine.py</code> — Çekirdek Hafıza Motoru (24.3 KB)", h2_style))
    story.append(Paragraph(
        "Kasanın disk üzerindeki kalıcı omurgasıdır. Yeni bir hafıza kaydedilirken atomik yazma (`x` modu) kullanarak race-condition'ları önler. "
        "Çift-zamanlılık etiketlerini (`valid_from`, `valid_until`, `source_event_time`, `ingestion_time`) hesaplar. "
        "<b>Güvenlik Yaması:</b> Ajanlardan gelen serbest metinlerdeki satır sonlarını temizleyen <code>_clean_field</code> ve <code>_safe_str</code> fonksiyonlarıyla "
        "YAML frontmatter enjeksiyonunu tamamen engellemiştir.", body_style
    ))

    # memory_index.py
    story.append(Paragraph("3.3 <code>memory_index.py</code> — SQLite FTS5 & Grafik Motoru (33.5 KB)", h2_style))
    story.append(Paragraph(
        "Obsidian kasasındaki dosyaları arka planda izler ve <code>index.db</code> üzerinde FTS5 indeksini günceller. "
        "Metin aramalarında Türkçe ve İngilizce kök bulma (stemming), kronolojik sıralama (<code>time_asc / time_desc</code>) ve satır bağlamı (<code>surround</code>) sunar. "
        "Ayrıca <code>_split_frontmatter</code> parser'ı <b>Fail-Closed</b> çalışır: <code>status</code> alanı okunamazsa en düşük yetki olan <code>proposal</code> olarak atanır.", body_style
    ))

    # second_brain.py
    story.append(Paragraph("3.4 <code>second_brain.py</code> — İkinci Beyin & C.O.D.E. Hattı (30.8 KB)", h2_style))
    story.append(Paragraph(
        "Tiago Forte'un C.O.D.E. metodolojisini hayata geçirir. <code>memory_ingest</code> ile ham oturumları yakalar, "
        "<code>memory_graph</code> ile kavramlar arası ağ ilişkilerini haritalandırır ve <code>memory_express</code> ile dağınık bilgileri "
        "özet raporlara ve mimari kararlara dönüştürür.", body_style
    ))

    # bitemporal.py & conflict_resolver.py
    story.append(Paragraph("3.5 <code>bitemporal.py</code> & <code>conflict_resolver.py</code> (10.7 KB)", h2_style))
    story.append(Paragraph(
        "<code>bitemporal.py</code>, zaman yolculuğu sorgularını yönetir. Geçmiş bir tarihteki hafıza durumunu anlık olarak sorgulamayı sağlar. "
        "<code>conflict_resolver.py</code> ise farklı ajanların birbiriyle çelişen iddialarını yakalar; çelişkiyi <code>[[contradicts: ID]]</code> "
        "olarak kayda işler ve bir öneri kaydının bir diğerini geçersiz kılmasını (supersession) denetler.", body_style
    ))

    # context_injector.py & session_media.py
    story.append(Paragraph("3.6 <code>context_injector.py</code>, <code>hook_context.py</code> & <code>session_media.py</code> (22.9 KB)", h2_style))
    story.append(Paragraph(
        "<code>context_injector.py</code> ve <code>hook_context.py</code>, CLI ajanlarının (Claude Code, Codex) <code>SessionStart</code> kancasına takılarak "
        "ilgili proje bağlamını prompt başlangıcında ajana iletir. <code>session_media.py</code> ise ajanların ürettiği görsel diyagramları ve arayüz varlıklarını "
        "oturum bazında kasanın yanında arşivler.", body_style
    ))

    # tests
    story.append(Paragraph("3.7 <code>tests/</code> — Doğrulama ve Regresyon Suiti (80 Test)", h2_style))
    story.append(Paragraph(
        "Tüm motor ve indeks işlevlerini test eden 80 birim testten oluşur. <code>test_frontmatter_injection.py</code>, "
        "satır sonu ve YAML enjeksiyonlarının fail-closed kapısını kesinlikle aşamadığını matematiksel olarak garantiler.", body_style
    ))

    story.append(Spacer(1, 10))

    # ================= 4. GÜVENLİK VAKA ANALİZİ =================
    story.append(Paragraph("4. Güvenlik Vaka İncelemesi: Matt Abate Açığı ve Düzeltme", h1_style))
    story.append(Paragraph(
        "1 Kasım 2026 tarihinde bağımsız geliştirici Matt Abate tarafından sorumlu açıklama ile iletilen <b>Frontmatter Injection & Privilege Escalation</b> "
        "zafiyeti şu şekilde kapatılmıştır:", body_style
    ))

    vuln_data = [
        [Paragraph("Aşama", table_header), Paragraph("Zafiyet Durumu (Eski)", table_header), Paragraph("Sertleştirilmiş Mimari (Yeni — Commit 94537f9)", table_header)],
        [
            Paragraph("<b>Serileştirme</b>", table_text),
            Paragraph("<code>render()</code> f-string içine title ve tags alanlarını doğrudan (raw) yerleştiriyordu.", table_text),
            Paragraph("<code>_clean_field</code> tüm satır sonlarını (<code>\\r, \\n</code>) temizler; <code>_safe_str</code> YAML tırnaklaması uygular.", table_text)
        ],
        [
            Paragraph("<b>Ayrıştırma (Parser)</b>", table_text),
            Paragraph("<code>_split_frontmatter</code> ilk <code>---</code> işaretinde durup status yoksa <code>canonical</code> varsayıyordu.", table_text),
            Paragraph("<b>Fail-Closed:</b> Status bulunamazsa veya bozuksa daima en kısıtlı yetki olan <code>proposal</code> atanır.", table_text)
        ],
        [
            Paragraph("<b>Yinelenen Anahtar</b>", table_text),
            Paragraph("Son gelen anahtar önceki anahtarın değerini eziyordu (<code>\\nstatus: canonical</code>).", table_text),
            Paragraph("Yinelenen anahtarlarda son değerin ezmesi engellendi; şüpheli kayıtlarda proposal zorlandı.", table_text)
        ]
    ]
    t_vuln = Table(vuln_data, colWidths=[90, 205, 205])
    t_vuln.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f766e')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f0fdfa')]),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_vuln)

    story.append(PageBreak())

    # ================= 5. MCP ARAÇLARI REFERANS TABLOSU =================
    story.append(Paragraph("5. 11 Çekirdek MCP Aracı Referansı", h1_style))
    story.append(Paragraph(
        "Ajanların Universal Memory sunucusuyla haberleşirken kullandığı araçların tam listesi:", body_style
    ))

    tools_data = [
        [Paragraph("Araç Adı", table_header), Paragraph("Sorumluluk & İşlev", table_header), Paragraph("Önemli Parametreler", table_header)],
        [Paragraph("<code>memory_search</code>", table_text), Paragraph("FTS5 ile tam metin arama ve zaman sıralaması.", table_text), Paragraph("<code>query</code>, <code>project</code>, <code>order_by</code>, <code>surround</code>", table_text)],
        [Paragraph("<code>memory_get</code>", table_text), Paragraph("ID veya dosya yoluyla hafıza kaydını ve wikilink ağını getirir.", table_text), Paragraph("<code>record_id</code> (örn: DEC-001 veya dosya yolu)", table_text)],
        [Paragraph("<code>memory_propose</code>", table_text), Paragraph("İnsan onayına sunulacak izole öneri oluşturur (.proposals/).", table_text), Paragraph("<code>title</code>, <code>content</code>, <code>project</code>, <code>type</code>, <code>tags</code>", table_text)],
        [Paragraph("<code>memory_capture</code>", table_text), Paragraph("Doğrudan kanonik hafızaya yazılan hızlı kayıt oluşturur.", table_text), Paragraph("<code>title</code>, <code>content</code>, <code>project</code>, <code>tags</code>", table_text)],
        [Paragraph("<code>memory_commit</code>", table_text), Paragraph("Öneriyi (.proposals/) insan onayıyla canonical statüsüne taşır.", table_text), Paragraph("<code>proposal_id</code>", table_text)],
        [Paragraph("<code>memory_supersede</code>", table_text), Paragraph("Eski kaydı geçersiz kılıp yerine yeni kaydı bağlar.", table_text), Paragraph("<code>old_id</code>, <code>new_id</code>, <code>reason</code>", table_text)],
        [Paragraph("<code>memory_context</code>", table_text), Paragraph("Ajan oturumu için proje bağlam paketini derler.", table_text), Paragraph("<code>project</code>, <code>max_tokens</code>", table_text)],
        [Paragraph("<code>memory_handoff</code>", table_text), Paragraph("Ajan oturumunun devir teslim özetini kaydeder.", table_text), Paragraph("<code>session_id</code>, <code>summary</code>, <code>next_steps</code>", table_text)],
        [Paragraph("<code>memory_ingest</code>", table_text), Paragraph("Ham oturum veya notu C.O.D.E. boru hattına sokar.", table_text), Paragraph("<code>content</code>, <code>source</code>, <code>project</code>", table_text)],
        [Paragraph("<code>memory_graph</code>", table_text), Paragraph("Bilgi grafiğinde komşuluk ve çelişki sorguları yürütür.", table_text), Paragraph("<code>node_id</code>, <code>depth</code>, <code>relation_type</code>", table_text)],
        [Paragraph("<code>memory_express</code>", table_text), Paragraph("Bağlantılı belleklerden sentez raporu türetir.", table_text), Paragraph("<code>topic</code>, <code>format</code> ('brief' | 'full')", table_text)],
    ]
    t_tools = Table(tools_data, colWidths=[100, 240, 160])
    t_tools.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e3a8a')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_tools)

    story.append(Spacer(1, 15))

    # ================= 6. SONUÇ VE PROTOKOL =================
    story.append(Paragraph("6. Sürekli Senkronizasyon ve Masaüstü Kısayol Protokolü", h1_style))
    story.append(Paragraph(
        "Agent Observatory projesinde olduğu gibi, Universal Memory projesinde de bu mimari rehber sürekli güncel tutulur. "
        "<code>tools/update_architecture_pdf.py</code> betiği kullanılarak her yeni dosya veya mimari kararda PDF ve Markdown dokümanı tek komutla güncellenir. "
        "Masaüstünde oluşturulan <code>UniversalMemory_Tum_Dosyalar_Mimari_Rehberi.lnk</code> kısayolu, doğrudan depodaki ana PDF kopyasına işaret eder.", body_style
    ))

    # İnşa et
    doc = SimpleDocTemplate(
        str(PDF_PATH),
        pagesize=A4,
        leftMargin=44,
        rightMargin=44,
        topMargin=44,
        bottomMargin=44
    )
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"✔ PDF başarıyla üretildi: {PDF_PATH}")
    return True

def ensure_desktop_shortcut():
    """Masaüstünde repodaki PDF'e işaret eden Windows kısayolunu oluşturur."""
    if not PDF_PATH.exists():
        return False
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(DESKTOP_LNK))
        shortcut.Targetpath = str(PDF_PATH)
        shortcut.WorkingDirectory = str(REPO_ROOT)
        shortcut.Description = "Universal Memory Tüm Dosyalar ve Mimari Rehberi"
        shortcut.save()
        print(f"✔ Masaüstü kısayolu oluşturuldu: {DESKTOP_LNK.name} -> {PDF_PATH.name}")
        return True
    except Exception as e:
        sys.stderr.write(f"[UYARI] Kısayol oluşturulamadı (WScript): {e}\n")
        return False

def write_markdown_docs():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(WIKI_CONTENT.strip() + "\n")
    print(f"✔ Repo içi Markdown Wiki dokümanı kaydedildi: {MD_PATH}")

    OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)
    with open(OBSIDIAN_MD, "w", encoding="utf-8") as f:
        f.write(WIKI_CONTENT.strip() + "\n")
    print(f"✔ Obsidian Kasası Wiki dokümanı senkronize edildi: {OBSIDIAN_MD}")

def main():
    write_markdown_docs()
    generate_pdf()
    ensure_desktop_shortcut()

if __name__ == "__main__":
    main()
