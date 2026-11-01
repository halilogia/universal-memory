# Güncel PDF Rehberi (Universal Memory)

`UniversalMemory_Tum_Dosyalar_Mimari_Rehberi.pdf` belgesi, projedeki her dosya veya mimari değişikliğinde (yeni dosya ekleme, çıkarma, MCP aracı ekleme veya işlev güncellemesinde) sürekli olarak güncel tutulmalıdır.

## Uygulama Kuralları

- Yeni bir kaynak dosya, test, araç veya modül eklendiğinde PDF ve Markdown Wiki dokümanı güncellenir.
- Bir dosya kaldırıldığında veya yeniden adlandırıldığında PDF'teki kaydı da güncellenir.
- Bir dosyanın sorumluluğu, arayüzü veya veri akışı değiştiğinde (örneğin güvenlik yamaları, FTS5 şeması, bi-temporal etiketler) açıklama güncellenir.
- `tools/update_architecture_pdf.py` aracı kullanılarak değişiklikler PDF'e işlenmeden commit atılmaz.
