# -*- coding: utf-8 -*-

import asyncio
import json
import os
import re
import uuid

import ymbotpy
from ymbotpy import BotAPI, Client, WebHookClient, logging
from ymbotpy.ext.command_util import Commands
from ymbotpy.interaction import Interaction
from ymbotpy.manage import GroupManageEvent
from ymbotpy.message import GroupMessage, MessageAudit
from ymbotpy.types.inline import Keyboard, Button, RenderData, Action, Permission, KeyboardRow
from ymbotpy.types.message import MarkdownPayload, KeyboardPayload

from libs.basic import GenerateRandomCode, GetQLogoUrl, IsGuid, IsNumber, SplitCommandParams, TryParseJson
from libs.chatService import ApplySensitiveFilter, ChatManager, COMMAND_CALLBACK_PREFIX, MessageReplyService
from libs.commandHelper import (
    AuthCommandService,
    BuildServerActionPayload,
    BuildServerSelectorPayload,
    CommandGuardService,
    PeekInteractionCallback,
    PERMISSION_DENIED_TEXT,
    PopInteractionCallback,
    RegisterInteractionCallback,
    SendServerSelectorWithCallback,
)
from libs.configManager import ConfigManager
from libs.motdService import MOTD_USAGE_TEXT, MotdCommandService
from libs.repositories import (
    AdminRepositoryInstance,
    AuthRepositoryInstance,
    BindRepositoryInstance,
    MotdBlockRepositoryInstance,
    NicknameRepositoryInstance,
    PendingBindStoreInstance,
)
from libs.websocketClient import WebsocketClient, WebsocketEventSet

_log = logging.get_logger()
_config_manager = ConfigManager()


def GetPublicGroups() -> list[str]:
    """读取允许查看公共在线服务器列表的群配置。"""
    return _config_manager.Get("PublicGroup", ConfigManager.DEFAULT_PUBLIC_GROUP)


def BuildWsSendFailedText(server_id: str) -> str:
    """构造统一的 WebSocket 发送失败提示。"""
    return f"无法向Id为{server_id}的服务器发送请求，请管理员检查连接状态"


class ServerManager:
    """管理当前进程持有的 WebSocket 客户端实例。"""

    def __init__(self) -> None:
        """初始化服务器连接容器。"""
        self.ws_server = None

    def SetWsServer(self, ws_server_obj: WebsocketClient) -> None:
        """注册当前进程持有的 WebSocket 客户端实例。"""
        self.ws_server = ws_server_obj

    def GetWsServer(self) -> WebsocketClient:
        """返回当前已注册的 WebSocket 客户端实例。"""
        return self.ws_server


ServerManagerInstance = ServerManager()


@Commands("帮助")
async def GetHelp(api: BotAPI, message: GroupMessage, params=None):
    """发送机器人文档、帮助和快速开始入口。"""
    bot_name = _config_manager.Get("BotName", ConfigManager.DEFAULT_BOT_NAME)
    reply_service = MessageReplyService(api, message)
    if (not params) or ("文档" in params):
        await reply_service.PostImageMessage(
            "https://pic.txssb.cn/docQrCode.png",
            f"{bot_name} 文档站请扫描二维码或手动输入网址",
            "图片发送失败，请稍后再试.",
        )
    elif "管理" in params:
        await reply_service.PostImageMessage(
            "https://pic.txssb.cn/adminHelp.jpeg",
            f"{bot_name} 管理帮助如图，更多详情请前往文档站查看",
            '图片发送失败，请使用"/帮助 文档"获取文档链接',
        )
    elif "指令" in params:
        await reply_service.PostImageMessage(
            "https://pic.txssb.cn/commandHelp.jpeg",
            f"{bot_name} 指令列表如图，更多详情请前往文档站查看",
            '图片发送失败，请使用"/帮助 文档"获取文档链接',
        )
    elif "快速开始" in params:
        await reply_service.PostImageMessage(
            "https://pic.txssb.cn/quickStartQrCode.png",
            f"{bot_name} 文档站快速开始请扫描二维码或手动输入网址",
            "图片发送失败，请稍后再试.",
        )
    return True


