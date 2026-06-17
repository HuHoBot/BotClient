# -*- coding: utf-8 -*-

import time

import ymbotpy
from ymbotpy import BotAPI, logging
from ymbotpy.message import GroupMessage
from ymbotpy.types.message import MarkdownPayload

from libs.SensitiveFilter import ApiSensitiveFilter
from libs.configManager import ConfigManager
from libs.generateImg import generate_img
from libs.markdownManager import mdManager

MAX_CALLBACK_MSG_SEQ = 5
COMMAND_CALLBACK_PREFIX = "[消息回报]"
CALLBACK_MARKDOWN_TEMPLATE = "callback"
CHAT_MESSAGE_PREFIX = "[聊天消息]"
CHAT_MESSAGE_EXPIRE_SECONDS = 5 * 60

_log = logging.get_logger()
_config_manager = ConfigManager()


def ApplySensitiveFilter(text: str) -> str:
    """按配置决定是否对文本执行敏感词替换。"""
    if _config_manager.Get("EnableSensitiveFilter", ConfigManager.DEFAULT_ENABLE_SENSITIVE_FILTER):
        return ApiSensitiveFilter.replace(text)
    return text


class MessageReplyService:
    """封装单条群消息上下文中的回复、回调和图片发送逻辑。"""

    def __init__(self, api: BotAPI, message: GroupMessage):
        """绑定当前机器人 API 和原始消息对象。"""
        self.api = api
        self.message = message

    async def PostImageMessage(self, img_url: str, text: str, failed_text: str):
        """发送带图消息，失败时回退为纯文本提示。"""
        try:
            upload_media = await self.api.post_group_file(
                self.message.group_openid,
                1,
                img_url,
                False,
            )
            await self.api.post_group_message(
                group_openid=self.message.group_openid,
                msg_type=7,
                msg_id=self.message.id,
                content=text,
                media=upload_media,
                msg_seq=1,
            )
        except Exception as exc:
            _log.error(f"发送图片失败: {exc}")
            await self.message.reply(content=failed_text)

    async def PostSensitiveMessage(self, text: str, msg_seq=1):
        """发送经过敏感词过滤的文本回复。"""
        return await self.message.reply(content=ApplySensitiveFilter(text), msg_seq=msg_seq)

    async def ReplyText(self, text: str, msg_seq=1, use_sensitive_filter=False):
        """按需发送原文或过滤后的文本。"""
        if use_sensitive_filter:
            return await self.PostSensitiveMessage(text, msg_seq=msg_seq)
        return await self.message.reply(content=text, msg_seq=msg_seq)

    async def ReplyTextWithRetry(
        self,
        text: str,
        msg_seq=2,
        use_sensitive_filter=False,
        error_prefix=None,
    ) -> bool:
        """在消息序号冲突时递增序号重试发送文本。"""
        if msg_seq > MAX_CALLBACK_MSG_SEQ:
            return True

        try:
            await self.ReplyText(text, msg_seq=msg_seq, use_sensitive_filter=use_sensitive_filter)
            return True
        except ymbotpy.errors.ServerError as exc:
            if msg_seq >= MAX_CALLBACK_MSG_SEQ:
                if error_prefix:
                    _log.error(f"{error_prefix}: {exc}")
                return True
            return await self.ReplyTextWithRetry(
                text,
                msg_seq=msg_seq + 1,
                use_sensitive_filter=use_sensitive_filter,
                error_prefix=error_prefix,
            )

    def _BuildCallbackMarkdown(self, content: str, img_url: str, img_width=0, img_height=0) -> str:
        """按 callback.md 模板组装带图命令回调 Markdown。"""
        return mdManager.GetTemplate(CALLBACK_MARKDOWN_TEMPLATE).get(
            {
                "width": img_width or 0,
                "height": img_height or 0,
                "image_url": img_url,
                "content": ApplySensitiveFilter(content),
            }
        )

    async def SendCallbackResponse(
        self,
        content: str,

        img_url=None,
        img_width=0,
        img_height=0,

        msg_seq=2,
        image_error_prefix="发送图片失败",
    ) -> None:
        """统一发送命令回调结果，支持文本和图片两种形式。"""
        if not img_url:
            await self.ReplyTextWithRetry(content, msg_seq=msg_seq)
            return

        try:
            md_content = self._BuildCallbackMarkdown(content, img_url, img_width, img_height)
            md_payload = MarkdownPayload(content=md_content)
            await self.api.post_group_message(
                group_openid=self.message.group_openid,
                msg_type=2,
                msg_id=self.message.id,
                markdown=md_payload,
                msg_seq=msg_seq,
            )
        except ymbotpy.errors.ServerError as exc:
            if msg_seq >= MAX_CALLBACK_MSG_SEQ:
                _log.error(f"{image_error_prefix}: {exc}")
                return
            await self.SendCallbackResponse(
                content,
                img_url=img_url,
                img_width=img_width,
                img_height=img_height,
                msg_seq=msg_seq + 1,
                image_error_prefix=image_error_prefix,
            )
        except Exception as exc:
            await self.PostSensitiveMessage(
                f"{COMMAND_CALLBACK_PREFIX}\n{image_error_prefix}:{exc}\n{content}",
                msg_seq=msg_seq,
            )

    def BuildCommandCallbackPayload(
        self,
        text: str,
        unique_id: str,
        callback_convert: int,
        render_text=None,
    ):
        """按行数决定命令回调结果是直接发文本还是先转图片。"""
        output_text = text if render_text is None else render_text
        if callback_convert <= 0 or len(text.split("\n")) < callback_convert:
            return f"{COMMAND_CALLBACK_PREFIX}\n{output_text}", None, 0, 0

        imageData = generate_img(output_text, unique_id)
        width = imageData.get("width",0)
        height = imageData.get("height",0)

        return COMMAND_CALLBACK_PREFIX, _config_manager.BuildGenerateImgUrl(unique_id), width, height

    def CreateTextReplyCallback(self, use_sensitive_filter=False, error_prefix=None):
        """创建仅回复 `text` 字段的回调处理器。"""

        async def Callback(packed_msg, _msg_seq=2):
            """把服务端返回的文本按统一重试策略发送到群里。"""
            text = packed_msg.get("text", "")
            return await self.ReplyTextWithRetry(
                text,
                msg_seq=_msg_seq,
                use_sensitive_filter=use_sensitive_filter,
                error_prefix=error_prefix,
            )

        return Callback


