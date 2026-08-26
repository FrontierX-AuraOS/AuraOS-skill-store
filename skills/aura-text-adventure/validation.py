"""Strict invariants for persisted AURA Text Adventure snapshots."""

from __future__ import annotations

import re
import uuid
from typing import Any


QUEST_EXPLORE = "探索第一层并确认通往下层的条件。"
QUEST_MONSTER = "击败已发现的守门石像，解锁下层石门。"
QUEST_GATE = "前往已解锁的下层石门。"
QUEST_COMPLETE = "第一关已完成；第二层尚未提供。"


class StateValidationError(ValueError):
    pass


def expected_quest(state: dict[str, Any], content: dict[str, Any]) -> str:
    if state.get("status") == "victory":
        return QUEST_COMPLETE
    flags = state.get("world_flags") or {}
    if flags.get("next_level_unlocked"):
        return QUEST_GATE
    level = content["levels"]["level-1"]
    visited = set(state.get("visited_locations") or [])
    monster_known = any(
        (item.get("hidden") or {}).get("monster_id") == level["target_monster_id"]
        and item.get("id") in visited
        for item in level["locations"]
    )
    return QUEST_MONSTER if monster_known else QUEST_EXPLORE


def _fail(message: str) -> None:
    raise StateValidationError(message)


