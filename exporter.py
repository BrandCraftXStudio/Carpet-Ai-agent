"""
core/exporter.py — Phase 5: PDF report generator
=================================================
Builds a professional, printable PDF carpet match report using fpdf2.

Report structure
----------------
Page 1  — Cover: store name · date · room photo · room palette analysis
           + summary bar ("N best matches found")
Page 2+ — One result block per carpet match, 2 blocks per page:
           • Coloured score header (rank · label · score · carpet name)
           • Carpet thumbnail
           • Metadata: price, temperature, harmony note, score breakdown
           • Score bar (visual)
           • Side-by-side palette swatches (room vs carpet)

Usage
-----
    from core.exporter import export_to_pdf

    pdf_bytes = export_to_pdf(
        room_analysis    = output["room_analysis"],
        results          = output["results"],
        room_image_bytes = room_bytes,
        store_name       = "Hawash Carpet",
        catalog_label    = "Carpets › Modern",
    )
    # pdf_bytes is ready for st.download_button
"""

from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from PIL import Image


# ── Internal helpers ──────────────────────────────────────────────────────────

def _safe(text: str, max_len: int = 999) -> str:
    """
    Strip characters outside the Latin-1 range (emojis, Arabic, etc.)
    so fpdf2's built-in Helvetica font doesn't raise an encoding error.
    All emoji / non-Latin content is silently dropped; the rest renders fine.
    """
    safe = text.encode("latin-1", errors="ignore").decode("latin-1")
    return safe[:max_len].strip()

def _score_rgb(score: float) -> tuple[int, int, int]:
    """Return a dark foreground colour for a score band."""
    if   score >= 85: return (27,  94,  32)   # deep green
    elif score >= 70: return (0,   77,  64)   # deep teal
    elif score >= 55: return (230, 81,  0)    # deep orange
    else:             return (183, 28,  28)   # deep red


def _score_rgb_light(score: float) -> tuple[int, int, int]:
    """Return a light background colour for a score band (for summary boxes)."""
    if   score >= 85: return (232, 245, 233)
    elif score >= 70: return (224, 242, 241)
    elif score >= 55: return (255, 243, 224)
    else:             return (255, 235, 238)


def _img_buf(pil_img: Image.Image, quality: int = 85) -> io.BytesIO:
    """Convert a PIL image to a JPEG BytesIO buffer for fpdf2."""
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return buf


def _draw_palette(
    pdf:     FPDF,
    palette: list[dict],
    x:       float,
    y:       float,
    swatch_w: float = 11,
    swatch_h: float = 7,
) -> None:
    """Draw a row of colour swatches at (x, y)."""
    for i, c in enumerate(palette[:6]):
        r, g, b = c["rgb"]
        pdf.set_fill_color(r, g, b)
        pdf.set_draw_color(180, 180, 180)
        pdf.rect(x + i * (swatch_w + 1), y, swatch_w, swatch_h, "FD")


def _draw_score_bar(
    pdf:   FPDF,
    score: float,
    x:     float,
    y:     float,
    w:     float = 110,
    h:     float = 5,
) -> None:
    """Draw a filled progress bar for a match score."""
    # Background track
    pdf.set_fill_color(225, 225, 225)
    pdf.rect(x, y, w, h, "F")
    # Filled portion
    r, g, b = _score_rgb(score)
    pdf.set_fill_color(r, g, b)
    pdf.rect(x, y, w * min(score, 100) / 100, h, "F")


# ── PDF class ─────────────────────────────────────────────────────────────────

class _ReportPDF(FPDF):
    """FPDF subclass with branded header and footer."""

    def __init__(self, store_name: str, catalog_label: str):
        super().__init__()
        self._store     = store_name
        self._catalog   = catalog_label
        self.set_margins(12, 12, 12)
        self.set_auto_page_break(auto=True, margin=18)

    def header(self) -> None:
        if self.page_no() == 1:
            return                              # cover page has no header
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(160, 160, 160)
        self.cell(0, 5, "Carpet Match Report", align="L")
        self.set_y(self.get_y() - 5)
        self.cell(0, 5, self._store, align="R")
        self.ln(2)
        self.set_draw_color(210, 210, 210)
        self.line(12, self.get_y(), 198, self.get_y())
        self.ln(4)
        self.set_text_color(40, 40, 40)

    def footer(self) -> None:
        self.set_y(-13)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(160, 160, 160)
        self.cell(0, 5, f"Page {self.page_no()}  ·  Carpet Match AI", align="C")


