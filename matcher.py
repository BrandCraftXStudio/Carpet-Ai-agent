"""
core/matcher.py — Phase 4: Room image analysis & matching engine
================================================================
Responsibilities
----------------
- analyze_room   : extract the dominant palette from a room photo,
                   optionally cropping out the floor area so the analysis
                   reflects only the walls and furniture the carpet must
                   complement (not the existing floor it will replace)
- find_matches   : score every carpet in the selected catalog section/type
                   against the room palette and return a ranked list

Scoring formula
---------------
final_score = color_similarity × 0.85  +  temperature_harmony × 0.15

  color_similarity   — Delta-E 2000 based, 0-100 (from color_extractor)
  temperature_harmony — look-up table, 0-100 (warm/cool/neutral alignment)

The 85/15 split keeps colour accuracy as king while giving a small, meaningful
bonus to carpets whose temperature naturally harmonises with the room.
"""

from __future__ import annotations

import io
from typing import Optional

from PIL import Image

from core.color_extractor import similarity_score, analyze_image
from core.db_manager import init_db, get_all_carpets


# ── Scoring weights ───────────────────────────────────────────────────────────

COLOR_WEIGHT: float = 0.85
TEMP_WEIGHT:  float = 0.15


# ── Temperature harmony tables ────────────────────────────────────────────────
# Numeric score (0-100) for how well two temperatures complement each other.
TEMP_HARMONY: dict[tuple[str, str], float] = {
    ("warm",    "warm"):     100.0,   # perfectly aligned
    ("cool",    "cool"):     100.0,
    ("neutral", "neutral"):   90.0,   # both neutral — very safe
    ("warm",    "neutral"):   75.0,   # carpet softens the warm room
    ("neutral", "warm"):      75.0,   # carpet adds gentle warmth
    ("cool",    "neutral"):   75.0,   # carpet softens the cool room
    ("neutral", "cool"):      75.0,   # carpet adds cool accent
    ("warm",    "cool"):      35.0,   # contrast — can clash
    ("cool",    "warm"):      35.0,
}

# Human-readable explanation for each pairing.
_HARMONY_LABEL: dict[tuple[str, str], str] = {
    ("warm",    "warm"):    "Perfect — both warm tones, seamless harmony",
    ("cool",    "cool"):    "Perfect — both cool tones, seamless harmony",
    ("neutral", "neutral"): "Great — both neutral, very safe combination",
    ("warm",    "neutral"): "Good — neutral carpet balances the warm room",
    ("neutral", "warm"):    "Good — warm carpet adds gentle life to neutral room",
    ("cool",    "neutral"): "Good — neutral carpet softens the cool room",
    ("neutral", "cool"):    "Good — cool carpet adds a crisp accent",
    ("warm",    "cool"):    "Contrast — warm room + cool carpet may clash",
    ("cool",    "warm"):    "Contrast — cool room + warm carpet may clash",
}


# ── Match quality labels & badge colours ─────────────────────────────────────

def match_label(score: float) -> str:
    if   score >= 85: return "Excellent"
    elif score >= 70: return "Great"
    elif score >= 55: return "Good"
    elif score >= 40: return "Fair"
    else:             return "Poor"


def match_badge_color(score: float) -> str:
    """Return a CSS colour string for a score badge."""
    if   score >= 85: return "#1b5e20"   # dark green
    elif score >= 70: return "#004d40"   # dark teal
    elif score >= 55: return "#e65100"   # dark orange
    else:             return "#b71c1c"   # dark red


# ── Room analysis ─────────────────────────────────────────────────────────────

