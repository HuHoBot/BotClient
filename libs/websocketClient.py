import asyncio
import json
import ssl
import uuid

import websockets
from ymbotpy import logging

from libs.chatService import ChatManager
from libs.repositories import AdminRepositoryInstance, BindRepositoryInstance, PendingBindStoreInstance

logger = logging.get_logger()


class WebsocketEvent:
    """保存机器人发往服务端的业务事件名称。"""

    def __init__(self):
        """初始化业务事件名称常量。"""
        self.AddWhiteList = "add"
        self.DelWhiteList = "delete"
        self.BindRequest = "bindRequest"
        self.SendConfig = "sendConfig"
        self.SendChat = "chat"
        self.SendCommand = "cmd"
        self.QueryWhiteList = "queryList"
        self.QueryOnlineList = "queryOnline"
        self.CustomRun = "run"
        self.CustomRunAdmin = "runAdmin"


class BotClientSendEvent:
    """保存机器人客户端主动发送的底层事件名称。"""

    def __init__(self):
        """初始化底层发送事件名称常量。"""
        self.SendMsgByServerId = "BotClient.sendMsgByServerId"
        self.QueryClientList = "BotClient.queryClientList"
        self.ShakeHand = "BotClient.shakeHand"
        self.QueryState = "BotClient.queryStatus"
        self.Heart = "BotClient.heart"


class BotClientRecvEvent:
    """保存机器人客户端接收的底层事件名称。"""

    def __init__(self):
        """初始化底层接收事件名称常量。"""
        self.QueryBindServerById = "BotClient.queryBindServerById"
        self.BindServer = "BotClient.bindServer"
        self.AddAdmin = "BotClient.addAdmin"
        self.CallbackFunc = "BotClient.callbackFunc"
        self.GetConfirmData = "BotClient.getConfirmData"
        self.Chat = "BotClient.chat"


WebsocketEventSet = WebsocketEvent()
BotClientSendEventSet = BotClientSendEvent()
BotClientRecvEventSet = BotClientRecvEvent()


