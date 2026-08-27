from __future__ import annotations

import asyncio
import ast
import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

from engine import (  # noqa: E402
    AdventureEngine,
    AdventureError,
    DECISION_TTL_MS,
    RobotDisplaySink,
    SaveError,
    _compact_json,
    format_event,
    render_ascii_grid,
)
from storage import StorageError  # noqa: E402


def game_projection(state: dict) -> dict:
    projected = deepcopy(state)
    projected.pop("request_history", None)
    return projected


def aura_action(event: dict, *, token: str | None = None, action: str = "attack", target: str = "stone-sentinel") -> str:
    return json.dumps(
        {
            "type": "AURA_ACTION",
            "decision_token": token or event["decision_token"],
            "action": action,
            "target": target,
        }
    )


class EngineCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.engine = AdventureEngine(self.data_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def start(self) -> dict:
        return self.engine.handle("开始冒险", request_id="start")

    def move_to_chest(self) -> None:
        self.start()
        self.engine.handle("向西", request_id="west-1")
        self.engine.handle("往西走", request_id="west-2")

    def move_to_combat(self, *, with_sword: bool = False) -> dict:
        self.start()
        if with_sword:
            self.engine.handle("向西", request_id="chest-west-1")
            self.engine.handle("向西", request_id="chest-west-2")
            self.engine.handle("打开宝箱", request_id="open-chest")
            self.engine.handle("向东", request_id="return-east-1")
            self.engine.handle("向东", request_id="return-east-2")
        self.engine.handle("朝北前进", request_id="north-1")
        return self.engine.handle("向北", request_id="north-2")


class ContentAndMapTests(EngineCase):
    def test_level_is_complete_5x5_centered_and_reachable(self) -> None:
        level = self.engine.content["levels"]["level-1"]
        self.assertEqual((level["width"], level["height"]), (5, 5))
        self.assertEqual(level["spawn"], [2, 2])
        self.assertEqual(len(level["locations"]), 25)
        self.assertEqual({tuple(x["coord"]) for x in level["locations"]}, {(x, y) for y in range(5) for x in range(5)})
        reachable = self.engine._reachable_from(level, "c-2-2")
        self.assertTrue(set(self.engine._important_location_ids(level)).issubset(reachable))

    def test_chest_has_route_that_avoids_target_monster(self) -> None:
        level = self.engine.content["levels"]["level-1"]
        locations = {x["id"]: x for x in level["locations"]}
        monster_cell = next(x["id"] for x in level["locations"] if (x.get("hidden") or {}).get("monster_id"))
        chest_cell = next(x["id"] for x in level["locations"] if (x.get("hidden") or {}).get("chest_id"))
        seen = {monster_cell}
        queue = ["c-2-2"]
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            queue.extend((locations[current].get("connections") or {}).values())
        self.assertIn(chest_cell, seen)

    def test_versioned_content_declares_only_first_level(self) -> None:
        content = self.engine.content
        self.assertEqual(content["world_version"], "dungeon-1-v1")
        self.assertEqual(set(content["levels"]), {"level-1"})
        self.assertEqual(content["levels"]["level-1"]["next_level_id"], "level-2")
        self.assertEqual(content["items"]["common-longsword"]["attack_bonus"], 2)

    def test_grid_snapshots_cover_1x1_non_rectangular_and_5x5(self) -> None:
        self.assertEqual(render_ascii_grid(1, 1, {(0, 0): "P"}), "```text\n      1 \nA  [P]\n```")
        non_rect = render_ascii_grid(3, 2, {(0, 0): "P", (1, 0): ".", (1, 1): "E"})
        self.assertIn("A  [P] [.] [#]", non_rect)
        self.assertIn("B  [#] [E] [#]", non_rect)
        maximum = render_ascii_grid(5, 5, {(0, 0): "C", (4, 4): "M"})
        self.assertEqual(sum(1 for line in maximum.splitlines() if line[:1] in "ABCDE"), 5)
        self.assertIn("[C]", maximum)
        self.assertIn("[M]", maximum)

    def test_grid_rejects_oversize_and_unicode_markers(self) -> None:
        with self.assertRaises(AdventureError):
            render_ascii_grid(6, 5, {})
        with self.assertRaises(AdventureError):
            render_ascii_grid(1, 1, {(0, 0): "🧭"})

    def test_initial_map_does_not_leak_hidden_objects(self) -> None:
        event = self.start()
        self.assertEqual(event["public_state"]["party_location"], [2, 2])
        rendered = self.engine.handle("查看地图", request_id="map")["narration"]
        grid = rendered.split("```", 2)[1]
        self.assertNotIn("[M]", grid)
        self.assertNotIn("[C]", grid)
        self.assertNotIn("[E]", grid)
        self.assertIn("[P]", grid)

    def test_discovered_objects_and_walls_remain_on_map(self) -> None:
        self.start()
        self.engine.handle("向西", request_id="w1")
        discovered = self.engine.handle("查看地图", request_id="map-1")["narration"]
        self.assertIn("[C]", discovered)
        self.assertIn("[#]", discovered)
        self.engine.handle("向东", request_id="e1")
        remembered = self.engine.handle("查看地图", request_id="map-2")["narration"]
        self.assertIn("[C]", remembered)


class ParsingAndExplorationTests(EngineCase):
    def test_new_game_output_contains_required_snapshot(self) -> None:
        event = self.start()
        self.assertTrue(event["state_changed"])
        self.assertIn("回声中庭", event["narration"])
        self.assertIn("10/10", event["narration"])
        self.assertGreaterEqual(len(event["choices"]), 2)
        self.assertLessEqual(len(event["choices"]), 5)
        self.assertEqual(event["public_state"]["party_location"], [2, 2])

    def test_existing_auto_save_requires_new_game_confirmation(self) -> None:
        self.start()
        self.engine.handle("向西", request_id="move")
        before = game_projection(self.engine._load_slot("auto"))
        response = self.engine.handle("开始新游戏", request_id="new-again")
        self.assertEqual(response["result_label"], "需要确认")
        self.assertEqual(game_projection(self.engine._load_slot("auto")), before)
        confirmed = self.engine.handle("确认开始新游戏", request_id="confirm-new")
        self.assertEqual(confirmed["public_state"]["party_location"], [2, 2])

    def test_direction_synonyms_and_named_adjacent_location(self) -> None:
        self.start()
        self.engine.handle("往西走", request_id="synonym")
        self.assertEqual(self.engine._load_slot("auto")["party_location"], [1, 2])
        event = self.engine.handle("去旧军械库", request_id="named")
        self.assertTrue(event["state_changed"])
        self.assertEqual(event["public_state"]["party_location"], [0, 2])

    def test_ambiguous_and_illegal_move_do_not_change_game(self) -> None:
        self.start()
        before = game_projection(self.engine._load_slot("auto"))
        ambiguous = self.engine.handle("向北还是向西", request_id="ambiguous")
        self.assertEqual(ambiguous["result_label"], "需要澄清")
        self.assertFalse(ambiguous["state_changed"])
        self.assertEqual(game_projection(self.engine._load_slot("auto")), before)
        self.engine.handle("向南", request_id="south-1")
        self.engine.handle("向南", request_id="south-2")
        end = game_projection(self.engine._load_slot("auto"))
        illegal = self.engine.handle("向南", request_id="blocked")
        self.assertFalse(illegal["state_changed"])
        self.assertEqual(game_projection(self.engine._load_slot("auto")), end)

    def test_queries_and_conversation_are_state_neutral(self) -> None:
        self.start()
        for index, command in enumerate(("观察", "调查这里", "队伍状态", "查看地图", "我们该往哪走", "和 AURA 聊天")):
            before = game_projection(self.engine._load_slot("auto"))
            event = self.engine.handle(command, request_id=f"query-{index}")
            self.assertFalse(event["state_changed"], command)
            self.assertEqual(game_projection(self.engine._load_slot("auto")), before, command)

    def test_advice_does_not_reveal_an_undiscovered_chest(self) -> None:
        self.start()
        hidden = self.engine.handle("我们该往哪走", request_id="advice-hidden")["narration"]
        self.assertNotIn("军械库", hidden)
        self.assertNotIn("长剑", hidden)
        self.engine.handle("向西", request_id="discover-west")
        known = self.engine.handle("询问建议", request_id="advice-known")["narration"]
        self.assertIn("军械库", known)

    def test_status_tables_are_authoritative_and_compact(self) -> None:
        self.move_to_chest()
        before = self.engine.handle("查看状态", request_id="before")["narration"]
        self.assertIn("| 基础攻击 | 3 | 3 |", before)
        self.assertIn("| 装备加成 | +0 | +0 |", before)
        self.assertIn("| 武器 | 空 | 空 |", before)
        self.engine.handle("打开宝箱", request_id="open")
        after = self.engine.handle("查看装备", request_id="after")["narration"]
        self.assertIn("| 装备加成 | +2 | +0 |", after)
        self.assertIn("| 总攻击 | 5 | 3 |", after)
        self.assertIn("| 武器 | 普通长剑 | 空 |", after)
        self.assertLessEqual(len(format_event(self.engine.handle("查看状态", request_id="compact"))), 400)

    def test_monster_query_requires_discovery_then_remains_available(self) -> None:
        self.start()
        initial_status = self.engine.handle("查看状态", request_id="initial-status")["narration"]
        self.assertNotIn("守门石像", initial_status)
        hidden = self.engine.handle("查看怪物属性", request_id="hidden")
        self.assertEqual(hidden["result_label"], "怪物未知")
        self.engine.handle("向北", request_id="north-1")
        known_status = self.engine.handle("查看状态", request_id="known-status")["narration"]
        self.assertIn("守门石像", known_status)
        discovered = self.engine.handle("怪物属性", request_id="known")
        self.assertIn("守门石像", discovered["narration"])
        self.engine.handle("向南", request_id="back")
        remembered = self.engine.handle("怪物属性", request_id="remembered")
        self.assertIn("12/12", remembered["narration"])

    def test_chest_is_idempotent_and_use_item_is_honest(self) -> None:
        self.move_to_chest()
        first = self.engine.handle("打开宝箱", request_id="open-1")
        state = self.engine._load_slot("auto")
        self.assertTrue(first["state_changed"])
        self.assertEqual(state["player_state"]["total_attack"], 5)
        self.assertEqual(len(state["inventory"]), 1)
        second = self.engine.handle("再次打开宝箱", request_id="open-2")
        state = self.engine._load_slot("auto")
        self.assertFalse(second["state_changed"])
        self.assertEqual(len(state["inventory"]), 1)
        self.assertEqual(state["player_state"]["attack_bonus"], 2)
        use = self.engine.handle("使用物品", request_id="use")
        self.assertFalse(use["state_changed"])
        self.assertIn("没有可消耗道具", use["narration"])


class CombatTests(EngineCase):
    def test_valid_two_step_round_and_fixed_order(self) -> None:
        self.move_to_combat(with_sword=True)
        decision = self.engine.handle("普通攻击", request_id="player-1")
        self.assertEqual(decision["result"], "AURA_DECISION_REQUIRED")
        self.assertEqual(decision["public_state"]["combat"]["monster_hp"], 7)
        resolved = self.engine.handle(aura_action(decision), request_id="aura-1")
        self.assertEqual(resolved["result"], "TURN_RESOLVED")
        self.assertEqual(resolved["public_state"]["combat"]["monster_hp"], 4)
        self.assertEqual(resolved["public_state"]["player"]["hp"], 8)
        self.assertEqual(resolved["public_state"]["aura"]["hp"], 10)
        self.assertIn("守门石像=4/12 HP", resolved["state_summary"])
        self.assertIn("【权威游戏状态，回复不得改写数值】", format_event(resolved))

    def test_forged_action_does_not_settle_then_new_player_action_falls_back(self) -> None:
        self.move_to_combat()
        decision = self.engine.handle("普通攻击", request_id="player")
        before = game_projection(self.engine._load_slot("auto"))
        forged = self.engine.handle(aura_action(decision, token="forged"), request_id="forged")
        self.assertEqual(forged["result"], "ERROR")
        self.assertEqual(game_projection(self.engine._load_slot("auto")), before)
        fallback = self.engine.handle("普通攻击", request_id="fallback")
        self.assertEqual(fallback["result"], "TURN_RESOLVED")
        self.assertIn("兜底", fallback["narration"])
        self.assertIn("新的玩家行动未执行", fallback["narration"])
        self.assertEqual(fallback["public_state"]["combat"]["monster_hp"], 6)
        self.assertIn("守门石像=6/12 HP", format_event(fallback))
        self.assertLessEqual(len(format_event(fallback)), 400)

    def test_pending_queries_and_conversation_do_not_advance_combat(self) -> None:
        self.move_to_combat()
        decision = self.engine.handle("普通攻击", request_id="player")
        before = game_projection(self.engine._load_slot("auto"))
        for index, command in enumerate((
            "查看状态", "查看地图", "查看怪物属性", "观察", "调查这里",
            "和 AURA 聊天", "我们商量一下", "帮助",
        )):
            event = self.engine.handle(command, request_id=f"pending-query-{index}")
            self.assertFalse(event["state_changed"], command)
            self.assertNotEqual(event["result"], "TURN_RESOLVED", command)
            self.assertIn("提交 AURA_ACTION", event["choices"], command)
            self.assertEqual(game_projection(self.engine._load_slot("auto")), before, command)
        resolved = self.engine.handle(aura_action(decision), request_id="aura-after-queries")
        self.assertEqual(resolved["result"], "TURN_RESOLVED")
        self.assertEqual(resolved["public_state"]["player"]["hp"], 8)

    def test_pending_save_and_exit_preserve_exact_checkpoint(self) -> None:
        self.move_to_combat()
        decision = self.engine.handle("普通攻击", request_id="player")
        before = game_projection(self.engine._load_slot("auto"))
        saved = self.engine.handle("存档 1", request_id="pending-save")
        self.assertEqual(saved["result_label"], "已存档")
        self.assertIn("提交 AURA_ACTION", saved["choices"])
        self.assertEqual(game_projection(self.engine._load_slot("manual_1")), before)
        self.assertEqual(game_projection(self.engine._load_slot("auto")), before)
        exited = self.engine.handle("退出冒险", request_id="pending-exit")
        self.assertEqual(exited["result_label"], "已保存退出")
        restored = AdventureEngine(self.data_dir)._load_slot("auto")
        self.assertEqual(game_projection(restored), before)
        self.assertEqual(restored["pending_aura_decision"]["token"], decision["decision_token"])

    def test_invalid_action_and_repeated_token_never_double_settle(self) -> None:
        self.move_to_combat()
        decision = self.engine.handle("普通攻击", request_id="player")
        invalid = self.engine.handle(aura_action(decision, action="defend"), request_id="invalid")
        self.assertEqual(invalid["result"], "ERROR")
        resolved = self.engine.handle(aura_action(decision), request_id="valid")
        after = game_projection(self.engine._load_slot("auto"))
        repeated = self.engine.handle(aura_action(decision), request_id="repeat")
        self.assertEqual(repeated["result"], "ERROR")
        self.assertEqual(game_projection(self.engine._load_slot("auto")), after)
        self.assertEqual(resolved["public_state"]["player"]["hp"], 8)

    def test_expired_token_uses_engine_fallback(self) -> None:
        self.move_to_combat()
        decision = self.engine.handle("普通攻击", request_id="player")
        state = self.engine._load_slot("auto")
        state["pending_aura_decision"]["created_at"] -= DECISION_TTL_MS + 1
        self.engine._write_state(state, allow_replace=True)
        resolved = self.engine.handle(aura_action(decision), request_id="expired")
        self.assertEqual(resolved["result"], "TURN_RESOLVED")
        self.assertIn("兜底", resolved["narration"])

    def test_pending_decision_survives_process_restart(self) -> None:
        self.move_to_combat()
        decision = self.engine.handle("普通攻击", request_id="player")
        restarted = AdventureEngine(self.data_dir)
        restored = restarted._load_slot("auto")
        self.assertEqual(restored["pending_aura_decision"]["token"], decision["decision_token"])
        resolved = restarted.handle(aura_action(decision), request_id="resume")
        self.assertEqual(resolved["result"], "TURN_RESOLVED")

    def test_down_characters_skip_and_monster_targets_survivor(self) -> None:
        self.move_to_combat()
        state = self.engine._load_slot("auto")
        state["player_state"]["hp"] = 0
        self.engine._write_state(state, allow_replace=True)
        decision = self.engine.handle("普通攻击", request_id="down-player")
        self.assertEqual(decision["result"], "AURA_DECISION_REQUIRED")
        self.assertEqual(decision["public_state"]["combat"]["monster_hp"], 12)
        resolved = self.engine.handle(aura_action(decision), request_id="aura")
        self.assertEqual(resolved["public_state"]["aura"]["hp"], 8)
        self.assertEqual(resolved["public_state"]["player"]["hp"], 0)

    def test_down_aura_skips_without_requesting_model(self) -> None:
        self.move_to_combat()
        state = self.engine._load_slot("auto")
        state["aura_state"]["hp"] = 0
        self.engine._write_state(state, allow_replace=True)
        resolved = self.engine.handle("普通攻击", request_id="aura-down")
        self.assertEqual(resolved["result"], "TURN_RESOLVED")
        self.assertIn("跳过行动", resolved["narration"])
        self.assertEqual(resolved["public_state"]["combat"]["monster_hp"], 9)
        self.assertEqual(resolved["public_state"]["player"]["hp"], 8)

    def test_total_defeat_restores_party_and_preserves_discovery_and_items(self) -> None:
        self.move_to_combat(with_sword=True)
        state = self.engine._load_slot("auto")
        discovered = list(state["visited_locations"])
        state["player_state"]["hp"] = 0
        state["aura_state"]["hp"] = 2
        state["combat_state"]["next_target"] = "aura"
        self.engine._write_state(state, allow_replace=True)
        decision = self.engine.handle("普通攻击", request_id="skip-player")
        defeated = self.engine.handle(aura_action(decision), request_id="last-aura")
        self.assertEqual(defeated["result_label"], "全队战败")
        restored = self.engine._load_slot("auto")
        self.assertEqual(restored["party_location"], [2, 2])
        self.assertEqual(restored["player_state"]["hp"], 10)
        self.assertEqual(restored["aura_state"]["hp"], 10)
        self.assertTrue(set(discovered).issubset(restored["visited_locations"]))
        self.assertTrue(restored["world_flags"]["chest_opened"])
        self.assertEqual(restored["player_state"]["total_attack"], 5)

    def test_victory_reward_and_no_dead_monster_counterattack(self) -> None:
        self.move_to_combat(with_sword=True)
        first = self.engine.handle("普通攻击", request_id="p1")
        self.engine.handle(aura_action(first), request_id="a1")
        victory = self.engine.handle("普通攻击", request_id="p2")
        self.assertEqual(victory["result_label"], "第一关完成")
        self.assertEqual(victory["public_state"]["player"]["hp"], 8)
        self.assertEqual(victory["public_state"]["player"]["xp"], 50)
        self.assertEqual(victory["public_state"]["aura"]["xp"], 50)
        self.assertTrue(victory["public_state"]["world_flags"]["next_level_unlocked"])


class PersistenceTests(EngineCase):
    def test_only_four_slots_are_exposed_and_manual_overwrite_requires_confirmation(self) -> None:
        self.start()
        self.engine.handle("存档 1", request_id="save-1")
        self.engine.handle("存档 2", request_id="save-2")
        self.engine.handle("存档 3", request_id="save-3")
        self.assertEqual({x["slot_name"] for x in self.engine.list_saves()}, {"auto", "manual_1", "manual_2", "manual_3"})
        self.engine.handle("向西", request_id="move")
        before = self.engine._load_slot("manual_1")
        prompt = self.engine.handle("存档 1", request_id="overwrite")
        self.assertEqual(prompt["result_label"], "需要确认")
        self.assertEqual(game_projection(self.engine._load_slot("manual_1")), game_projection(before))
        self.engine.handle("确认覆盖 1", request_id="confirm")
        self.assertEqual(self.engine._load_slot("manual_1")["party_location"], [1, 2])
        listing = self.engine.handle("查看存档", request_id="list")["narration"]
        self.assertEqual(listing.count("已有存档"), 4)

    def test_manual_load_replaces_auto_with_exact_snapshot(self) -> None:
        self.start()
        self.engine.handle("存档 1", request_id="save")
        self.engine.handle("向西", request_id="move")
        loaded = self.engine.handle("读档 1", request_id="load")
        self.assertEqual(loaded["public_state"]["party_location"], [2, 2])
        self.assertEqual(self.engine._load_slot("auto")["party_location"], [2, 2])

    def test_exit_and_restart_restore_exact_exploration_and_combat_checkpoints(self) -> None:
        self.start()
        self.engine.handle("向西", request_id="move")
        expected = game_projection(self.engine._load_slot("auto"))
        self.engine.handle("退出冒险", request_id="exit")
        restarted = AdventureEngine(self.data_dir)
        restarted.handle("继续冒险", request_id="continue")
        self.assertEqual(game_projection(restarted._load_slot("auto")), expected)

        # A separate save verifies an unresolved combat checkpoint.
        other_dir = self.data_dir / "combat"
        combat_engine = AdventureEngine(other_dir)
        combat_engine.handle("开始冒险", request_id="s")
        combat_engine.handle("向北", request_id="n1")
        combat_engine.handle("向北", request_id="n2")
        decision = combat_engine.handle("普通攻击", request_id="p")
        combat_engine.handle("退出冒险", request_id="x")
        combat_restart = AdventureEngine(other_dir)
        pending = combat_restart._load_slot("auto")["pending_aura_decision"]
        self.assertEqual(pending["token"], decision["decision_token"])

    def test_delete_auto_requires_confirmation_and_does_not_recreate_it(self) -> None:
        self.start()
        prompt = self.engine.handle("删除存档", request_id="delete")
        self.assertEqual(prompt["result_label"], "需要确认")
        self.assertIsNotNone(self.engine._load_slot("auto"))
        self.engine.handle("确认删除 auto", request_id="delete-confirm")
        self.assertIsNone(self.engine._load_slot("auto"))

    def test_export_import_round_trip_across_data_directories(self) -> None:
        self.move_to_chest()
        self.engine.handle("打开宝箱", request_id="open")
        self.engine.handle("导出存档 MySave.JSON", request_id="export")
        exported = self.data_dir / "exports" / "MySave.JSON"
        self.assertTrue(exported.is_file())
        payload = json.loads(exported.read_text(encoding="utf-8"))
        self.assertEqual(payload["state_sha256"], hashlib.sha256(_compact_json(payload["state"]).encode("utf-8")).hexdigest())

        target_dir = self.data_dir / "another-device"
        imported_engine = AdventureEngine(target_dir)
        imported = imported_engine.handle(f"导入存档 {exported}", request_id="import")
        self.assertEqual(imported["result_label"], "导入完成")
        self.assertEqual(imported_engine._load_slot("auto")["player_state"]["total_attack"], 5)
        history = imported_engine._load_slot("auto")["request_history"]
        self.assertEqual([item["request_id"] for item in history], ["import"])

    def test_tampered_or_incompatible_import_preserves_existing_save(self) -> None:
        self.start()
        self.engine.handle("导出存档", request_id="export")
        path = self.data_dir / "exports" / "aura-text-adventure-save.json"
        original = game_projection(self.engine._load_slot("auto"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["state"]["party_location"] = [99, 99]
        path.write_text(json.dumps(payload), encoding="utf-8")
        rejected = self.engine.handle(f"导入存档 {path}", request_id="bad-hash")
        self.assertEqual(rejected["result"], "ERROR")
        self.assertEqual(game_projection(self.engine._load_slot("auto")), original)

        payload["state"]["party_location"] = [2, 2]
        payload["state"]["schema_version"] = 0
        payload["state_sha256"] = hashlib.sha256(_compact_json(payload["state"]).encode("utf-8")).hexdigest()
        path.write_text(json.dumps(payload), encoding="utf-8")
        incompatible = self.engine.handle(f"导入存档 {path}", request_id="bad-version")
        self.assertEqual(incompatible["result"], "ERROR")
        self.assertEqual(game_projection(self.engine._load_slot("auto")), original)

    def test_corrupt_auto_row_is_preserved_and_recovery_commands_remain_available(self) -> None:
        self.start()
        self.engine.handle("存档 1", request_id="manual-before-corruption")
        with self.engine._connect() as conn:
            conn.execute("UPDATE saves SET state_json='{' WHERE profile_id='default' AND slot_name='auto'")
        blocked = self.engine.handle("向西", request_id="blocked-by-corruption")
        self.assertEqual(blocked["result"], "ERROR")
        self.assertIn("原数据未被覆盖", blocked["narration"])
        with self.engine._connect() as conn:
            raw = conn.execute("SELECT state_json FROM saves WHERE slot_name='auto'").fetchone()[0]
        self.assertEqual(raw, "{")
        listing = self.engine.handle("查看存档", request_id="list-corrupt")["narration"]
        self.assertIn("手动存档 1", listing)
        recovered = self.engine.handle("读档 1", request_id="recover-manual")
        self.assertEqual(recovered["result_label"], "继续冒险")
        self.assertEqual(self.engine._load_slot("auto")["party_location"], [2, 2])

    def test_self_consistent_malicious_import_cannot_forge_game_facts(self) -> None:
        self.move_to_combat(with_sword=False)
        original = game_projection(self.engine._load_slot("auto"))
        self.engine.handle("导出存档", request_id="export-combat")
        path = self.data_dir / "exports" / "aura-text-adventure-save.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["state"]["combat_state"]["monster_attack"] = 999
        payload["state_sha256"] = hashlib.sha256(
            _compact_json(payload["state"]).encode("utf-8")
        ).hexdigest()
        path.write_text(json.dumps(payload), encoding="utf-8")
        rejected = self.engine.handle(f"导入存档 {path}", request_id="forged-facts")
        self.assertEqual(rejected["result"], "ERROR")
        self.assertIn("目标怪物属性被篡改", rejected["narration"])
        self.assertEqual(game_projection(self.engine._load_slot("auto")), original)

        payload["state"]["combat_state"]["monster_attack"] = 2
        payload["state"]["active_quest"] = "伪造任务"
        payload["state_sha256"] = hashlib.sha256(
            _compact_json(payload["state"]).encode("utf-8")
        ).hexdigest()
        path.write_text(json.dumps(payload), encoding="utf-8")
        rejected = self.engine.handle(f"导入存档 {path}", request_id="forged-quest")
        self.assertIn("当前任务与已发现进度不一致", rejected["narration"])
        self.assertEqual(game_projection(self.engine._load_slot("auto")), original)

    def test_export_path_is_confined_to_skill_data_directory(self) -> None:
        self.start()
        self.engine.handle("导出存档 ../../outside.json", request_id="export")
        self.assertTrue((self.data_dir / "exports" / "outside.json").is_file())
        self.assertFalse((self.data_dir.parent / "outside.json").exists())

    def test_request_idempotency_returns_same_event_without_reapplying_action(self) -> None:
        self.start()
        first = self.engine.handle("向西", request_id="same-request")
        state = game_projection(self.engine._load_slot("auto"))
        repeated = self.engine.handle("向西", request_id="same-request")
        self.assertEqual(repeated, first)
        self.assertEqual(game_projection(self.engine._load_slot("auto")), state)

    def test_sqlite_wal_user_version_and_concurrent_serialization(self) -> None:
        self.start()
        with self.engine._connect() as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)

        errors: list[Exception] = []
        state = self.engine._load_slot("auto")

        def writer(index: int) -> None:
            try:
                AdventureEngine(self.data_dir)._write_state(deepcopy(state), f"manual_{(index % 3) + 1}")
            except Exception as exc:  # pragma: no cover - assertion below reports it
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.engine.list_saves()), 4)

    def test_stale_same_sequence_snapshot_cannot_overwrite_committed_gameplay(self) -> None:
        self.start()
        base = self.engine._load_slot("auto")
        west = deepcopy(base)
        west["party_location"] = [1, 2]
        west["turn_number"] += 1
        west["event_sequence"] += 1
        east = deepcopy(base)
        east["party_location"] = [3, 2]
        east["turn_number"] += 1
        east["event_sequence"] += 1
        self.engine._write_state(west)
        with self.assertRaises(SaveError):
            self.engine._write_state(east)
        self.assertEqual(self.engine._load_slot("auto")["party_location"], [1, 2])

    def test_transaction_error_rolls_back_existing_snapshot(self) -> None:
        self.start()
        original = game_projection(self.engine._load_slot("auto"))
        with self.engine._connect() as conn:
            conn.execute("CREATE TRIGGER reject_update BEFORE UPDATE ON saves BEGIN SELECT RAISE(ABORT, 'test rollback'); END")
        changed = self.engine._load_slot("auto")
        changed["party_location"] = [1, 2]
        with self.assertRaises(SaveError):
            self.engine._write_state(changed)
        self.assertEqual(game_projection(self.engine._load_slot("auto")), original)

    def test_pre_release_primary_key_layout_is_migrated(self) -> None:
        legacy_dir = self.data_dir / "legacy"
        legacy_dir.mkdir()
        db = legacy_dir / "saves.sqlite3"
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                "CREATE TABLE saves (save_id TEXT PRIMARY KEY, profile_id TEXT, slot_name TEXT, schema_version INTEGER, world_version TEXT, state_json TEXT, created_at INTEGER, updated_at INTEGER)"
            )
            conn.commit()
        finally:
            conn.close()
        migrated = AdventureEngine(legacy_dir)
        with migrated._connect() as conn:
            primary = [row[1] for row in conn.execute("PRAGMA table_info(saves)") if row[5]]
        self.assertEqual(primary, ["profile_id", "slot_name"])


