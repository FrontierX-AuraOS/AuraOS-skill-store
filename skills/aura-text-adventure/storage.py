"""SQLite snapshot storage for AURA Text Adventure."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable


class StorageError(Exception):
    """A SQLite save cannot be read or written safely."""


class SQLiteSaveStore:
    def __init__(
        self,
        data_dir: Path,
        *,
        schema_version: int,
        world_version: str,
        profile_id: str,
        slots: tuple[str, ...],
        validate_state: Callable[[dict[str, Any]], None],
    ) -> None:
        self.data_dir = data_dir
        self.db_path = data_dir / "saves.sqlite3"
        self.schema_version = schema_version
        self.world_version = world_version
        self.profile_id = profile_id
        self.slots = slots
        self.validate_state = validate_state
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._init_db()
        except (OSError, sqlite3.Error) as exc:
            raise StorageError(f"游戏存档目录不可用：{exc}") from exc

    def connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            return conn
        except sqlite3.Error as exc:
            raise StorageError(f"SQLite 不可用：{exc}") from exc

    @contextmanager
    def connection(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saves (
                save_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                slot_name TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                world_version TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(profile_id, slot_name)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_saves_profile_updated "
            "ON saves(profile_id, updated_at DESC)"
        )

    def _init_db(self) -> None:
        with self.connection() as conn:
            columns = conn.execute("PRAGMA table_info(saves)").fetchall()
            primary = [row["name"] for row in columns if row["pk"]]
            if columns and primary == ["save_id"]:
                # Migrate the pre-release layout that made save_id the sole PK,
                # which prevented one playthrough from occupying several slots.
                conn.execute("ALTER TABLE saves RENAME TO saves_legacy")
                self._create_schema(conn)
                conn.execute(
                    """
                    INSERT OR REPLACE INTO saves
                    SELECT save_id, profile_id, slot_name, schema_version,
                           world_version, state_json, created_at, updated_at
                    FROM saves_legacy
                    """
                )
                conn.execute("DROP TABLE saves_legacy")
            else:
                self._create_schema(conn)
            conn.execute(f"PRAGMA user_version={self.schema_version}")

    def _check_slot(self, slot: str) -> None:
        if slot not in self.slots:
            raise StorageError("存档位只能是 auto、manual_1、manual_2 或 manual_3。")

    def row(self, slot: str) -> sqlite3.Row | None:
        self._check_slot(slot)
        try:
            with self.connection() as conn:
                return conn.execute(
                    "SELECT * FROM saves WHERE profile_id=? AND slot_name=?",
                    (self.profile_id, slot),
                ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(f"读取存档失败：{exc}") from exc

    def load_slot(self, slot: str) -> dict[str, Any] | None:
        row = self.row(slot)
        if row is None:
            return None
        if row["schema_version"] != self.schema_version or row["world_version"] != self.world_version:
            raise StorageError(
                f"存档版本不兼容：schema={row['schema_version']} world={row['world_version']}。"
            )
        try:
            state = json.loads(row["state_json"])
        except json.JSONDecodeError as exc:
            raise StorageError("存档内容损坏，已拒绝覆盖原文件。") from exc
        self.validate_state(state)
        return state

    @staticmethod
    def _game_projection(state: dict[str, Any]) -> dict[str, Any]:
        projected = dict(state)
        projected.pop("request_history", None)
        return projected

    def write_state(
        self, state: dict[str, Any], slot: str, now_ms: int, *, allow_replace: bool = False
    ) -> None:
        self.validate_state(state)
        self._check_slot(slot)
        serialized = json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        try:
            with self.connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT created_at, state_json FROM saves WHERE profile_id=? AND slot_name=?",
                    (self.profile_id, slot),
                ).fetchone()
                if existing and not allow_replace:
                    try:
                        stored = json.loads(existing["state_json"])
                        old_sequence = int(stored.get("event_sequence", -1))
                        new_sequence = int(state.get("event_sequence", -1))
                    except (json.JSONDecodeError, TypeError, ValueError) as exc:
                        raise StorageError("现有存档损坏；只有确认恢复操作可以替换它。") from exc
                    conflicts = new_sequence < old_sequence or (
                        new_sequence == old_sequence
                        and self._game_projection(stored) != self._game_projection(state)
                    )
                    if conflicts:
                        raise StorageError("存档已被另一个请求更新；本次旧快照未写入，请重试。")
                created_at = int(existing["created_at"]) if existing else now_ms
                conn.execute(
                    """
                    INSERT INTO saves
                      (save_id, profile_id, slot_name, schema_version, world_version,
                       state_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile_id, slot_name) DO UPDATE SET
                      save_id=excluded.save_id,
                      schema_version=excluded.schema_version,
                      world_version=excluded.world_version,
                      state_json=excluded.state_json,
                      updated_at=excluded.updated_at
                    """,
                    (str(state["save_id"]), self.profile_id, slot, self.schema_version,
                     self.world_version, serialized, created_at, now_ms),
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"写入存档失败：{exc}") from exc

    def delete_slot(self, slot: str) -> None:
        self._check_slot(slot)
        try:
            with self.connection() as conn:
                conn.execute("DELETE FROM saves WHERE profile_id=? AND slot_name=?", (self.profile_id, slot))
        except sqlite3.Error as exc:
            raise StorageError(f"删除存档失败：{exc}") from exc

    def list_saves(self) -> list[dict[str, Any]]:
        try:
            with self.connection() as conn:
                rows = conn.execute(
                    "SELECT slot_name, save_id, schema_version, world_version, created_at, updated_at "
                    "FROM saves WHERE profile_id=? ORDER BY updated_at DESC",
                    (self.profile_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"列出存档失败：{exc}") from exc
        return [dict(row) for row in rows]
