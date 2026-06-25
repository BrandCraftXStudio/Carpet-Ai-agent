"""
color_extractor.py — Phase 2: Color Extraction Engine
======================================================
Responsibilities:
  - Extract dominant colors from any image using KMeans clustering
  - Convert colors from RGB → LAB (perceptually uniform color space)
  - Calculate Delta-E 2000 distance between colors (scientific standard)
  - Score palette similarity between a room and a carpet image
  - Detect color temperature (warm / cool / neutral)
  - Classify colors into named families (red, blue, green, etc.)

All public functions accept image file paths or RGB tuples and return
plain Python dicts/lists — no Streamlit dependency in this module.
"""

import json
import numpy as np
from PIL import Image
from sklearn.cluster import KMeans
from skimage import color as skcolor


# ── Constants ─────────────────────────────────────────────────────────────────

# Delta-E reference points (CIEDE2000 scale):
#   0        → identical colors
#   1        → just barely perceptible difference
#   2 - 10   → noticeable but similar
#   10 - 25  → clearly different
#   > 25     → opposite ends of the color spectrum
DELTA_E_MAX = 50.0   # clamp for similarity → percentage conversion


# ── Image loading ─────────────────────────────────────────────────────────────

def load_image(source, max_size: int = 300) -> Image.Image:
    """
    Load an image from a file path or a file-like object (Streamlit upload).
    Resize to max_size × max_size to speed up processing while keeping
    enough pixels for accurate color sampling.
    """
    img = Image.open(source).convert("RGB")
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    return img


# ── Dominant color extraction ─────────────────────────────────────────────────

def extract_dominant_colors(source, n_colors: int = 6) -> list[dict]:
    """
    Extract the N most dominant colors from an image using KMeans clustering.

    Parameters
    ----------
    source    : file path (str) or file-like object (Streamlit UploadedFile)
    n_colors  : how many dominant colors to extract (default 6)

    Returns
    -------
    List of dicts sorted by dominance (most dominant first):
    [
        {"rgb": (R, G, B), "hex": "#rrggbb", "percentage": 34.2},
        ...
    ]
    """
    img    = load_image(source)
    pixels = np.array(img, dtype=float).reshape(-1, 3)

    # KMeans groups pixels into n_colors clusters
    kmeans = KMeans(n_clusters=n_colors, random_state=42, n_init=10)
    kmeans.fit(pixels)

    centers = kmeans.cluster_centers_.astype(int)  # cluster RGB centers
    labels  = kmeans.labels_
    counts  = np.bincount(labels)                  # how many pixels per cluster

    # Sort by frequency so the most dominant color is first
    order = np.argsort(-counts)
    total = counts.sum()

    palette = []
    for idx in order:
        r, g, b  = int(centers[idx][0]), int(centers[idx][1]), int(centers[idx][2])
        pct      = round(float(counts[idx]) / total * 100, 1)
        palette.append({
            "rgb":        (r, g, b),
            "hex":        f"#{r:02x}{g:02x}{b:02x}",
            "percentage": pct,
        })

    return palette


# ── Color space conversion ────────────────────────────────────────────────────

def rgb_to_lab(rgb: tuple) -> np.ndarray:
    """
    Convert a single RGB tuple (values 0–255) to CIE LAB color space.

    LAB is perceptually uniform: a distance of 1 ΔE looks the same
    regardless of where in the color space you are.  RGB is NOT —
    a distance of 10 in the blues looks very different from a distance
    of 10 in the reds.

    Returns a numpy array [L, a, b].
    """
    rgb_norm    = np.array(rgb, dtype=float) / 255.0
    rgb_shaped  = rgb_norm.reshape(1, 1, 3)
    lab         = skcolor.rgb2lab(rgb_shaped)
    return lab[0, 0]  # shape (3,)


# ── Delta-E distance ──────────────────────────────────────────────────────────

def delta_e_single(rgb1: tuple, rgb2: tuple) -> float:
    """
    Calculate the CIEDE2000 Delta-E distance between two RGB colors.

    CIEDE2000 is the current international standard for color difference.
    It corrects for known perceptual non-uniformities in the earlier
    Delta-E 76 and Delta-E 94 formulas (especially in blues and grays).

    Returns a float:  0 = identical,  > 10 = clearly different.
    """
    lab1 = rgb_to_lab(rgb1).reshape(1, 1, 3)
    lab2 = rgb_to_lab(rgb2).reshape(1, 1, 3)
    return float(skcolor.deltaE_ciede2000(lab1, lab2)[0, 0])


def palette_distance(palette1: list[dict], palette2: list[dict]) -> float:
    """
    Calculate the weighted average color distance between two palettes.

    Strategy:
      For each color in palette1 (weighted by its dominance %) find the
      closest matching color in palette2 using Delta-E.  The dominant
      colors of the room carry more weight than minor accent colors.

    Returns a float distance score:
      ~0   → palettes are very similar
      ~25+ → palettes are clearly different
    """
    if not palette1 or not palette2:
        return DELTA_E_MAX

    total_distance = 0.0
    total_weight   = 0.0

    for c1 in palette1:
        lab1   = rgb_to_lab(c1["rgb"])
        weight = c1["percentage"] / 100.0

        # Find the closest color in palette2
        best_dist = float("inf")
        for c2 in palette2:
            lab2 = rgb_to_lab(c2["rgb"])
            d    = float(skcolor.deltaE_ciede2000(
                lab1.reshape(1, 1, 3),
                lab2.reshape(1, 1, 3)
            )[0, 0])
            if d < best_dist:
                best_dist = d

        total_distance += best_dist * weight
        total_weight   += weight

    raw = total_distance / total_weight if total_weight else DELTA_E_MAX
    return round(raw, 2)


