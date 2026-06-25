import streamlit as st
import importlib.util
import json
import os
import sys
from pathlib import Path

# ── Project root on sys.path ──────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.catalog import (
    get_sections, get_types, has_types,
    full_label, default_selection, ensure_folders,
    get_all_image_folders,
)


# ── Page loader ───────────────────────────────────────────────────────────────
def load_page(filename: str):
    path = os.path.join(ROOT, "ui", filename)
    spec = importlib.util.spec_from_file_location(filename[:-3], path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Load & resolve config ─────────────────────────────────────────────────────
with open(os.path.join(ROOT, "config.json"), "r") as f:
    config = json.load(f)

config["database"]["db_path"] = os.path.join(ROOT, config["database"]["db_path"])
for section in config["catalog"]["sections"]:
    section["folder"] = os.path.join(ROOT, section["folder"])
    for t in section.get("types", []):
        t["folder"] = os.path.join(ROOT, t["folder"])

ensure_folders(config)


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title=config["app"]["name"],
    page_icon="🪑",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Sidebar — navigation ──────────────────────────────────────────────────────
st.sidebar.title("Carpet Match AI")
st.sidebar.caption(f"v{config['app']['version']}")
st.sidebar.divider()

# Navigation labels — no emoji (prevents garbled characters on some systems)
NAV_OPTIONS = ["Home", "Color Extractor", "Match Carpets", "Manage Database"]

page = st.sidebar.radio(
    "Navigation",
    NAV_OPTIONS,
    key="nav_page",               # key-based: single click always works
)

st.sidebar.divider()


# ── Sidebar — catalog selector ────────────────────────────────────────────────
st.sidebar.markdown("**Catalog**")
st.sidebar.caption("Choose what to compare with the room photo.")

sections     = get_sections(config)
section_ids  = [s["id"]    for s in sections]
section_lbls = [s["label"] for s in sections]   # plain labels — no emoji

# ── Fix: key-based radio — no index= — eliminates the double-click bug ────────
#
# Root cause of double-click:
#   Using index=computed_value forces Streamlit to reset the widget value on
#   every rerun. When the user clicks once, the new value is read, session
#   state is updated, and a rerun fires — but that rerun recalculates the
#   same index and resets the widget, requiring a second click to "confirm".
#
# Fix: pass key= and let Streamlit own the widget state entirely.
#   st.session_state[key] holds the current label string automatically.
#   We only set it manually when we need to force a reset (e.g. section change).
# ─────────────────────────────────────────────────────────────────────────────

# Initialise section key on very first load
if "sidebar_section" not in st.session_state:
    st.session_state["sidebar_section"] = section_lbls[0]
# Guard: reset if stored value is no longer valid (e.g. config changed)
if st.session_state["sidebar_section"] not in section_lbls:
    st.session_state["sidebar_section"] = section_lbls[0]

# Section radio — single click, no index
chosen_section_lbl = st.sidebar.radio(
    "Section",
    section_lbls,
    key="sidebar_section",
    label_visibility="collapsed",
)
chosen_section_id = section_ids[section_lbls.index(chosen_section_lbl)]

# Detect section change → reset type + clear stale state
prev_section = st.session_state.get("selected_section")
if prev_section is not None and chosen_section_id != prev_section:
    types = get_types(config, chosen_section_id)
    # Force type radio to first option of new section
    if types:
        st.session_state["sidebar_type"] = types[0]["label"]
    # Clear page-level state that belongs to the old section
    st.session_state.pop("editing_id",     None)
    st.session_state.pop("confirm_delete", None)
    st.session_state.pop("match_output",   None)

st.session_state.selected_section = chosen_section_id


# ── Type radio (Carpets only — Rolls has no sub-types) ───────────────────────
chosen_type_id = None

if has_types(config, chosen_section_id):
    types     = get_types(config, chosen_section_id)
    type_ids  = [t["id"]    for t in types]
    type_lbls = [t["label"] for t in types]

    # Initialise / validate type key
    if ("sidebar_type" not in st.session_state or
            st.session_state["sidebar_type"] not in type_lbls):
        st.session_state["sidebar_type"] = type_lbls[0]

    prev_type = st.session_state.get("selected_type")

    # Type radio — single click, no index
    chosen_type_lbl = st.sidebar.radio(
        "Type",
        type_lbls,
        key="sidebar_type",
    )
    chosen_type_id = type_ids[type_lbls.index(chosen_type_lbl)]

    # Detect type change → clear stale state
    if prev_type is not None and chosen_type_id != prev_type:
        st.session_state.pop("editing_id",     None)
        st.session_state.pop("confirm_delete", None)
        st.session_state.pop("match_output",   None)

st.session_state.selected_type = chosen_type_id


# ── Active selection badge (plain text — no emoji) ────────────────────────────
active_label = full_label(config, chosen_section_id, chosen_type_id)

st.sidebar.markdown(
    f"<div style='"
    f"background:rgba(99,153,34,.12);"
    f"border:1px solid rgba(99,153,34,.35);"
    f"border-radius:6px;padding:6px 10px;"
    f"font-size:13px;margin-top:6px;"
    f"'><b>{active_label}</b></div>",
    unsafe_allow_html=True,
)


# ── Setup check (Home page helper) ────────────────────────────────────────────
def run_checks() -> dict[str, bool]:
    results = {}
    for display, module in {
        "Pillow":       "PIL",
        "ColorThief":   "colorthief",
        "scikit-learn": "sklearn",
        "scikit-image": "skimage",
        "NumPy":        "numpy",
        "fpdf2":        "fpdf",
    }.items():
        try:
            __import__(module)
            results[display] = True
        except ImportError:
            results[display] = False

    for folder in get_all_image_folders(config):
        results[f"Folder: {folder.name}"] = folder.exists()

    results["config.json"] = Path(os.path.join(ROOT, "config.json")).exists()
    return results


# ── Pages ─────────────────────────────────────────────────────────────────────
if page == "Home":
    st.title("Welcome to Carpet Match AI")
    st.caption("All 5 phases complete — agent is fully operational")
    st.divider()

    checks = run_checks()
    all_ok = all(checks.values())
    items  = list(checks.items())
    mid    = len(items) // 2

    col_a, col_b = st.columns(2)
    with col_a:
        for n, ok in items[:mid]:
            st.write(f"{'OK' if ok else 'MISSING'}  {n}")
    with col_b:
        for n, ok in items[mid:]:
            st.write(f"{'OK' if ok else 'MISSING'}  {n}")

    st.divider()
    if all_ok:
        st.success(
            "Everything is ready. "
            "Add carpet images in **Manage Database**, "
            "then use **Match Carpets** to find the best match for a room."
        )
    else:
        st.error("Some checks failed — run setup.bat to reinstall libraries.")

    st.subheader("Catalog folders")
    for section in get_sections(config):
        types = section.get("types", [])
        if types:
            st.markdown(f"**{section['label']}**")
            for t in types:
                folder = Path(t["folder"])
                imgs   = len(
                    list(folder.glob("*.jpg")) +
                    list(folder.glob("*.jpeg")) +
                    list(folder.glob("*.png"))
                ) if folder.exists() else 0
                exists = "OK" if folder.exists() else "MISSING"
                st.write(f"  {exists}  {t['label']} — {imgs} image(s)")
        else:
            folder = Path(section["folder"])
            imgs   = len(
                list(folder.glob("*.jpg")) +
                list(folder.glob("*.jpeg")) +
                list(folder.glob("*.png"))
            ) if folder.exists() else 0
            exists = "OK" if folder.exists() else "MISSING"
            st.write(f"{exists}  {section['label']} — {imgs} image(s)")

    with st.expander("View config.json"):
        st.json(config)

elif page == "Color Extractor":
    load_page("color_test.py").render(config)

elif page == "Match Carpets":
    load_page("match_carpets.py").render(config)

elif page == "Manage Database":
    load_page("database_manager.py").render(config)
