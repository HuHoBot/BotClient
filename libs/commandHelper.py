# -*- coding: utf-8 -*-

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from ymbotpy import BotAPI, logging
from ymbotpy.message import GroupMessage
from ymbotpy.types.inline import Action, Button, Keyboard, KeyboardRow, Permission, RenderData
from ymbotpy.types.message import KeyboardPayload, MarkdownPayload

from libs.basic import IsValidOpenId, IsValidQQ
from libs.chatService import ApplySensitiveFilter
from libs.configManager import ConfigManager
from libs.keyboardManager import KeyboardPayloadFromJson
from libs.markdownManager import mdManager
from libs.repositories import AdminRepositoryInstance, AuthRepositoryInstance, BindRepositoryInstance
from libs.switchAvatars import CompareQQAvatars, GenerateQQAvatarCompareImage

PERMISSION_DENIED_TEXT = "你没有足够的权限."
SERVER_NOT_BOUND_TEXT = "您还未绑定服务器，请按说明进行绑定."
AUTH_QQ_MIN_SIMILARITY = 0.98

_log = logging.get_logger()
_config_manager = ConfigManager()


class CommandGuardService:
    """封装命令执行前的权限、开关和绑定校验。"""

    def __init__(self, message: GroupMessage):
        """绑定当前命令所属的群消息。"""
        self.message = message

    async def RequireAdmin(self,onlyCheck=False) -> bool:
        """校验当前消息发送者是否为群管理员。"""
        if await AdminRepositoryInstance.IsAdmin(self.message.group_openid, self.message.author.member_openid):
            return True
        if not onlyCheck:
            await self.message.reply(content=PERMISSION_DENIED_TEXT)
        return False

    async def GetBoundServer(self) -> list[str]:
        """获取当前群绑定的服务器信息，不存在时直接回复提示。"""
        server_id_list = []
        bind_server = await BindRepositoryInstance.GetByGroup(self.message.group_openid)
        if len(bind_server) == 0:
            await self.message.reply(content=SERVER_NOT_BOUND_TEXT)
            return []
        else:
            for bind_server in bind_server:
                server_id_list.append(bind_server[1])
        return server_id_list

    async def _EnsureFeatureEnabled(self, key: str, default: bool, disabled_text: str) -> bool:
        """校验功能开关是否启用，未启用时直接回复提示。"""
        if _config_manager.Get(key, default):
            return True
        await self.message.reply(content=disabled_text)
        return False

    async def EnsureAuthReady(self) -> bool:
        """确认认证功能已启用且当前群已经绑定服务器。"""
        if not await self._EnsureFeatureEnabled(
            "EnableAuth",
            ConfigManager.DEFAULT_ENABLE_AUTH,
            "认证功能未启用",
        ):
            return False
        return (await self.GetBoundServer()) is not None