@Commands("添加白名单")
async def AddAllowList(api: BotAPI, message: GroupMessage, params=None):
    """向绑定服务器发送添加白名单请求。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True
    if not params:
        await message.reply(content="参数不正确")
        return True

    unique_id = str(uuid.uuid4())

    async def run(server_id: str):

        server_instance = ServerManagerInstance.GetWsServer()
        reply_service = MessageReplyService(api, message)
        server_instance.AddCallbackFunc(unique_id, reply_service.CreateTextReplyCallback())
        ws_ret = await server_instance.SendMsgByServerId(
                server_id,
                WebsocketEventSet.AddWhiteList,
                {"xboxid": params},
                unique_id,
        )
        if ws_ret:
            await reply_service.PostSensitiveMessage(
                f"已请求添加白名单.\nXbox Id:{params}\n请管理员核对.如有错误,请输入/删除白名单 {params}"
                )
        else:
            await message.reply(content=BuildWsSendFailedText(server_id))

    bind_server = await guard_service.GetBoundServer()
    if len(bind_server) == 1:
        await run(bind_server[0])
    elif len(bind_server) > 1:
        await SendServerSelectorWithCallback(api, message, unique_id, run)
    return True


@Commands("删除白名单")
async def DeleteAllowList(api: BotAPI, message: GroupMessage, params=None):
    """向绑定服务器发送删除白名单请求。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True
    if not params:
        await message.reply(content="参数不正确")
        return True

    unique_id = str(uuid.uuid4())

    async def run(server_id: str):

        server_instance = ServerManagerInstance.GetWsServer()
        reply_service = MessageReplyService(api, message)
        server_instance.AddCallbackFunc(unique_id, reply_service.CreateTextReplyCallback())
        ws_ret = await server_instance.SendMsgByServerId(
                server_id,
                WebsocketEventSet.DelWhiteList,
                {"xboxid": params},
                unique_id,
        )
        if ws_ret:
            await reply_service.PostSensitiveMessage(f"已请求删除Xbox Id为{params}的白名单.")
        else:
            await message.reply(content=BuildWsSendFailedText(server_id))

    bind_server = await guard_service.GetBoundServer()
    if len(bind_server) == 1:
        await run(bind_server[0])
    elif len(bind_server) > 1:
        await SendServerSelectorWithCallback(api, message, unique_id, run)
    return True

@Commands("绑定")
async def Bind(api: BotAPI, message: GroupMessage, params=None):
    """校验并发起群与服务器的绑定流程。"""
    params_list = SplitCommandParams(params)

    if len(params_list) == 0:
        bind_ret = await BindRepositoryInstance.GetByGroup(message.group_openid)
        if not bind_ret:
            await message.reply(content="当前群未绑定任何服务器。")
            return True
        lines = ["当前群已绑定服务器:"]
        for row in bind_ret:
            server_id = row[1]
            server_name = await BindRepositoryInstance.GetServerName(message.group_openid, server_id)
            if server_name is None:
                server_name = "未命名服务器"
            lines.append(f"名称: {server_name}")
            lines.append(f"ID: {server_id}")
        await message.reply(content="\n".join(lines))
        return True

    if len(params_list) < 1 or len(params_list) > 2:
        await message.reply(content="参数不正确，格式应为：/命令 <serverId> [多群]")
        return True

    is_more_group = False
    if len(params_list) == 2:
        if params_list[1] != "多群":
            await message.reply(content="第二个参数只能是「多群」")
            return True
        is_more_group = True

    server_id = params_list[0]
    guard_service = CommandGuardService(message)
    bind_ret = await BindRepositoryInstance.GetByGroup(message.group_openid)
    if bind_ret is not None and not await guard_service.RequireAdmin():
        return True

    unique_id = str(uuid.uuid4())
    server_instance = ServerManagerInstance.GetWsServer()
    reply_service = MessageReplyService(api, message)
    server_instance.AddCallbackFunc(unique_id, reply_service.CreateTextReplyCallback(error_prefix="绑定回复重试失败"))

    if IsGuid(server_id):
        bind_code = GenerateRandomCode()
        bind_req_ret = await server_instance.SendMsgByServerId(
            server_id,
            WebsocketEventSet.BindRequest,
            {"bindCode": bind_code},
            unique_id,
        )
        if bind_req_ret:
            PendingBindStoreInstance.AddRequest(
                unique_id,
                server_id,
                message.group_openid,
                message.author.member_openid,
                is_more_group,
            )
            await message.reply(content=f"已向服务端下发绑定请求，本次绑定校验码为:{bind_code}，请查看服务端控制台出现的信息。")
        else:
            await message.reply(content=BuildWsSendFailedText(server_id))
        return True

    await reply_service.PostImageMessage(
        "https://pic.txssb.cn/quickStartQrCode.png",
        "你发送的内容不是一个合法的绑定Key，请重新确认（绑定Key应为32个字符长度的十六进制字符串）\n详情请查看文档中的快速开始，扫描二维码查看",
        "你发送的内容不是一个合法的绑定Key，请重新确认（绑定Key应为32个字符长度的十六进制字符串）\n详情请查看文档中的快速开始(请使用 /帮助 来获取文档)",
    )
    return True

