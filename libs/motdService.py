# -*- coding: utf-8 -*-

import re

import requests
import random
from ymbotpy import BotAPI, logging
from ymbotpy.message import GroupMessage
from ymbotpy.types.message import MarkdownPayload, MessageMarkdownParams

from libs.basic import SplitCommandParams
from libs.SensitiveFilter import current_audit_group_id
from libs.chatService import ApplySensitiveFilter, MessageReplyService
from libs.configManager import ConfigManager
from libs.markdownManager import mdManager
from libs.repositories import AdminRepositoryInstance, MotdBlockRepositoryInstance

ONLINE_MARKDOWN_TEMPLATE_ID = "102006490_1775389207"
MOTD_MARKDOWN_TEMPLATE_ID = "102147135_1775388930"
MOTD_USAGE_TEXT = "Motd参数不正确\n使用方法:/motd <url> <platform>\nurl(必填):指定的服务器地址\nplatform(选填):<je|be>"
MOTD_FAILED_TEXT = (
    "❌无法获取服务器状态信息。\n"
    "⚠️原因可能有以下几种：\n"
    "1.服务器没有开启或已经关闭或不允许获取motd\n"
    "2.描述(motd)中含有链接，官方机器人不允许发送没有授权的链接\n"
    "3.指定的平台错误(je,be,auto)(不填默认auto)\n"
    "4.ip或端口输入错误，或者接口维护这个可以问问机器人主人😝"
)
MOTD_OFFLINE_FAILED_TEXT = (
    "❌无法获取服务器状态信息。\n"
    "⚠️状态检测为Offline：\n"
    "1.服务器没有开启或已经关闭或不允许获取motd\n"
    "2.指定的平台错误(je,be,auto)(不填默认auto)\n"
    "3.ip或端口输入错误，或者接口维护这个可以问问机器人主人😝"
)

_log = logging.get_logger()
_config_manager = ConfigManager()


def GetIframeImgUrl() -> str:
    """读取 iframe 截图接口模板地址。"""
    return _config_manager.Get("UrlGetIframeImg", ConfigManager.DEFAULT_URL_GET_IFRAME_IMG)


def GetDefaultImgUrl() -> str:
    """读取 Motd 查询失败时的默认图片地址。"""
    return _config_manager.Get("UrlDefaultImg", ConfigManager.DEFAULT_URL_DEFAULT_IMG)


def GetMotdOriginUrl() -> str:
    """读取需要被代理替换的原始 Motd 域名。"""
    return _config_manager.Get("MotdOriginUrl", ConfigManager.DEFAULT_MOTD_ORIGIN_URL)


def GetMotdProxyUrl() -> str:
    """读取 Motd 图片代理前缀地址。"""
    return _config_manager.Get("MotdProxyUrl", ConfigManager.DEFAULT_MOTD_PROXY_URL)


def ResolveMotdProxyImgUrl(img_url: str) -> str:
    """按配置把 Motd 图片地址替换为代理地址。"""
    origin_url = GetMotdOriginUrl()
    proxy_url = GetMotdProxyUrl()
    if not (origin_url and proxy_url and ((origin_url in img_url) or (proxy_url in img_url)) and "/api/app_img?" in img_url):
        return img_url

    try:
        imgUrlProxy = img_url.replace(
            f"https://{origin_url}",
            proxy_url.rstrip("/"),
        ).replace(
            f"http://{origin_url}",
            proxy_url.rstrip("/"),
        )
        return imgUrlProxy+"&"+str(random.randint(1000, 9999))
    except Exception as exc:
        _log.error(f"Motd 图片代理地址转换失败: {exc}")
        return img_url


def IsValidDomainPort(domain_port: str):
    """校验域名或 IPv4 地址以及可选端口是否合法。"""
    pattern = r"^((?:[a-zA-Z0-9][-\w]*\.)+[a-zA-Z]{2,63}|(?:\d{1,3}\.){3}\d{1,3})(?::(\d{1,5}))?$"
    match = re.match(pattern, domain_port)
    if match:
        port = match.group(2)
        if port:
            return 1 <= int(port) <= 65535
        return True
    return False


