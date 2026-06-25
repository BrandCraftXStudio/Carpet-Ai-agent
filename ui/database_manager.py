"""
ui/database_manager.py — Phase 3: Database Manager page
========================================================
Three tabs:
  📋 View Catalog  — grid of carpet cards with edit / delete
  ➕ Add Carpets   — multi-file uploader with price / notes
  📂 Bulk Import   — import every image in a folder at once
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import streamlit as st
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.db_manager import (
    init_db, add_carpet, get_all_carpets,
    update_carpet, delete_carpet, catalog_stats,
    sync_all_folders,
)
from core.catalog import full_label


# ── Visual helpers ────────────────────────────────────────────────────────────

TEMP_STYLE: dict[str, tuple[str, str, str]] = {
    "warm":    ("🔥", "#fff3e0", "#bf360c"),
    "cool":    ("❄️",  "#e3f2fd", "#0d47a1"),
    "neutral": ("⚪", "#f5f5f5", "#424242"),
}


def make_thumbnail(image_path: str, size: tuple[int, int] = (300, 220)) -> bytes | None:
    """Return JPEG thumbnail bytes for st.image(), or None on failure."""
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail(size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return None


def palette_swatches(palette: list[dict]) -> str:
    """Return an HTML string of colour swatches for a palette."""
    chips = "".join(
        f'<span title="{c["hex"]} · {c["percentage"]}%"'
        f' style="display:inline-block;width:20px;height:20px;'
        f'background:{c["hex"]};border-radius:4px;'
        f'border:1px solid rgba(0,0,0,0.12);margin-right:3px;"></span>'
        for c in palette[:6]
    )
    return f'<div style="margin:5px 0 2px">{chips}</div>'


def temp_badge(temperature: str) -> str:
    """Return an HTML badge for warm / cool / neutral."""
    icon, bg, fg = TEMP_STYLE.get(temperature, TEMP_STYLE["neutral"])
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 9px;'
        f'border-radius:10px;font-size:12px;font-weight:500;">'
        f'{icon} {temperature.capitalize()}</span>'
    )


# ── Card rendering ────────────────────────────────────────────────────────────

def _display_card(carpet: dict, db_path: str):
    """Normal (read-only) card view."""
    img_path = carpet["image_path"]
    exists   = Path(img_path).exists()

    if exists:
        thumb = make_thumbnail(img_path)
        if thumb:
            st.image(thumb, use_container_width=True)
        else:
            st.caption("⚠️ Cannot render image")
    else:
        st.caption("⚠️ Image file not found")

    st.markdown(f"**{carpet['name']}**")

    price_str = f" &nbsp;·&nbsp; 💰 {carpet['price']}" if carpet.get("price") else ""
    st.markdown(
        temp_badge(carpet.get("temperature", "neutral")) + price_str,
        unsafe_allow_html=True,
    )
    st.markdown(palette_swatches(carpet["palette"]), unsafe_allow_html=True)

    if carpet.get("notes"):
        st.caption(carpet["notes"])

    c1, c2 = st.columns(2)
    cid = carpet["id"]
    with c1:
        if st.button("✏️ Edit", key=f"edit_{cid}", use_container_width=True):
            st.session_state["editing_id"]    = cid
            st.session_state.pop("confirm_delete", None)
            st.rerun()
    with c2:
        if st.button("🗑 Delete", key=f"del_{cid}", use_container_width=True):
            st.session_state["confirm_delete"] = cid
            st.session_state.pop("editing_id", None)
            st.rerun()


def _edit_form(carpet: dict, db_path: str):
    """Inline edit form shown inside the card."""
    cid = carpet["id"]

    img_path = carpet["image_path"]
    if Path(img_path).exists():
        thumb = make_thumbnail(img_path, (300, 160))
        if thumb:
            st.image(thumb, use_container_width=True)

    new_name  = st.text_input("Name",  value=carpet["name"],  key=f"ename_{cid}")
    new_price = st.text_input("Price", value=carpet.get("price", ""), key=f"eprice_{cid}")
    new_notes = st.text_area( "Notes", value=carpet.get("notes", ""), key=f"enotes_{cid}", height=72)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 Save", key=f"save_{cid}", use_container_width=True, type="primary"):
            update_carpet(db_path, cid, new_name, new_price, new_notes)
            st.session_state.pop("editing_id", None)
            st.success("Saved!")
            st.rerun()
    with c2:
        if st.button("✖ Cancel", key=f"cancel_{cid}", use_container_width=True):
            st.session_state.pop("editing_id", None)
            st.rerun()


def _confirm_delete(carpet: dict, db_path: str):
    """Delete-confirmation view shown inside the card."""
    cid = carpet["id"]

    img_path = carpet["image_path"]
    if Path(img_path).exists():
        thumb = make_thumbnail(img_path, (300, 160))
        if thumb:
            st.image(thumb, use_container_width=True)

    st.warning(f"Delete **{carpet['name']}**?\nThis also removes the image file.")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🗑 Confirm", key=f"conf_{cid}", use_container_width=True, type="primary"):
            delete_carpet(db_path, cid, delete_image=True)
            st.session_state.pop("confirm_delete", None)
            st.rerun()
    with c2:
        if st.button("✖ Cancel", key=f"nodel_{cid}", use_container_width=True):
            st.session_state.pop("confirm_delete", None)
            st.rerun()


def render_card(carpet: dict, db_path: str):
    """Route a carpet to the correct card view based on session state."""
    cid = carpet["id"]
    with st.container(border=True):
        if st.session_state.get("editing_id") == cid:
            _edit_form(carpet, db_path)
        elif st.session_state.get("confirm_delete") == cid:
            _confirm_delete(carpet, db_path)
        else:
            _display_card(carpet, db_path)


# ── Tab: View Catalog ─────────────────────────────────────────────────────────

def tab_view(db_path: str, config: dict, section_id: str,
             type_id: str | None, label: str):

    search = st.text_input(
        "🔍 Search by name",
        placeholder="Type to filter…",
        key="search_input",
    )

    carpets = get_all_carpets(db_path, section_id, type_id, search.strip())

    if not carpets:
        msg = (
            f'No carpets in **{label}** yet.\n'
            'Use the **➕ Add Carpets** or **📂 Bulk Import** tab to get started.'
        )
        if search:
            msg = f'No results for "{search}" in **{label}**.'
        st.info(msg)
        return

    st.caption(f"{len(carpets)} item(s) found")

    cols = st.columns(3, gap="medium")
    for i, carpet in enumerate(carpets):
        with cols[i % 3]:
            render_card(carpet, db_path)


# ── Tab: Add Carpets ──────────────────────────────────────────────────────────

def tab_add(db_path: str, config: dict, section_id: str,
            type_id: str | None, label: str, n_colors: int):

    st.markdown(f"Uploading to: **{label}**")
    st.caption(
        "Select one or more images. Names are auto-filled from filenames — "
        "you can rename any carpet later from the View tab."
    )

    uploads = st.file_uploader(
        "Choose carpet images",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="uploader",
    )

    if not uploads:
        return

    st.markdown(f"**{len(uploads)} file(s) selected**")

    col_p, col_n = st.columns([1, 2])
    with col_p:
        price = st.text_input("Price (optional)", placeholder="e.g. 450 EGP")
    with col_n:
        notes = st.text_area("Notes (optional)", height=68, placeholder="Material, size, origin…")

    if st.button(
        f"➕ Add {len(uploads)} carpet(s) to {label}",
        type="primary",
        use_container_width=True,
    ):
        progress = st.progress(0, text="Starting…")
        added = errors = skipped = 0

        for i, f in enumerate(uploads):
            progress.progress(i / len(uploads), text=f"Processing {f.name}…")
            try:
                add_carpet(
                    db_path, config, f,
                    section_id, type_id,
                    price=price, notes=notes,
                    n_colors=n_colors,
                )
                added += 1
            except ValueError as e:
                skipped += 1
                st.warning(f"⚠️ {e}")
            except Exception as e:
                errors += 1
                st.error(f"❌ Error on {f.name}: {e}")

        progress.progress(1.0, text="Done!")
        parts = []
        if added:   parts.append(f"✅ {added} added")
        if skipped: parts.append(f"⚠️ {skipped} already in DB")
        if errors:  parts.append(f"❌ {errors} failed")
        st.success("  ·  ".join(parts) if parts else "Nothing imported.")
        st.rerun()


# ── Tab: Bulk Import ──────────────────────────────────────────────────────────

def tab_bulk(db_path: str, config: dict, section_id: str,
             type_id: str | None, label: str, n_colors: int):

    st.markdown(f"Import all images from a folder on your PC into **{label}**.")
    st.caption("Paste the full path to the folder that contains your carpet images.")

    folder_str = st.text_input(
        "Folder path",
        placeholder=r"e.g.  C:\Users\YourName\Desktop\Modern Carpets",
        key="bulk_folder",
    )

    if not folder_str:
        return

    folder = Path(folder_str.strip())

    if not folder.exists():
        st.error("❌ Folder not found — check the path and try again.")
        return
    if not folder.is_dir():
        st.error("❌ That path points to a file, not a folder.")
        return

    exts   = ("*.jpg", "*.jpeg", "*.png", "*.webp")
    images = sorted(p for ext in exts for p in folder.glob(ext))

    if not images:
        st.warning("No JPEG / PNG / WebP images found in that folder.")
        return

    st.success(f"Found **{len(images)}** image(s) in that folder.")

    with st.expander("Preview file list"):
        for img in images:
            st.write(f"• {img.name}")

    if not st.button(
        f"📥 Import {len(images)} image(s) into {label}",
        type="primary",
        use_container_width=True,
    ):
        return

    bar    = st.progress(0, text="Starting…")
    status = st.empty()
    added = skipped = errors = 0

    for i, img_path in enumerate(images):
        bar.progress(i / len(images), text=f"Processing {img_path.name}…")
        status.caption(f"{i + 1} / {len(images)}")
        try:
            add_carpet(
                db_path, config, img_path,
                section_id, type_id,
                n_colors=n_colors,
            )
            added += 1
        except ValueError:
            skipped += 1
        except Exception as e:
            errors += 1
            st.error(f"Error on {img_path.name}: {e}")

    bar.progress(1.0, text="Done!")
    status.empty()

    parts = []
    if added:   parts.append(f"✅ {added} imported")
    if skipped: parts.append(f"⚠️ {skipped} already in DB")
    if errors:  parts.append(f"❌ {errors} failed")
    st.success("  ·  ".join(parts) if parts else "Nothing imported.")
    st.rerun()


# ── Main entry point ──────────────────────────────────────────────────────────

def render(config: dict):
    db_path    = config["database"]["db_path"]
    n_colors   = config["color"]["num_dominant_colors"]
    section_id = st.session_state.get("selected_section", "carpets")
    type_id    = st.session_state.get("selected_type")
    label      = full_label(config, section_id, type_id)

    # Ensure DB exists
    init_db(db_path)

    # ── Header ────────────────────────────────────────────────────────────────
    st.title("🗄️ Manage Database")
    st.caption(f"Currently managing: **{label}**")

    # ── Stats bar ─────────────────────────────────────────────────────────────
    stats      = catalog_stats(db_path, config)
    stat_cols  = st.columns(len(stats))
    for col, stat in zip(stat_cols, stats):
        col.metric(stat["label"], stat["count"])

    st.divider()

    # ── Sync All Folders ───────────────────────────────────────────────────────
    # Drop images into any catalog subfolder, click Sync — done.
    with st.container(border=True):
        col_txt, col_btn = st.columns([3, 1], gap="large")

        with col_txt:
            st.markdown("**Sync All Folders**")
            st.caption(
                "Scans every catalog folder and imports any new images "
                "that are not yet in the database. "
                "Already-imported images are skipped automatically."
            )

        with col_btn:
            sync_clicked = st.button(
                "Sync Now",
                type="primary",
                use_container_width=True,
                key="sync_all_btn",
            )

    if sync_clicked:
        bar = st.progress(0, text="Starting sync…")

        # Run sync — show a live status line per folder
        from core.catalog import get_sections, get_types

        all_folders = []
        for section in get_sections(config):
            types = get_types(config, section["id"])
            if types:
                for t in types:
                    all_folders.append((
                        f"{section['label']} > {t['label']}",
                        section["id"], t["id"]
                    ))
            else:
                all_folders.append((section["label"], section["id"], None))

        sync_results = []
        status_line  = st.empty()

        for i, (flabel, sid, tid) in enumerate(all_folders):
            bar.progress(i / len(all_folders), text=f"Scanning {flabel}…")
            status_line.caption(f"Processing: {flabel}")

            from core.db_manager import bulk_import
            from pathlib import Path as _Path
            from core.catalog import get_folder as _get_folder

            folder = _get_folder(config, sid, tid)
            if not folder.exists():
                sync_results.append({
                    "label": flabel, "added": 0,
                    "skipped": 0, "error": True,
                })
                continue

            added, skipped = bulk_import(
                db_path, config, str(folder),
                sid, tid, n_colors=n_colors,
            )
            sync_results.append({
                "label": flabel, "added": added,
                "skipped": skipped, "error": False,
            })

        bar.progress(1.0, text="Sync complete!")
        status_line.empty()

        # ── Results summary ────────────────────────────────────────────────────
        total_added   = sum(r["added"]   for r in sync_results)
        total_skipped = sum(r["skipped"] for r in sync_results)

        if total_added:
            st.success(
                f"Sync complete — "
                f"**{total_added}** new image(s) added, "
                f"{total_skipped} already in database."
            )
        else:
            st.info(
                f"Everything is already up to date — "
                f"{total_skipped} image(s) in database, nothing new to import."
            )

        # Per-folder breakdown table
        with st.expander("Folder breakdown", expanded=total_added > 0):
            for r in sync_results:
                if r.get("error"):
                    st.write(f"MISSING  {r['label']} — folder not found on disk")
                elif r["added"]:
                    st.write(f"+{r['added']} added  ·  "
                             f"{r['skipped']} already in DB  |  {r['label']}")
                else:
                    st.write(f"Up to date  ({r['skipped']} in DB)  |  {r['label']}")

        if total_added:
            st.rerun()

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────────────────
    t_view, t_add, t_bulk = st.tabs(
        ["📋 View Catalog", "➕ Add Carpets", "📂 Bulk Import"]
    )

    with t_view:
        tab_view(db_path, config, section_id, type_id, label)

    with t_add:
        tab_add(db_path, config, section_id, type_id, label, n_colors)

    with t_bulk:
        tab_bulk(db_path, config, section_id, type_id, label, n_colors)
