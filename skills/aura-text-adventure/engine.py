"""Deterministic engine and local SQLite saves for AURA Text Adventure."""

from __future__ import annotations

import json
import hashlib
import re
import time
import uuid
from pathlib import Path
from typing import Any

from storage import SQLiteSaveStore, StorageError
from validation import QUEST_EXPLORE, StateValidationError, expected_quest, validate_game_state


SCHEMA_VERSION = 1
WORLD_VERSION = "dungeon-1-v1"
PROFILE_ID = "default"
AUTO_SLOT = "auto"
MANUAL_SLOTS = ("manual_1", "manual_2", "manual_3")
ALL_SLOTS = (AUTO_SLOT, *MANUAL_SLOTS)
DECISION_TTL_MS = 15 * 60 * 1000
MAX_IMPORT_BYTES = 2 * 1024 * 1024
DIRS = {"north": (0, -1), "south": (0, 1), "west": (-1, 0), "east": (1, 0)}
DIR_ALIASES = {
    "北": "north", "向北": "north", "上": "north", "north": "north", "n": "north",
    "南": "south", "向南": "south", "下": "south", "south": "south", "s": "south",
    "西": "west", "向西": "west", "左": "west", "west": "west", "w": "west",
    "东": "east", "向东": "east", "右": "east", "east": "east", "e": "east",
}


class AdventureError(Exception):
    """Expected user-facing engine error."""


class SaveError(AdventureError):
    """A save is missing, corrupt, incompatible, or unsafe."""


class RobotDisplaySink:
    """Stable display boundary until AuraOS exposes a production screen API."""

    def capability(self) -> dict[str, Any]:
        return {"status": "unavailable", "reason": "AuraOS 未提供已确认的 Skill 屏幕协议"}

    def emit(self, display_state: str) -> dict[str, Any]:
        return {"status": "unavailable", "display_state": display_state, "emitted": False}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def render_ascii_grid(width: int, height: int, markers: dict[tuple[int, int], str]) -> str:
    """Render a stable 1..5 square-frame grid using ASCII-width cells only."""
    if not (1 <= width <= 5 and 1 <= height <= 5):
        raise AdventureError("地图渲染范围只能是 1×1 到 5×5。")
    allowed = {"P", "M", "C", "E", ".", "#", "?"}
    if any(marker not in allowed for marker in markers.values()):
        raise AdventureError("地图包含未知标记。")
    lines = ["```text", "     " + " ".join(f" {x + 1} " for x in range(width))]
    for y in range(height):
        cells = [f"[{markers.get((x, y), '#')}]" for x in range(width)]
        lines.append(f"{chr(65 + y)}  " + " ".join(cells))
    lines.append("```")
    return "\n".join(lines)


