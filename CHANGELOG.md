# 📝 Değişiklik Günlüğü (CHANGELOG.md)

Tüm önemli değişiklikler bu dosyada SemVer standardına uygun olarak belgelenmektedir.

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