class MotdClient:
    """负责请求 Motd 接口并整理返回数据。"""

    def __init__(self, url: str) -> None:
        """保存当前待查询的服务器地址。"""
        self.url = url

    def IsValid(self) -> bool:
        """判断服务器地址格式是否合法。"""
        return IsValidDomainPort(self.url)

    def _Request(self, url: str) -> dict:
        """向 Motd 接口发起 HTTP 请求。"""
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            return {"status": "error", "msg": str(exc)}

    def _RemoveColorCodes(self, text: str) -> str:
        """移除 Minecraft 颜色代码并压缩多余空白。"""
        cleaned_text = re.sub(r"§.", "", text)
        return re.sub(r"\s+", " ", cleaned_text.strip())

    async def _BuildMarkdownParams(
        self,
        platform="基岩版",
        motd_img_url="",
        motd_text="",
        delay=-1,
        protocol=0,
        version="0.0.0",
        player="0/0",
        level_name="Unknown",
        game_mode="Unknown",
    ):
        """组装 Motd Markdown 模板所需参数。"""
        motd_text = await ApplySensitiveFilter(motd_text)
        level_name = await ApplySensitiveFilter(level_name)
        return [
            MessageMarkdownParams(key="platform", values=[platform]),
            MessageMarkdownParams(key="motd_img_url", values=[motd_img_url]),
            MessageMarkdownParams(key="motd", values=[motd_text.replace("\n", "\u200B")]),
            MessageMarkdownParams(key="delay", values=[str(delay)]),
            MessageMarkdownParams(key="protocal", values=[str(protocol)]),
            MessageMarkdownParams(key="version", values=[version]),
            MessageMarkdownParams(key="player", values=[player]),
            MessageMarkdownParams(key="levelname", values=[level_name.replace("\n", "\u200B")]),
            MessageMarkdownParams(key="gamemode", values=[game_mode]),
        ]

    def _BuildPlainText(
        self,
        platform_title: str,
        motd_text: str,
        delay: int,
        protocol: int,
        version: str,
        player: str,
        level_name: str,
        game_mode: str,
    ) -> str:
        """按统一模板构造 Motd 普通文本结果。"""
        return (
            f"\nMC {platform_title}服务器状态查询\n"
            "⭕️状态: 在线\n"
            f"描述: {motd_text}\n"
            f"延迟: {delay} ms\n"
            f"协议版本: {protocol}\n"
            f"游戏版本: {version}\n"
            f"在线人数: {player}\n"
            f"地图名称: {level_name}\n"
            f"默认模式: {game_mode}"
        )

    async def _BuildBedrockResponse(self, motd_raw: dict) -> dict:
        """把基岩版返回结果转成模板参数。"""
        server_data = motd_raw.get("serverData")
        pure_motd = server_data.get("pureMotd", "").replace(".", "·")
        img_url = ResolveMotdProxyImgUrl(motd_raw.get("screenshotUrl", GetDefaultImgUrl()))
        motd_text = self._RemoveColorCodes(pure_motd)
        delay = server_data.get("delay", -1)
        protocol = server_data.get("protocol", -1)
        version = server_data.get("version", "0.0.0")
        player = f"{server_data.get('players').get('online', -1)}/{server_data.get('players').get('max', -1)}"
        level_name = server_data.get("levelname", "world").replace(".", "·")
        game_mode = server_data.get("gamemode", "Unknown")
        markdown_params = await self._BuildMarkdownParams(
            platform="Bedrock",
            motd_img_url=img_url,
            motd_text=motd_text,
            delay=delay,
            protocol=protocol,
            version=version,
            player=player,
            level_name=level_name,
            game_mode=game_mode,
        )
        return {
            "online": True,
            "params": markdown_params,
            "imgUrl": img_url,
            "text": self._BuildPlainText(
                "基岩版",
                motd_text,
                delay,
                protocol,
                version,
                player,
                level_name,
                game_mode,
            ),
        }

    async def _BuildJavaResponse(self, motd_raw: dict) -> dict:
        """把 Java 版返回结果转成模板参数。"""
        server_data = motd_raw.get("serverData")
        pure_motd = server_data.get("pureMotd", "").replace(".", "·")
        img_url = ResolveMotdProxyImgUrl(motd_raw.get("screenshotUrl", GetDefaultImgUrl()))
        motd_text = self._RemoveColorCodes(pure_motd)
        delay = server_data.get("delay", -1)
        protocol = server_data.get("protocol", -1)
        version = server_data.get("version", "0.0.0")
        player = f"{server_data.get('players').get('online', -1)}/{server_data.get('players').get('max', -1)}"
        markdown_params = await self._BuildMarkdownParams(
            platform="Java",
            motd_img_url=img_url,
            motd_text=motd_text,
            delay=delay,
            protocol=protocol,
            version=version,
            player=player,
            level_name="不可用",
            game_mode="不可用",
        )
        return {
            "online": True,
            "params": markdown_params,
            "imgUrl": img_url,
            "text": self._BuildPlainText(
                "Java",
                motd_text,
                delay,
                protocol,
                version,
                player,
                "不可用",
                "不可用",
            ),
        }

    async def SendRequest(self, url: str):
        """发送已组装好的请求地址，并规范化返回结构。"""
        motd_raw = self._Request(url)
        server_data = motd_raw.get("serverData", {"status": "offline"})
        status = server_data.get("status", "offline")
        if status != "online":
            return {"online": False}

        platform = server_data.get("type")
        if platform == "Java":
            return await self._BuildJavaResponse(motd_raw)
        if platform == "Bedrock":
            return await self._BuildBedrockResponse(motd_raw)
        return {"online": False}

    async def Motd(self, platform="auto") -> dict:
        """按平台查询当前服务器地址的 Motd 数据。"""
        url = GetIframeImgUrl().format(SERVERHOST=self.url, PLATFORM=platform)
        return await self.SendRequest(url)