@Commands("解绑")
async def unBind(api: BotAPI, message: GroupMessage, params=None):
    """按服务器ID删除当前群的绑定关系，无参数时弹出选择框。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True

    params_list = SplitCommandParams(params)
    if len(params_list) == 0:
        async def do_unbind(server_id: str):
            await BindRepositoryInstance.UnbindServer(message.group_openid, server_id)
            await message.reply(content=f"已解除当前群与服务器 {server_id} 的绑定。")

        await SendServerSelectorWithCallback(
            api, message,
            str(uuid.uuid4()),
            do_unbind,
            markdown_text="# 选择要解绑的服务器\n请点击下方按钮",
        )
        return True

    server_id = params_list[0]
    bind_ret = await BindRepositoryInstance.GetByGroup(message.group_openid)
    if not bind_ret:
        await message.reply(content="当前群未绑定任何服务器，无需解绑。")
        return True

    matched = any(row[1] == server_id for row in bind_ret)
    if not matched:
        await message.reply(content=f"当前群未绑定服务器 {server_id}。")
        return True

    await BindRepositoryInstance.UnbindServer(message.group_openid, server_id)
    await message.reply(content=f"已解除当前群与服务器 {server_id} 的绑定。")
    return True


@Commands("设置服务器")
async def SetServer(api: BotAPI, message: GroupMessage, params=None):
    """弹出服务器选择框或直接操作指定服务器。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True

    async def send_action_form(server_id: str):
        server_name = await BindRepositoryInstance.GetServerName(message.group_openid, server_id) or "未命名服务器"
        markdown, keyboard = BuildServerActionPayload(server_id, server_name)
        await api.post_group_message(
            group_openid=message.group_openid,
            msg_type=2,
            msg_id=message.id,
            msg_seq=2,
            markdown=markdown,
            keyboard=keyboard,
        )

    params_list = SplitCommandParams(params)
    if len(params_list) >= 1:
        server_id = params_list[0]
        bind_ret = await BindRepositoryInstance.GetByGroup(message.group_openid)
        matched = any(row[1] == server_id for row in bind_ret)
        if not matched:
            await message.reply(content=f"当前群未绑定服务器 {server_id}。")
            return True
        await send_action_form(server_id)
        return True

    unique_id = str(uuid.uuid4())
    await SendServerSelectorWithCallback(api, message, unique_id, send_action_form)
    return True


@Commands("命名服务器")
async def RenameServer(api: BotAPI, message: GroupMessage, params=None):
    """重命名已绑定的服务器。格式：/命名服务器 <ServerId> <名称>"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True

    params_list = SplitCommandParams(params)
    if len(params_list) < 2:
        await message.reply(content="参数不正确，格式应为：/命名服务器 <ServerId> <名称>")
        return True

    server_id = params_list[0]
    name = " ".join(params_list[1:])

    bind_ret = await BindRepositoryInstance.GetByGroup(message.group_openid)
    matched = any(row[1] == server_id for row in bind_ret)
    if not matched:
        await message.reply(content=f"当前群未绑定服务器 {server_id}。")
        return True

    await BindRepositoryInstance.SetServerName(message.group_openid, server_id, name)
    await message.reply(content=f"已将该服务器重命名为: {name}")
    return True


@Commands("查信息")
async def QueryInfo(api: BotAPI, message: GroupMessage, params=None):
    """查询当前用户信息或指定 OpenId 的 QQ 绑定信息。"""
    guard_service = CommandGuardService(message)
    if params:
        if not await guard_service.RequireAdmin():
            return True
        bind_qq = await AuthRepositoryInstance.GetBoundQQ(message.group_openid, params)
        if bind_qq:
            await message.reply(content=f"此用户已绑定QQ:{bind_qq}")
        else:
            await message.reply(content="此用户未绑定QQ")
        return True

    nick = await NicknameRepositoryInstance.GetName(message.group_openid, message.author.member_openid)
    if not nick:
        nick = "未绑定昵称"

    await message.reply(
        content=f"你的OpenId:{message.author.member_openid}\n群的OpenId:{message.group_openid}\n绑定的昵称:{ApplySensitiveFilter(nick)}"
    )
    return True


@Commands("查管理")
async def QueryAdminCommand(api: BotAPI, message: GroupMessage, params=None):
    """查询指定 OpenId 是否为当前群管理员。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True
    ret = await AdminRepositoryInstance.IsAdmin(message.group_openid, params)
    if ret:
        await message.reply(content="此人是管理员")
    else:
        await message.reply(content="此人不是管理员")
    return True


