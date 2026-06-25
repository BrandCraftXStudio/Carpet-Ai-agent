"""
core/db_manager.py — Phase 3: SQLite carpet database manager
=============================================================
Handles all read/write operations for the carpet catalog.

Database schema
---------------
One table — carpets — stores every image record across all sections
and types.  Section ("carpets" / "rolls") and type ("modern" / "classic" /
"new_classic" / NULL) work as filters so the same DB file covers the entire
catalog.

Responsibilities
----------------
- init_db          : create the DB and table on first run
- add_carpet       : copy image → catalog folder, extract palette, insert row
- bulk_import      : process every image in a folder
- get_all_carpets  : list records for a section/type (with optional search)
- get_carpet       : fetch one record by ID
- update_carpet    : edit name / price / notes
- delete_carpet    : remove DB row and optionally the image file
- catalog_stats    : image counts per section / type (for the stats bar)
- reprocess_palette: re-extract colors (use when color engine is updated)
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.color_extractor import analyze_image, palette_to_json
from core.catalog import get_folder


# ── Database connection ───────────────────────────────────────────────────────

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safer for concurrent access
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS carpets (
    id              INTEGER  PRIMARY KEY AUTOINCREMENT,
    name            TEXT     NOT NULL,
    section         TEXT     NOT NULL,
    type            TEXT,
    image_path      TEXT     NOT NULL UNIQUE,
    palette         TEXT     NOT NULL,
    temperature     TEXT     NOT NULL,
    color_families  TEXT     NOT NULL,
    price           TEXT     DEFAULT '',
    notes           TEXT     DEFAULT '',
    added_at        TEXT     NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_section_type ON carpets (section, type);
"""


def init_db(db_path: str) -> None:
    """
    Create the SQLite database file and tables if they do not exist yet.
    Safe to call every startup — it is a no-op when the DB is already set up.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _save_image(source, dest_folder: Path) -> Path:
    """
    Copy an image to dest_folder and return its destination Path.

    source can be:
      - a Streamlit UploadedFile  (has .name and .read())
      - a file path string or Path object
    """
    dest_folder.mkdir(parents=True, exist_ok=True)

    if hasattr(source, "read"):                    # Streamlit UploadedFile
        filename = Path(source.name).name
        dest     = dest_folder / filename
        source.seek(0)
        dest.write_bytes(source.read())

    else:                                          # regular file path
        src  = Path(source)
        dest = dest_folder / src.name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)

    return dest


def _deserialize(row: dict) -> dict:
    """Convert JSON strings back to Python objects for a carpet row."""
    row["palette"] = json.loads(row["palette"])
    row["color_families"] = json.loads(row["color_families"])
    for item in row["palette"]:
        item["rgb"] = tuple(item["rgb"])
    return row


# ── Add / Import ──────────────────────────────────────────────────────────────

def add_carpet(
    db_path:    str,
    config:     dict,
    source,                             # UploadedFile or file path
    section_id: str,
    type_id:    Optional[str],
    name:       str = "",
    price:      str = "",
    notes:      str = "",
    n_colors:   int = 6,
) -> dict:
    """
    Add one carpet to the catalog.

    Steps
    -----
    1. Copy / save the image file to the correct catalog folder.
    2. Auto-generate a name from the filename if none is given.
    3. Extract the dominant color palette (KMeans + Delta-E pipeline).
    4. Insert a new row into the DB.

    Returns the new record as a plain dict.
    Raises ValueError if the image path already exists in the DB.
    """
    dest_folder = get_folder(config, section_id, type_id)
    dest        = _save_image(source, dest_folder)

    if not name:
        name = dest.stem.replace("_", " ").replace("-", " ").title()

    analysis = analyze_image(str(dest), n_colors)

    try:
        with _connect(db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO carpets
                    (name, section, type, image_path, palette,
                     temperature, color_families, price, notes, added_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    name, section_id, type_id, str(dest),
                    palette_to_json(analysis["palette"]),
                    analysis["temperature"],
                    json.dumps(analysis["color_families"]),
                    price.strip(), notes.strip(),
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM carpets WHERE id=?", (cur.lastrowid,)
            ).fetchone()

        return _deserialize(dict(row))

    except sqlite3.IntegrityError:
        raise ValueError(f"'{dest.name}' is already in the database.")


def bulk_import(
    db_path:     str,
    config:      dict,
    folder:      str,
    section_id:  str,
    type_id:     Optional[str],
    n_colors:    int = 6,
    progress_cb  = None,        # callable(current: int, total: int, filename: str)
) -> tuple[int, int]:
    """
    Import every JPEG / PNG / WebP image from a folder into the catalog.

    Returns (added_count, skipped_count).
    progress_cb is called after each file so the UI can update a progress bar.
    """
    exts   = ("*.jpg", "*.jpeg", "*.png", "*.webp")
    images = sorted(p for ext in exts for p in Path(folder).glob(ext))

    added = skipped = 0
    total = len(images)

    for i, img_path in enumerate(images):
        if progress_cb:
            progress_cb(i, total, img_path.name)
        try:
            add_carpet(db_path, config, img_path, section_id, type_id,
                       n_colors=n_colors)
            added += 1
        except (ValueError, Exception):
            skipped += 1

    if progress_cb:
        progress_cb(total, total, "done")

    return added, skipped


# ── Read ──────────────────────────────────────────────────────────────────────

def get_all_carpets(
    db_path:    str,
    section_id: str,
    type_id:    Optional[str] = None,
    search:     str = "",
) -> list[dict]:
    """
    Return all carpets for a section / type, newest first.
    Optional search string filters by name (case-insensitive).
    """
    with _connect(db_path) as conn:
        if type_id is not None:
            rows = conn.execute(
                "SELECT * FROM carpets WHERE section=? AND type=?"
                " ORDER BY added_at DESC",
                (section_id, type_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM carpets WHERE section=?"
                " ORDER BY added_at DESC",
                (section_id,),
            ).fetchall()

    carpets = [_deserialize(dict(r)) for r in rows]

    if search:
        q = search.lower()
        carpets = [c for c in carpets if q in c["name"].lower()]

    return carpets


def get_carpet(db_path: str, carpet_id: int) -> Optional[dict]:
    """Return a single carpet record by ID, or None if not found."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM carpets WHERE id=?", (carpet_id,)
        ).fetchone()
    return _deserialize(dict(row)) if row else None


