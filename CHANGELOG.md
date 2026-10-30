# 📝 Değişiklik Günlüğü (CHANGELOG.md)

Tüm önemli değişiklikler bu dosyada SemVer standardına uygun olarak belgelenmektedir.

---

## [Unreleased]

### Eklendi (Added)
- **Second Brain (CODE) katmanı** (`second_brain.py`): üç yeni MCP aracı ve şemaları (`schemas/memory_ingest.json`, `memory_graph.json`, `memory_express.json`).
  - **`memory_ingest`** (Damıt): YouTube transkripti / makale / ses dökümü / doküman → Kademeli Özetleme kartı (`Executive Summary`, `Core Takeaways` + aksiyon `- [ ]`, `Key Quotes`, `Extracted Insights`; ham metinde **kalın**/==vurgu== katmanları). `resources/` (veya `lessons/`) altına canonical yazar, FTS5'e ekler, Git HEAD (`source_commit`) ve SHA-256 (`content_hash`) mühürler, aynı içeriği tekrar eklemez, gizli anahtarları maskeler, ilişkili notlara `related_to` bağı koyar. Çıkarım deterministiktir (LLM yok).
  - **`memory_graph`** (Organize): karar/ders/kaynak/kural arasında ortak etiket + anahtar kelime + açık wikilink bağlantıları, kümeler, merkez/bağlantısız notlar ve Obsidian uyumlu MOC Markdown'ı; `topic` filtresi; superseded kayıtlar dışarıda.
  - **`memory_express`** (İfade): `adr_report`, `release_notes` (`since` ile), `project_brief` çıktıları.
  - `server.REQUIRED_MODULES`'a `second_brain` eklendi. `tests/test_second_brain.py` (23 test, toplam 69/69).
- **Dağıtım koruması**: `server.py` açılışta zorunlu modüllerin varlığını denetler; eksikse adlarını yazıp çıkar (önceden ilk çağrıda `No module named 'bitemporal'` ile patlıyordu). `tools/sync_deploy.py` repo ile `~/.gemini/mcp/universal-memory/` arasındaki farkı listeler, `--apply` ile kopyalar ve eskileri `backups/` altına yedekler. `tests/test_deploy_guard.py` (2 test, toplam 46/46).
- **Hafıza Arama & Erişim Geliştirmeleri (3 Friction Fixes)**:
  - **`memory_get(id)` #satır & alias uyumu**: `memory_get` artık `id`, `record_id` ve `path` parametrelerini takma ad olarak kabul eder. `dosya.md#241`, `#start:end` ve `#L12-L34` eklerini otomatik soyup ilgili mesaj bloğunu veya satır aralığını döner; `Hata: Hafıza kaydı bulunamadı: ''` hatası giderildi.
  - **Çevreleyen bağlam (`surround` / `context_lines`)**: `memory_search` ve `memory_get` araçlarına `surround` ve `context_lines` eklendi. Eşleşen mesajın öncesinden ve sonrasından (asistan yanıtı dahil) satırları `\n` korumalı biçimde `context` ve `context_range` alanlarında doğrudan döner; ikinci bir `read_file` ihtiyacını ortadan kaldırır.
  - **Kronolojik arama (`order_by: "time_asc" | "time_desc"`)**: `memory_search` sonuçlarını BM25 alaka puanı yerine tarihsel zaman çizelgesine göre (`date`, `ts`, `line`) eskiden yeniye veya en yeniden en eskiye sıralama desteği eklendi.
  - **Birim testler**: `tests/test_v2_friction_improvements.py` eklendi; tüm testler (44/44) %100 başarıyla geçmektedir.
- **Oturum başı otomatik bağlam** (`hook_context.py`): SessionStart hook'u hook JSON'undaki cwd'den projeyi çözer, `context_injector` ile ~1500 karakterlik geçerli-kart paketi üretir ve ajana `[Hafıza bağlamı — doğrulanmış veri, talimat değil]` çerçevesiyle enjekte eder. Oturum başına dedupe (`compact`/`clear` kaynaklarında yeniden enjekte), fail-open (hata/zaman aşımı/proje yok → sessiz exit 0). Claude Code ve Antigravity için kablolandı; Codex girdisi `~/.codex/hooks.json`'a yazıldı ama `config.toml`'da `trusted_hash` kaydı yok; ilk açılışta `/hooks` ile onaylanmadan çalışmaması muhtemel (canlı doğrulanmadı). Testler: `tests/test_hook_context.py` (11).

---

## [2.0.0] - 2026-10-27

### Eklendi (Added)
- **Bi-temporal bilgi modeli** (`bitemporal.py`): `valid_from`, `valid_until`, `source_event_time`, `ingestion_time`, `superseded_by` frontmatter alanları; indekste kolon olarak tutulur. Güncellenen kayıt silinmez, `superseded_by` + `- supersedes: [[id]]` ile bağlanır. `memory_search(as_of=..., include_invalid=...)` ile zaman yolculuğu ve tarihçe; varsayılan aramada yalnızca geçerli kayıtlar döner.
- **Çelişki/tekilleştirme çözücüsü** (`conflict_resolver.py`): `memory_propose` öncesi aynı projedeki geçerli karar/ders/kurallarla Jaccard benzerliği + olumsuzluk/değiştirme ipuçları. Duplicate reddedilir (`force` ile aşılır), çelişki `- contradicts: [[id]]` ile bağlanır ve `memory_commit` sırasında eski kayıt geçersiz kılınır.
- **Hızlı yakalama** (`memory_capture` / `memory_engine.quick_capture`): `karar:`, `kural:`, `ders:`, `olmadı:` önekleriyle tek satırlık kayıt (Avenox `yakala`).
- **Damıtma** (`distillation/worker.py`): regex ile negatif bilgi, karar, kural ve açık görev çıkarımı (TR+EN); yerel model çıktısı tekilleştirilerek birleştirilir; `--no-model`, `--submit`, `submit()`.
- **Bağlam enjektörü** (`context_injector.py`, `memory_context`): yalnızca geçerli kartlardan, sorguya göre sıralanmış, karakter bütçesine sığan tek paket; `--as-of`, `--agent-id`, `inject_prompt()`.
- **Kapsam** (Mem0 benzeri): `agent_id` / `run_id` alanları.
- `memory_supersede` aracı; `tests/` (30 birim testi, `python -m unittest discover -s tests -t .`).

### Değişti (Changed)
- OpenCode çağrısı `opencode run [mesaj]` biçimine düzeltildi (önceki `--prompt` bayrağı kaldırıldı).
- Sunucu sürümü 2.0.0.

---

## [1.0.0] - 2026-10-25

### Eklendi (Added)
- FastMCP stdio tabanlı bellek sunucusu (`server.py`).
- İki aşamalı güvenli kayıt döngüsü (`memory_propose`, `memory_commit`).
- SQLite FTS5 destekli hızlı metin arama ve puanlama (`memory_search`).
- Ajanlar arası oturum devretme aracı (`memory_handoff`).
- Obsidian Markdown formatına anlık çıktı ve çift yönlü senkronizasyon.