@Commands("加管理")
async def AddAdminCommand(api: BotAPI, message: GroupMessage, params=None):
    """为当前群新增管理员。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True
    ret = await AdminRepositoryInstance.AddAdmin(message.group_openid, params)
    if ret:
        reply_service = MessageReplyService(api, message)
        await reply_service.PostSensitiveMessage(f"已为本群添加OpenId:{params}的管理员")
    return True


@Commands("删管理")
async def DelAdminCommand(api: BotAPI, message: GroupMessage, params=None):
    """移除当前群的管理员。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True
    ret = await AdminRepositoryInstance.RemoveAdmin(message.group_openid, params)
    if ret:
        reply_service = MessageReplyService(api, message)
        await reply_service.PostSensitiveMessage(f"已为本群删除OpenId:{params}的管理员")
    return True

@Commands("设置名称")
async def SetGroupName(api: BotAPI, message: GroupMessage, params=None):
    """设置或强制修改群服互通昵称。"""
    guard_service = CommandGuardService(message)
    if await guard_service.GetBoundServer() is None:
        return True

    async def SetNameTag(nick, member_id=None, force_edit=False, change_status=False):
        """执行昵称写入并统一回复设置结果。"""
        if not member_id:
            member_id = message.author.member_openid
            call_name = f"您(OpenId:{member_id})"
        else:
            call_name = f"OpenId:{member_id}"

        result = await NicknameRepositoryInstance.SetName(
            message.group_openid,
            member_id,
            nick,
            force_edit=force_edit,
            change_status=change_status,
        )
        if result:
            is_force_text = "强制" if force_edit else ""
            await message.reply(content=f"已将{call_name}的群服互通昵称{is_force_text}设置为{ApplySensitiveFilter(nick)}")
        else:
            await message.reply(content="设置失败，该名称已被群内其他成员使用或被管理员强制锁定.")

    params_list = SplitCommandParams(params)
    admin_ret = await AdminRepositoryInstance.IsAdmin(message.group_openid, message.author.member_openid)

    if len(params_list) < 1:
        await message.reply(content="设置名称使用帮助:\n/设置名称 名称-可自行设定名称(无需管理员权限)\n/设置名称 名称 OpenId-管理员设定某人名称(或解除锁定)\n/设置名称 名称 OpenId 强制-管理员强制设定某人名称并锁定\n注:如输入的名称带有空格请使用\"\"（英文双引号）包裹")
        return True
    if len(params_list) == 1:
        await SetNameTag(nick=params_list[0], force_edit=False)
        return True
    if len(params_list) == 2:
        if not admin_ret:
            await message.reply(content=PERMISSION_DENIED_TEXT)
            return True
        await SetNameTag(nick=params_list[0], member_id=params_list[1], force_edit=False, change_status=True)
        return True
    if len(params_list) == 3:
        is_force = params_list[2] == "强制"
        if not admin_ret:
            await message.reply(content=PERMISSION_DENIED_TEXT)
            return True
        await SetNameTag(nick=params_list[0], member_id=params_list[1], force_edit=is_force, change_status=True)
        return True
    return True

@Commands("发信息")
async def SendGameMessage(api: BotAPI, message: GroupMessage, params=None):
    """把群消息转发到绑定服务器的游戏聊天。"""
    guard_service = CommandGuardService(message)
    bind_server = await guard_service.GetBoundServer()
    if bind_server is None:
        return True

    nick = await NicknameRepositoryInstance.GetName(message.group_openid, message.author.member_openid)
    if nick is None:
        await message.reply(content="没有找到你的昵称数据，请使用/设置名称 <昵称>来设置")
        return True

    #server_id = bind_server[1]

    unique_id = str(uuid.uuid4())

    async def run(server_id:str):
        ChatManager.SetBotApi(api)
        ChatManager.RememberMessage(server_id, message.group_openid, message.id, 1)

        if params:
            server_instance = ServerManagerInstance.GetWsServer()
            ws_ret = await server_instance.SendMsgByServerId(
                server_id,
                WebsocketEventSet.SendChat,
                {"msg": params, "nick": nick},
                str(uuid.uuid4()),
            )
            if not ws_ret:
                await message.reply(content=BuildWsSendFailedText(server_id))

    if len(bind_server) == 1:
        await run(bind_server[0])
    elif len(bind_server) > 1:
        await SendServerSelectorWithCallback(api, message, unique_id, run)
    return True