def similarity_score(palette1: list[dict], palette2: list[dict]) -> float:
    """
    Convert palette distance to a human-readable similarity score (0–100).

    100 = perfect color match
      0 = completely different palettes
    """
    dist  = palette_distance(palette1, palette2)
    score = max(0.0, 100.0 - (dist / DELTA_E_MAX * 100.0))
    return round(score, 1)


# ── Color intelligence ────────────────────────────────────────────────────────

def get_color_temperature(palette: list[dict]) -> str:
    """
    Classify a palette as 'warm', 'cool', or 'neutral'.

    Warm  → reds, oranges, yellows, beige, browns
    Cool  → blues, greens, purples, grays with blue undertone
    Neutral → balanced mix, pure grays, whites, blacks
    """
    warm = cool = neutral = 0.0

    for c in palette:
        r, g, b = c["rgb"]
        w       = c["percentage"]

        chroma = max(r, g, b) - min(r, g, b)

        if chroma < 30:
            # Low saturation → neutral (gray / white / black)
            neutral += w
        elif r >= g and r >= b:
            if g > b * 1.2 and g > 100:
                warm += w   # orange / yellow
            else:
                warm += w   # red
        elif b >= r and b >= g:
            cool += w       # blue / violet
        elif g >= r and g >= b:
            if r > 130:
                warm += w   # yellow-green → warm side
            else:
                cool += w   # pure green → cool side
        else:
            neutral += w

    total = warm + cool + neutral or 1.0

    if warm / total > 0.45:
        return "warm"
    elif cool / total > 0.45:
        return "cool"
    else:
        return "neutral"


def get_color_family(rgb: tuple) -> str:
    """
    Map an RGB color to its named color family.
    Returns one of: red, orange, yellow, green, blue, purple,
                    pink, brown, beige, gray, white, black.
    """
    r, g, b = rgb

    max_c  = max(r, g, b)
    min_c  = min(r, g, b)
    chroma = max_c - min_c

    # ── Achromatic ────────────────────────────────────────────────────────────
    if chroma < 25:
        if max_c > 210:
            return "white"
        elif max_c < 60:
            return "black"
        else:
            return "gray"

    # ── Chromatic — find hue ──────────────────────────────────────────────────
    if max_c == r:
        hue = (g - b) / chroma % 6          # 0–6 range
    elif max_c == g:
        hue = (b - r) / chroma + 2
    else:
        hue = (r - g) / chroma + 4

    hue_deg = hue * 60  # convert to 0–360 degrees

    # Low-saturation check → beige / brown
    saturation = chroma / max_c if max_c else 0
    if saturation < 0.25:
        if max_c > 160:
            return "beige"
        else:
            return "brown"

    # Hue angle → color family
    if hue_deg < 15 or hue_deg >= 345:
        return "red"
    elif hue_deg < 45:
        return "orange"
    elif hue_deg < 70:
        return "yellow"
    elif hue_deg < 150:
        return "green"
    elif hue_deg < 195:
        return "cyan"
    elif hue_deg < 255:
        return "blue"
    elif hue_deg < 285:
        return "purple"
    elif hue_deg < 315:
        return "pink"
    elif hue_deg < 345:
        return "red"
    else:
        return "other"


# ── Full image analysis ───────────────────────────────────────────────────────

def analyze_image(source, n_colors: int = 6) -> dict:
    """
    Run a complete color analysis on an image.

    Parameters
    ----------
    source   : file path (str) or file-like object
    n_colors : dominant colors to extract

    Returns
    -------
    {
        "palette":       [{"rgb": ..., "hex": ..., "percentage": ...}, ...],
        "temperature":   "warm" | "cool" | "neutral",
        "color_families": ["beige", "brown", "gray", ...],
        "dominant_rgb":  (R, G, B),
        "dominant_hex":  "#rrggbb",
    }
    """
    palette     = extract_dominant_colors(source, n_colors)
    temperature = get_color_temperature(palette)
    families    = [get_color_family(c["rgb"]) for c in palette]

    return {
        "palette":        palette,
        "temperature":    temperature,
        "color_families": families,
        "dominant_rgb":   palette[0]["rgb"] if palette else None,
        "dominant_hex":   palette[0]["hex"] if palette else None,
    }


# ── Serialization helpers (for DB storage) ────────────────────────────────────

def palette_to_json(palette: list[dict]) -> str:
    """Serialize a palette list to a JSON string for SQLite storage."""
    return json.dumps(palette)


def palette_from_json(json_str: str) -> list[dict]:
    """Deserialize a palette list from a SQLite JSON string."""
    data = json.loads(json_str)
    # Ensure rgb values are tuples (JSON stores them as lists)
    for item in data:
        item["rgb"] = tuple(item["rgb"])
    return data
