#!/usr/bin/env python3
"""
Universal Memory Mimari Rehberi PDF Senkronizasyon ve Güncelleme Aracı.

Kullanım:
    python tools/update_architecture_pdf.py --rebuild
    python tools/update_architecture_pdf.py --sync
    python tools/update_architecture_pdf.py --add "Başlık" "Bölüm Açıklaması..."
"""
import sys
import os
import argparse
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_PDF = REPO_ROOT / "UniversalMemory_Tum_Dosyalar_Mimari_Rehberi.pdf"
DESKTOP_LNK = Path(os.path.expanduser("~")) / "Desktop" / "UniversalMemory_Tum_Dosyalar_Mimari_Rehberi.lnk"
GEN_SCRIPT = REPO_ROOT / "tools" / "generate_architecture_pdf.py"

def ensure_desktop_shortcut():
    """Masaüstünde doğrudan repodaki PDF'i gösteren Windows kısayolunu (.lnk) sağlar."""
    if not REPO_PDF.exists():
        print(f"[HATA] Kaynak PDF bulunamadı: {REPO_PDF}", file=sys.stderr)
        return False

    if DESKTOP_LNK.exists():
        print(f"✔ Masaüstü kısayolu zaten hazır ve repo PDF'ine bağlı: {DESKTOP_LNK.name}")
        return True

    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(DESKTOP_LNK))
        shortcut.Targetpath = str(REPO_PDF)
        shortcut.WorkingDirectory = str(REPO_ROOT)
        shortcut.Description = "Universal Memory Tüm Dosyalar ve Mimari Rehberi"
        shortcut.save()
        print(f"✔ Masaüstü kısayolu oluşturuldu: {DESKTOP_LNK.name} -> {REPO_PDF.name}")
        return True
    except Exception as sc_err:
        sys.stderr.write(f"[UYARI] Kısayol oluşturulamadı: {sc_err}\n")
        return False

def add_section(title: str, body: str, subtitle: str = "Mimari ve Kod Değişikliği Güncellemesi"):
    """PDF sonuna yeni bir zeyilname / mimari güncelleme sayfası ekler."""
    try:
        from io import BytesIO
        from pypdf import PdfReader, PdfWriter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as e:
        print(f"[HATA] Gerekli Python kütüphaneleri eksik (pypdf, reportlab): {e}", file=sys.stderr)
        return False

    if not REPO_PDF.exists():
        print(f"[HATA] Güncellenecek PDF bulunamadı: {REPO_PDF}", file=sys.stderr)
        return False

    font_regular = "SegoeUI"
    font_bold = "SegoeUI-Bold"
    try:
        pdfmetrics.registerFont(TTFont('SegoeUI', 'C:/Windows/Fonts/segoeui.ttf'))
        pdfmetrics.registerFont(TTFont('SegoeUI-Bold', 'C:/Windows/Fonts/segoeuib.ttf'))
    except Exception:
        font_regular = "Helvetica"
        font_bold = "Helvetica-Bold"

    buf = BytesIO()
    styles = getSampleStyleSheet()
    
    t_style = ParagraphStyle('ZeyilTitle', parent=styles['Heading1'], fontName=font_bold, fontSize=16, leading=20, textColor=colors.HexColor('#1e3a8a'))
    sub_style = ParagraphStyle('ZeyilSub', parent=styles['Heading2'], fontName=font_bold, fontSize=11, leading=15, textColor=colors.HexColor('#0f766e'))
    body_style = ParagraphStyle('ZeyilBody', parent=styles['BodyText'], fontName=font_regular, fontSize=9.5, leading=14, textColor=colors.HexColor('#334155'))

    items = [
        Paragraph(title, t_style),
        Paragraph(subtitle, sub_style),
        Spacer(1, 12),
        Paragraph(body, body_style)
    ]

    SimpleDocTemplate(
        buf,
        pagesize=(595.28, 841.89),
        leftMargin=44,
        rightMargin=44,
        topMargin=44,
        bottomMargin=44
    ).build(items)

    writer = PdfWriter()
    writer.append(PdfReader(REPO_PDF))
    writer.append(PdfReader(buf))

    tmp_out = REPO_PDF.with_suffix(".tmp.pdf")
    with tmp_out.open("wb") as f:
        writer.write(f)
    tmp_out.replace(REPO_PDF)

    reader = PdfReader(REPO_PDF)
    print(f"✔ PDF güncellendi! Yeni toplam sayfa: {len(reader.pages)}")
    ensure_desktop_shortcut()
    return True

def rebuild():
    if GEN_SCRIPT.exists():
        import subprocess
        subprocess.run([sys.executable, str(GEN_SCRIPT)], check=True)
    else:
        print("[HATA] generate_architecture_pdf.py bulunamadı.", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="Universal Memory Mimari PDF Senkronizasyonu")
    parser.add_argument("--sync", action="store_true", help="Masaüstü kısayolunu eşitler")
    parser.add_argument("--rebuild", action="store_true", help="PDF ve Wiki'yi sıfırdan yeniden üretir")
    parser.add_argument("--add", nargs=2, metavar=("BASLIK", "METIN"), help="PDF sonuna yeni mimari bölüm ekler")
    args = parser.parse_args()

    if args.add:
        add_section(args.add[0], args.add[1])
    elif args.rebuild:
        rebuild()
    else:
        ensure_desktop_shortcut()

if __name__ == "__main__":
    main()