def analyze_room(
    image_bytes:   bytes,
    n_colors:      int  = 6,
    exclude_floor: bool = True,
) -> dict:
    """
    Extract the dominant color palette from a room photo.

    Parameters
    ----------
    image_bytes   : raw bytes of the uploaded image file
    n_colors      : number of dominant colors to extract (default 6)
    exclude_floor : if True, crop to the top 70 % of the image so the
                    analysis focuses on walls and furniture rather than
                    the floor the carpet will replace

    Returns
    -------
    Standard analysis dict from color_extractor.analyze_image():
    {palette, temperature, color_families, dominant_rgb, dominant_hex}
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    if exclude_floor:
        w, h   = img.size
        crop_h = int(h * 0.70)                  # keep top 70 %
        img    = img.crop((0, 0, w, crop_h))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    buf.seek(0)

    return analyze_image(buf, n_colors)


# ── Single-pair scoring ───────────────────────────────────────────────────────

def _score_pair(
    room_palette:   list[dict],
    room_temp:      str,
    carpet_palette: list[dict],
    carpet_temp:    str,
) -> tuple[float, float, float]:
    """
    Score one room-carpet pair.

    Returns
    -------
    (final_score, color_score, temp_score) — all in the 0-100 range.
    """
    color_score = similarity_score(room_palette, carpet_palette)
    temp_score  = TEMP_HARMONY.get((room_temp, carpet_temp), 50.0)
    final       = round(color_score * COLOR_WEIGHT + temp_score * TEMP_WEIGHT, 1)
    return final, round(color_score, 1), temp_score


# ── Main matching function ────────────────────────────────────────────────────

def find_matches(
    db_path:       str,
    config:        dict,
    image_bytes:   bytes,
    section_id:    str,
    type_id:       Optional[str],
    n_colors:      int   = 6,
    exclude_floor: bool  = True,
    top_n:         int   = 5,
    min_score:     float = 0.0,
) -> dict:
    """
    Analyse a room photo and rank every carpet in the selected catalog
    section / type by colour compatibility.

    Parameters
    ----------
    db_path       : absolute path to the SQLite database file
    config        : resolved app config dict (paths already absolute)
    image_bytes   : raw bytes of the room image
    section_id    : catalog section  ("carpets" | "rolls")
    type_id       : catalog type     ("modern" | "classic" | "new_classic" | None)
    n_colors      : dominant colours to extract from the room image
    exclude_floor : focus analysis on walls + furniture (top 70 %)
    top_n         : max results to return
    min_score     : discard results below this score (0 = return all)

    Returns
    -------
    {
      "room_analysis":     dict,   # palette, temperature, color_families, …
      "total_checked":     int,    # total carpets evaluated
      "all_results_count": int,    # carpets that passed min_score filter
      "results":           list,   # top_n match dicts (see below)
    }

    Each match dict:
    {
      "rank":         int,
      "carpet":       dict,        # full DB record incl. palette
      "score":        float,       # final weighted score  (0-100)
      "color_score":  float,       # colour-only component (0-100)
      "temp_score":   float,       # temperature harmony   (0-100)
      "label":        str,         # "Excellent" / "Great" / "Good" / "Fair" / "Poor"
      "temp_harmony": str,         # human-readable temperature note
      "badge_color":  str,         # CSS colour string for the score badge
    }
    """
    # ── 1. Analyse the room ───────────────────────────────────────────────────
    room_analysis = analyze_room(image_bytes, n_colors, exclude_floor)
    room_palette  = room_analysis["palette"]
    room_temp     = room_analysis["temperature"]

    # ── 2. Load carpets ───────────────────────────────────────────────────────
    init_db(db_path)
    carpets = get_all_carpets(db_path, section_id, type_id)

    # ── 3. Score every carpet ─────────────────────────────────────────────────
    results: list[dict] = []

    for carpet in carpets:
        if not carpet.get("palette"):
            continue

        carpet_temp = carpet.get("temperature", "neutral")

        final, color, temp = _score_pair(
            room_palette,   room_temp,
            carpet["palette"], carpet_temp,
        )

        if final < min_score:
            continue

        results.append({
            "rank":         0,          # assigned after sort
            "carpet":       carpet,
            "score":        final,
            "color_score":  color,
            "temp_score":   temp,
            "label":        match_label(final),
            "temp_harmony": _HARMONY_LABEL.get(
                (room_temp, carpet_temp),
                f"{room_temp.capitalize()} room · {carpet_temp.capitalize()} carpet",
            ),
            "badge_color":  match_badge_color(final),
        })

    # ── 4. Sort, assign ranks, slice ─────────────────────────────────────────
    results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return {
        "room_analysis":     room_analysis,
        "total_checked":     len(carpets),
        "all_results_count": len(results),
        "results":           results[:top_n],
    }
