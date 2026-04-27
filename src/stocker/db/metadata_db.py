"""SQLite metadata DB. One DB per managed folder, stored in <root>/.stocker/metadata.db."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from stocker.app_paths import db_path, ensure_stocker_layout
from stocker.core.models import FileItem

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


class MetadataDB:
    """Thin wrapper around a sqlite3.Connection scoped to one managed folder."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    @classmethod
    def open(cls, folder_root: Path) -> MetadataDB:
        ensure_stocker_layout(folder_root)
        path = db_path(folder_root)
        conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cls._apply_pragmas(conn)
        cls._migrate(conn)
        return cls(conn)

    @staticmethod
    def _apply_pragmas(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=134217728")  # 128 MB
        conn.execute("PRAGMA foreign_keys=ON")

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        ddl = _SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(ddl)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def close(self) -> None:
        self._conn.close()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    # ------- CRUD -------

    def upsert_file(self, item: FileItem) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO files (rel_path, name, ext, size_bytes, mtime_ns, added_at,
                               width, height, thumb_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rel_path) DO UPDATE SET
              name=excluded.name,
              ext=excluded.ext,
              size_bytes=excluded.size_bytes,
              mtime_ns=excluded.mtime_ns,
              width=COALESCE(excluded.width, files.width),
              height=COALESCE(excluded.height, files.height),
              thumb_hash=COALESCE(excluded.thumb_hash, files.thumb_hash)
            """,
            (
                item.rel_path,
                item.name,
                item.ext,
                item.size_bytes,
                item.mtime_ns,
                item.added_at,
                item.width,
                item.height,
                item.thumb_hash,
            ),
        )
        if cur.lastrowid:
            return int(cur.lastrowid)
        row = self._conn.execute("SELECT id FROM files WHERE rel_path=?", (item.rel_path,)).fetchone()
        return int(row["id"])

    def bulk_upsert(self, items: Iterable[FileItem]) -> int:
        rows = [
            (
                it.rel_path, it.name, it.ext, it.size_bytes, it.mtime_ns,
                it.added_at, it.width, it.height, it.thumb_hash,
            )
            for it in items
        ]
        if not rows:
            return 0
        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO files (rel_path, name, ext, size_bytes, mtime_ns, added_at,
                                   width, height, thumb_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rel_path) DO UPDATE SET
                  name=excluded.name,
                  ext=excluded.ext,
                  size_bytes=excluded.size_bytes,
                  mtime_ns=excluded.mtime_ns,
                  width=COALESCE(excluded.width, files.width),
                  height=COALESCE(excluded.height, files.height),
                  thumb_hash=COALESCE(excluded.thumb_hash, files.thumb_hash)
                """,
                rows,
            )
        return len(rows)

    def delete_by_rel(self, rel_path: str) -> bool:
        cur = self._conn.execute("DELETE FROM files WHERE rel_path=?", (rel_path,))
        return cur.rowcount > 0

    def bulk_delete(self, rel_paths: Iterable[str]) -> int:
        rows = [(p,) for p in rel_paths]
        if not rows:
            return 0
        with self._conn:
            cur = self._conn.executemany("DELETE FROM files WHERE rel_path=?", rows)
        return cur.rowcount

    def rename(self, old_rel: str, new_rel: str, new_name: str) -> bool:
        cur = self._conn.execute(
            "UPDATE files SET rel_path=?, name=? WHERE rel_path=?",
            (new_rel, new_name, old_rel),
        )
        return cur.rowcount > 0

    def get_by_rel(self, rel_path: str) -> FileItem | None:
        row = self._conn.execute("SELECT * FROM files WHERE rel_path=?", (rel_path,)).fetchone()
        return _row_to_item(row) if row else None

    def list_files(self, sort_key: str = "name", sort_dir: str = "asc") -> list[FileItem]:
        col_map = {"name": "name", "mtime": "mtime_ns", "added": "added_at"}
        col = col_map.get(sort_key, "name")
        direction = "DESC" if sort_dir == "desc" else "ASC"
        rows = self._conn.execute(f"SELECT * FROM files ORDER BY {col} {direction}").fetchall()
        return [_row_to_item(r) for r in rows]

    def list_rel_paths(self) -> set[str]:
        rows = self._conn.execute("SELECT rel_path FROM files").fetchall()
        return {r["rel_path"] for r in rows}

    def get_signatures(self) -> dict[str, tuple[int, int]]:
        """Returns {rel_path: (mtime_ns, size_bytes)} for change detection."""
        rows = self._conn.execute("SELECT rel_path, mtime_ns, size_bytes FROM files").fetchall()
        return {r["rel_path"]: (r["mtime_ns"], r["size_bytes"]) for r in rows}

    def count_files(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()
        return int(row["c"])

    def update_thumb_hash(self, rel_path: str, thumb_hash: str | None) -> None:
        self._conn.execute(
            "UPDATE files SET thumb_hash=? WHERE rel_path=?", (thumb_hash, rel_path)
        )

    def update_dimensions(self, rel_path: str, width: int, height: int) -> None:
        self._conn.execute(
            "UPDATE files SET width=?, height=? WHERE rel_path=?",
            (width, height, rel_path),
        )

    # ------- settings / scan_state -------

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def get_setting(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_scan_state(self, last_scan_ns: int, file_count: int) -> None:
        self._conn.execute(
            "INSERT INTO scan_state(id,last_scan_ns,file_count) VALUES(1,?,?) "
            "ON CONFLICT(id) DO UPDATE SET last_scan_ns=excluded.last_scan_ns, "
            "file_count=excluded.file_count",
            (last_scan_ns, file_count),
        )


def _row_to_item(row: sqlite3.Row) -> FileItem:
    return FileItem(
        db_id=row["id"],
        rel_path=row["rel_path"],
        name=row["name"],
        ext=row["ext"],
        size_bytes=row["size_bytes"],
        mtime_ns=row["mtime_ns"],
        added_at=row["added_at"],
        width=row["width"],
        height=row["height"],
        thumb_hash=row["thumb_hash"],
    )