def catalog_stats(db_path: str, config: dict) -> list[dict]:
    """
    Return image counts for every section / type in the config.
    Used by the UI stats bar.

    Returns
    -------
    [{"label": "Carpets › Modern", "section": "carpets",
      "type": "modern", "count": 12}, ...]
    """
    from core.catalog import get_sections, get_types, full_label

    stats = []
    with _connect(db_path) as conn:
        for section in get_sections(config):
            sid   = section["id"]
            types = get_types(config, sid)

            if types:
                for t in types:
                    cnt = conn.execute(
                        "SELECT COUNT(*) FROM carpets WHERE section=? AND type=?",
                        (sid, t["id"]),
                    ).fetchone()[0]
                    stats.append({
                        "label":   full_label(config, sid, t["id"]),
                        "section": sid,
                        "type":    t["id"],
                        "count":   cnt,
                    })
            else:
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM carpets WHERE section=?", (sid,)
                ).fetchone()[0]
                stats.append({
                    "label":   full_label(config, sid),
                    "section": sid,
                    "type":    None,
                    "count":   cnt,
                })

    return stats


# ── Update ────────────────────────────────────────────────────────────────────

def update_carpet(
    db_path:   str,
    carpet_id: int,
    name:      str,
    price:     str,
    notes:     str,
) -> None:
    """Update the editable metadata fields (name, price, notes) for a carpet."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE carpets SET name=?, price=?, notes=? WHERE id=?",
            (name.strip(), price.strip(), notes.strip(), carpet_id),
        )
        conn.commit()


def reprocess_palette(db_path: str, carpet_id: int, n_colors: int = 6) -> None:
    """
    Re-run color extraction for a single carpet.
    Useful after updating the color engine (Phase 2).
    """
    carpet = get_carpet(db_path, carpet_id)
    if not carpet or not Path(carpet["image_path"]).exists():
        return

    analysis = analyze_image(carpet["image_path"], n_colors)

    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE carpets
            SET palette=?, temperature=?, color_families=?
            WHERE id=?
            """,
            (
                palette_to_json(analysis["palette"]),
                analysis["temperature"],
                json.dumps(analysis["color_families"]),
                carpet_id,
            ),
        )
        conn.commit()


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_carpet(
    db_path:      str,
    carpet_id:    int,
    delete_image: bool = True,
) -> None:
    """
    Remove a carpet from the DB.
    If delete_image=True, also delete the image file from disk.
    """
    carpet = get_carpet(db_path, carpet_id)
    if not carpet:
        return

    with _connect(db_path) as conn:
        conn.execute("DELETE FROM carpets WHERE id=?", (carpet_id,))
        conn.commit()

    if delete_image:
        img = Path(carpet["image_path"])
        if img.exists():
            img.unlink(missing_ok=True)


# ── Sync ──────────────────────────────────────────────────────────────────────

def sync_all_folders(
    db_path:  str,
    config:   dict,
    n_colors: int = 6,
) -> list[dict]:
    """
    Scan every catalog image folder and import any images not yet in the DB.

    Works identically to Bulk Import but covers all sections and types
    in one pass — no folder path needed from the user.

    Returns a list of result dicts, one per folder:
    [
        {
            "label":   "Carpets > Modern",
            "folder":  "database/carpets/modern",
            "added":   5,
            "skipped": 12,
            "total":   17,
        },
        ...
    ]
    """
    from core.catalog import get_sections, get_types

    results = []

    for section in get_sections(config):
        sid   = section["id"]
        types = get_types(config, sid)

        if types:
            for t in types:
                folder = Path(t["folder"])
                label  = f"{section['label']} > {t['label']}"

                if not folder.exists():
                    results.append({
                        "label":   label,
                        "folder":  str(folder),
                        "added":   0,
                        "skipped": 0,
                        "total":   0,
                        "error":   "Folder not found on disk",
                    })
                    continue

                added, skipped = bulk_import(
                    db_path, config, str(folder),
                    sid, t["id"], n_colors=n_colors,
                )
                results.append({
                    "label":   label,
                    "folder":  str(folder),
                    "added":   added,
                    "skipped": skipped,
                    "total":   added + skipped,
                })

        else:
            folder = Path(section["folder"])
            label  = section["label"]

            if not folder.exists():
                results.append({
                    "label":   label,
                    "folder":  str(folder),
                    "added":   0,
                    "skipped": 0,
                    "total":   0,
                    "error":   "Folder not found on disk",
                })
                continue

            added, skipped = bulk_import(
                db_path, config, str(folder),
                sid, None, n_colors=n_colors,
            )
            results.append({
                "label":   label,
                "folder":  str(folder),
                "added":   added,
                "skipped": skipped,
                "total":   added + skipped,
            })

    return results
