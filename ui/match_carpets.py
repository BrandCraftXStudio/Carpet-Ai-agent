"""
ui/match_carpets.py — Phase 5: Enhanced results UI & display
=============================================================
Improvements over Phase 4
--------------------------
• Two-panel layout after matching:
    Left  (1/3) — room photo · compact analysis · Export PDF button
    Right (2/3) — live-filter controls · polished result cards
• Result cards redesigned:
    Full-width score bar with colour-coded badge
    Thumbnail + metadata + palette comparison in one cohesive card
    Score breakdown expander (colour % · temp harmony)
• Export to PDF — one-click download of a branded match report
• Live filters applied to stored results (no re-processing):
    Minimum score slider
    Carpet temperature selector
    Price search (free-text)
• Sidebar catalogue count shown for context
"""

from __future__ import annotations

import io
import os
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.matcher  import find_matches, match_badge_color
from core.exporter import export_to_pdf
from core.db_manager import init_db, get_all_carpets
from core.catalog    import full_label


# ── Constants ─────────────────────────────────────────────────────────────────

TEMP_EMOJI = {"warm": "🔥", "cool": "❄️", "neutral": "⚪"}
TEMP_LABEL = {"warm": "Warm", "cool": "Cool", "neutral": "Neutral"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _thumb(image_path: str, size: tuple[int, int] = (320, 240)) -> bytes | None:
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail(size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return None


def _swatches_html(palette: list[dict], label: str = "") -> str:
    chips = "".join(
        f'<span title="{c["hex"]}  {c["percentage"]}%"'
        f' style="display:inline-block;width:22px;height:22px;'
        f'background:{c["hex"]};border-radius:4px;'
        f'border:1px solid rgba(0,0,0,.12);margin-right:3px;"></span>'
        for c in palette[:6]
    )
    lbl = (
        f'<span style="font-size:11px;color:var(--color-text-secondary);'
        f'margin-right:5px;vertical-align:middle;">{label}</span>'
        if label else ""
    )
    return f'<div style="margin:3px 0">{lbl}{chips}</div>'


def _score_bar_html(score: float, label: str, color: str) -> str:
    return (
        f'<div style="margin:0 0 10px">'
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">'
        f'<span style="font-size:28px;font-weight:600;'
        f'color:{color};line-height:1">{score:.0f}%</span>'
        f'<span style="background:{color};color:#fff;padding:3px 12px;'
        f'border-radius:12px;font-size:13px;font-weight:500">{label}</span>'
        f'</div>'
        f'<div style="background:rgba(128,128,128,.15);border-radius:5px;height:9px">'
        f'<div style="background:{color};width:{min(score,100):.0f}%;'
        f'height:9px;border-radius:5px"></div>'
        f'</div></div>'
    )


def _rank_badge_html(rank: int, color: str) -> str:
    return (
        f'<div style="background:{color};color:#fff;border-radius:50%;'
        f'width:32px;height:32px;display:flex;align-items:center;'
        f'justify-content:center;font-weight:700;font-size:14px;'
        f'margin-bottom:8px">#{rank}</div>'
    )


# ── Room analysis panel ───────────────────────────────────────────────────────

def _room_panel(room_analysis: dict, image_bytes: bytes) -> None:
    """Compact room photo + colour summary for the left column."""
    st.image(image_bytes, use_container_width=True)

    temp     = room_analysis.get("temperature", "neutral")
    palette  = room_analysis.get("palette", [])
    families = list(dict.fromkeys(room_analysis.get("color_families", [])))

    st.markdown(
        f"**Temperature:** {TEMP_EMOJI.get(temp,'')} {TEMP_LABEL.get(temp,temp)}"
    )
    st.markdown("**Color families:** " + " · ".join(f"`{f}`" for f in families[:5]))
    st.markdown("**Room palette:**")
    st.markdown(_swatches_html(palette), unsafe_allow_html=True)


# ── Result card ───────────────────────────────────────────────────────────────

def _result_card(result: dict, room_analysis: dict) -> None:
    """
    Render one match card.

    Layout
    ------
    Full-width score bar
    [thumbnail col]  [metadata col]
    Palette comparison row at the bottom
    """
    carpet      = result["carpet"]
    score       = result["score"]
    label       = result["label"]
    rank        = result["rank"]
    color       = result["badge_color"]
    carpet_temp = carpet.get("temperature", "neutral")
    img_path    = carpet["image_path"]

    with st.container(border=True):

        # Score bar (full width)
        st.markdown(_score_bar_html(score, label, color), unsafe_allow_html=True)

        col_img, col_meta = st.columns([1, 2], gap="medium")

        with col_img:
            st.markdown(_rank_badge_html(rank, color), unsafe_allow_html=True)
            if Path(img_path).exists():
                thumb = _thumb(img_path, (280, 210))
                if thumb:
                    st.image(thumb, use_container_width=True)
                else:
                    st.caption("⚠️ Cannot render image")
            else:
                st.caption("⚠️ Image file missing")

        with col_meta:
            st.markdown(f"### {carpet['name']}")

            r_temp = room_analysis.get("temperature", "neutral")
            st.markdown(
                f"{TEMP_EMOJI.get(r_temp,'⚪')} Room &nbsp;→&nbsp; "
                f"{TEMP_EMOJI.get(carpet_temp,'⚪')} Carpet",
                unsafe_allow_html=True,
            )
            st.caption(result.get("temp_harmony", ""))

            if carpet.get("price"):
                st.markdown(f"💰 &nbsp;**{carpet['price']}**",
                            unsafe_allow_html=True)
            if carpet.get("notes"):
                st.caption(f"📝 {carpet['notes']}")

            with st.expander("Score breakdown"):
                c1, c2 = st.columns(2)
                c1.metric("🎨 Color match",      f"{result['color_score']:.1f}%")
                c2.metric("🌡️ Temp. harmony",   f"{result['temp_score']:.0f}/100")
                st.caption("Final = colour × 85% + temp. harmony × 15%")

        # Palette comparison (full width, below columns)
        st.markdown(
            _swatches_html(room_analysis.get("palette", []),   "Room:  ") +
            _swatches_html(carpet.get("palette",         []),   "Carpet:"),
            unsafe_allow_html=True,
        )


# ── Filters ───────────────────────────────────────────────────────────────────

def _apply_filters(
    results:    list[dict],
    min_score:  float,
    temp_pick:  str,
    price_text: str,
) -> list[dict]:
    out = [r for r in results if r["score"] >= min_score]

    TEMP_MAP = {
        "Warm only":    "warm",
        "Cool only":    "cool",
        "Neutral only": "neutral",
    }
    if temp_pick in TEMP_MAP:
        wanted = TEMP_MAP[temp_pick]
        out = [r for r in out if r["carpet"].get("temperature") == wanted]

    if price_text.strip():
        q = price_text.strip().lower()
        out = [r for r in out if q in str(r["carpet"].get("price", "")).lower()]

    return out


# ── Main render ───────────────────────────────────────────────────────────────

def render(config: dict) -> None:
    db_path    = config["database"]["db_path"]
    n_colors   = config["color"]["num_dominant_colors"]
    top_n_cfg  = config["app"]["top_n_results"]
    section_id = st.session_state.get("selected_section", "carpets")
    type_id    = st.session_state.get("selected_type")
    label      = full_label(config, section_id, type_id)

    init_db(db_path)

    # ── Header ────────────────────────────────────────────────────────────────
    st.title("🔍 Match Carpets")
    st.caption(f"Searching in: **{label}**")

    # ── Guard — catalog must have carpets ─────────────────────────────────────
    carpets = get_all_carpets(db_path, section_id, type_id)
    if not carpets:
        st.warning(
            f"No carpets in **{label}** yet. "
            "Open **🗄️ Manage Database** and add images first."
        )
        return

    st.caption(f"{len(carpets)} carpet(s) available in this catalog")
    st.divider()

    # ── Upload & options ──────────────────────────────────────────────────────
    st.markdown("#### Step 1 — Upload the customer's room photo")
    upload = st.file_uploader(
        "Room photo", type=["jpg", "jpeg", "png", "webp"],
        label_visibility="collapsed", key="room_upload",
    )
    if upload is not None:
        st.session_state["room_bytes"] = upload.read()
        st.session_state["room_name"]  = upload.name

    room_bytes: bytes | None = st.session_state.get("room_bytes")

    col_opt1, col_opt2 = st.columns([2, 1], gap="large")
    with col_opt1:
        st.markdown("#### Step 2 — Options")
        exclude_floor = st.toggle(
            "Focus on walls & furniture — exclude floor area (recommended)",
            value=True,
            help=(
                "Crops the bottom 30% of the room photo before colour analysis. "
                "Since the carpet replaces the floor, we match walls and furniture "
                "colours rather than the existing floor colour."
            ),
        )
    with col_opt2:
        st.markdown("#### &nbsp;", unsafe_allow_html=True)
        top_n = st.slider("Max results", min_value=3, max_value=20, value=top_n_cfg)

    if room_bytes:
        with st.expander("Preview uploaded photo"):
            st.image(room_bytes, use_container_width=True)

    # ── Match button ──────────────────────────────────────────────────────────
    st.markdown("#### Step 3 — Run matching")

    if not room_bytes:
        st.info("📷 Upload a room photo above, then click the button below.")
    else:
        if st.button(
            "🔍  Find Best Matches",
            type="primary",
            use_container_width=True,
        ):
            with st.spinner(
                f"Analysing room and scoring {len(carpets)} carpet(s)…"
            ):
                output = find_matches(
                    db_path       = db_path,
                    config        = config,
                    image_bytes   = room_bytes,
                    section_id    = section_id,
                    type_id       = type_id,
                    n_colors      = n_colors,
                    exclude_floor = exclude_floor,
                    top_n         = top_n,
                    min_score     = 0.0,
                )
            st.session_state["match_output"]  = output
            st.session_state["match_section"] = section_id
            st.session_state["match_type"]    = type_id
            st.rerun()

    # ── Results ───────────────────────────────────────────────────────────────
    output: dict | None = st.session_state.get("match_output")
    if not output:
        return

    # Stale-result warning when catalog changes
    if (st.session_state.get("match_section") != section_id or
            st.session_state.get("match_type") != type_id):
        st.warning(
            "Catalog changed since last match. "
            "Click **Find Best Matches** to re-run."
        )
        return

    room_analysis = output["room_analysis"]
    all_results   = output["results"]

    st.divider()

    # ── Two-panel layout: room (left) | results (right) ──────────────────────
    col_room, col_results = st.columns([1, 2], gap="large")

    # ── Left panel — room photo + analysis + export ───────────────────────────
    with col_room:
        st.markdown("#### Room photo")
        _room_panel(room_analysis, room_bytes)

        st.divider()

        # Quick stats
        c1, c2 = st.columns(2)
        c1.metric("Checked", output["total_checked"])
        c2.metric("Matched", output["all_results_count"])

        st.divider()

        # ── Export PDF button ─────────────────────────────────────────────────
        st.markdown("#### Export")
        store_name = st.text_input(
            "Store name for report",
            value="Hawash Carpet Store",
            key="store_name_input",
        )

        if all_results:
            with st.spinner("Building PDF…"):
                pdf_bytes = export_to_pdf(
                    room_analysis    = room_analysis,
                    results          = all_results,
                    room_image_bytes = room_bytes,
                    store_name       = store_name,
                    catalog_label    = label,
                )

            filename = (
                f"carpet_match_"
                f"{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
            )
            st.download_button(
                label        = "📄 Download PDF Report",
                data         = pdf_bytes,
                file_name    = filename,
                mime         = "application/pdf",
                use_container_width = True,
                type         = "primary",
            )
            st.caption(
                f"Includes {len(all_results)} match(es). "
                "Ready to print or share with the customer."
            )
        else:
            st.info("No results yet to export.")

    # ── Right panel — filters + result cards ──────────────────────────────────
    with col_results:
        st.markdown("#### Filter results")
        f1, f2, f3 = st.columns([2, 2, 2], gap="small")

        with f1:
            min_score = st.slider(
                "Min score", 0, 100, 0, key="min_score_filter"
            )
        with f2:
            temp_pick = st.selectbox(
                "Temperature",
                ["All", "Warm only", "Cool only", "Neutral only"],
                key="temp_filter",
            )
        with f3:
            price_text = st.text_input(
                "Price contains", placeholder="e.g. 500",
                key="price_filter",
            )

        filtered = _apply_filters(all_results, min_score, temp_pick, price_text)

        st.markdown(
            f"**{len(filtered)}** result(s) · "
            f"Room: {TEMP_EMOJI.get(room_analysis.get('temperature',''),'⚪')} "
            f"{TEMP_LABEL.get(room_analysis.get('temperature','neutral'),'')}"
        )
        st.divider()

        if not filtered:
            st.info(
                "No carpets match the current filters. "
                "Try lowering the minimum score."
            )
        else:
            for result in filtered:
                _result_card(result, room_analysis)