# ── Public API ────────────────────────────────────────────────────────────────

def export_to_pdf(
    room_analysis:    dict,
    results:          list[dict],
    room_image_bytes: bytes,
    store_name:       str = "Carpet Store",
    catalog_label:    str = "",
) -> bytes:
    """
    Generate a PDF carpet match report.

    Parameters
    ----------
    room_analysis    : dict from matcher.analyze_room / find_matches
    results          : list of match dicts from find_matches (already sliced)
    room_image_bytes : raw bytes of the room photo
    store_name       : printed in the report header
    catalog_label    : e.g. "Carpets › Modern"

    Returns
    -------
    PDF as a bytes object — pass directly to st.download_button.
    """
    TEMP_LABEL = {"warm": "Warm", "cool": "Cool", "neutral": "Neutral"}

    pdf = _ReportPDF(store_name, catalog_label)

    # ── Page 1 — Cover ────────────────────────────────────────────────────────
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(27, 94, 32)
    pdf.ln(4)
    pdf.cell(0, 13, _safe("Carpet Match Report"), align="C")
    pdf.ln(0)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 8,  _safe(store_name), align="C")
    pdf.ln(0)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7,  _safe(datetime.now().strftime("%d %B %Y  -  %H:%M")), align="C")
    pdf.ln(0)
    if catalog_label:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 6, _safe(f"Catalog: {catalog_label}"), align="C")
    pdf.ln(5)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(12, pdf.get_y(), 198, pdf.get_y())
    pdf.ln(6)

    # Section heading
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(0, 7, _safe("Room Analysis"))
    pdf.ln(5)

    room_y = pdf.get_y()

    # Room photo
    try:
        room_img = Image.open(io.BytesIO(room_image_bytes)).convert("RGB")
        room_img.thumbnail((400, 300), Image.LANCZOS)
        pdf.image(_img_buf(room_img), x=12, y=room_y, w=82)
    except Exception:
        pass

    # Analysis text block (right of photo)
    tx, ty = 100, room_y
    palette  = room_analysis.get("palette", [])
    temp     = room_analysis.get("temperature", "neutral")
    families = list(dict.fromkeys(room_analysis.get("color_families", [])))

    pdf.set_xy(tx, ty)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, _safe("Color Temperature"))
    pdf.set_xy(tx, ty + 6)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, _safe(TEMP_LABEL.get(temp, temp.capitalize())))

    pdf.set_xy(tx, ty + 15)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, _safe("Color Families"))
    pdf.set_xy(tx, ty + 21)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 5, _safe(", ".join(families[:6]) or "-"))
    pdf.set_text_color(40, 40, 40)

    pdf.set_xy(tx, ty + 31)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 5, _safe("Dominant Palette"))
    _draw_palette(pdf, palette, tx, ty + 38)

    # Score of top match (teaser)
    if results:
        top = results[0]
        r, g, b = _score_rgb_light(top["score"])
        fr, fg, fb = _score_rgb(top["score"])
        pdf.set_xy(tx, ty + 52)
        pdf.set_fill_color(r, g, b)
        pdf.set_draw_color(fr, fg, fb)
        pdf.rect(tx, ty + 52, 96, 18, "FD")
        pdf.set_xy(tx + 2, ty + 55)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(fr, fg, fb)
        pdf.cell(0, 5, _safe(f"Best match: {top['carpet']['name']}"))
        pdf.set_xy(tx + 2, ty + 62)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, _safe(f"Score: {top['score']:.0f}%  ·  {top['label']}"))
        pdf.set_text_color(40, 40, 40)

    # Summary banner
    pdf.set_y(room_y + 76)
    pdf.set_fill_color(245, 250, 245)
    pdf.set_draw_color(160, 200, 160)
    pdf.rect(12, pdf.get_y(), 186, 10, "FD")
    pdf.set_x(14)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(30, 100, 40)
    pdf.cell(0, 10,
        _safe(f"  {len(results)} carpet match(es) found  -  "
              f"Catalog: {catalog_label}"))
    pdf.set_text_color(40, 40, 40)
    pdf.ln(14)

    # ── Results pages ─────────────────────────────────────────────────────────
    pdf.set_draw_color(220, 220, 220)

    BLOCK_H = 76           # vertical space each result block occupies (mm)
    PER_PAGE = 2           # try to fit 2 results per page

    for idx, result in enumerate(results):
        # New page for every 2nd result (or for the first result on page 1 if no room)
        if idx % PER_PAGE == 0:
            pdf.add_page()

        carpet      = result["carpet"]
        score       = result["score"]
        label       = result["label"]
        rank        = result["rank"]
        dr, dg, db  = _score_rgb(score)
        carpet_temp = carpet.get("temperature", "neutral")

        block_y = pdf.get_y()

        # ── Score header strip ────────────────────────────────────────────────
        pdf.set_fill_color(dr, dg, db)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 10)
        pdf.rect(12, block_y, 186, 9, "F")
        pdf.set_xy(14, block_y + 1.5)
        carpet_name_short = carpet["name"][:45]
        pdf.cell(0, 6,
            _safe(f"#{rank}  {label}  |  {score:.0f}%  |  {carpet_name_short}"))
        pdf.set_text_color(40, 40, 40)
        pdf.ln(11)

        content_y = pdf.get_y()

        # ── Carpet thumbnail ──────────────────────────────────────────────────
        img_path = carpet.get("image_path", "")
        if os.path.exists(img_path):
            try:
                cimg = Image.open(img_path).convert("RGB")
                cimg.thumbnail((240, 180), Image.LANCZOS)
                pdf.image(_img_buf(cimg), x=12, y=content_y, w=54)
            except Exception:
                pass

        # ── Details column ────────────────────────────────────────────────────
        dx, dy = 70, content_y

        pdf.set_xy(dx, dy)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 5, _safe(carpet["name"][:55]))

        if carpet.get("price"):
            pdf.set_xy(dx, dy + 7)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 5, _safe(f"Price:  {carpet['price']}"))
            pdf.set_text_color(40, 40, 40)

        pdf.set_xy(dx, dy + 14)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5,
            _safe(f"Carpet temperature:  "
                  f"{TEMP_LABEL.get(carpet_temp, carpet_temp.capitalize())}"))

        pdf.set_xy(dx, dy + 21)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(100, 100, 100)
        harmony = result.get("temp_harmony", "")
        pdf.cell(0, 5, _safe(harmony[:72]))
        pdf.set_text_color(40, 40, 40)

        # Score breakdown labels
        pdf.set_xy(dx, dy + 30)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(55, 5, _safe(f"Color match:  {result['color_score']:.1f}%"))
        pdf.cell(0,  5, _safe(f"Temp. harmony:  {result['temp_score']:.0f}/100"))

        # Score bar
        _draw_score_bar(pdf, score, dx, dy + 37, w=124, h=5)

        # Palette labels + swatches
        pdf.set_xy(dx, dy + 45)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(18, 5, _safe("Room:"))
        _draw_palette(pdf, room_analysis.get("palette", []),
                      dx + 18, dy + 45, swatch_w=10, swatch_h=6)

        pdf.set_xy(dx, dy + 53)
        pdf.cell(18, 5, _safe("Carpet:"))
        _draw_palette(pdf, carpet.get("palette", []),
                      dx + 18, dy + 53, swatch_w=10, swatch_h=6)
        pdf.set_text_color(40, 40, 40)

        if carpet.get("notes"):
            pdf.set_xy(dx, dy + 62)
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(120, 120, 120)
            pdf.cell(0, 4, _safe(f"Notes: {str(carpet['notes'])[:80]}"))
            pdf.set_text_color(40, 40, 40)

        # Divider between blocks on the same page
        sep_y = content_y + BLOCK_H - 2
        pdf.set_draw_color(220, 220, 220)
        pdf.line(12, sep_y, 198, sep_y)
        pdf.set_y(sep_y + 4)

    return bytes(pdf.output())