@Commands("执行命令")
async def SendCommand(api: BotAPI, message: GroupMessage, params=None):
    """向绑定服务器执行管理员命令并处理回调。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True

    unique_id = str(uuid.uuid4())

    async def run(server_id:str):

        server_instance = ServerManagerInstance.GetWsServer()
        reply_service = MessageReplyService(api, message)

        async def CmdReply(packed_msg, _msg_seq=3):
            """处理执行命令后的服务端回报。"""
            try:
                text = packed_msg.get("text", "")
                callback_convert = packed_msg.get("callbackConvert", 0)
                content, image_url, width, height = reply_service.BuildCommandCallbackPayload(
                    text, unique_id, callback_convert
                    )
                await reply_service.SendCallbackResponse(
                        content,
                        img_url=image_url,
                        img_width=width,
                        img_height=height,
                        msg_seq=_msg_seq
                )
                return True
            except Exception as exc:
                _log.error(f"命令回调处理失败: {exc}")
                await reply_service.PostSensitiveMessage(f"出现错误：{exc}", msg_seq=3)
                return True

        server_instance.AddCallbackFunc(unique_id, CmdReply)
        ws_ret = await server_instance.SendMsgByServerId(
                server_id,
                WebsocketEventSet.SendCommand,
                {"cmd": params},
                unique_id,
        )
        if ws_ret:
            await message.reply(content="已向服务器发送命令，请等待执行.")
        else:
            await message.reply(content=BuildWsSendFailedText(server_id))

    bind_server = await guard_service.GetBoundServer()
    if len(bind_server) == 1:
        await run(bind_server[0])
    elif len(bind_server) > 1:
        await SendServerSelectorWithCallback(api, message, unique_id, run)
    return True


@Commands("查白名单")
async def QueryWhiteList(api: BotAPI, message: GroupMessage, params=None):
    """查询白名单列表或按关键字筛选白名单。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True

    unique_id = str(uuid.uuid4())

    async def run(server_id:str):
        payload = {}
        if params:
            if IsNumber(params):
                payload = {"page": int(params)}
            else:
                payload = {"key": params}


        server_instance = ServerManagerInstance.GetWsServer()
        reply_service = MessageReplyService(api, message)
        server_instance.AddCallbackFunc(unique_id, reply_service.CreateTextReplyCallback(use_sensitive_filter=True))
        ws_ret = await server_instance.SendMsgByServerId(
                server_id,
                WebsocketEventSet.QueryWhiteList,
                payload,
                unique_id,
        )
        if not ws_ret:
            await message.reply(content=BuildWsSendFailedText(server_id))

    bind_server = await guard_service.GetBoundServer()
    if len(bind_server) == 1:
        await run(bind_server[0])
    elif len(bind_server) > 1:
        await SendServerSelectorWithCallback(api, message, unique_id, run)
    return True


@Commands("查在线")
async def QueryOnline(api: BotAPI, message: GroupMessage, params=None):
    """查询服务器在线玩家并注册结果回调。"""
    guard_service = CommandGuardService(message)
    bind_server = await guard_service.GetBoundServer()

    unique_id = str(uuid.uuid4())

    async def run(server_id:str):

        server_instance = ServerManagerInstance.GetWsServer()
        motd_service = MotdCommandService(api, message)
        server_instance.AddCallbackFunc(unique_id, motd_service.CreateOnlineReplyCallback())
        ws_ret = await server_instance.SendMsgByServerId(
                server_id,
                WebsocketEventSet.QueryOnlineList,
                {},
                unique_id,
        )
        if ws_ret:
            await message.reply(content="已向服务器发送查在线请求,请稍后...")
        else:
            await message.reply(content=BuildWsSendFailedText(server_id))

    if len(bind_server) == 1:
        await run(bind_server[0])
    elif len(bind_server) > 1:
        await SendServerSelectorWithCallback(api, message, unique_id, run)
    return True


@Commands("在线服务器")
async def QueryClientList(api: BotAPI, message: GroupMessage, params=None):
    """查询当前群可见的在线服务器列表。"""
    guard_service = CommandGuardService(message)
    bind_server = await guard_service.GetBoundServer()
    if len(bind_server) == 0:
        return True

    server_instance = ServerManagerInstance.GetWsServer()
    if message.group_openid in GetPublicGroups():
        client_list = await server_instance.QueryClientList(["MainServer"])
    else:
        server_id_list = []
        for item in bind_server:
            server_id_list.append(item[1])
        client_list = await server_instance.QueryClientList(server_id_list)

    client_text = ""
    for item in client_list:
        client_text += item + "\n"

    reply_service = MessageReplyService(api, message)
    await reply_service.PostSensitiveMessage(
        f"已连接{_config_manager.Get('BotName', ConfigManager.DEFAULT_BOT_NAME)}的服务器:\n{client_text}"
    )
    return True