def validate_game_state(state: dict[str, Any], content: dict[str, Any]) -> None:
    if not isinstance(state, dict):
        _fail("存档不是对象。")
    if state.get("schema_version") != 1 or state.get("world_version") != "dungeon-1-v1":
        _fail("存档版本不兼容。")
    required = {
        "save_id", "profile_id", "status", "current_level", "party_location",
        "visited_locations", "world_flags", "completed_events", "collected_items",
        "player_state", "aura_state", "inventory", "active_quest", "combat_state",
        "pending_aura_decision", "turn_number", "event_sequence", "random_seed",
        "random_state", "request_history",
    }
    if not required.issubset(state):
        _fail("存档缺少必要字段。")
    try:
        uuid.UUID(str(state["save_id"]))
    except (ValueError, AttributeError):
        _fail("存档 ID 无效。")
    if state.get("profile_id") != "default" or state.get("current_level") != "level-1":
        _fail("存档档案或关卡标识不受支持。")

    level = content["levels"]["level-1"]
    locations = {item["id"]: item for item in level["locations"]}
    location = state.get("party_location")
    current = next((item for item in level["locations"] if item["coord"] == location), None)
    if not current or current.get("blocked"):
        _fail("存档地图位置无效。")
    visited = state.get("visited_locations")
    if not isinstance(visited, list) or len(visited) != len(set(visited)):
        _fail("已发现地图列表无效。")
    if current["id"] not in visited or not set(visited).issubset(locations):
        _fail("已发现地图包含未知格或缺少当前位置。")

    for key in ("turn_number", "event_sequence"):
        if not isinstance(state.get(key), int) or state[key] < 0:
            _fail(f"存档字段 {key} 无效。")
    if state.get("random_seed") != 24 or state.get("random_state") != {
        "algorithm": "deterministic-v1", "seed": 24
    }:
        _fail("随机状态无效。")
    if state.get("status") not in {"exploring", "combat", "victory"}:
        _fail("存档阶段无效。")

    flags = state.get("world_flags")
    if not isinstance(flags, dict) or set(flags) != {
        "chest_opened", "monster_defeated", "level_complete", "next_level_unlocked"
    } or not all(isinstance(value, bool) for value in flags.values()):
        _fail("存档世界标志无效。")
    if not (flags["monster_defeated"] == flags["level_complete"] == flags["next_level_unlocked"]):
        _fail("关卡完成标志不一致。")
    if state["status"] == "victory" and (
        not flags["next_level_unlocked"] or location != level["next_level_entrance"]
    ):
        _fail("结局阶段与下层入口状态不一致。")
    if state.get("active_quest") != expected_quest(state, content):
        _fail("当前任务与已发现进度不一致。")

    completed = state.get("completed_events")
    collected = state.get("collected_items")
    if not isinstance(completed, list) or len(completed) != len(set(completed)):
        _fail("已完成事件列表无效。")
    if not isinstance(collected, list) or len(collected) != len(set(collected)):
        _fail("已收集物品列表无效。")
    expected_events = set()
    if flags["chest_opened"]:
        expected_events.add("open:armory-chest")
    if flags["monster_defeated"]:
        expected_events.add("defeat:stone-sentinel")
    if set(completed) != expected_events:
        _fail("一次性事件与世界标志不一致。")
    expected_items = ["common-longsword"] if flags["chest_opened"] else []
    if collected != expected_items:
        _fail("物品归属与宝箱状态不一致。")
    expected_inventory = ([{
        "item_id": "common-longsword", "name": "普通长剑",
        "slot": "weapon", "attack_bonus": 2,
    }] if flags["chest_opened"] else [])
    if state.get("inventory") != expected_inventory:
        _fail("背包内容与已收集物品不一致。")

    for key in ("player_state", "aura_state"):
        actor = state.get(key)
        if not isinstance(actor, dict):
            _fail("角色状态无效。")
        if not isinstance(actor.get("hp"), int) or not 0 <= actor["hp"] <= 10:
            _fail("角色生命值超出范围。")
        if actor.get("max_hp") != 10 or actor.get("level") != 1 or actor.get("next_xp") != 100:
            _fail("角色基础成长值无效。")
        expected_xp = 50 if flags["monster_defeated"] else 0
        if actor.get("xp") != expected_xp or actor.get("base_attack") != 3:
            _fail("角色经验或基础攻击无效。")
        slots = actor.get("equipment_slots")
        if not isinstance(slots, dict) or set(slots) != {"weapon", "head", "body", "accessory"}:
            _fail("角色装备插槽无效。")
        expected_weapon = "common-longsword" if key == "player_state" and flags["chest_opened"] else None
        if slots != {"weapon": expected_weapon, "head": None, "body": None, "accessory": None}:
            _fail("角色装备与游戏进度不一致。")
        expected_bonus = 2 if expected_weapon else 0
        if actor.get("attack_bonus") != expected_bonus or actor.get("total_attack") != 3 + expected_bonus:
            _fail("角色攻击加成无效。")
        if actor.get("skill_slots") != [] or actor.get("resources") != {} or actor.get("statuses") != []:
            _fail("第一版不能包含未实现的技能、资源或状态效果。")

    combat = state.get("combat_state")
    pending = state.get("pending_aura_decision")
    if state["status"] == "combat":
        if flags["monster_defeated"] or not isinstance(combat, dict):
            _fail("战斗阶段与关卡完成状态冲突。")
        exact = {
            "monster_id": "stone-sentinel", "monster_name": "守门石像",
            "monster_max_hp": 12, "monster_attack": 2, "monster_level": 1,
        }
        if any(combat.get(key) != value for key, value in exact.items()):
            _fail("战斗中的目标怪物属性被篡改。")
        if not isinstance(combat.get("monster_hp"), int) or not 0 < combat["monster_hp"] <= 12:
            _fail("怪物生命值无效。")
        if combat.get("phase") not in {"player", "aura"} or combat.get("next_target") not in {"player", "aura"}:
            _fail("战斗行动阶段或目标顺序无效。")
        if not isinstance(combat.get("round"), int) or combat["round"] < 0:
            _fail("战斗回合号无效。")
        if (combat["phase"] == "aura") != (pending is not None):
            _fail("AURA 决策与战斗阶段不一致。")
    elif combat is not None or pending is not None:
        _fail("非战斗阶段不能携带战斗或 AURA 决策状态。")

    if pending is not None:
        if not isinstance(pending, dict):
            _fail("未决 AURA 行动无效。")
        if pending.get("schema_version") != 1 or pending.get("state_sequence") != state["event_sequence"]:
            _fail("AURA 决策版本或状态序号无效。")
        if not re.fullmatch(r"d\d+-[0-9a-f]{8}", str(pending.get("token", ""))):
            _fail("AURA 决策令牌无效。")
        if pending.get("legal_actions") != ["attack"] or pending.get("legal_targets") != ["stone-sentinel"]:
            _fail("未决 AURA 动作集合无效。")
        if not isinstance(pending.get("created_at"), int) or pending["created_at"] <= 0:
            _fail("AURA 决策时间无效。")

    history = state.get("request_history")
    if not isinstance(history, list) or len(history) > 64:
        _fail("存档请求历史无效。")
    for record in history:
        if not isinstance(record, dict) or set(record) != {"request_id", "event"}:
            _fail("存档请求记录无效。")
        request_id = record.get("request_id")
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", request_id):
            _fail("存档请求标识无效。")
        if not isinstance(record.get("event"), dict) or record["event"].get("request_id") != request_id:
            _fail("存档请求事件无效。")