class WebsocketClient:
    """负责维护机器人与主控服务之间的 WebSocket 连接。"""

    def __init__(self, name, uri, ws_key):
        """初始化连接参数、回调表和连接状态。"""
        self.name = name
        self.uri = uri
        self.ws_key = ws_key
        self.ws = None
        self.pending_requests = {}
        self.callback = {}
        self._listen_task = None
        self._heartbeat_task = None
        self._reconnecting = False
        self._heartbeat_fail_count = 0
        self._max_heartbeat_fails = 3
        self._shook_hands = False

    async def Connect(self):
        """建立 WebSocket 连接并启动监听与心跳任务。"""
        try:
            await self._Cleanup()

            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            if not self.uri.startswith("wss://"):
                ssl_context = None

            self.ws = await asyncio.wait_for(
                websockets.connect(
                    self.uri,
                    ssl=ssl_context,
                    ping_interval=30,
                    ping_timeout=20,
                ),
                timeout=15,
            )

            logger.info("Connected to the server")
            self._shook_hands = False
            self._heartbeat_fail_count = 0
            await self._SendShakeHand()
            self._listen_task = asyncio.create_task(self.Listen())
            self._heartbeat_task = asyncio.create_task(self.SendHeartbeat())
            return True
        except Exception as exc:
            logger.error(f"Connection failed: {exc}")
            await self._Cleanup()
            return False

    async def _Cleanup(self):
        """清理旧连接、旧任务以及挂起中的请求。"""
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except (asyncio.CancelledError, Exception):
                pass
        self._listen_task = None

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass
        self._heartbeat_task = None

        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

        for request_id, future in self.pending_requests.items():
            if not future.done():
                future.set_result({})
        self.pending_requests.clear()

    async def Listen(self):
        """持续监听服务端消息，并在连接断开后触发重连。"""
        if self.ws is None:
            return

        try:
            async for message in self.ws:
                await self.ProcessMessage(message)
        except websockets.exceptions.ConnectionClosed as exc:
            logger.warning(f"Connection closed: {exc}")
        except Exception as exc:
            logger.error(f"[Websocket] Listening error: {exc}")
        finally:
            asyncio.create_task(self.Reconnect())

    def OnShaked(self, request_id, body):
        """处理握手结果。"""
        code = body.get("code")
        if code == 1:
            self._shook_hands = True
            logger.info("握手完成!")
        else:
            self._shook_hands = False
            logger.error(f"握手失败!原因: {body.get('msg', '未知错误')}")

    async def OnBindServer(self, request_id: str, body: dict):
        """处理服务端推送的绑定落库请求。"""
        group = body.get("group", "")
        server_config = body.get("serverConfig", {})
        await BindRepositoryInstance.BindServer(group, server_config)

    async def OnAddAdmin(self, request_id: str, body: dict):
        """处理服务端推送的管理员落库请求。"""
        group = body.get("group", "")
        author = body.get("author", "")
        await AdminRepositoryInstance.AddAdmin(group, author)

    async def OnQueryBindServerById(self, request_id: str, body: dict):
        """按服务端请求回传对应的绑定哈希密钥。"""
        server_id = body.get("serverId", "")
        hash_key = await BindRepositoryInstance.GetHashKeyByServerId(server_id)
        if hash_key is None:
            hash_key = "none."
        await self._SendMsg(BotClientRecvEventSet.QueryBindServerById, {"hashKey": hash_key}, request_id)

    async def OnCallbackFunc(self, request_id: str, body: dict):
        """转发服务端回调到本地注册的处理器。"""
        param = body.get("param", "")
        await self.CallBackFunc(request_id, param)

    async def OnGetConfirmData(self, request_id: str, body: dict):
        """回传待确认的绑定请求数据。"""
        server_temp_data = PendingBindStoreInstance.GetRequest(request_id)
        if server_temp_data is None:
            logger.error(f"[Websocket] bindServer 中不存在 id: {request_id}")
            return
        await self._SendMsg(BotClientRecvEventSet.GetConfirmData, {"serverTempData": server_temp_data}, request_id)
        PendingBindStoreInstance.RemoveRequest(request_id)

    async def OnChat(self, request_id: str, body: dict):
        """把服务端聊天广播回各群。"""
        server_id = body.get("serverId", "")
        msg = body.get("msg")
        await ChatManager.BroadcastChat(server_id, msg)

    async def ProcessMessage(self, message):
        """解析并分发收到的 WebSocket 消息。"""
        try:
            json_msg = json.loads(message)
        except json.JSONDecodeError:
            logger.error(f"[Websocket] 收到非JSON消息: {message[:200]}")
            return

        header = json_msg.get("header", {})
        body = json_msg.get("body", {})
        event_type = header.get("type")
        request_id = header.get("id")

        if request_id in self.pending_requests:
            future = self.pending_requests.pop(request_id)
            if not future.done():
                future.set_result(body)
            return

        try:
            if event_type == "shaked":
                self.OnShaked(request_id, body)
            elif event_type == BotClientRecvEventSet.BindServer:
                await self.OnBindServer(request_id, body)
            elif event_type == BotClientRecvEventSet.QueryBindServerById:
                await self.OnQueryBindServerById(request_id, body)
            elif event_type == BotClientRecvEventSet.AddAdmin:
                await self.OnAddAdmin(request_id, body)
            elif event_type == BotClientRecvEventSet.CallbackFunc:
                await self.OnCallbackFunc(request_id, body)
            elif event_type == BotClientRecvEventSet.GetConfirmData:
                await self.OnGetConfirmData(request_id, body)
            elif event_type == BotClientRecvEventSet.Chat:
                await self.OnChat(request_id, body)
        except Exception as exc:
            logger.error(f"[Websocket] 处理消息时异常: type={event_type}, error={exc}")

    async def _SendShakeHand(self):
        """向服务端发送握手消息。"""
        await self._SendMsg(
            BotClientSendEventSet.ShakeHand,
            {
                "serverId": "BotClient",
                "hashKey": self.ws_key,
                "name": "HuHoBot",
                "platform": "botclient",
                "version": "1.0.0",
            },
        )

    async def SendAndWait(self, event_type, body, request_id=None, timeout=10.0):
        """发送消息并等待服务端同步响应。"""
        if not self.IsActive():
            logger.warning("[Websocket] 连接未就绪，无法发送消息")
            return {}

        if request_id is None:
            request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        request_id = str(request_id)
        self.pending_requests[request_id] = future

        sent = await self._SendMsg(event_type, body, request_id)
        if not sent:
            self.pending_requests.pop(request_id, None)
            if not future.done():
                future.set_result({})
            return {}

        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            logger.error(f"等待响应超时: UUID={request_id}")
            self.pending_requests.pop(request_id, None)
            return {}

    async def SendHeartbeat(self):
        """定时发送心跳，并在心跳失效时触发重连。"""
        try:
            while True:
                await asyncio.sleep(5)
                if self.ws is None or self.ws.closed:
                    logger.warning("[Websocket] 心跳检测到连接已断开")
                    break

                try:
                    heart_id = str(uuid.uuid4())
                    future = asyncio.get_running_loop().create_future()
                    self.pending_requests[heart_id] = future
                    await self._SendMsg(BotClientSendEventSet.Heart, {}, heart_id)

                    try:
                        await asyncio.wait_for(future, timeout=5)
                        self._heartbeat_fail_count = 0
                    except asyncio.TimeoutError:
                        self.pending_requests.pop(heart_id, None)
                        self._heartbeat_fail_count += 1
                        logger.warning(f"[Websocket] 心跳响应超时 ({self._heartbeat_fail_count}/{self._max_heartbeat_fails})")
                        if self._heartbeat_fail_count >= self._max_heartbeat_fails:
                            logger.error("[Websocket] 连续心跳超时，判定为假连接，触发重连")
                            break
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("Connection closed while sending heartbeat")
                    break
                except Exception as exc:
                    logger.error(f"[Websocket] 心跳异常: {exc}")
                    break
        except asyncio.CancelledError:
            return

        await self.Reconnect()

    async def _SendMsg(self, event_type, body, request_id=None):
        """向当前 WebSocket 连接发送一条消息。"""
        if request_id is None:
            request_id = str(uuid.uuid4())
        if self.ws is None or self.ws.closed:
            logger.error("[Websocket] 连接不可用，无法发送消息")
            return False

        message = json.dumps({"header": {"type": event_type, "id": request_id}, "body": body})
        try:
            await self.ws.send(message)
            return True
        except Exception as exc:
            logger.error(f"[Websocket] 发送消息失败: {exc}")
            return False

    async def Reconnect(self):
        """串行执行全局重连流程，直到连接恢复。"""
        if self._reconnecting:
            return

        self._reconnecting = True
        try:
            attempt = 0
            while not self.IsActive():
                attempt += 1
                wait_time = min(3 * attempt, 30)
                logger.info(f"Reconnecting... (Attempt {attempt}), waiting {wait_time}s")
                await asyncio.sleep(wait_time)
                if await self.Connect():
                    logger.info("Reconnection successful.")
                    break
        finally:
            self._reconnecting = False

    async def Close(self):
        """主动关闭当前连接和关联任务。"""
        await self._Cleanup()

    def IsActive(self):
        """判断当前 WebSocket 是否处于可用状态。"""
        return self.ws is not None and not self.ws.closed

    async def SendMsgByServerId(self, server_id, event_type: str, msg: dict, unique_id=None):
        """按服务器编号向服务端发送业务消息。"""
        if unique_id is None:
            unique_id = str(uuid.uuid4())
        try:
            ret = await self.SendAndWait(
                BotClientSendEventSet.SendMsgByServerId,
                {"serverId": server_id, "type": event_type, "data": msg},
                unique_id,
            )
        except Exception as exc:
            logger.error(f"[Websocket] {exc}")
            return False
        return ret.get("status", False)

    async def QueryClientList(self, server_id_list):
        """查询指定服务器编号列表的在线连接状态。"""
        try:
            ret = await self.SendAndWait(
                BotClientSendEventSet.QueryClientList,
                {"serverIdList": server_id_list},
            )
            return ret.get("clientList", [])
        except Exception as exc:
            logger.error(f"[Websocket] {exc}")
            return []

    def AddCallbackFunc(self, callback_id, callback_func):
        """注册一条等待服务端回传的回调处理器。"""
        self.callback[callback_id] = callback_func
        return True

    async def CallBackFunc(self, callback_id: str, args):
        """执行指定回调，并根据返回值决定是否删除。"""
        if callback_id in self.callback:
            try:
                should_delete = await self.callback[callback_id](args)
                if should_delete:
                    del self.callback[callback_id]
            except Exception as exc:
                logger.error(f"[Websocket] Callback执行异常: {exc}")
                del self.callback[callback_id]
            return True

        logger.error("[Websocket] Callback Id不存在")
        return False


async def Main():
    """用于本地调试 WebSocket 客户端。"""
    client = WebsocketClient("HuHoBot", "ws://127.0.0.1:8888", "")
    if not await client.Connect():
        await client.Reconnect()


if __name__ == "__main__":
    asyncio.run(Main())