async def CustomRun(is_admin: bool, api: BotAPI, message: GroupMessage, params=None):
    """执行服务端自定义命令并处理流式回报。"""
    guard_service = CommandGuardService(message)
    bind_server = await guard_service.GetBoundServer()

    unique_id = str(uuid.uuid4())

    async def run(server_id:str):
        params_list = SplitCommandParams(params)
        if len(params_list) < 1:
            await message.reply(content="参数不正确")
            return True

        key_word = params_list.pop(0)

        server_instance = ServerManagerInstance.GetWsServer()
        reply_service = MessageReplyService(api, message)

        async def CmdReply(packed_msg, _msg_seq=2):
            """处理自定义执行命令的文本或图片回报。"""
            try:
                text = packed_msg.get("text", "")
                callback_convert = packed_msg.get("callbackConvert", 0)
                is_json, parsed_data = TryParseJson(text)
                is_dict = is_json and isinstance(parsed_data, dict)
                msg_continue = is_dict and parsed_data.get("msgContinue", False)

                if is_dict:
                    content = f"{COMMAND_CALLBACK_PREFIX}\n{parsed_data.get('text', '无消息')}"
                    image_url = parsed_data.get("imgUrl")
                    width = parsed_data.get("width", parsed_data.get("imgWidth", 0))
                    height = parsed_data.get("height", parsed_data.get("imgHeight", 0))
                else:
                    filtered_text = ApplySensitiveFilter(text)
                    content, image_url, width, height = reply_service.BuildCommandCallbackPayload(
                        text,
                        unique_id,
                        callback_convert,
                        render_text=filtered_text,
                    )

                await reply_service.SendCallbackResponse(
                    content,
                    img_url=image_url,
                    img_width=width,
                    img_height=height,
                    msg_seq=_msg_seq,
                )
                return not msg_continue
            except Exception as exc:
                _log.error(f"自定义命令回调处理失败: {exc}")
                await reply_service.PostSensitiveMessage(f"出现错误：{exc}", msg_seq=2)
                return True

        server_instance.AddCallbackFunc(unique_id, CmdReply)
        send_event = WebsocketEventSet.CustomRunAdmin if is_admin else WebsocketEventSet.CustomRun
        nick = await NicknameRepositoryInstance.GetName(message.group_openid, message.author.member_openid)
        bind_qq = await AuthRepositoryInstance.GetBoundQQ(message.group_openid, message.author.member_openid)
        app_id = _config_manager.Get("AppId")
        ws_ret = await server_instance.SendMsgByServerId(
            server_id,
            send_event,
            {
                "key": key_word,
                "runParams": params_list,
                "author": {
                    "qlogoUrl": GetQLogoUrl(app_id, message.author.member_openid),
                    "bindNick": nick,
                    "openId": message.author.member_openid,
                    "bindQQ": bind_qq,
                },
                "group": {
                    "openId": message.group_openid,
                },
            },
            unique_id,
        )
        if ws_ret:
            admin_text = "(管理员)" if is_admin else ""
            await reply_service.PostSensitiveMessage(f"已向服务器发送自定义执行{admin_text}请求，请等待执行.")
        else:
            await message.reply(content=BuildWsSendFailedText(server_id))
        return  True

    if len(bind_server) == 1:
        await run(bind_server[0])
    elif len(bind_server) > 1:
        await SendServerSelectorWithCallback(api, message, unique_id, run)
    return True


@Commands("管理员执行")
async def AdminRunCommand(api: BotAPI, message: GroupMessage, params=None):
    """以管理员身份执行自定义命令。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True
    await CustomRun(True, api, message, params)
    return True


@Commands("执行")
async def RunCommand(api: BotAPI, message: GroupMessage, params=None):
    """以普通身份执行自定义命令。"""
    await CustomRun(False, api, message, params)
    return True


@Commands("motd")
async def Motd(api: BotAPI, message: GroupMessage, params=None):
    """查询指定地址的 Motd 信息。"""
    motd_service = MotdCommandService(api, message)
    if not await motd_service.EnsureAccess():
        return True
    motd_args = motd_service.ParseParams(params)
    if motd_args is None:
        await message.reply(content=MOTD_USAGE_TEXT)
        return True
    await motd_service.SendMotdResponse(motd_args[0], motd_args[1])
    return True


@Commands("unblockMotd")
async def UnblockMotd(api: BotAPI, message: GroupMessage, params=None):
    """解除当前群对 Motd 功能的屏蔽。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True
    ret = await MotdBlockRepositoryInstance.RemoveBlock(message.group_openid)
    if ret:
        await message.reply(content="本群已设置为:解除屏蔽Motd.")
    return True