class AdventureEngine:
    """The complete first-layer game engine."""

    def __init__(self, data_dir: Path | None = None, content_path: Path | None = None) -> None:
        self.skill_dir = Path(__file__).resolve().parent
        self.content_path = content_path or (self.skill_dir / "content.json")
        try:
            self.content = json.loads(self.content_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AdventureError(f"读取地牢内容失败：{exc}") from exc
        self._validate_content()
        self.data_dir = data_dir or (Path.home() / ".aura" / "skill-data" / "aura-text-adventure")
        try:
            self.store = SQLiteSaveStore(
                self.data_dir,
                schema_version=SCHEMA_VERSION,
                world_version=WORLD_VERSION,
                profile_id=PROFILE_ID,
                slots=ALL_SLOTS,
                validate_state=self._validate_state,
            )
        except StorageError as exc:
            raise AdventureError(str(exc)) from exc
        self.db_path = self.store.db_path

    def _connect(self):
        return self.store.connection()

    def _row(self, slot: str):
        try:
            return self.store.row(slot)
        except StorageError as exc:
            raise SaveError(str(exc)) from exc

    def _load_slot(self, slot: str = AUTO_SLOT) -> dict[str, Any] | None:
        try:
            return self.store.load_slot(slot)
        except StorageError as exc:
            raise SaveError(str(exc)) from exc

    def _write_state(
        self, state: dict[str, Any], slot: str = AUTO_SLOT, *, allow_replace: bool = False
    ) -> None:
        try:
            self.store.write_state(state, slot, _now_ms(), allow_replace=allow_replace)
        except StorageError as exc:
            raise SaveError(str(exc)) from exc

    def _delete_slot(self, slot: str) -> None:
        try:
            self.store.delete_slot(slot)
        except StorageError as exc:
            raise SaveError(str(exc)) from exc

    def list_saves(self) -> list[dict[str, Any]]:
        try:
            return self.store.list_saves()
        except StorageError as exc:
            raise SaveError(str(exc)) from exc

    def _validate_content(self) -> None:
        if self.content.get("schema_version") != SCHEMA_VERSION:
            raise AdventureError("地牢内容 schema 版本不支持。")
        levels = self.content.get("levels") or {}
        level = levels.get("level-1")
        if not isinstance(level, dict) or level.get("width") != 5 or level.get("height") != 5:
            raise AdventureError("第一层地图必须恰好是 5×5。")
        locations = level.get("locations") or []
        if len(locations) != 25:
            raise AdventureError("第一层必须包含 25 个地图格。")
        by_id = {str(item.get("id")): item for item in locations}
        if len(by_id) != 25 or level.get("spawn") != [2, 2]:
            raise AdventureError("地图坐标或中心出生点不合法。")
        for item in locations:
            if item.get("blocked"):
                continue
            for direction, target in (item.get("connections") or {}).items():
                if direction not in DIRS or target not in by_id or by_id[target].get("blocked"):
                    raise AdventureError(f"地图连接无效：{item.get('id')} -> {target}")
                reverse = {"north": "south", "south": "north", "west": "east", "east": "west"}[direction]
                if (by_id[target].get("connections") or {}).get(reverse) != item.get("id"):
                    raise AdventureError(f"地图连接不是双向：{item.get('id')} -> {target}")
        reachable = self._reachable_from(level, self._location_id(level, level["spawn"]))
        if not all(x in reachable for x in self._important_location_ids(level)):
            raise AdventureError("出生点无法到达宝箱、目标怪物或下一层入口。")

    def _reachable_from(self, level: dict[str, Any], start: str) -> set[str]:
        locations = {str(item["id"]): item for item in level["locations"]}
        seen: set[str] = set()
        queue = [start]
        while queue:
            current = queue.pop(0)
            if current in seen or current not in locations or locations[current].get("blocked"):
                continue
            seen.add(current)
            queue.extend((locations[current].get("connections") or {}).values())
        return seen

    def _important_location_ids(self, level: dict[str, Any]) -> list[str]:
        wanted: list[str] = []
        target = level["target_monster_id"]
        for item in level["locations"]:
            hidden = item.get("hidden") or {}
            if hidden.get("monster_id") == target or hidden.get("chest_id") or hidden.get("entrance"):
                wanted.append(str(item["id"]))
        return wanted

    @staticmethod
    def _location_id(level: dict[str, Any], coord: list[int]) -> str:
        for item in level["locations"]:
            if item.get("coord") == coord:
                return str(item["id"])
        raise AdventureError(f"找不到地图坐标：{coord}")

    def _validate_state(self, state: dict[str, Any]) -> None:
        try:
            validate_game_state(state, self.content)
        except StateValidationError as exc:
            raise SaveError(str(exc)) from exc

    def _new_state(self) -> dict[str, Any]:
        level = self.content["levels"]["level-1"]
        spawn = list(level["spawn"])
        return {
            "schema_version": SCHEMA_VERSION,
            "world_version": WORLD_VERSION,
            "save_id": str(uuid.uuid4()),
            "profile_id": PROFILE_ID,
            "status": "exploring",
            "current_level": "level-1",
            "party_location": spawn,
            "visited_locations": [self._location_id(level, spawn)],
            "world_flags": {
                "chest_opened": False,
                "monster_defeated": False,
                "level_complete": False,
                "next_level_unlocked": False,
            },
            "completed_events": [],
            "collected_items": [],
            "player_state": self._actor_state(),
            "aura_state": self._actor_state(),
            "inventory": [],
            "active_quest": QUEST_EXPLORE,
            "combat_state": None,
            "pending_aura_decision": None,
            "turn_number": 0,
            "event_sequence": 0,
            "random_seed": 24,
            "random_state": {"algorithm": "deterministic-v1", "seed": 24},
            "request_history": [],
        }

    @staticmethod
    def _actor_state() -> dict[str, Any]:
        return {
            "level": 1,
            "xp": 0,
            "next_xp": 100,
            "max_hp": 10,
            "hp": 10,
            "base_attack": 3,
            "attack_bonus": 0,
            "total_attack": 3,
            "equipment_slots": {"weapon": None, "head": None, "body": None, "accessory": None},
            "skill_slots": [],
            "resources": {},
            "statuses": [],
        }

    def handle(self, task: str = "", request_id: str | None = None) -> dict[str, Any]:
        command, parsed_request_id = self._extract_request_id(task)
        request_id = request_id or parsed_request_id or str(uuid.uuid4())
        load_error = None
        try:
            existing_state = self._load_slot(AUTO_SLOT)
        except SaveError as exc:
            existing_state, load_error = None, exc
        normalized = self._normalize(command)
        recovery_command = (
            self._is_list_saves(normalized) or self._is_import(normalized)
            or self._is_reset(normalized) or self._is_continue(normalized)
            or (self._is_start(normalized) and ("确认" in normalized or "confirm" in normalized))
        )
        if load_error and not recovery_command:
            return self._error_event(
                f"自动存档无法读取，原数据未被覆盖：{load_error} "
                "可查看存档、读档 1/2/3、导入存档，或确认开始新游戏。",
                request_id, None,
            )
        if existing_state:
            for record in existing_state.get("request_history", []):
                if record.get("request_id") == request_id:
                    return _copy_json(record["event"])
        try:
            event = self._dispatch(command, request_id, existing_state, force_replace=load_error is not None)
        except AdventureError as exc:
            event = self._error_event(str(exc), request_id, existing_state)
        try:
            current_state = self._load_slot(AUTO_SLOT)
        except SaveError:
            current_state = None
        if current_state is not None:
            self._record_request(current_state, request_id, event)
            self._write_state(current_state, AUTO_SLOT)
        return event

    def _dispatch(
        self, command: str, request_id: str, state: dict[str, Any] | None, *, force_replace: bool = False
    ) -> dict[str, Any]:
        normalized = self._normalize(command)
        if self._is_start(normalized):
            return self._start_new(normalized, request_id, state, force_replace=force_replace)
        if self._is_continue(normalized):
            return self._continue_game(normalized, request_id, state)
        if self._is_list_saves(normalized):
            return self._list_event(request_id, state)
        if self._is_import(normalized):
            return self._import_command(command, request_id, state)
        if self._is_export(normalized):
            return self._export_command(command, request_id, state)
        if self._is_reset(normalized):
            return self._reset_command(normalized, request_id, state)
        if self._is_help(normalized):
            help_text = "你可以说：向北/南/东/西、观察、调查、开宝箱、查看状态、查看地图、存档、继续、退出。战斗中说普通攻击。"
            if state is not None and state.get("pending_aura_decision"):
                help_text = "当前正在等待 AURA_ACTION。查询、聊天、存档和退出不会推进回合；新的玩家行动会被拒绝，并先结算 AURA 兜底。"
            return self._event(
                request_id, state, "system", "帮助", False,
                help_text,
                choices=self._choices(state) if state is not None else ["开始冒险", "继续冒险", "查看存档"],
            )
        if state is None:
            return self._error_event("还没有冒险存档，请先说“开始冒险”。", request_id, state)
        if self._is_exit(normalized):
            self._write_state(state, AUTO_SLOT)
            return self._event(
                request_id, state, "system", "已保存退出", True,
                "冒险已保存到自动存档。下次激活后说“继续冒险”即可从当前节点恢复。",
                choices=["继续冒险", "查看存档"], display_state="save",
            )
        if state.get("pending_aura_decision"):
            return self._pending_command(state, normalized, request_id)
        if self._parse_aura_action(normalized) is not None:
            return self._error_event("当前没有可消费的 AURA 决策令牌；它可能已使用或顺序错误。", request_id, state)
        if self._is_save(normalized):
            return self._save_command(normalized, request_id, state)
        if state.get("status") == "victory":
            return self._event(
                request_id, state, "query", "第一关已完成", False,
                "第一关已经完成。下层入口已解锁，但第二层内容尚未提供。",
                choices=["查看地图", "查看状态", "退出冒险"], display_state="victory",
            )
        if state.get("status") == "combat":
            return self._combat_command(state, normalized, request_id)
        intent = self._classify(normalized)
        if intent == "move":
            return self._move_command(state, normalized, request_id)
        if intent == "chest":
            return self._open_chest(state, request_id)
        if intent == "query_status":
            return self._status_event(request_id, state)
        if intent == "query_map":
            return self._map_event(request_id, state)
        if intent == "query_monster":
            return self._monster_event(request_id, state)
        if intent == "use_item":
            return self._event(
                request_id, state, "action", "无法使用", False,
                "第一版没有可消耗道具；普通长剑已自动装备，只影响玩家普通攻击。",
                choices=self._choices(state),
            )
        if intent in {"observe", "investigate"}:
            return self._observe_event(request_id, state, intent)
        if intent in {"talk", "advice"}:
            return self._conversation_event(request_id, state, intent)
        return self._event(
            request_id, state, "conversation", "自由交谈", False,
            "我在队伍里，当前没有替你移动或消耗资源。你可以问路线、血量或下一步建议。",
            choices=["观察", "查看状态", "查看地图", "询问建议"], display_state="dialogue",
        )

    def _start_new(
        self, command: str, request_id: str, old_state: dict[str, Any] | None, *, force_replace: bool = False
    ) -> dict[str, Any]:
        if old_state is not None and "确认" not in command and "confirm" not in command:
            return self._event(
                request_id, old_state, "system", "需要确认", False,
                "自动存档中已有冒险。说“继续冒险”恢复，或说“确认开始新游戏”覆盖自动档；手动档不会受影响。",
                choices=["继续冒险", "确认开始新游戏", "查看存档"], display_state="save",
            )
        state = self._new_state()
        self._discover_visible(state)
        self._bump(state)
        self._write_state(state, AUTO_SLOT, allow_replace=force_replace or old_state is not None)
        current = self._location(state)
        surroundings = "、".join(x["name"] for x in self._visible_locations(state) if x["id"] != current["id"])
        event = self._event(
            request_id, state, "system", "新游戏", True,
            f"我们从{current['name']}出发。{current['visible']} 相邻可见：{surroundings}。玩家与 AURA 均为 10/10 生命、攻击 3。",
            choices=["向北", "向西", "向东", "查看地图"], display_state="explore",
        )
        self._record_request(state, request_id, event)
        self._write_state(state, AUTO_SLOT)
        return event

    def _continue_game(self, command: str, request_id: str, state: dict[str, Any] | None) -> dict[str, Any]:
        slot = self._slot_from_text(command) or AUTO_SLOT
        loaded = self._load_slot(slot)
        if loaded is None:
            return self._error_event(f"{self._slot_label(slot)}不存在，请先开始冒险或选择其他存档。", request_id, state)
        state = loaded
        if slot != AUTO_SLOT:
            self._write_state(state, AUTO_SLOT, allow_replace=True)
        self._discover_visible(state)
        return self._event(
            request_id, state, "system", "继续冒险", False,
            f"已从{self._slot_label(slot)}恢复到{self._location(state)['name']}。当前阶段：{self._phase_label(state)}。",
            choices=self._choices(state), display_state=self._display_state(state),
        )

    def _save_command(self, command: str, request_id: str, state: dict[str, Any]) -> dict[str, Any]:
        slot = self._slot_from_text(command) or AUTO_SLOT
        if slot in MANUAL_SLOTS and self._row(slot) is not None and "确认" not in command and "confirm" not in command:
            return self._event(
                request_id, state, "system", "需要确认", False,
                f"{slot} 已有存档。请说“确认覆盖 {slot[-1]}”后再写入。",
                choices=[f"确认覆盖 {slot[-1]}", "返回"], display_state="save",
            )
        replacing = slot in MANUAL_SLOTS and ("确认" in command or "confirm" in command)
        self._write_state(state, slot, allow_replace=replacing)
        return self._event(
            request_id, state, "system", "已存档", True,
            f"已保存到{self._slot_label(slot)}。当前节点和战斗阶段已完整写入。",
            choices=self._choices(state) if state.get("pending_aura_decision") else ["继续", "查看存档", "退出冒险"],
            display_state="save",
        )

    def _reset_command(self, command: str, request_id: str, state: dict[str, Any] | None) -> dict[str, Any]:
        slot = self._slot_from_text(command) or AUTO_SLOT
        if "确认" not in command and "confirm" not in command:
            return self._event(
                request_id, state, "system", "需要确认", False,
                f"删除{self._slot_label(slot)}会永久丢失进度。请说“确认删除 {slot}”。",
                choices=[f"确认删除 {slot}", "返回"], display_state="save",
            )
        self._delete_slot(slot)
        return self._event(request_id, state, "system", "已删除存档", True, f"已删除{self._slot_label(slot)}。")

    def _export_command(self, command: str, request_id: str, state: dict[str, Any]) -> dict[str, Any]:
        if state is None:
            return self._error_event("没有可导出的自动存档。", request_id, state)
        path = self._safe_export_path(command)
        state_json = _compact_json(state)
        payload = {"format": "aura-text-adventure-save", "schema_version": SCHEMA_VERSION,
                   "world_version": WORLD_VERSION, "exported_at": _now_ms(),
                   "state_sha256": hashlib.sha256(state_json.encode("utf-8")).hexdigest(), "state": state}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_compact_json(payload), encoding="utf-8")
        return self._event(request_id, state, "system", "导出存档", False, f"已导出版本化存档：{path.name}。", display_state="save")

    def _import_command(self, command: str, request_id: str, state: dict[str, Any] | None) -> dict[str, Any]:
        path = self._path_from_command(command)
        if path is None or path.suffix.lower() != ".json" or not path.is_file() or path.is_symlink():
            return self._error_event("请提供存在的 JSON 存档路径，例如“导入存档 C:\\temp\\aura-save.json”。", request_id, state)
        try:
            if path.stat().st_size > MAX_IMPORT_BYTES:
                raise SaveError("导入文件超过 2 MiB 限制。")
            payload = json.loads(path.read_text(encoding="utf-8"))
            imported = payload.get("state") if isinstance(payload, dict) else None
            if payload.get("format") != "aura-text-adventure-save":
                raise SaveError("导入文件格式标识无效。")
            expected_hash = payload.get("state_sha256")
            actual_hash = hashlib.sha256(_compact_json(imported).encode("utf-8")).hexdigest()
            if not isinstance(expected_hash, str) or expected_hash != actual_hash:
                raise SaveError("导入文件完整性校验失败。")
            if not isinstance(imported, dict):
                raise SaveError("导入存档状态不是对象。")
            imported = _copy_json(imported)
            imported["request_history"] = []
            self._validate_state(imported)
        except (OSError, json.JSONDecodeError, AttributeError, SaveError) as exc:
            return self._error_event(f"导入失败，原有存档未被覆盖：{exc}", request_id, state)
        self._write_state(imported, AUTO_SLOT, allow_replace=True)
        return self._event(request_id, imported, "system", "导入完成", True, "已校验并恢复导入存档。", choices=self._choices(imported), display_state=self._display_state(imported))

    def _move_command(self, state: dict[str, Any], command: str, request_id: str) -> dict[str, Any]:
        direction, target_name = self._parse_move(command)
        if direction == "ambiguous":
            return self._event(
                request_id, state, "action", "需要澄清", False,
                "这句话包含多个移动方向。请只选择北、南、东、西中的一个。",
                choices=self._choices(state),
            )
        level = self.content["levels"][state["current_level"] if state["current_level"] in self.content.get("levels", {}) else "level-1"]
        current = self._location(state)
        target_id = None
        if direction:
            target_id = (current.get("connections") or {}).get(direction)
        elif target_name:
            for candidate in self._visible_locations(state):
                if target_name in candidate["name"] or candidate["name"] in target_name:
                    target_id = candidate["id"]
                    break
        if not target_id:
            return self._event(request_id, state, "action", "移动失败", False, "这个方向没有可进入的通道。", choices=self._choices(state))
        locations = {str(item["id"]): item for item in level["locations"]}
        destination = locations.get(target_id)
        if not destination or destination.get("blocked"):
            return self._event(request_id, state, "action", "移动失败", False, "那条路被墙或落石挡住了。", choices=self._choices(state))
        state["party_location"] = list(destination["coord"])
        self._discover_visible(state)
        state["turn_number"] += 1
        self._bump(state)
        hidden = destination.get("hidden") or {}
        target_monster = level["target_monster_id"]
        if hidden.get("monster_id") == target_monster and not state["world_flags"]["monster_defeated"]:
            self._enter_combat(state, target_monster)
            self._write_state(state, AUTO_SLOT)
            return self._event(request_id, state, "action", "进入战斗", True,
                               f"你抵达{destination['name']}，守门石像苏醒了。现在轮到玩家行动。",
                               choices=["普通攻击", "查看状态", "查看怪物属性"], display_state="battle")
        if hidden.get("entrance"):
            if state["world_flags"]["next_level_unlocked"]:
                state["status"] = "victory"
                state["active_quest"] = expected_quest(state, self.content)
                self._bump(state)
                self._write_state(state, AUTO_SLOT)
                return self._event(request_id, state, "action", "第一关完成", True,
                                   "你抵达已解锁的下层石门。第一关完成，第二层内容尚未提供。",
                                   choices=["查看状态", "查看地图", "退出冒险"], display_state="victory")
            self._write_state(state, AUTO_SLOT)
            return self._event(request_id, state, "action", "入口未解锁", True,
                               "下层石门还锁着。先找到并击败目标怪物。", choices=["查看地图", "向西", "向北"])
        self._write_state(state, AUTO_SLOT)
        return self._event(request_id, state, "action", "移动完成", True,
                           f"队伍来到{destination['name']}。{destination['visible']}", choices=self._choices(state))

    def _open_chest(self, state: dict[str, Any], request_id: str) -> dict[str, Any]:
        current = self._location(state)
        chest_id = (current.get("hidden") or {}).get("chest_id")
        if not chest_id:
            return self._event(request_id, state, "action", "没有宝箱", False, "当前格没有可以打开的宝箱。", choices=self._choices(state))
        if state["world_flags"]["chest_opened"]:
            return self._event(request_id, state, "action", "宝箱已空", False, "军械库木箱已经打开过了，没有新的物品。", choices=self._choices(state))
        chest = self.content["chests"][chest_id]
        item_id = chest["item_id"]
        item = self.content["items"][item_id]
        state["world_flags"]["chest_opened"] = True
        state["collected_items"].append(item_id)
        state["inventory"].append({"item_id": item_id, "name": item["name"], "slot": item["slot"], "attack_bonus": item["attack_bonus"]})
        player = state["player_state"]
        player["equipment_slots"][item["slot"]] = item_id
        player["attack_bonus"] = item["attack_bonus"]
        player["total_attack"] = player["base_attack"] + player["attack_bonus"]
        state["completed_events"].append("open:armory-chest")
        state["turn_number"] += 1
        self._bump(state)
        self._write_state(state, AUTO_SLOT)
        return self._event(request_id, state, "action", "获得装备", True,
                           f"你打开军械库木箱，获得并装备{item['name']}。玩家攻击力从 3 提升到 5。",
                           choices=["查看状态", "查看地图", "向东"], display_state="loot")

    def _combat_command(self, state: dict[str, Any], command: str, request_id: str) -> dict[str, Any]:
        if self._is_monster_query(command):
            return self._monster_event(request_id, state)
        if self._is_status_query(command):
            return self._status_event(request_id, state)
        if self._is_map_query(command):
            return self._map_event(request_id, state)
        if state["player_state"]["hp"] <= 0:
            return self._require_aura_decision(state, request_id, "玩家处于倒地状态，本回合跳过玩家行动。")
        if self._is_attack(command):
            return self._player_attack(state, request_id)
        return self._event(request_id, state, "conversation", "战斗中", False,
                           "现在轮到玩家行动。第一版可执行动作只有普通攻击。", choices=["普通攻击", "查看状态", "查看怪物属性"], display_state="player_turn")

    def _pending_command(
        self, state: dict[str, Any], command: str, request_id: str
    ) -> dict[str, Any]:
        action = self._parse_aura_action(command)
        if action is not None:
            return self._submit_aura_action(state, action, request_id)
        if self._is_save(command):
            return self._save_command(command, request_id, state)

        intent = self._classify(command)
        if intent == "query_status":
            return self._status_event(request_id, state)
        if intent == "query_map":
            return self._map_event(request_id, state)
        if intent == "query_monster":
            return self._monster_event(request_id, state)
        if intent in {"observe", "investigate"}:
            return self._observe_event(request_id, state, intent)
        if intent in {"talk", "advice", "conversation"} and not self._is_attack(command):
            return self._conversation_event(request_id, state, intent)
        if intent == "move" and self._parse_move(command)[0] == "ambiguous":
            return self._event(
                request_id, state, "action", "需要澄清", False,
                "这句话包含多个移动方向。请只选择北、南、东、西中的一个。",
                choices=self._choices(state),
            )
        return self._resolve_pending_fallback(state, request_id, rejected_action=True)

    def _player_attack(self, state: dict[str, Any], request_id: str) -> dict[str, Any]:
        combat = state.get("combat_state") or {}
        if combat.get("phase") != "player":
            return self._error_event("现在不是玩家行动阶段。", request_id, state)
        damage = int(state["player_state"]["total_attack"])
        combat["monster_hp"] = max(0, int(combat["monster_hp"]) - damage)
        state["combat_state"] = combat
        if combat["monster_hp"] <= 0:
            return self._finish_victory(state, request_id, f"玩家普通攻击命中，造成 {damage} 点伤害。")
        return self._require_aura_decision(state, request_id, f"玩家普通攻击命中，造成 {damage} 点伤害。")

    def _require_aura_decision(
        self, state: dict[str, Any], request_id: str, narration: str
    ) -> dict[str, Any]:
        combat = state.get("combat_state") or {}
        if state["aura_state"]["hp"] <= 0:
            return self._resolve_aura_and_monster(
                state, request_id, f"{narration} AURA 处于倒地状态，本回合跳过行动。"
            )
        token = f"d{state['event_sequence'] + 1}-{uuid.uuid4().hex[:8]}"
        pending = {
            "token": token,
            "schema_version": 1,
            "state_sequence": state["event_sequence"] + 1,
            "legal_actions": ["attack"],
            "legal_targets": [combat["monster_id"]],
            "created_at": _now_ms(),
        }
        combat["phase"] = "aura"
        state["pending_aura_decision"] = pending
        self._bump(state)
        self._write_state(state, AUTO_SLOT)
        event = self._event(
            request_id, state, "action", "AURA 决策", True, narration,
            result="AURA_DECISION_REQUIRED", choices=["提交 AURA_ACTION"], display_state="aura_turn",
        )
        event["decision_token"] = token
        event["legal_actions"] = ["attack"]
        event["legal_targets"] = [combat["monster_id"]]
        event["protocol"] = "aura-text-adventure/1"
        self._record_request(state, request_id, event)
        self._write_state(state, AUTO_SLOT)
        return event

    def _submit_aura_action(self, state: dict[str, Any], action: dict[str, str], request_id: str) -> dict[str, Any]:
        pending = state.get("pending_aura_decision") or {}
        if action.get("token") != pending.get("token"):
            return self._error_event("AURA 决策令牌无效或已使用，未结算这一回合。", request_id, state)
        if int(pending.get("state_sequence", -1)) != int(state.get("event_sequence", -2)):
            return self._error_event("AURA 决策令牌对应的状态版本已过期，未结算这一回合。", request_id, state)
        if _now_ms() - int(pending.get("created_at", 0)) > DECISION_TTL_MS:
            return self._resolve_pending_fallback(state, request_id)
        if action.get("action") != "attack" or action.get("target") not in pending.get("legal_targets", []):
            return self._error_event("AURA_ACTION 不在引擎提供的合法动作和目标集合中。", request_id, state)
        return self._resolve_aura_and_monster(state, request_id, "AURA 选择了普通攻击。")

    def _resolve_pending_fallback(
        self, state: dict[str, Any], request_id: str, *, rejected_action: bool = False
    ) -> dict[str, Any]:
        prefix = "AURA 决策未按协议返回，本回合使用普通攻击兜底。"
        if rejected_action:
            prefix = "上一回合仍在等待 AURA 决策；新的玩家行动未执行，本回合由 AURA 使用普通攻击兜底。"
        return self._resolve_aura_and_monster(state, request_id, prefix)

    def _resolve_aura_and_monster(self, state: dict[str, Any], request_id: str, prefix: str) -> dict[str, Any]:
        combat = state.get("combat_state") or {}
        aura = state["aura_state"]
        damage = 3 if aura["hp"] > 0 else 0
        if damage:
            combat["monster_hp"] = max(0, int(combat["monster_hp"]) - damage)
        else:
            prefix += " AURA 处于倒地状态，本回合跳过行动。"
        state["pending_aura_decision"] = None
        if combat["monster_hp"] <= 0:
            return self._finish_victory(state, request_id, f"{prefix} AURA 造成 {damage} 点伤害，目标怪物被击败。")
        target_key = combat.get("next_target", "player")
        player = state["player_state"]
        preferred = player if target_key == "player" else aura
        alternate = aura if preferred is player else player
        target = preferred if preferred["hp"] > 0 else alternate
        target_name = "玩家" if target is player else "AURA"
        target["hp"] = max(0, int(target["hp"]) - int(combat["monster_attack"]))
        combat["next_target"] = "aura" if target is player else "player"
        combat["round"] = int(combat.get("round", 0)) + 1
        state["turn_number"] += 1
        if player["hp"] <= 0 and aura["hp"] <= 0:
            return self._finish_defeat(state, request_id, f"{prefix} 守门石像反击了 {target_name}，全队倒地。")
        combat["phase"] = "player"
        state["combat_state"] = combat
        self._bump(state)
        self._write_state(state, AUTO_SLOT)
        return self._event(request_id, state, "action", "回合结算", True,
                           f"{prefix} 守门石像攻击{target_name}，造成 {combat['monster_attack']} 点伤害。",
                           result="TURN_RESOLVED", choices=["普通攻击", "查看状态", "查看怪物属性"], display_state="player_turn")

    def _finish_victory(self, state: dict[str, Any], request_id: str, narration: str) -> dict[str, Any]:
        state["world_flags"]["monster_defeated"] = True
        state["world_flags"]["level_complete"] = True
        state["world_flags"]["next_level_unlocked"] = True
        state["completed_events"].append("defeat:stone-sentinel")
        state["player_state"]["xp"] += 50
        state["aura_state"]["xp"] += 50
        state["combat_state"] = None
        state["pending_aura_decision"] = None
        state["status"] = "exploring"
        state["active_quest"] = expected_quest(state, self.content)
        state["turn_number"] += 1
        self._bump(state)
        self._write_state(state, AUTO_SLOT)
        return self._event(request_id, state, "action", "第一关完成", True,
                           f"{narration} 玩家和 AURA 各获得 50 经验。下层石门已解锁。",
                           result="TURN_RESOLVED", choices=["前往下层石门", "查看状态", "查看地图"], display_state="victory")

    def _finish_defeat(self, state: dict[str, Any], request_id: str, narration: str) -> dict[str, Any]:
        level = self.content["levels"][state["current_level"]]
        state["party_location"] = list(level["spawn"])
        state["player_state"]["hp"] = 10
        state["aura_state"]["hp"] = 10
        state["status"] = "exploring"
        state["combat_state"] = None
        state["pending_aura_decision"] = None
        self._discover_visible(state)
        self._bump(state)
        self._write_state(state, AUTO_SLOT)
        return self._event(request_id, state, "action", "全队战败", True,
                           f"{narration} 队伍回到回声中庭，双方恢复至 10 点生命；地图和已获得物品保留。",
                           result="TURN_RESOLVED", choices=["查看状态", "查看地图", "向北"], display_state="defeat")

    def _enter_combat(self, state: dict[str, Any], monster_id: str) -> None:
        monster = self.content["monsters"][monster_id]
        state["status"] = "combat"
        state["combat_state"] = {
            "monster_id": monster_id,
            "monster_name": monster["name"],
            "monster_hp": monster["max_hp"],
            "monster_max_hp": monster["max_hp"],
            "monster_attack": monster["attack"],
            "monster_level": monster["level"],
            "phase": "player",
            "next_target": "player",
            "round": 0,
        }
        state["pending_aura_decision"] = None

    def _status_event(self, request_id: str, state: dict[str, Any]) -> dict[str, Any]:
        p, a = state["player_state"], state["aura_state"]
        text = (
            "| 属性 | 玩家 | AURA |\n|---|---:|---:|\n"
            f"| 生命 | {p['hp']}/{p['max_hp']} | {a['hp']}/{a['max_hp']} |\n"
            f"| 等级 | {p['level']} | {a['level']} |\n"
            f"| 经验 | {p['xp']}/{p['next_xp']} | {a['xp']}/{a['next_xp']} |\n"
            f"| 基础攻击 | {p['base_attack']} | {a['base_attack']} |\n"
            f"| 装备加成 | +{p['attack_bonus']} | +{a['attack_bonus']} |\n"
            f"| 总攻击 | {p['total_attack']} | {a['total_attack']} |\n"
            "| 阶段 | " + self._phase_label(state) + " | " + self._phase_label(state) + " |\n\n"
            f"| 装备位 | 玩家 | AURA |\n|---|---|---|\n| 武器 | {self._equipment_label(p, 'weapon')} | {self._equipment_label(a, 'weapon')} |\n"
            f"| 头部 | {self._equipment_label(p, 'head')} | {self._equipment_label(a, 'head')} |\n"
            f"| 身体 | {self._equipment_label(p, 'body')} | {self._equipment_label(a, 'body')} |\n"
            f"| 饰品 | {self._equipment_label(p, 'accessory')} | {self._equipment_label(a, 'accessory')} |\n\n"
            f"当前任务：{state['active_quest']}"
        )
        return self._event(request_id, state, "query", "队伍状态", False, text, choices=self._choices(state), display_state=self._display_state(state), raw_narration=text)

    def _list_event(self, request_id: str, state: dict[str, Any] | None) -> dict[str, Any]:
        by_slot = {row["slot_name"]: row for row in self.list_saves()}
        rows = ["| 存档位 | 状态 |", "|---|---|"]
        for slot in ALL_SLOTS:
            row = by_slot.get(slot)
            status = "已有存档" if row else "空"
            rows.append(f"| {self._slot_label(slot)} | {status} |")
        return self._event(
            request_id, state, "query", "存档列表", False, "\n".join(rows),
            choices=["继续冒险", "存档 1", "存档 2", "存档 3"], display_state="save",
            raw_narration="\n".join(rows),
        )

    def _monster_event(self, request_id: str, state: dict[str, Any]) -> dict[str, Any]:
        monster_id = self.content["levels"][state["current_level"]]["target_monster_id"]
        known = self._object_visible(state, monster_id=monster_id)
        combat = state.get("combat_state")
        if not known and not combat and not state["world_flags"]["monster_defeated"]:
            return self._event(request_id, state, "query", "怪物未知", False, "你还没有发现目标怪物，继续探索可见通道。", choices=self._choices(state))
        monster = self.content["monsters"][monster_id]
        hp = combat["monster_hp"] if combat else (0 if state["world_flags"]["monster_defeated"] else monster["max_hp"])
        status = "已击败" if state["world_flags"]["monster_defeated"] else "存活"
        text = f"| 属性 | 目标怪物 |\n|---|---:|\n| 名称 | {monster['name']} |\n| 生命 | {hp}/{monster['max_hp']} |\n| 等级 | {monster['level']} |\n| 普通攻击 | {monster['attack']} |\n| 状态 | {status} |"
        return self._event(request_id, state, "query", "怪物属性", False, text, choices=self._choices(state), display_state=self._display_state(state), raw_narration=text)

    def _map_event(self, request_id: str, state: dict[str, Any]) -> dict[str, Any]:
        return self._event(request_id, state, "query", "当前地图", False, self.render_map(state), choices=self._choices(state), display_state=self._display_state(state), raw_narration=self.render_map(state))

    def _observe_event(self, request_id: str, state: dict[str, Any], intent: str) -> dict[str, Any]:
        before = set(state["visited_locations"])
        self._discover_visible(state)
        if before != set(state["visited_locations"]):
            self._write_state(state, AUTO_SLOT)
        current = self._location(state)
        visible = self._visible_locations(state)
        extras = ", ".join(item["name"] for item in visible if item["id"] != current["id"]) or "没有其他相邻地点"
        return self._event(request_id, state, "query", "环境观察" if intent == "observe" else "调查结果", False,
                           f"当前位置：{current['name']}。{current['visible']} 相邻可见：{extras}。", choices=self._choices(state), display_state=self._display_state(state))

    def _conversation_event(self, request_id: str, state: dict[str, Any], intent: str) -> dict[str, Any]:
        if intent == "advice":
            if state.get("pending_aura_decision"):
                text = "这一拍轮到我选择行动；查询和商量不会推进回合，我只能提交引擎允许的普通攻击。"
            elif state["status"] == "combat":
                text = "先保持普通攻击的节奏。AURA 只会从引擎给出的合法动作里行动。"
            elif not state["world_flags"]["chest_opened"]:
                if self._object_visible(state, chest_id="armory-chest"):
                    text = "已发现旧军械库的木箱，可以过去调查。"
                else:
                    text = "先观察相邻通道，逐格确认地形；我不会猜未发现区域里有什么。"
            elif not state["world_flags"]["monster_defeated"]:
                text = "长剑已经装备好，可以沿北侧回廊寻找守门石像。"
            else:
                text = "第一关已经完成，去东侧的下层石门看看吧。"
        else:
            text = self.content["aura_lines"]["explore"]
        return self._event(request_id, state, "conversation", "AURA 对话", False, text, choices=self._choices(state), display_state="dialogue")

    def render_map(self, state: dict[str, Any]) -> str:
        level = self.content["levels"][state["current_level"]]
        current_id = self._location(state)["id"]
        visible_ids = {item["id"] for item in self._visible_locations(state)}
        visited = set(state["visited_locations"])
        target_id = level["target_monster_id"]
        markers: dict[tuple[int, int], str] = {}
        for y in range(5):
            for x in range(5):
                item = next(loc for loc in level["locations"] if loc["coord"] == [x, y])
                marker = "?"
                if item["id"] in visited or item["id"] in visible_ids:
                    marker = "#" if item.get("blocked") else "."
                    hidden = item.get("hidden") or {}
                    if item["id"] == current_id:
                        marker = "P"
                    elif hidden.get("monster_id") == target_id and not state["world_flags"]["monster_defeated"] and item["id"] in visited:
                        marker = "M"
                    elif hidden.get("chest_id") and not state["world_flags"]["chest_opened"] and item["id"] in visited:
                        marker = "C"
                    elif hidden.get("entrance") and item["id"] in visited:
                        marker = "E"
                markers[(x, y)] = marker
        grid = render_ascii_grid(5, 5, markers)
        return grid + "\n图例：[P]队伍 [M]目标怪物 [C]宝箱 [E]入口 [.]已知 [#]阻挡 [?]未知"

    def _public_state(self, state: dict[str, Any]) -> dict[str, Any]:
        p, a = state["player_state"], state["aura_state"]
        public: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "world_version": WORLD_VERSION,
            "status": state["status"],
            "current_level": state["current_level"],
            "party_location": list(state["party_location"]),
            "current_location": self._location(state)["name"],
            "visited_locations": list(state["visited_locations"]),
            "player": {"hp": p["hp"], "max_hp": p["max_hp"], "level": p["level"], "xp": p["xp"], "next_xp": p["next_xp"], "attack": p["total_attack"], "equipment": self._equipment_label(p, "weapon")},
            "aura": {"hp": a["hp"], "max_hp": a["max_hp"], "level": a["level"], "xp": a["xp"], "next_xp": a["next_xp"], "attack": a["total_attack"], "equipment": self._equipment_label(a, "weapon")},
            "visible_locations": [{"id": x["id"], "coord": x["coord"], "name": x["name"], "description": x["visible"]} for x in self._visible_locations(state)],
            "world_flags": {"chest_opened": state["world_flags"]["chest_opened"], "monster_defeated": state["world_flags"]["monster_defeated"], "level_complete": state["world_flags"]["level_complete"], "next_level_unlocked": state["world_flags"]["next_level_unlocked"]},
        }
        if state.get("combat_state"):
            c = state["combat_state"]
            public["combat"] = {"phase": c["phase"], "monster_id": c["monster_id"], "monster_hp": c["monster_hp"], "monster_max_hp": c["monster_max_hp"], "round": c["round"]}
        return public

    @staticmethod
    def _normalize(command: str) -> str:
        return re.sub(r"\s+", " ", (command or "").strip().lower())

    @staticmethod
    def _extract_request_id(task: str) -> tuple[str, str | None]:
        match = re.search(r"(?:^|\s)request_id\s*[:=]\s*([A-Za-z0-9._-]{1,80})", task or "", re.I)
        if not match:
            return task, None
        command = (task[:match.start()] + task[match.end():]).strip()
        return command, match.group(1)

    def _classify(self, command: str) -> str:
        if any(x in command for x in ("地图", "我在哪里", "周围有什么")):
            return "query_map"
        if any(x in command for x in ("怪物属性", "敌人属性", "怪有多少血", "守门石像")):
            return "query_monster"
        if any(x in command for x in ("使用道具", "使用物品", "喝药", "吃药")):
            return "use_item"
        if any(x in command for x in ("状态", "属性", "血量", "装备", "队伍", "背包", "物品", "任务", "技能")):
            return "query_status"
        if any(x in command for x in ("宝箱", "开箱", "打开箱", "拾取")):
            return "chest"
        if any(x in command for x in ("观察", "看看", "环顾")):
            return "observe"
        if any(x in command for x in ("调查", "检查")):
            return "investigate"
        if any(x in command for x in ("建议", "商量", "怎么走", "怎么办", "对策")):
            return "advice"
        if any(x in command for x in ("交谈", "聊天", "说话", "你好", "aura")):
            return "talk"
        direction, target = self._parse_move(command)
        if direction or target:
            return "move"
        return "conversation"

    def _parse_move(self, command: str) -> tuple[str | None, str | None]:
        matched: set[str] = set()
        for char, direction in (("北", "north"), ("南", "south"), ("西", "west"), ("东", "east")):
            if re.search(rf"(?:向|往|朝){char}", command) or re.search(rf"{char}(?:走|移动|前进|边$)", command) or command == char:
                matched.add(direction)
        for key, direction in DIR_ALIASES.items():
            if re.search(rf"(?:^|\s|向|往|朝){re.escape(key)}(?:$|\s|走|移动|去|前进)", command):
                matched.add(direction)
        if len(matched) > 1:
            return "ambiguous", None
        if matched:
            return next(iter(matched)), None
        if command in DIR_ALIASES:
            return DIR_ALIASES[command], None
        match = re.search(r"(?:去|前往|走到|移动到)\s*(.+)$", command)
        if match:
            return None, match.group(1).strip()
        return None, None

    @staticmethod
    def _is_start(command: str) -> bool:
        return any(x in command for x in ("开始冒险", "开始新游戏", "新游戏", "重新开始", "文字冒险"))

    @staticmethod
    def _is_continue(command: str) -> bool:
        return any(x in command for x in ("继续冒险", "继续游戏", "读档", "恢复进度", "读取自动"))

    @staticmethod
    def _is_list_saves(command: str) -> bool:
        return any(x in command for x in ("查看存档", "存档列表", "有哪些存档"))

    @staticmethod
    def _is_export(command: str) -> bool:
        return "导出" in command and "存档" in command

    @staticmethod
    def _is_import(command: str) -> bool:
        return "导入" in command and "存档" in command

    @staticmethod
    def _is_reset(command: str) -> bool:
        return any(x in command for x in ("删除存档", "重置存档", "清空存档", "确认删除"))

    @staticmethod
    def _is_save(command: str) -> bool:
        return any(x in command for x in ("存档", "保存进度", "保存游戏", "确认覆盖"))

    @staticmethod
    def _is_exit(command: str) -> bool:
        return any(x in command for x in ("退出冒险", "结束冒险", "离开冒险", "退出游戏"))

    @staticmethod
    def _is_help(command: str) -> bool:
        return command in {"帮助", "help", "怎么玩", "操作"} or "有哪些操作" in command

    @staticmethod
    def _is_attack(command: str) -> bool:
        return any(x in command for x in ("普通攻击", "攻击", "打怪", "出剑"))

    @staticmethod
    def _is_status_query(command: str) -> bool:
        return any(x in command for x in ("状态", "属性", "血量", "装备"))

    @staticmethod
    def _is_monster_query(command: str) -> bool:
        return "怪物" in command or "敌人" in command or "守门石像" in command

    @staticmethod
    def _is_map_query(command: str) -> bool:
        return "地图" in command or "我在哪里" in command

    def _parse_aura_action(self, command: str) -> dict[str, str] | None:
        raw = command.strip()
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and str(data.get("type", "")).upper() == "AURA_ACTION":
                return {"token": str(data.get("decision_token") or data.get("token") or ""), "action": str(data.get("action") or ""), "target": str(data.get("target") or "")}
        except json.JSONDecodeError:
            pass
        if "aura_action" not in raw.lower():
            return None
        token = re.search(r"(?:token|decision_token)\s*[:=]\s*([A-Za-z0-9._-]+)", raw, re.I)
        target = re.search(r"target\s*[:=]\s*([A-Za-z0-9._-]+)", raw, re.I)
        return {"token": token.group(1) if token else "", "action": "attack", "target": target.group(1) if target else "stone-sentinel"}

    @staticmethod
    def _slot_from_text(command: str) -> str | None:
        if "auto" in command or "自动" in command:
            return AUTO_SLOT
        match = re.search(r"(?:manual[_ ]?|手动\s*|存档\s*|读档\s*|覆盖\s*|删除\s*)([123])", command)
        if match:
            return f"manual_{match.group(1)}"
        return None

    def _path_from_command(self, command: str) -> Path | None:
        match = re.search(r"(?:导入存档|导入)\s+(.+)$", command, re.I)
        if not match:
            return None
        value = match.group(1).strip().strip('"')
        return Path(value).expanduser()

    def _safe_export_path(self, command: str) -> Path:
        match = re.search(r"(?:导出存档|导出)\s+(.+)$", command, re.I)
        filename = "aura-text-adventure-save.json"
        if match:
            candidate_name = Path(match.group(1).strip().strip('"')).name
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\.json", candidate_name, re.I):
                filename = candidate_name
        return self.data_dir / "exports" / filename

    def _location(self, state: dict[str, Any]) -> dict[str, Any]:
        level = self.content["levels"][state["current_level"]]
        for item in level["locations"]:
            if item["coord"] == state["party_location"]:
                return item
        raise SaveError("当前队伍位置不存在。")

    def _visible_locations(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        current = self._location(state)
        level = self.content["levels"][state["current_level"]]
        by_id = {str(item["id"]): item for item in level["locations"]}
        ids = {current["id"]}
        ids.update((current.get("connections") or {}).values())
        return [by_id[x] for x in ids if x in by_id and not by_id[x].get("blocked")]

    def _discover_visible(self, state: dict[str, Any]) -> None:
        known = set(state.get("visited_locations", []))
        known.update(item["id"] for item in self._visible_locations(state))
        current = self._location(state)
        x, y = current["coord"]
        level = self.content["levels"][state["current_level"]]
        for item in level["locations"]:
            ix, iy = item["coord"]
            if item.get("blocked") and abs(ix - x) + abs(iy - y) == 1:
                known.add(item["id"])
        state["visited_locations"] = sorted(known)
        state["active_quest"] = expected_quest(state, self.content)

    def _object_visible(
        self, state: dict[str, Any], monster_id: str | None = None, chest_id: str | None = None
    ) -> bool:
        visited = set(state.get("visited_locations", []))
        level = self.content["levels"][state["current_level"]]
        return any(
            item["id"] in visited and (
                (monster_id is not None and (item.get("hidden") or {}).get("monster_id") == monster_id)
                or (chest_id is not None and (item.get("hidden") or {}).get("chest_id") == chest_id)
            )
            for item in level["locations"]
        )

    def _phase_label(self, state: dict[str, Any]) -> str:
        status = state.get("status")
        if status == "combat":
            return "玩家行动" if (state.get("combat_state") or {}).get("phase") == "player" else "AURA 行动"
        return {"exploring": "探索", "victory": "第一关完成", "defeated": "战败恢复", "new": "新游戏"}.get(status, status or "未知")

    def _display_state(self, state: dict[str, Any]) -> str:
        if state.get("status") == "combat":
            phase = (state.get("combat_state") or {}).get("phase")
            return "player_turn" if phase == "player" else "aura_turn"
        if state.get("status") == "victory":
            return "victory"
        return "explore"

    def _choices(self, state: dict[str, Any]) -> list[str]:
        if state.get("pending_aura_decision"):
            return ["提交 AURA_ACTION", "查看状态", "查看地图", "查看怪物属性", "退出冒险"]
        if state.get("status") == "combat":
            return ["普通攻击", "查看状态", "查看怪物属性"]
        choices = ["观察", "查看状态", "查看地图"]
        current = self._location(state)
        for direction in ("north", "south", "west", "east"):
            if direction in (current.get("connections") or {}):
                choices.append({"north": "向北", "south": "向南", "west": "向西", "east": "向东"}[direction])
        hidden = current.get("hidden") or {}
        if hidden.get("chest_id") and not state["world_flags"]["chest_opened"]:
            choices.insert(0, "打开宝箱")
        if hidden.get("entrance") and state["world_flags"]["next_level_unlocked"]:
            choices.insert(0, "前往下层石门")
        return choices[:5]

    @staticmethod
    def _equipment_label(actor: dict[str, Any], slot: str) -> str:
        value = actor.get("equipment_slots", {}).get(slot)
        return "普通长剑" if value == "common-longsword" else "空"

    @staticmethod
    def _slot_label(slot: str) -> str:
        return {"auto": "自动存档", "manual_1": "手动存档 1", "manual_2": "手动存档 2", "manual_3": "手动存档 3"}.get(slot, slot)

    def _record_request(self, state: dict[str, Any], request_id: str, event: dict[str, Any]) -> None:
        records = [x for x in state.get("request_history", []) if x.get("request_id") != request_id]
        records.append({"request_id": request_id, "event": _copy_json(event)})
        state["request_history"] = records[-64:]

    @staticmethod
    def _bump(state: dict[str, Any]) -> None:
        state["event_sequence"] = int(state.get("event_sequence", 0)) + 1

    def _event(
        self, request_id: str, state: dict[str, Any] | None, intent: str, result_label: str,
        state_changed: bool, narration: str, *, result: str = "OK", choices: list[str] | None = None,
        display_state: str | None = None, raw_narration: str | None = None,
    ) -> dict[str, Any]:
        state = state or self._new_state()
        spoken = narration.split("\n", 1)[0][:180]
        return {
            "protocol_version": "aura-text-adventure/1",
            "request_id": request_id,
            "save_id": state.get("save_id"),
            "sequence": int(state.get("event_sequence", 0)),
            "phase": self._phase_label(state),
            "intent": intent,
            "result": result,
            "result_label": result_label,
            "state_changed": state_changed,
            "narration": raw_narration or narration,
            "aura_dialogue": self.content["aura_lines"].get("battle" if state.get("status") == "combat" else "explore", ""),
            "choices": choices or self._choices(state),
            "public_state": self._public_state(state),
            "state_summary": self._state_summary(state),
            "display_state": display_state or self._display_state(state),
            "display_capability": RobotDisplaySink().capability(),
            "spoken_text": spoken,
            "should_speak": bool(state_changed or intent in {"action", "system"}),
        }

    def _error_event(self, message: str, request_id: str, state: dict[str, Any] | None) -> dict[str, Any]:
        return self._event(request_id, state, "error", "未执行", False, message, result="ERROR", display_state="error")

    def _state_summary(self, state: dict[str, Any]) -> str:
        p, a = state["player_state"], state["aura_state"]
        location = self._location(state)["name"]
        summary = f"位置={location}; 阶段={self._phase_label(state)}; 玩家={p['hp']}/{p['max_hp']} HP 攻击{p['total_attack']}; AURA={a['hp']}/{a['max_hp']} HP 攻击{a['total_attack']}"
        combat = state.get("combat_state")
        if combat:
            summary += f"; {combat['monster_name']}={combat['monster_hp']}/{combat['monster_max_hp']} HP"
        return summary


def format_event(event: dict[str, Any]) -> str:
    """Format one event for the outer Agent's compact tool-result budget."""
    result = event.get("result")
    if result == "AURA_DECISION_REQUIRED":
        c = event["public_state"].get("combat", {})
        return (
            f"AURA_DECISION_REQUIRED v1 token={event['decision_token']} action=attack target={event['legal_targets'][0]} "
            f"monster_hp={c.get('monster_hp', '?')}/{c.get('monster_max_hp', '?')}。请立即再次调用 run_skill_code，提交 "
            f"{{\"type\":\"AURA_ACTION\",\"decision_token\":\"{event['decision_token']}\",\"action\":\"attack\",\"target\":\"{event['legal_targets'][0]}\"}}。"
        )
    if result == "TURN_RESOLVED":
        return (
            f"{event.get('narration', '')}\n"
            f"【权威游戏状态，回复不得改写数值】{event.get('state_summary', '')}\n"
            f"可选：{'、'.join(event.get('choices', [])[:5])}"
        )
    text = str(event.get("narration", ""))
    if event.get("result_label") not in {"自由交谈", "环境观察", "调查结果", "队伍状态", "怪物属性", "当前地图"}:
        text = f"{event.get('result_label', '')}：{text}"
    if event.get("result") == "ERROR":
        return f"错误：{text}"
    if event.get("state_changed") and "```" not in text and "| 属性 |" not in text:
        text += f"\n{event.get('state_summary', '')}"
    choices = event.get("choices") or []
    if choices and "```" not in text and "| 属性 |" not in text:
        text += f"\n可选：{'、'.join(choices[:5])}"
    return text
