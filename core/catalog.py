"""
core/catalog.py — Catalog structure helpers
============================================
Single source of truth for navigating sections and types.
All other modules import from here instead of reading config directly.

Catalog layout
--------------
Section: Carpets  →  Types: Modern | Classic | New Classic
Section: Rolls    →  (no sub-types, images go directly in the rolls folder)

Folder layout
-------------
database/
├── carpets/
│   ├── modern/
│   ├── classic/
│   └── new_classic/
└── rolls/
"""

from __future__ import annotations
from pathlib import Path


# ── Section / type accessors ──────────────────────────────────────────────────

def get_sections(config: dict) -> list[dict]:
    """Return all top-level sections from config."""
    return config["catalog"]["sections"]


def get_section(config: dict, section_id: str) -> dict | None:
    """Return a single section dict by its id, or None if not found."""
    for s in get_sections(config):
        if s["id"] == section_id:
            return s
    return None


def get_types(config: dict, section_id: str) -> list[dict]:
    """
    Return the list of type dicts for a section.
    Returns an empty list for sections that have no sub-types (e.g. Rolls).
    """
    section = get_section(config, section_id)
    return section.get("types", []) if section else []


def has_types(config: dict, section_id: str) -> bool:
    """Return True if a section has sub-types (e.g. Carpets), False otherwise."""
    return len(get_types(config, section_id)) > 0


def get_type(config: dict, section_id: str, type_id: str) -> dict | None:
    """Return a single type dict, or None if not found."""
    for t in get_types(config, section_id):
        if t["id"] == type_id:
            return t
    return None


# ── Folder resolution ─────────────────────────────────────────────────────────

def get_folder(config: dict, section_id: str, type_id: str | None = None) -> Path:
    """
    Resolve the image folder for a section (and optionally a type).

    Examples
    --------
    get_folder(cfg, "carpets", "modern")  → Path("database/carpets/modern")
    get_folder(cfg, "carpets")            → Path("database/carpets")
    get_folder(cfg, "rolls")              → Path("database/rolls")
    """
    if type_id:
        t = get_type(config, section_id, type_id)
        if t:
            return Path(t["folder"])

    section = get_section(config, section_id)
    if section:
        return Path(section["folder"])

    raise ValueError(f"Unknown section '{section_id}' or type '{type_id}'")


def get_images_folder(config: dict, section_id: str, type_id: str | None = None) -> Path:
    """
    Return the correct images folder for the given selection.
    For sections without types (Rolls), section_id alone is enough.
    For sections with types (Carpets), type_id must be provided.
    """
    if has_types(config, section_id) and not type_id:
        raise ValueError(
            f"Section '{section_id}' has sub-types. "
            "Please specify a type_id (e.g. 'modern')."
        )
    return get_folder(config, section_id, type_id)


def get_all_image_folders(config: dict) -> list[Path]:
    """
    Return every leaf folder where images can be stored.
    Used by setup scripts to ensure all folders exist.
    """
    folders = []
    for section in get_sections(config):
        if section.get("types"):
            for t in section["types"]:
                folders.append(Path(t["folder"]))
        else:
            folders.append(Path(section["folder"]))
    return folders


# ── Folder management ─────────────────────────────────────────────────────────

def ensure_folders(config: dict) -> None:
    """
    Create all catalog folders if they do not already exist.
    Safe to call multiple times — will not overwrite existing folders.
    """
    for folder in get_all_image_folders(config):
        folder.mkdir(parents=True, exist_ok=True)


def folder_exists(config: dict, section_id: str, type_id: str | None = None) -> bool:
    """Return True if the images folder for a selection exists on disk."""
    try:
        return get_folder(config, section_id, type_id).exists()
    except ValueError:
        return False


# ── Label helpers (for UI display) ───────────────────────────────────────────

def section_label(config: dict, section_id: str) -> str:
    """Return the display label for a section (e.g. 'Carpets')."""
    s = get_section(config, section_id)
    return s["label"] if s else section_id


def type_label(config: dict, section_id: str, type_id: str) -> str:
    """Return the display label for a type (e.g. 'New Classic')."""
    t = get_type(config, section_id, type_id)
    return t["label"] if t else type_id


def full_label(config: dict, section_id: str, type_id: str | None = None) -> str:
    """
    Return a combined display label for the current selection.

    Examples
    --------
    full_label(cfg, "carpets", "modern")   → "Carpets › Modern"
    full_label(cfg, "rolls")               → "Rolls"
    """
    base = section_label(config, section_id)
    if type_id:
        return f"{base} › {type_label(config, section_id, type_id)}"
    return base


# ── Selection state helpers ───────────────────────────────────────────────────

def default_selection(config: dict) -> tuple[str, str | None]:
    """
    Return (section_id, type_id) for the first available section/type.
    Used to initialise session state on first load.
    """
    sections = get_sections(config)
    if not sections:
        return ("", None)

    first = sections[0]
    types = first.get("types", [])
    type_id = types[0]["id"] if types else None
    return (first["id"], type_id)