class ChatRelayManager:
    """缓存近期群消息，用于把游戏聊天回推到群里。"""

    def __init__(self):
        """初始化聊天缓存和机器人 API 引用。"""
        self._message_cache = {}
        self._bot_api = None

    def SetBotApi(self, bot_api: BotAPI):
        """保存后续用于回推聊天的机器人 API。"""
        self._bot_api = bot_api

    def RememberMessage(self, server_id: str, group_id: str, msg_id: str, current_seq=1):
        """记录一条最近使用的群消息模板。"""
        if server_id not in self._message_cache:
            self._message_cache[server_id] = {}
        if group_id not in self._message_cache[server_id]:
            self._message_cache[server_id][group_id] = []

        self._message_cache[server_id][group_id].append(
            {
                "msg_id": msg_id,
                "last_time": time.time(),
                "current_seq": current_seq,
            }
        )
        return True

    async def BroadcastChat(self, server_id: str, msg: str):
        """把游戏聊天转发到指定服务器绑定过的群聊中。"""
        if server_id not in self._message_cache or self._bot_api is None:
            return False

        sent = False
        now = time.time()
        for group_id, msg_pool in self._message_cache[server_id].items():
            if not msg_pool:
                continue

            msg_pool.sort(key=lambda item: item["last_time"], reverse=True)
            for msg_obj in msg_pool:
                if msg_obj["current_seq"] <= MAX_CALLBACK_MSG_SEQ and now - msg_obj["last_time"] <= CHAT_MESSAGE_EXPIRE_SECONDS:
                    msg_obj["current_seq"] += 1
                    msg_obj["last_time"] = now
                    try:
                        await self._bot_api.post_group_message(
                            group_openid=group_id,
                            content=f"{CHAT_MESSAGE_PREFIX}\n{ApplySensitiveFilter(msg)}",
                            msg_id=msg_obj["msg_id"],
                            msg_seq=msg_obj["current_seq"],
                        )
                    except ymbotpy.errors.ServerError as exc:
                        _log.error(f"发送群聊天消息失败: {exc}")
                    sent = True
                    break

            self._message_cache[server_id][group_id] = [
                item
                for item in msg_pool
                if item["current_seq"] <= MAX_CALLBACK_MSG_SEQ
                and now - item["last_time"] <= CHAT_MESSAGE_EXPIRE_SECONDS
            ]

        return sent


ChatManager = ChatRelayManager()


__all__ = [
    "ApplySensitiveFilter",
    "COMMAND_CALLBACK_PREFIX",
    "ChatManager",
    "ChatRelayManager",
    "MAX_CALLBACK_MSG_SEQ",
    "MessageReplyService",
]