class IntegrationAndOutputTests(EngineCase):
    def test_full_new_game_to_first_floor_boundary(self) -> None:
        self.move_to_combat(with_sword=True)
        decision = self.engine.handle("普通攻击", request_id="p1")
        self.engine.handle(aura_action(decision), request_id="a1")
        self.engine.handle("普通攻击", request_id="p2")
        for index, command in enumerate(("向南", "向南", "向东", "向东")):
            final = self.engine.handle(command, request_id=f"gate-{index}")
        self.assertEqual(final["phase"], "第一关完成")
        self.assertIn("第二层内容尚未提供", final["narration"])
        self.assertEqual(self.engine._load_slot("auto")["status"], "victory")

    def test_turn_event_has_unified_text_speech_display_and_sequence(self) -> None:
        event = self.start()
        for key in ("request_id", "save_id", "sequence", "phase", "intent", "result", "state_changed", "narration", "choices", "public_state", "state_summary", "display_state", "spoken_text", "should_speak"):
            self.assertIn(key, event)
        self.assertIn(event["spoken_text"], format_event(event))
        self.assertEqual(event["display_capability"]["status"], "unavailable")
        self.assertFalse(RobotDisplaySink().emit("explore")["emitted"])

    def test_tool_results_fit_auraos_limit(self) -> None:
        events = [self.start()]
        for index, command in enumerate(("查看地图", "查看状态", "向西", "打开宝箱", "帮助", "询问建议")):
            events.append(self.engine.handle(command, request_id=f"compact-{index}"))
        self.assertTrue(all(len(format_event(event)) <= 400 for event in events))

    def test_entry_files_are_installer_compatible(self) -> None:
        manifest = (SKILL_DIR / "MANIFEST.yaml").read_text(encoding="utf-8")
        for name in ("main.py", "engine.py", "storage.py", "validation.py", "content.json"):
            self.assertIn(name, manifest)
            self.assertTrue((SKILL_DIR / name).is_file())
            self.assertLessEqual((SKILL_DIR / name).stat().st_size, 64 * 1024)
        for path in (SKILL_DIR / "main.py", SKILL_DIR / "engine.py", SKILL_DIR / "storage.py", SKILL_DIR / "validation.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_main_entry_calls_engine_and_returns_visible_event(self) -> None:
        spec = importlib.util.spec_from_file_location("adventure_entry_test", SKILL_DIR / "main.py")
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)

        class FakeEngine:
            def handle(self, task: str) -> dict:
                return self_event

        self_event = self.start()
        module.AdventureEngine = FakeEngine
        output = asyncio.run(module.run(object(), "开始冒险"))
        self.assertIn(self_event["spoken_text"], output)


if __name__ == "__main__":
    unittest.main()