class AuthCommandService:
    """封装 QQ 认证相关命令处理逻辑。"""

    def __init__(self, message: GroupMessage, api: BotAPI = None):
        """绑定当前命令所属的群消息和可选 Bot API。"""
        self.message = message
        self.api = api

    async def HandleAuthStatusQuery(self, open_id: str):
        """查询并回复当前 OpenId 的认证绑定状态。"""
        bind_qq = await AuthRepositoryInstance.GetBoundQQ(self.message.group_openid, open_id)
        if bind_qq is not None:
            await self.message.reply(content=f'您已绑定QQ:{bind_qq}\n如需解除请联系机器人管理员使用"/解除认证 {open_id}"以解除认证')
            return
        await self.message.reply(content='您暂未绑定QQ，请使用"/认证 <qq号>"进行绑定，例如"/认证 123456789"')

    async def HandleSelfAuth(self, qq_num: str):
        """处理用户自行发起的 QQ 头像认证流程。"""
        if not IsValidQQ(qq_num):
            await self.message.reply(content="认证失败，请检查输入的QQ号是否正确")
            return

        open_id = self.message.author.member_openid
        bind_qq = await AuthRepositoryInstance.GetBoundQQ(self.message.group_openid, open_id)
        if bind_qq is not None:
            await self.message.reply(content=f"您已绑定QQ:{bind_qq}")
            return

        app_id = _config_manager.Get("AppId")
        result = await CompareQQAvatars(app_id, qq_num, open_id)
        if result[1] != 0:
            await self.message.reply(
                content=await ApplySensitiveFilter(f'图像比对失败: 错误 ({result[1]}): {str(result[2])}\n管理员可手动使用"/认证 {qq_num} {open_id}"进行人工确认')
            )
            return

        similarity = result[0]
        similarity_percent = similarity * 100
        required_percent = AUTH_QQ_MIN_SIMILARITY * 100
        if similarity >= AUTH_QQ_MIN_SIMILARITY:
            result_text = f'✅ 认证通过！相似度：{similarity_percent:.2f}%'
            await self._SendSelfAuthMarkdownOrText(
                qq_num,
                open_id,
                result_text,
                f'✅ 认证通过！绑定信息如下\nOpenId:{open_id}\nQQ账号:{qq_num}\n如绑定有误，请管理员输入"/解除认证 {open_id}"',
                self._BuildSelfAuthKeyboardJson("👮管理员取消", f"/解除认证 {open_id}"),
            )
            await AuthRepositoryInstance.AddBinding(self.message.group_openid, open_id, qq_num)
            return

        await self._SendSelfAuthMarkdownOrText(
            qq_num,
            open_id,
            f'❌ 认证失败，当前匹配度：{similarity_percent:.2f}%（需≥{required_percent:.2f}%）',
            f'❌ 认证失败，当前匹配度：{similarity_percent:.2f}%（需≥{required_percent:.2f}%）\n管理员可手动使用"/认证 {qq_num} {open_id}"进行人工确认',
            self._BuildSelfAuthKeyboardJson("👮管理员确认", f"/认证 {qq_num} {open_id}"),
        )

    def _BuildSelfAuthKeyboardJson(self, label: str, action_data: str) -> dict:
        """构造自助认证结果按钮 JSON。"""
        return {
            "rows": [
                {
                    "buttons": [
                        {
                            "id": "1",
                            "render_data": {
                                "label": label,
                                "visited_label": label,
                                "style": 1,
                            },
                            "action": {
                                "type": 2,
                                "permission": {
                                    "type": 1,
                                    "specify_role_ids": [],
                                    "specify_user_ids": [],
                                },
                                "click_limit": 1,
                                "unsupport_tips": "暂不支持",
                                "data": action_data,
                                "at_bot_show_channel_list": False,
                            },
                        }
                    ]
                }
            ]
        }

    async def _SendSelfAuthMarkdownOrText(
        self,
        qq_num: str,
        open_id: str,
        result_text: str,
        fallback_text: str,
        keyboard_json: dict,
    ):
        """发送自助认证 Markdown 结果，失败时回退普通文本。"""
        if self.api is None:
            await self.message.reply(content=fallback_text)
            return

        avatar_image = await GenerateQQAvatarCompareImage(_config_manager.Get("AppId"), qq_num, open_id)
        if not avatar_image.get("success"):
            _log.error(f"认证头像对比图生成失败: {avatar_image.get('msg')}")
            await self.message.reply(content=fallback_text)
            return

        try:
            md_content = mdManager.GetTemplate("switchAvatars").get(
                {
                    "avatarUrl": avatar_image.get("imgUrl", ""),
                    "openid": open_id,
                    "qq": qq_num,
                    "result": result_text,
                }
            )
            keyboard = KeyboardPayloadFromJson(keyboard_json)
            await self.api.post_group_message(
                group_openid=self.message.group_openid,
                msg_type=2,
                msg_id=self.message.id,
                msg_seq=1,
                markdown=MarkdownPayload(content=md_content),
                keyboard=keyboard,
            )
        except Exception as exc:
            _log.error(f"认证 Markdown 发送失败: {exc}")
            await self.message.reply(content=fallback_text)

    async def HandleAdminAuth(self, qq_num: str, target_open_id: str):
        """处理管理员手动确认的 QQ 认证绑定。"""
        if not IsValidOpenId(target_open_id):
            await self.message.reply(content="OpenId 输入有误")
            return
        await self.message.reply(content=f"✅ 认证通过！已为{target_open_id}绑定为QQ账号:{qq_num}")
        await AuthRepositoryInstance.AddBinding(self.message.group_openid, target_open_id, qq_num)

    async def HandleAuthUnbind(self, target_open_id):
        """处理管理员发起的 QQ 认证解绑。"""
        if not target_open_id:
            await self.message.reply(content="请输入要解除认证的OpenId")
            return
        if not IsValidOpenId(target_open_id):
            await self.message.reply(content="OpenId 输入有误")
            return

        if await AuthRepositoryInstance.DeleteBindingByOpenId(self.message.group_openid, target_open_id):
            await self.message.reply(content=f"✅ 解除认证成功！已为{target_open_id}解除绑定QQ账号")
            return

        await self.message.reply(content="❌ 解除认证失败！请检查输入的OpenId是否正确")


# 全局交互按钮回调池 actionId → {needAdmin, function}
_interaction_callbacks: dict[str, dict[str, Any]] = {}


def RegisterInteractionCallback(
        group_id: str,
        user_id: str,
        action_id: str,
        callback: Callable[..., Awaitable[Any]],
        need_admin: bool = False
    ):
    """注册按钮交互回调。"""
    _interaction_callbacks[action_id] = {
        "needAdmin": need_admin,
        "function": callback,
        "group_id": group_id,
        "user_id": user_id,
    }


