"""SQLite-backed alias & category storage with O(1) memory cache and non-destructive migration."""

from __future__ import annotations

from pathlib import Path
import json
import os
import sqlite3
import threading
import time
from typing import Iterable

from .config import DEFAULT_DATA_DIR
from .file_id import get_file_identity, resolve_path_by_identity
from .models import (
    DEFAULT_CATEGORY,
    AliasEntry,
    normalize_category,
    normalize_key,
    normalize_path,
)


PRESET_COLORS = [
    ("#0F6CBD", "静谧蓝"),
    ("#64748B", "岩石灰"),
    ("#059669", "青松绿"),
    ("#B45309", "暖琥珀"),
    ("#6D28D9", "暮光紫"),
]


class AliasStore:
    """Persistent SQLite store + synchronized memory index for zero-latency UI/inline queries."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self.db_path = db_path or (DEFAULT_DATA_DIR / "aliases.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._by_key: dict[str, AliasEntry] = {}
        self._by_parent: dict[str, dict[str, AliasEntry]] = {}
        self._categories: list[str] = [DEFAULT_CATEGORY]
        self._last_reconcile_ts: float = 0.0
        self._init_schema()
        self._reload_cache()
        self._backfill_missing_identities()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS aliases (
                    path_key      TEXT PRIMARY KEY,
                    path          TEXT NOT NULL,
                    alias         TEXT NOT NULL,
                    note          TEXT NOT NULL DEFAULT '',
                    category      TEXT NOT NULL DEFAULT '{DEFAULT_CATEGORY}',
                    tags_json     TEXT NOT NULL DEFAULT '[]',
                    color         TEXT NOT NULL DEFAULT '#0F6CBD',
                    is_dir        INTEGER NOT NULL DEFAULT 0,
                    pinned        INTEGER NOT NULL DEFAULT 0,
                    volume_serial INTEGER NOT NULL DEFAULT 0,
                    file_id       TEXT NOT NULL DEFAULT '0',
                    created_at    REAL NOT NULL,
                    updated_at    REAL NOT NULL
                );
                """
            )
            # Non-destructive schema migrations for existing databases
            cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(aliases);").fetchall()
            }
            if "category" not in cols:
                self._conn.execute(
                    f"ALTER TABLE aliases ADD COLUMN category TEXT NOT NULL DEFAULT '{DEFAULT_CATEGORY}';"
                )
            if "volume_serial" not in cols:
                self._conn.execute(
                    "ALTER TABLE aliases ADD COLUMN volume_serial INTEGER NOT NULL DEFAULT 0;"
                )
            if "file_id" not in cols:
                # Stored as TEXT so unsigned 64-bit IDs > 2^63-1 never overflow SQLite signed INT64
                self._conn.execute(
                    "ALTER TABLE aliases ADD COLUMN file_id TEXT NOT NULL DEFAULT '0';"
                )

            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    name        TEXT PRIMARY KEY,
                    created_at  REAL NOT NULL
                );
                """
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO categories (name, created_at) VALUES (?, ?);",
                (DEFAULT_CATEGORY, 0.0),
            )
            self._conn.commit()

    def _row_to_entry(self, row: sqlite3.Row) -> AliasEntry:
        try:
            tags = json.loads(row["tags_json"]) if row["tags_json"] else []
            if not isinstance(tags, list):
                tags = []
        except Exception:
            tags = []
        raw_cat = row["category"] if "category" in row.keys() else DEFAULT_CATEGORY
        vol_ser = int(row["volume_serial"] or 0) if "volume_serial" in row.keys() else 0
        try:
            fid = int(row["file_id"] or 0) if "file_id" in row.keys() else 0
        except Exception:
            fid = 0
        return AliasEntry(
            path=row["path"],
            path_key=row["path_key"],
            alias=row["alias"],
            note=row["note"] or "",
            category=normalize_category(raw_cat),
            tags=[str(t).strip() for t in tags if str(t).strip()],
            color=row["color"] or "#0F6CBD",
            is_dir=bool(row["is_dir"]),
            pinned=bool(row["pinned"]),
            volume_serial=vol_ser,
            file_id=fid,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def _reload_cache(self) -> None:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM aliases").fetchall()
            by_key: dict[str, AliasEntry] = {}
            by_parent: dict[str, dict[str, AliasEntry]] = {}
            used_cats: set[str] = set()

            for row in rows:
                entry = self._row_to_entry(row)
                by_key[entry.path_key] = entry
                used_cats.add(entry.category)
                pk = entry.parent_key
                if pk:
                    by_parent.setdefault(pk, {})[entry.path_key] = entry

            cat_rows = self._conn.execute(
                "SELECT name FROM categories ORDER BY created_at ASC, name ASC"
            ).fetchall()
            ordered_cats = [DEFAULT_CATEGORY]
            seen = {DEFAULT_CATEGORY}
            for r in cat_rows:
                nm = normalize_category(r["name"])
                if nm not in seen:
                    seen.add(nm)
                    ordered_cats.append(nm)
            for c in sorted(used_cats):
                if c not in seen:
                    seen.add(c)
                    ordered_cats.append(c)
                    self._conn.execute(
                        "INSERT OR IGNORE INTO categories (name, created_at) VALUES (?, ?);",
                        (c, time.time()),
                    )
            self._conn.commit()

            self._by_key = by_key
            self._by_parent = by_parent
            self._categories = ordered_cats

    def _index_put(self, entry: AliasEntry) -> None:
        old = self._by_key.get(entry.path_key)
        if old and old.parent_key in self._by_parent:
            self._by_parent[old.parent_key].pop(old.path_key, None)
        self._by_key[entry.path_key] = entry
        if entry.parent_key:
            self._by_parent.setdefault(entry.parent_key, {})[entry.path_key] = entry
        if entry.category not in self._categories:
            self._categories.append(entry.category)

    def _index_remove(self, path_key: str) -> bool:
        old = self._by_key.pop(path_key, None)
        if not old:
            return False
        if old.parent_key in self._by_parent:
            self._by_parent[old.parent_key].pop(path_key, None)
            if not self._by_parent[old.parent_key]:
                self._by_parent.pop(old.parent_key, None)
        return True

    def _backfill_missing_identities(self) -> None:
        """Populate NTFS (volume_serial, file_id) for legacy records that already exist on disk."""
        with self._lock:
            updated = False
            for entry in list(self._by_key.values()):
                if (entry.volume_serial == 0 or entry.file_id == 0) and os.path.exists(entry.path):
                    ident = get_file_identity(entry.path)
                    if ident:
                        vol_ser, fid = ident
                        entry.volume_serial = vol_ser
                        entry.file_id = fid
                        self._conn.execute(
                            "UPDATE aliases SET volume_serial = ?, file_id = ? WHERE path_key = ?;",
                            (vol_ser, str(fid), entry.path_key),
                        )
                        updated = True
            if updated:
                self._conn.commit()

    def reconcile_moved_files(self, force: bool = False) -> int:
        """
        Automatically detect renamed or moved files/folders via NTFS FileId (`OpenFileById`)
        and update their paths in SQLite + memory index seamlessly.
        """
        now = time.monotonic()
        if not force and (now - self._last_reconcile_ts) < 0.65:
            return 0
        self._last_reconcile_ts = now

        with self._lock:
            missing = [
                e for e in self._by_key.values()
                if e.volume_serial and e.file_id and not os.path.exists(e.path)
            ]

        if not missing:
            return 0

        # Process parent folders before nested children so folder rename cascades cleanly
        missing.sort(key=lambda e: len(e.path))
        total_healed = 0

        for entry in missing:
            # Re-check in case an earlier parent-folder cascade already updated this child!
            cur = self.get(entry.path)
            if cur is None or os.path.exists(cur.path):
                continue
            resolved = resolve_path_by_identity(
                cur.volume_serial,
                cur.file_id,
                hint_path=cur.path,
            )
            if resolved and normalize_key(resolved) != cur.path_key:
                # Don't overwrite a distinct existing alias at target unless none exists
                if self.get(resolved) is None:
                    total_healed += self.relocate_path(cur.path, resolved)

        return total_healed

    # ---- Category Management ----

    def list_categories(self) -> list[str]:
        """Return ordered category names, always starting with '默认分类'."""
        with self._lock:
            return list(self._categories)

    def category_counts(self) -> dict[str, int]:
        """Return {category_name: item_count} for all categories."""
        with self._lock:
            counts = {c: 0 for c in self._categories}
            for e in self._by_key.values():
                counts[e.category] = counts.get(e.category, 0) + 1
            return counts

    def add_category(self, name: str) -> str:
        """Create a new category (no-op if it already exists) and return normalized name."""
        clean = normalize_category(name)
        with self._lock:
            if clean not in self._categories:
                self._conn.execute(
                    "INSERT OR IGNORE INTO categories (name, created_at) VALUES (?, ?);",
                    (clean, time.time()),
                )
                self._conn.commit()
                self._categories.append(clean)
        return clean

    def rename_category(self, old_name: str, new_name: str) -> int:
        """Rename a custom category and move all its entries to `new_name`."""
        old_c = normalize_category(old_name)
        new_c = normalize_category(new_name)
        if old_c == DEFAULT_CATEGORY:
            raise ValueError("默认分类不可重命名")
        if old_c == new_c:
            return 0

        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO categories (name, created_at) VALUES (?, ?);",
                (new_c, time.time()),
            )
            cur = self._conn.execute(
                "UPDATE aliases SET category = ?, updated_at = ? WHERE category = ?;",
                (new_c, time.time(), old_c),
            )
            self._conn.execute("DELETE FROM categories WHERE name = ?;", (old_c,))
            self._conn.commit()
            self._reload_cache()
            return cur.rowcount

    def delete_category(self, name: str) -> int:
        """Delete a custom category and reassign its entries safely back to '默认分类'."""
        target = normalize_category(name)
        if target == DEFAULT_CATEGORY:
            raise ValueError("默认分类不可删除")

        with self._lock:
            cur = self._conn.execute(
                "UPDATE aliases SET category = ?, updated_at = ? WHERE category = ?;",
                (DEFAULT_CATEGORY, time.time(), target),
            )
            self._conn.execute("DELETE FROM categories WHERE name = ?;", (target,))
            self._conn.commit()
            self._reload_cache()
            return cur.rowcount

    # ---- Alias Entry CRUD ----

    def upsert(
        self,
        raw_path: str | Path,
        alias: str,
        note: str = "",
        category: str | None = None,
        tags: Iterable[str] | None = None,
        color: str = "#0F6CBD",
        pinned: bool = False,
        is_dir: bool | None = None,
    ) -> AliasEntry:
        """Create or update an alias entry. Unspecified/empty category defaults to '默认分类'."""
        norm_path = normalize_path(raw_path)
        key = normalize_key(norm_path)
        if not key:
            raise ValueError("路径不能为空")
        clean_alias = alias.strip()
        if not clean_alias:
            raise ValueError("别名不能为空")

        now = time.time()
        clean_tags = []
        if tags:
            seen = set()
            for t in tags:
                s = str(t).strip().lstrip("#")
                if s and s.lower() not in seen:
                    seen.add(s.lower())
                    clean_tags.append(s)

        with self._lock:
            existing = self._by_key.get(key)
            created_at = existing.created_at if existing else now
            if category is None and existing is not None:
                clean_cat = existing.category
            else:
                clean_cat = normalize_category(category)

            if is_dir is None:
                if os.path.exists(norm_path):
                    actual_is_dir = os.path.isdir(norm_path)
                elif existing is not None:
                    actual_is_dir = existing.is_dir
                else:
                    actual_is_dir = False
            else:
                actual_is_dir = bool(is_dir)

            self._conn.execute(
                "INSERT OR IGNORE INTO categories (name, created_at) VALUES (?, ?);",
                (clean_cat, now),
            )

            ident = get_file_identity(norm_path)
            if ident is not None:
                vol_ser, fid = ident
            elif existing is not None:
                vol_ser, fid = existing.volume_serial, existing.file_id
            else:
                vol_ser, fid = 0, 0

            entry = AliasEntry(
                path=norm_path,
                path_key=key,
                alias=clean_alias,
                note=note.strip(),
                category=clean_cat,
                tags=clean_tags,
                color=color or "#0F6CBD",
                is_dir=actual_is_dir,
                pinned=bool(pinned),
                volume_serial=vol_ser,
                file_id=fid,
                created_at=created_at,
                updated_at=now,
            )
            self._conn.execute(
                """
                INSERT INTO aliases
                (path_key, path, alias, note, category, tags_json, color, is_dir, pinned, volume_serial, file_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path_key) DO UPDATE SET
                    path = excluded.path,
                    alias = excluded.alias,
                    note = excluded.note,
                    category = excluded.category,
                    tags_json = excluded.tags_json,
                    color = excluded.color,
                    is_dir = excluded.is_dir,
                    pinned = excluded.pinned,
                    volume_serial = excluded.volume_serial,
                    file_id = excluded.file_id,
                    updated_at = excluded.updated_at;
                """,
                (
                    entry.path_key,
                    entry.path,
                    entry.alias,
                    entry.note,
                    entry.category,
                    json.dumps(entry.tags, ensure_ascii=False),
                    entry.color,
                    int(entry.is_dir),
                    int(entry.pinned),
                    entry.volume_serial,
                    str(entry.file_id),
                    entry.created_at,
                    entry.updated_at,
                ),
            )
            self._conn.commit()
            self._index_put(entry)
            return entry

    def delete(self, raw_path: str | Path) -> bool:
        key = normalize_key(raw_path)
        if not key:
            return False
        with self._lock:
            cur = self._conn.execute("DELETE FROM aliases WHERE path_key = ?", (key,))
            self._conn.commit()
            self._index_remove(key)
            return cur.rowcount > 0

    def get(self, raw_path: str | Path) -> AliasEntry | None:
        key = normalize_key(raw_path)
        if not key:
            return None
        with self._lock:
            return self._by_key.get(key)

    def resolve_item_in_dir(self, dir_path: str | Path, item_name: str) -> AliasEntry | None:
        clean_name = item_name.strip()
        if not clean_name or not dir_path:
            return None
        norm_dir = normalize_path(dir_path)
        if not norm_dir:
            return None

        candidate = os.path.join(norm_dir, clean_name)
        exact = self.get(candidate)
        if exact is not None:
            return exact

        dir_key = normalize_key(norm_dir)
        target_lower = clean_name.lower()
        with self._lock:
            children = self._by_parent.get(dir_key)
            if not children:
                return None
            matches = [
                e for e in children.values()
                if not e.is_dir and Path(e.name).stem.lower() == target_lower
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                existing = [m for m in matches if m.exists]
                pool = existing or matches
                pool.sort(key=lambda x: x.updated_at, reverse=True)
                return pool[0]
        return None

    def list_in_dir(self, dir_path: str | Path) -> list[AliasEntry]:
        dir_key = normalize_key(dir_path)
        if not dir_key:
            return []
        with self._lock:
            children = list(self._by_parent.get(dir_key, {}).values())
        children.sort(key=lambda e: (not e.pinned, not e.is_dir, e.name.lower()))
        return children

    def list_all(self) -> list[AliasEntry]:
        with self._lock:
            items = list(self._by_key.values())
        items.sort(key=lambda e: (not e.pinned, -e.updated_at))
        return items

    def all_tags(self) -> list[str]:
        with self._lock:
            tag_set: dict[str, str] = {}
            for entry in self._by_key.values():
                for t in entry.tags:
                    if t.lower() not in tag_set:
                        tag_set[t.lower()] = t
        return sorted(tag_set.values(), key=str.lower)

    def count(self) -> int:
        with self._lock:
            return len(self._by_key)

    def search(
        self,
        query: str = "",
        category_filter: str = "",
        tag_filter: str = "",
        only_dirs: bool = False,
        only_broken: bool = False,
    ) -> list[AliasEntry]:
        """Multi-keyword ranked search across alias, basename, category, note, tags, and path."""
        tokens = [t.lower() for t in query.strip().split() if t.strip()]
        cat_q = category_filter.strip()
        tag_q = tag_filter.strip().lstrip("#").lower()

        with self._lock:
            candidates = list(self._by_key.values())

        results: list[tuple[int, float, AliasEntry]] = []
        for entry in candidates:
            if cat_q and entry.category != cat_q:
                continue
            if only_dirs and not entry.is_dir:
                continue
            if only_broken and entry.exists:
                continue
            if tag_q and not any(t.lower() == tag_q for t in entry.tags):
                continue

            if not tokens:
                score = 100 if entry.pinned else 50
                results.append((score, entry.updated_at, entry))
                continue

            alias_l = entry.alias.lower()
            name_l = entry.name.lower()
            cat_l = entry.category.lower()
            note_l = entry.note.lower()
            tags_l = " ".join(entry.tags).lower()
            path_l = entry.path_key
            haystack = f"{alias_l} {name_l} {cat_l} {note_l} {tags_l} {path_l}"

            if not all(tok in haystack for tok in tokens):
                continue

            score = 0
            if entry.pinned:
                score += 30
            first = tokens[0]
            if alias_l == first:
                score += 120
            elif alias_l.startswith(first):
                score += 90
            elif first in alias_l:
                score += 70
            if name_l.startswith(first):
                score += 60
            elif first in name_l:
                score += 45
            if first in cat_l:
                score += 42
            if first in tags_l:
                score += 40
            if first in note_l:
                score += 25
            results.append((score, entry.updated_at, entry))

        results.sort(key=lambda item: (-item[0], -item[1]))
        return [item[2] for item in results]

    def relocate_path(self, old_raw_path: str | Path, new_raw_path: str | Path) -> int:
        old_norm = normalize_path(old_raw_path)
        old_key = normalize_key(old_norm)
        new_norm = normalize_path(new_raw_path)
        new_key = normalize_key(new_norm)
        if not old_key or not new_key or old_key == new_key:
            return 0

        now = time.time()
        prefix = old_key.rstrip("\\") + "\\"
        updated_count = 0

        with self._lock:
            to_move: list[tuple[AliasEntry, str]] = []
            for key, entry in list(self._by_key.items()):
                if key == old_key:
                    to_move.append((entry, new_norm))
                elif key.startswith(prefix):
                    rel_suffix = entry.path[len(old_norm.rstrip("\\")) + 1:]
                    target_child = os.path.join(new_norm, rel_suffix)
                    to_move.append((entry, normalize_path(target_child)))

            for entry, target_path in to_move:
                target_key = normalize_key(target_path)
                self._conn.execute("DELETE FROM aliases WHERE path_key = ?", (entry.path_key,))
                is_dir_val = os.path.isdir(target_path) if os.path.exists(target_path) else entry.is_dir
                ident = get_file_identity(target_path)
                vol_ser, fid = ident if ident else (entry.volume_serial, entry.file_id)
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO aliases
                    (path_key, path, alias, note, category, tags_json, color, is_dir, pinned, volume_serial, file_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        target_key,
                        target_path,
                        entry.alias,
                        entry.note,
                        entry.category,
                        json.dumps(entry.tags, ensure_ascii=False),
                        entry.color,
                        int(is_dir_val),
                        int(entry.pinned),
                        vol_ser,
                        str(fid),
                        entry.created_at,
                        now,
                    ),
                )
                updated_count += 1

            if updated_count:
                self._conn.commit()
                self._reload_cache()
        return updated_count

    def export_json(self, target_file: str | Path) -> int:
        entries = self.list_all()
        payload = {
            "app": "FileAlias",
            "version": 2,
            "exported_at": time.time(),
            "categories": self.list_categories(),
            "entries": [
                {
                    "path": e.path,
                    "alias": e.alias,
                    "note": e.note,
                    "category": e.category,
                    "tags": e.tags,
                    "color": e.color,
                    "is_dir": e.is_dir,
                    "pinned": e.pinned,
                    "created_at": e.created_at,
                    "updated_at": e.updated_at,
                }
                for e in entries
            ],
        }
        Path(target_file).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return len(entries)

    def import_json(self, source_file: str | Path, overwrite: bool = True) -> int:
        raw = json.loads(Path(source_file).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for c in raw.get("categories", []):
                if c:
                    self.add_category(str(c))
            items = raw.get("entries", [])
        else:
            items = raw if isinstance(raw, list) else []

        imported = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            p = item.get("path", "")
            a = item.get("alias", "")
            if not p or not a:
                continue
            if not overwrite and self.get(p) is not None:
                continue
            self.upsert(
                raw_path=p,
                alias=a,
                note=item.get("note", ""),
                category=item.get("category", DEFAULT_CATEGORY),
                tags=item.get("tags", []),
                color=item.get("color", "#0F6CBD"),
                pinned=bool(item.get("pinned", False)),
                is_dir=item.get("is_dir"),
            )
            imported += 1
        return imported

    def close(self) -> None:
        with self._lock:
            self._conn.close()
