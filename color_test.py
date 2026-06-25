"""
ui/color_test.py — Phase 2 visual test page
============================================
Lets you upload one or two images and immediately see:
  - Extracted dominant color palette with swatches
  - Percentage share of each color
  - Color temperature (warm / cool / neutral)
  - Color family labels
  - Similarity score when two images are compared
"""

import sys
import os
import streamlit as st
from PIL import Image

# Make sure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.color_extractor import (
    analyze_image,
    similarity_score,
    palette_distance,
    delta_e_single,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

TEMP_EMOJI = {"warm": "🔥 Warm", "cool": "❄️ Cool", "neutral": "⚪ Neutral"}
TEMP_COLOR = {"warm": "🟠", "cool": "🔵", "neutral": "⚫"}


def draw_palette(palette: list[dict]):
    """Render color swatches with percentage bars inside Streamlit."""
    for item in palette:
        r, g, b  = item["rgb"]
        pct      = item["percentage"]
        hex_code = item["hex"]

        # Use a colored markdown block as a swatch
        st.markdown(
            f"""
            <div style="
                display: flex;
                align-items: center;
                gap: 10px;
                margin-bottom: 6px;
            ">
                <div style="
                    width: 36px; height: 36px;
                    background: {hex_code};
                    border-radius: 6px;
                    border: 1px solid rgba(0,0,0,0.12);
                    flex-shrink: 0;
                "></div>
                <div style="flex: 1;">
                    <div style="
                        background: {hex_code};
                        height: 10px;
                        width: {min(pct * 2, 100):.0f}%;
                        border-radius: 4px;
                        margin-bottom: 2px;
                        border: 1px solid rgba(0,0,0,0.1);
                    "></div>
                    <span style="font-size:12px; color: #888;">
                        {hex_code.upper()} &nbsp;·&nbsp; {pct:.1f}%
                    </span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def score_color(score: float) -> str:
    """Return a color for the similarity score badge."""
    if score >= 75:
        return "green"
    elif score >= 50:
        return "orange"
    else:
        return "red"


def match_label(score: float) -> str:
    if score >= 80:
        return "Excellent match 🎯"
    elif score >= 65:
        return "Good match ✅"
    elif score >= 50:
        return "Moderate match 🔶"
    elif score >= 35:
        return "Weak match ⚠️"
    else:
        return "Poor match ❌"


# ── Main page ─────────────────────────────────────────────────────────────────

def render(config: dict):
    st.title("🎨 Color Extractor")
    st.caption("Phase 2 — test the color engine on any image")
    st.divider()

    n_colors = st.slider(
        "Number of dominant colors to extract",
        min_value=3,
        max_value=10,
        value=config["color"]["num_dominant_colors"],
        help="More colors = finer detail, but slower.",
    )

    mode = st.radio(
        "Mode",
        ["Analyze one image", "Compare two images"],
        horizontal=True,
    )

    st.divider()

    # ── Single image ──────────────────────────────────────────────────────────
    if mode == "Analyze one image":
        upload = st.file_uploader(
            "Upload any image (carpet or room photo)",
            type=["jpg", "jpeg", "png", "webp"],
        )

        if upload:
            col_img, col_results = st.columns([1, 1], gap="large")

            with col_img:
                st.image(upload, caption="Uploaded image", use_container_width=True)

            with col_results:
                with st.spinner("Extracting colors…"):
                    result = analyze_image(upload, n_colors=n_colors)

                palette     = result["palette"]
                temperature = result["temperature"]
                families    = result["color_families"]

                # Temperature badge
                st.markdown(f"**Color temperature:** {TEMP_EMOJI[temperature]}")
                st.markdown(
                    f"**Color families:** "
                    + " · ".join(
                        f"`{f}`" for f in dict.fromkeys(families)  # deduplicated
                    )
                )
                st.markdown(
                    f"**Dominant color:** "
                    f'<span style="'
                    f'background:{palette[0]["hex"]};'
                    f'padding:2px 10px;border-radius:4px;'
                    f'border:1px solid rgba(0,0,0,0.15);">&nbsp;</span> '
                    f'`{palette[0]["hex"].upper()}`',
                    unsafe_allow_html=True,
                )

                st.markdown("**Full palette:**")
                draw_palette(palette)

                # Raw data expander
                with st.expander("Raw palette data"):
                    st.json(palette)

    # ── Two-image comparison ──────────────────────────────────────────────────
    else:
        col1, col2 = st.columns(2, gap="medium")

        with col1:
            st.subheader("Image A (room)")
            upload_a = st.file_uploader(
                "Upload room photo",
                type=["jpg", "jpeg", "png", "webp"],
                key="upload_a",
            )

        with col2:
            st.subheader("Image B (carpet)")
            upload_b = st.file_uploader(
                "Upload carpet photo",
                type=["jpg", "jpeg", "png", "webp"],
                key="upload_b",
            )

        if upload_a and upload_b:
            st.divider()

            with st.spinner("Analyzing both images…"):
                result_a = analyze_image(upload_a, n_colors=n_colors)
                result_b = analyze_image(upload_b, n_colors=n_colors)

            # ── Side-by-side palettes ─────────────────────────────────────────
            col_a, col_b = st.columns(2, gap="large")

            with col_a:
                st.image(upload_a, use_container_width=True)
                st.markdown(
                    f"**Temperature:** {TEMP_EMOJI[result_a['temperature']]}"
                )
                st.markdown("**Palette:**")
                draw_palette(result_a["palette"])

            with col_b:
                st.image(upload_b, use_container_width=True)
                st.markdown(
                    f"**Temperature:** {TEMP_EMOJI[result_b['temperature']]}"
                )
                st.markdown("**Palette:**")
                draw_palette(result_b["palette"])

            # ── Similarity result ─────────────────────────────────────────────
            st.divider()
            score    = similarity_score(result_a["palette"], result_b["palette"])
            distance = palette_distance(result_a["palette"], result_b["palette"])

            score_col, label_col, delta_col = st.columns(3)

            with score_col:
                st.metric(
                    label="Color similarity",
                    value=f"{score:.1f} / 100",
                    delta=None,
                )

            with label_col:
                st.metric(
                    label="Verdict",
                    value=match_label(score),
                )

            with delta_col:
                st.metric(
                    label="Delta-E distance",
                    value=f"{distance:.1f}",
                    help=(
                        "CIEDE2000 scale: "
                        "0 = identical · "
                        "< 5 = very similar · "
                        "10+ = clearly different"
                    ),
                )

            # Visual score bar
            st.progress(int(score))

            # Temperature harmony note
            temp_a = result_a["temperature"]
            temp_b = result_b["temperature"]
            if temp_a == temp_b:
                st.success(
                    f"Both images share a **{temp_a}** color temperature — "
                    "good harmony."
                )
            else:
                st.warning(
                    f"The room is **{temp_a}** and the carpet is **{temp_b}**. "
                    "Mixed temperatures can still work as contrast, "
                    "but may feel less cohesive."
                )