def PeekInteractionCallback(action_id: str) -> dict[str, Any] | None:
    """查看按钮交互回调（不移除），返回 {needAdmin, function} 或 None。"""
    return _interaction_callbacks.get(action_id)


def PopInteractionCallback(action_id: str) -> dict[str, Any] | None:
    """取出并移除一个按钮交互回调，返回 {needAdmin, function} 或 None。"""
    return _interaction_callbacks.pop(action_id, None)


async def BuildServerSelectorPayload(
    group_openid: str,
    action_id:str,
    markdown_title: str = "# 选择服务器\n请点击下方按钮选择要操作的服务器",
):
    """查询当前群绑定的服务器，构建按钮选择表单。

    返回 (MarkdownPayload, KeyboardPayload, action_map)，无绑定时返回 None。
    action_map: {action_id: server_id}
    """
    bind_ret = await BindRepositoryInstance.GetByGroup(group_openid)
    if not bind_ret:
        return None

    rows: list[KeyboardRow] = []
    server_list_lines: list[str] = []
    for i in range(0, len(bind_ret), 2):
        buttons: list[Button] = []
        for j in range(i, min(i + 2, len(bind_ret))):
            server_id = bind_ret[j][1]
            server_name = await BindRepositoryInstance.GetServerName(group_openid, server_id) or "未命名服务器"
            masked_id = f"{server_id[:4]}{'*' * 6}{server_id[-3:]}" if len(server_id) >= 7 else server_id
            server_list_lines.append(f"**{server_name}**:`{masked_id}`")
            # Button label 截断防止过长，敏感词过滤在最终 markdown_content 统一处理
            safe_label = server_name[:20]

            buttons.append(
                Button(
                    id=str(i),
                    render_data=RenderData(label=safe_label, visited_label=safe_label, style=1),
                    action=Action(
                        type=1,
                        permission=Permission(type=2),
                        data=json.dumps({"actionId": action_id, "serverId": server_id}),
                    ),
                )
            )
        rows.append(KeyboardRow(buttons=buttons))

    server_list = "\n".join(server_list_lines)
    markdown_content = await ApplySensitiveFilter(f"{markdown_title}\n\n{server_list}")
    return MarkdownPayload(content=markdown_content), KeyboardPayload(content=Keyboard(rows=rows))

async def SendServerSelectorWithCallback(
    api:BotAPI,
    message:GroupMessage,
    action_id: str,
    needAdmin: bool,
    callback: Callable[..., Awaitable[Any]],
    markdown_text: str = "# 选择服务器\n请点击下方按钮选择要操作的服务器",
):
    payload = await BuildServerSelectorPayload(message.group_openid, action_id, markdown_text)
    if payload is None:
        await message.reply(content="当前群未绑定任何服务器。")
        return True

    markdown, keyboard = payload
    await api.post_group_message(
            group_openid=message.group_openid,
            msg_type=2,
            msg_id=message.id,
            msg_seq=5,
            markdown=markdown,
            keyboard=keyboard,
    )
    RegisterInteractionCallback(
            message.group_openid,
            message.author.member_openid,
            action_id,
            callback,
            needAdmin)
    return True


async def BuildServerActionPayload(server_id: str, server_name: str):
    """构建服务器操作二级表单，包含重命名和解绑两个指令按钮。

    type=2 指令按钮：点击后自动在输入框插入 @bot data。
    返回 (MarkdownPayload, KeyboardPayload)。
    """
    row = KeyboardRow(
        buttons=[
            Button(
                id=str(uuid.uuid4()),
                render_data=RenderData(label="重命名", visited_label="重命名", style=1),
                action=Action(
                    type=2,
                    permission=Permission(type=2),
                    data=f"/命名服务器 {server_id} ",
                ),
            ),
            Button(
                id=str(uuid.uuid4()),
                render_data=RenderData(label="解绑", visited_label="解绑", style=1),
                action=Action(
                    type=2,
                    permission=Permission(type=2),
                    data=f"/解绑 {server_id}",
                ),
            ),
        ]
    )
    markdown = MarkdownPayload(content=await ApplySensitiveFilter(f"# 操作服务器\n**{server_name}** ({server_id})"))
    return markdown, KeyboardPayload(content=Keyboard(rows=[row]))


__all__ = [
    "AUTH_QQ_MIN_SIMILARITY",
    "AuthCommandService",
    "BuildServerActionPayload",
    "BuildServerSelectorPayload",
    "CommandGuardService",
    "PERMISSION_DENIED_TEXT",
    "PeekInteractionCallback",
    "PopInteractionCallback",
    "RegisterInteractionCallback",
    "SERVER_NOT_BOUND_TEXT",
    "SendServerSelectorWithCallback",
]