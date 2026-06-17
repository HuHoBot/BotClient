# -*- coding: utf-8 -*-

import json
from typing import Any, Mapping, cast

from ymbotpy.types.inline import Action, Button, Keyboard, KeyboardRow, Permission, RenderData
from ymbotpy.types.message import KeyboardPayload


def _NormalizeStringList(value: Any) -> list[str]:
    """把任意列表值规范为字符串列表。"""
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _NormalizePermission(data: Mapping[str, Any]) -> Permission:
    """把 JSON permission 字段转换为 Keyboard Permission。"""
    return {
        "type": int(data.get("type", 1)),
        "specify_role_ids": _NormalizeStringList(data.get("specify_role_ids", [])),
        "specify_user_ids": _NormalizeStringList(data.get("specify_user_ids", [])),
    }


def _NormalizeRenderData(data: Mapping[str, Any]) -> RenderData:
    """把 JSON render_data 字段转换为 Keyboard RenderData。"""
    label = str(data.get("label", ""))
    return {
        "label": label,
        "visited_label": str(data.get("visited_label", label)),
        "style": int(data.get("style", 1)),
    }


def _NormalizeAction(data: Mapping[str, Any]) -> Action:
    """把 JSON action 字段转换为 Keyboard Action。"""
    permission = data.get("permission", {})
    if not isinstance(permission, Mapping):
        permission = {}

    return {
        "type": int(data.get("type", 2)),
        "permission": _NormalizePermission(permission),
        "click_limit": int(data.get("click_limit", 1)),
        "data": str(data.get("data", "")),
        "at_bot_show_channel_list": bool(data.get("at_bot_show_channel_list", False)),
    }


def _NormalizeButton(data: Mapping[str, Any]) -> Button:
    """把 JSON button 字段转换为 Keyboard Button。"""
    render_data = data.get("render_data", {})
    if not isinstance(render_data, Mapping):
        render_data = {}

    action = data.get("action", {})
    if not isinstance(action, Mapping):
        action = {}

    return {
        "id": str(data.get("id", "")),
        "render_data": _NormalizeRenderData(render_data),
        "action": _NormalizeAction(action),
    }


def KeyboardFromJson(data: Any) -> Keyboard:
    """把普通 JSON 字典转换为 ymbotpy.types.inline.Keyboard。"""
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, Mapping):
        raise ValueError("Keyboard JSON 必须是对象")

    rows: list[KeyboardRow] = []
    raw_rows = data.get("rows", [])
    if not isinstance(raw_rows, list):
        raw_rows = []

    for row in raw_rows:
        if not isinstance(row, Mapping):
            continue

        raw_buttons = row.get("buttons", [])
        if not isinstance(raw_buttons, list):
            raw_buttons = []

        buttons = [_NormalizeButton(button) for button in raw_buttons if isinstance(button, Mapping)]
        rows.append({"buttons": buttons})

    return cast(Keyboard, {"rows": rows})


def KeyboardPayloadFromJson(data: Any) -> KeyboardPayload:
    """把普通 JSON 字典转换为可直接发送的 KeyboardPayload。"""
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, Mapping):
        raise ValueError("Keyboard JSON 必须是对象")

    keyboard_id = data.get("id")
    if keyboard_id is not None:
        return cast(KeyboardPayload, {"id": str(keyboard_id)})

    return cast(KeyboardPayload, {"content": KeyboardFromJson(data)})


__all__ = ["KeyboardFromJson", "KeyboardPayloadFromJson"]