class MotdCommandService:
    """封装 Motd 与查在线命令的处理逻辑。"""

    def __init__(self, api: BotAPI, message: GroupMessage):
        """绑定当前机器人 API、原始消息和回复服务。"""
        self.api = api
        self.message = message
        self.reply_service = MessageReplyService(api, message)

    async def EnsureAccess(self) -> bool:
        """校验当前群是否允许使用 Motd 相关功能。"""
        if not _config_manager.Get("EnableMotd", ConfigManager.DEFAULT_ENABLE_MOTD):
            await self.message.reply(content="Motd 功能未启用")
            return False

        if await AdminRepositoryInstance.IsAdmin(self.message.group_openid, self.message.author.member_openid):
            return True

        if not await MotdBlockRepositoryInstance.IsBlocked(self.message.group_openid):
            return True

        await self.message.reply(content="本群已屏蔽Motd")
        return False

    def ParseParams(self, params):
        """解析 motd 命令参数，返回 `(地址, 平台)`。"""
        params_list = SplitCommandParams(params)
        if len(params_list) == 1:
            return params_list[0], "auto"
        if len(params_list) == 2:
            return params_list[0], params_list[1]
        return None

    async def _PostMarkdownMessage(self, md_payload: MarkdownPayload):
        """发送 Markdown 群消息。"""
        await self.api.post_group_message(
                group_openid=self.message.group_openid,
                msg_type=2,
                msg_id=self.message.id,
                msg_seq=2,
                markdown=md_payload,
        )

    async def _SendMarkdownMessage(self, templateName: str, params):
        """发送指定模板的 Markdown 群消息。"""
        mdContent = mdManager.GetTemplate(templateName).get(params)
        md_payload = MarkdownPayload(content=mdContent)
        await self._PostMarkdownMessage(md_payload)

    async def _SendMarkdownCustomMessage(self, content: str, params):
        """发送自定义的 Markdown 群消息。"""
        md_content = mdManager.Render(content, params)
        md_payload = MarkdownPayload(content=await ApplySensitiveFilter(md_content))
        await self._PostMarkdownMessage(md_payload)

    def _BuildOnlineSpecialTip(self, url: str, tip_text: str) -> str:
        """为特殊服务器地址补充额外提示。"""
        if ("easecation" in url) or ("hypixel" in url):
            return f"({tip_text})\n"
        return ""

    async def _BuildOnlinePlayerMarkdownList(self, player: str) -> str:
        """把逗号分隔的玩家名格式化为 Markdown 列表。"""
        filtered_player = await ApplySensitiveFilter(player)
        player_names = [name.strip() for name in filtered_player.split(",") if name.strip()]
        if not player_names:
            return filtered_player
        return "\n".join(f"- {name}" for name in player_names)

    async def _SendOnlineTextResult(self, content: str, img_url=None, error_prefix="查在线图片上传失败"):
        """发送查在线的图文结果，失败时退回纯文本。"""
        if not img_url:
            await self.reply_service.PostSensitiveMessage(content, msg_seq=2)
            return

        try:
            upload_media = await self.api.post_group_file(self.message.group_openid, 1, img_url, False)
            filtered_content = await ApplySensitiveFilter(content)
            await self.api.post_group_message(
                group_openid=self.message.group_openid,
                msg_type=7,
                msg_id=self.message.id,
                content=filtered_content,
                media=upload_media,
                msg_seq=2,
            )
        except Exception as exc:
            _log.error(f"{error_prefix}: {exc}")
            await self.reply_service.PostSensitiveMessage(f"(图片上传失败)\n{content}", msg_seq=2)

    async def _BuildOnlineMarkdownParams(self, server_name: str, online_num: str, img_url: str, player: str):
        """组装查在线 Markdown 所需参数。"""
        return [
            MessageMarkdownParams(key="server", values=[await ApplySensitiveFilter(server_name)]),
            MessageMarkdownParams(key="online_num", values=[online_num]),
            MessageMarkdownParams(key="img_url", values=[img_url]),
            MessageMarkdownParams(key="player", values=[await self._BuildOnlinePlayerMarkdownList(player)]),
        ]

    async def _SendOnlineMarkdownResult(
        self,
        server_name: str,
        online_num: str,
        img_url: str,
        player: str,
        custom_markdown=None,
    ):
        """把查在线结果发送为 Markdown 消息，支持自定义 Markdown 内容。"""
        md_params = await self._BuildOnlineMarkdownParams(server_name, online_num, img_url, player)
        if isinstance(custom_markdown, str) and custom_markdown.strip():
            await self._SendMarkdownCustomMessage(custom_markdown, md_params)
            return

        await self._SendMarkdownMessage("onlineList", md_params)

    async def _ResolveOnlineProxyImgUrl(self, img_url: str) -> str:
        """在命中规则时把在线图片地址替换为代理地址。"""
        return ResolveMotdProxyImgUrl(img_url)

    def _BuildOnlineStatusImgUrl(self, server_type: str, motd_address: str) -> str:
        """构造查在线兜底使用的状态图地址。"""
        if server_type == "java":
            return ResolveMotdProxyImgUrl(f"https://motdbe.blackbe.work/status_img/java?host={motd_address}")
        return ResolveMotdProxyImgUrl(f"https://motdbe.blackbe.work/status_img?host={motd_address}")

    async def HandleOnlineCallback(self, data: dict):
        """处理服务端回传的在线玩家查询结果。"""
        current_audit_group_id.set(self.message.group_openid)
        try:
            reply_text = data.get("msg", "").replace("\u200b", "\n")
            motd_address = data.get("url", "")
            img_url = data.get("imgUrl")
            use_markdown = data.get("useMarkdown", False)
            custom_markdown = data.get("customMarkdown")
            server_name = data.get("serverName", "server")
            current_online = str(data.get("currentOnline", "0"))

            if img_url:
                if not data.get("post_img", False):
                    await self.reply_service.PostSensitiveMessage(reply_text, msg_seq=2)
                    return

                pre_tip = self._BuildOnlineSpecialTip(
                    motd_address,
                    "若发现查询出来的图片不是本服务器，请先修改config中的motd字段，或修改post_img使其不推送图片",
                )
                proxy_img_url = await self._ResolveOnlineProxyImgUrl(img_url)
                player_text = f"{pre_tip}{reply_text}"
                if use_markdown:
                    try:
                        await self._SendOnlineMarkdownResult(
                            server_name,
                            current_online,
                            proxy_img_url,
                            player_text,
                            custom_markdown,
                        )
                        return
                    except Exception as exc:
                        _log.exception("查在线Markdown发送失败")

                await self._SendOnlineTextResult(player_text, proxy_img_url, "查在线图片上传失败")
                return

            pre_tip = self._BuildOnlineSpecialTip(
                motd_address,
                "若发现查询出来的图片不是本服务器，请先修改config中的motdUrl字段",
            )
            content = f"{pre_tip}在线玩家列表:\n{reply_text}"
            if not motd_address or not IsValidDomainPort(motd_address):
                await self.reply_service.PostSensitiveMessage(content, msg_seq=2)
                return

            status_img_url = self._BuildOnlineStatusImgUrl(data.get("serverType", "bedrock"), motd_address)
            if use_markdown:
                try:
                    await self._SendOnlineMarkdownResult(
                        server_name,
                        current_online,
                        status_img_url,
                        f"{pre_tip}{reply_text}",
                        custom_markdown,
                    )
                    return
                except Exception as exc:
                    _log.error(f"查在线MOTD Markdown发送失败: {exc}")

            await self._SendOnlineTextResult(content, status_img_url, "查在线MOTD图片上传失败")
        except Exception as exc:
            _log.error(f"HandleOnlineCallback 出现错误: {exc}")
            await self.reply_service.PostSensitiveMessage(f"出现错误：{exc}", msg_seq=2)

    def CreateOnlineReplyCallback(self):
        """创建查在线命令使用的回调包装器。"""

        async def Callback(data: dict):
            """把服务端返回的查在线结果转交给当前服务处理。"""
            await self.HandleOnlineCallback(data)
            return True

        return Callback

    async def _SendMotdMarkdownResult(self, motd_data: dict):
        """发送 Motd 成功结果的 Markdown 消息。"""
        await self._SendMarkdownMessage("beMotd", motd_data.get("params"))

    async def _SendMotdTextResult(self, motd_data: dict):
        """在 Markdown 发送失败时回退为带图普通文本。"""
        text = self._BuildMotdPlainText(motd_data)
        img_url = motd_data.get("imgUrl")
        if not img_url:
            await self.reply_service.PostSensitiveMessage(text, msg_seq=2)
            return

        try:
            upload_media = await self.api.post_group_file(self.message.group_openid, 1, img_url, False)
            filtered_text = await ApplySensitiveFilter(text)
            await self.api.post_group_message(
                group_openid=self.message.group_openid,
                msg_type=7,
                msg_id=self.message.id,
                content=filtered_text,
                media=upload_media,
                msg_seq=2,
            )
        except Exception as exc:
            _log.error(f"发送 MOTD 图片失败，改为纯文本回退: {exc}")
            await self.reply_service.PostSensitiveMessage(text, msg_seq=2)

    def _BuildMotdPlainText(self, motd_data: dict) -> str:
        """把 Motd 模板参数还原为普通文本内容。"""
        if motd_data.get("text"):
            return motd_data["text"]

        param_map = {}
        for item in motd_data.get("params", []):
            key = getattr(item, "key", "")
            values = getattr(item, "values", [])
            param_map[key] = values[0] if values else ""

        platform = param_map.get("platform", "未知")
        platform_title = "基岩版" if platform == "Bedrock" else "Java" if platform == "Java" else str(platform)
        motd_text = param_map.get("motd", "").replace("\u200B", "\n")
        delay = param_map.get("delay", "-1")
        protocol = param_map.get("protocal", "0")
        version = param_map.get("version", "0.0.0")
        player = param_map.get("player", "0/0")
        level_name = param_map.get("levelname", "").replace("\u200B", "\n") or "不可用"
        game_mode = param_map.get("gamemode", "") or "不可用"
        return self._BuildPlainText(
            platform_title,
            motd_text,
            delay,
            protocol,
            version,
            player,
            level_name,
            game_mode,
        )

    async def SendMotdResponse(self, url: str, platform: str):
        """执行 Motd 查询并把结果回到当前群。"""
        await self.message.reply(content="已发起Motd请求，请稍等...")

        motd_client = MotdClient(url)
        if not motd_client.IsValid():
            await self.message.reply(content="服务器地址参数不正确", msg_seq=2)
            return

        motd_data = await motd_client.Motd(platform)
        if not motd_data.get("online"):
            await self.message.reply(content=MOTD_OFFLINE_FAILED_TEXT, msg_seq=2)
            return

        try:
            await self._SendMotdMarkdownResult(motd_data)
        except Exception as exc:
            _log.error(f"发送 MOTD Markdown 失败，改为图文回退: {exc}")
            await self._SendMotdTextResult(motd_data)


__all__ = [
    "GetDefaultImgUrl",
    "GetIframeImgUrl",
    "GetMotdOriginUrl",
    "GetMotdProxyUrl",
    "IsValidDomainPort",
    "MOTD_USAGE_TEXT",
    "MotdClient",
    "MotdCommandService",
    "ResolveMotdProxyImgUrl",
]