@Commands("blockMotd")
async def BlockMotd(api: BotAPI, message: GroupMessage, params=None):
    """屏蔽当前群对 Motd 功能的访问。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.RequireAdmin():
        return True
    ret = await MotdBlockRepositoryInstance.AddBlock(message.group_openid)
    if ret:
        await message.reply(content="本群已设置为:屏蔽Motd.")
    return True


@Commands("解除认证")
async def UnauthQQAvatar(api: BotAPI, message: GroupMessage, params=None):
    """解除指定 OpenId 的 QQ 认证绑定。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.EnsureAuthReady():
        return True
    if not await guard_service.RequireAdmin():
        return True
    auth_service = AuthCommandService(message, api)
    await auth_service.HandleAuthUnbind(params)
    return True


@Commands("认证")
async def AuthQQAvatar(api: BotAPI, message: GroupMessage, params=None):
    """执行用户自助或管理员手动的 QQ 认证。"""
    guard_service = CommandGuardService(message)
    if not await guard_service.EnsureAuthReady():
        return True

    auth_service = AuthCommandService(message, api)
    param_list = SplitCommandParams(params)
    if len(param_list) == 0:
        await auth_service.HandleAuthStatusQuery(message.author.member_openid)
        return True
    if len(param_list) == 1:
        await auth_service.HandleSelfAuth(param_list[0])
        return True

    if not await guard_service.RequireAdmin():
        return True
    await auth_service.HandleAdminAuth(param_list[0], param_list[1])
    return True

class BaseBotMixin:
    """提供群消息分发与公共事件处理逻辑。"""

    @property
    def bot_api(self):
        """统一返回当前客户端持有的 API 实例。"""
        if isinstance(self, WebHookClient):
            return self.api
        if isinstance(self, Client):
            return self.api
        raise AttributeError("无法获取API实例")

    async def on_group_at_message_create(self, message: GroupMessage):
        """分发群聊命令，并在未命中时转入自定义执行。"""
        handlers = [
            GetHelp,
            AddAllowList,
            Bind,
            unBind,
            SetServer,
            DeleteAllowList,
            SetGroupName,
            SendGameMessage,
            SendCommand,
            QueryWhiteList,
            QueryOnline,
            QueryClientList,
            AdminRunCommand,
            RunCommand,
            QueryInfo,
            QueryAdminCommand,
            AddAdminCommand,
            DelAdminCommand,
            Motd,
            UnblockMotd,
            BlockMotd,
            UnauthQQAvatar,
            AuthQQAvatar,
        ]
        for handler in handlers:
            if await handler(api=self.bot_api, message=message):
                return

        admin_ret = await AdminRepositoryInstance.IsAdmin(message.group_openid, message.author.member_openid)
        match = re.match(r"^\s*\/(\S+)(?:\s+(.*))?$", message.content)
        if match:
            command = match.group(1)
            params = match.group(2) or ""
            await CustomRun(admin_ret, self.bot_api, message, command + " " + params.strip())

    async def on_message_audit_reject(self, message: MessageAudit):
        """记录被平台审核拒绝的消息。"""
        if message.message_id is not None:
            _log.warning(f"消息：{message.audit_id} 审核未通过.")

    async def on_group_add_robot(self, event: GroupManageEvent):
        """在机器人入群后发送欢迎和使用指引。"""
        bot_name = _config_manager.Get("BotName", ConfigManager.DEFAULT_BOT_NAME)
        try:
            upload_media = await self.bot_api.post_group_file(
                event.group_openid,
                1,
                "https://pic.txssb.cn/docQrCode.png",
                False,
            )
            await self.bot_api.post_group_message(
                group_openid=event.group_openid,
                msg_type=7,
                event_id=event.event_id,
                content=f"欢迎使用{bot_name}，首次使用请根据文档中的快速开始进行配置，文档可扫描上方二维码或手动输入网址.\n操作过程中需要@我，如:@{bot_name} /绑定 xxx\n欢迎加入交流群：1005746321",
                media=upload_media,
                msg_seq=1,
            )
        except Exception as exc:
            _log.error(f"机器人入群欢迎消息发送失败: {exc}")
            await self.bot_api.post_group_message(
                group_openid=event.group_openid,
                msg_type=0,
                event_id=event.event_id,
                content=f'欢迎使用{bot_name}，首次使用请根据文档中的快速开始进行配置,(图片发送失败,请稍后使用"@{bot_name} /帮助"进行查询)\n操作过程中需要@我，如:@{bot_name} /绑定 xxx\n欢迎加入交流群：1005746321',
            )

    async def on_interaction_create(self, interaction: Interaction):
        """处理按钮交互回调。

        result code: 0 成功 1 失败 2 频繁 3 重复 4 无权限 5 仅管理员
        """
        try:
            interaction_data = interaction.data
            resolved = interaction_data.resolved
            button_data = json.loads(resolved.button_data)
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            _log.warning(f"解析 interaction 按钮数据失败: {exc}")
            await self.bot_api.on_interaction_result(interaction.id, 1)
            return None

        action_id = button_data.get("actionId", "")
        server_id = button_data.get("serverId", "")

        #print(button_data)
        #print(_interaction_callbacks)

        # 先查看回调（不移除），校验权限
        entry = PeekInteractionCallback(action_id)
        if entry is None:
            _log.warning(f"无法获取 interaction 回调 [actionId={action_id}]")
            await self.bot_api.on_interaction_result(interaction.id, 1)
            return None

        if entry.get("needAdmin", False):
            group_openid = getattr(interaction, "group_openid", "")
            group_member_openid = getattr(interaction, "group_member_openid", "")
            if not group_openid or not group_member_openid:
                _log.warning(f"无法获取 interaction 群/用户信息 [actionId={action_id}]")
                await self.bot_api.on_interaction_result(interaction.id, 1)
                return None
            if not await AdminRepositoryInstance.IsAdmin(group_openid, group_member_openid):
                await self.bot_api.on_interaction_result(interaction.id, 4)
                return None

        # 权限通过后再取出并执行
        entry = PopInteractionCallback(action_id)
        if entry is None:
            _log.warning(f"无法获取 interaction 回调 [actionId={action_id}]")
            await self.bot_api.on_interaction_result(interaction.id, 1)
            return None

        callback = entry.get("function")
        if callback is not None:
            try:
                await callback(server_id)
            except Exception as exc:
                _log.error(f"按钮回调执行异常 [actionId={action_id}]: {exc}")

        await self.bot_api.on_interaction_result(interaction.id, 0)
        return None


class WsBotClient(BaseBotMixin, ymbotpy.Client):
    """定义 WebSocket 模式下的 Bot 客户端。"""

    def __init__(self, *args, **kwargs):
        """初始化长连接模式所需的 intents。"""
        self.intents = ymbotpy.Intents(
            public_messages=True,
            interaction=True,
            message_audit=True,
        )
        super().__init__(intents=self.intents or ymbotpy.Intents.none(), *args, **kwargs)


class WebhookBotClient(BaseBotMixin, ymbotpy.WebHookClient):
    """定义 Webhook 模式下的 Bot 客户端。"""


async def StartClient(app_id: str, secret: str, sandbox: bool, webhook: bool):
    """按运行模式启动 Bot 客户端。"""
    client_class = WebhookBotClient if webhook else WsBotClient
    if webhook:
        client = client_class(is_sandbox=sandbox)
        ssl_keyfile = None
        ssl_certfile = None
        if os.path.exists("ssl/private.key") and os.path.exists("ssl/public.crt"):
            ssl_keyfile = "ssl/private.key"
            ssl_certfile = "ssl/public.crt"
            _log.info("使用SSL证书")

        await client.start(
            appid=app_id,
            secret=secret,
            port=8443,
            system_log=False,
            ssl_certfile=ssl_certfile,
            ssl_keyfile=ssl_keyfile,
        )
        return client

    client = client_class(is_sandbox=sandbox)
    await client.start(appid=app_id, secret=secret)
    return client


async def CreateServer(ws_name: str, ws_url: str, ws_key: str):
    """创建并注册 WebSocket 桥接实例。"""
    server_instance = WebsocketClient(ws_name, ws_url, ws_key)
    ServerManagerInstance.SetWsServer(server_instance)
    return server_instance


async def StartServer(ws_name: str, ws_url: str, ws_key: str):
    """启动 WebSocket 桥接连接。"""
    server = await CreateServer(ws_name, ws_url, ws_key)
    if not await server.Connect():
        await server.Reconnect()


async def Main(app_id, secret, ws_key, bot_name, ws_url, sandbox, webhook):
    """并发启动桥接连接和 Bot 客户端。"""
    server_coroutine = StartServer(bot_name, ws_url, ws_key)
    client_coroutine = StartClient(app_id, secret, sandbox, webhook)
    await asyncio.gather(server_coroutine, client_coroutine)


if __name__ == "__main__":
    _log.info("请使用index.py启动")

    
    