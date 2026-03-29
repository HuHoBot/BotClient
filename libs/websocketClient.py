import json
import websockets
import uuid
import asyncio
from libs.basic import *
from ymbotpy import logging
import ssl

logger = logging.get_logger()    #Botpy Logger

#Websocket事件类
class WebsocketEvent:
    def __init__(self):
        self.addWhiteList = "add"
        self.delWhiteList = "delete"
        self.bindRequest = "bindRequest"
        self.sendConfig = "sendConfig"
        self.sendChat = "chat"
        self.sendCommand = "cmd"
        self.queryWhiteList = "queryList"
        self.queryOnlineList = "queryOnline"
        self.customRun = "run"
        self.customRun_Admin = "runAdmin"

websocketEvent = WebsocketEvent()

class BotClientSendEvent:
    def __init__(self):
        self.sendMsgByServerId = "BotClient.sendMsgByServerId"
        self.queryClientList = "BotClient.queryClientList"
        self.shakeHand = "BotClient.shakeHand"
        self.queryState = "BotClient.queryStatus"
        self.heart = "BotClient.heart"

class BotClientRecvEvent:
    def __init__(self):
        self.queryBindServerById = "BotClient.queryBindServerById"
        self.bindServer = "BotClient.bindServer"
        self.addAdmin = "BotClient.addAdmin"
        self.callbackFunc = "BotClient.callbackFunc"
        self.getConfirmData = "BotClient.getConfirmData"
        self.chat = "BotClient.chat"

botClientSendEvent = BotClientSendEvent()
botClientRecvEvent = BotClientRecvEvent()

# 定义WebSocket客户端类
class WebsocketClient:
    def __init__(self, name, uri,wsKey):
        self.name = name
        self.uri = uri
        self.wsKey = wsKey
        self.ws = None
        self.pending_requests = {}  # 存储 {uuid: Future} 的映射
        self.callback = {}
        self._listen_task = None
        self._heartbeat_task = None
        self._reconnecting = False  # 重连锁，防止并发重连
        self._heartbeat_fail_count = 0  # 连续心跳失败计数
        self._max_heartbeat_fails = 3  # 最大连续心跳失败次数
        self._shook_hands = False  # 握手是否完成

    async def connect(self):
        try:
            # 先清理旧连接
            await self._cleanup()

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
                        ping_timeout=20
                ),
                timeout=15
            )

            logger.info("Connected to the server")
            self._shook_hands = False
            self._heartbeat_fail_count = 0
            await self._sendShakeHand()
            self._listen_task = asyncio.create_task(self.listen())
            self._heartbeat_task = asyncio.create_task(self.send_heartbeat())
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            await self._cleanup()
            await self.reconnect()

    async def _cleanup(self):
        """清理旧的连接和任务"""
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

        # 清理所有挂起的请求，让等待者收到错误而非永久阻塞
        for uid, future in self.pending_requests.items():
            if not future.done():
                future.set_result({})
        self.pending_requests.clear()

    async def listen(self):
        """
        监听消息，结束后自动触发重连
        """
        if self.ws is None:
            return
        try:
            async for message in self.ws:
                await self.process_message(message)
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"Connection closed: {e}")
        except Exception as e:
            logger.error(f"[Websocket] Listening error: {e}")
        finally:
            # 无论因为什么原因退出 listen，都触发重连循环
            asyncio.create_task(self.reconnect())

    def onShaked(self, id, body):
        code = body.get("code")
        if code == 1:
            self._shook_hands = True
            logger.info("握手完成!")
        else:
            self._shook_hands = False
            logger.error(f"握手失败!原因: {body.get('msg', '未知错误')}")

    async def onBindServer(self, id:str, body:dict):
        group = body.get("group","")
        serverConfig = body.get("serverConfig",{})
        await bindServer(group,serverConfig)

    async def onAddAdmin(self, id:str, body:dict):
        group = body.get("group","")
        author = body.get("author","")
        await addAdmin(group,author)

    async def onQueryBindServerById(self, id:str, body:dict):
        serverId = body.get("serverId","")
        rawData = await queryBindServerById(serverId)
        if(len(rawData) > 0):
            hashKey = rawData[0][2]
            await self._sendMsg(botClientRecvEvent.queryBindServerById,{'hashKey':hashKey},id)
        else:
            await self._sendMsg(botClientRecvEvent.queryBindServerById,{'hashKey':"none."},id)

    async def onCallbackFunc(self, id:str, body:dict):
        param = body.get("param","")
        await self.callBackFunc(id,param)

    async def onGetConfirmData(self, id:str, body:dict):
        serverTempData = bindServerObj.getBindServer(id)
        if serverTempData is None:
            logger.error(f"[Websocket] bindServer 中不存在 id: {id}")
            return
        await self._sendMsg(botClientRecvEvent.getConfirmData,{'serverTempData':serverTempData},id)
        bindServerObj.delBindServer(id)

    async def onChat(self, id:str, body:dict):
        serverId = body.get("serverId","")
        msg = body.get("msg")
        await chatManager.postChat(serverId,msg)

    async def process_message(self, message):
        try:
            json_msg = json.loads(message)
        except json.JSONDecodeError:
            logger.error(f"[Websocket] 收到非JSON消息: {message[:200]}")
            return
        header = json_msg.get("header", {})
        body = json_msg.get("body", {})
        type_ = header.get("type")
        uuid_ = header.get("id")

        # 检查是否有挂起的请求
        if uuid_ in self.pending_requests:
            future = self.pending_requests.pop(uuid_)  # 从挂起请求中移除
            if not future.done():  # 确保 Future 尚未完成
                future.set_result(body)
        else:
            # 普通的消息处理
            try:
                if type_ == "shaked":
                    self.onShaked(uuid_, body)
                elif type_ == botClientRecvEvent.bindServer:
                    await self.onBindServer(uuid_,body)
                elif type_ == botClientRecvEvent.queryBindServerById:
                    await self.onQueryBindServerById(uuid_,body)
                elif type_ == botClientRecvEvent.addAdmin:
                    await self.onAddAdmin(uuid_,body)
                elif type_ == botClientRecvEvent.callbackFunc:
                    await self.onCallbackFunc(uuid_,body)
                elif type_ == botClientRecvEvent.getConfirmData:
                    await self.onGetConfirmData(uuid_,body)
                elif type_ == botClientRecvEvent.chat:
                    await self.onChat(uuid_,body)
            except Exception as e:
                logger.error(f"[Websocket] 处理消息时异常: type={type_}, error={e}")

    async def _sendShakeHand(self):
        await self._sendMsg(
            botClientSendEvent.shakeHand,
            {
                "serverId": "BotClient",
                "hashKey": self.wsKey,
                "name": "HuHoBot",
                "platform":"botclient",
                "version":"1.0.0"
            }
        )

    async def send_and_wait(self, type_, body, uuid_=None, timeout=10.):
        if not self.isActive():
            logger.warning("[Websocket] 连接未就绪，无法发送消息")
            return {}
        if uuid_ is None:
            uuid_ = str(uuid.uuid4())
        future = asyncio.Future()
        uuid_ = str(uuid_)
        self.pending_requests[uuid_] = future

        # 发送消息
        sent = await self._sendMsg(type_, body, uuid_)
        if not sent:
            self.pending_requests.pop(uuid_, None)
            if not future.done():
                future.set_result({})
            return {}

        try:
            # 等待响应或超时
            response = await asyncio.wait_for(future, timeout)
            return response
        except asyncio.TimeoutError:
            logger.error(f"等待响应超时: UUID={uuid_}")
            # 超时后清理挂起的请求
            self.pending_requests.pop(uuid_, None)
        return {}

    async def send_heartbeat(self):
        try:
            while True:
                await asyncio.sleep(5)
                if self.ws is None or self.ws.closed:
                    logger.warning("[Websocket] 心跳检测到连接已断开")
                    break

                try:
                    # 使用 send_and_wait 验证服务端是否真正响应心跳
                    heart_uuid = str(uuid.uuid4())
                    future = asyncio.Future()
                    self.pending_requests[heart_uuid] = future
                    await self._sendMsg(botClientSendEvent.heart, {}, heart_uuid)

                    try:
                        await asyncio.wait_for(future, timeout=5)
                        # 心跳正常，重置失败计数
                        self._heartbeat_fail_count = 0
                    except asyncio.TimeoutError:
                        self.pending_requests.pop(heart_uuid, None)
                        self._heartbeat_fail_count += 1
                        logger.warning(f"[Websocket] 心跳响应超时 ({self._heartbeat_fail_count}/{self._max_heartbeat_fails})")
                        if self._heartbeat_fail_count >= self._max_heartbeat_fails:
                            logger.error("[Websocket] 连续心跳超时，判定为假连接，触发重连")
                            break
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("Connection closed while sending heartbeat")
                    break
                except Exception as e:
                    logger.error(f"[Websocket] 心跳异常: {e}")
                    break
        except asyncio.CancelledError:
            return
        # 心跳退出后触发重连
        await self.reconnect()

    async def _sendMsg(self, type_, body, uuid_=None):
        if uuid_ is None:
            uuid_ = str(uuid.uuid4())
        if self.ws is None or self.ws.closed:
            logger.error("[Websocket] 连接不可用，无法发送消息")
            return False
        message = json.dumps({"header": {"type": type_, "id": uuid_}, "body": body})
        try:
            await self.ws.send(message)
            return True
        except Exception as e:
            logger.error(f"[Websocket] 发送消息失败: {e}")
            return False

    async def reconnect(self):
        """
        全局重连守护逻辑
        使用锁防止并发，使用循环确保最终连上
        """
        if self._reconnecting:
            return

        self._reconnecting = True
        try:
            attempt = 0
            while not self.isActive():
                attempt += 1
                # 阶梯式等待，防止请求过快被服务器屏蔽 (3s, 6s, 9s...)
                wait_time = min(3 * attempt, 30)
                logger.info(f"Reconnecting... (Attempt {attempt}), waiting {wait_time}s")

                await asyncio.sleep(wait_time)

                # 尝试连接
                if await self.connect():
                    logger.info("Reconnection successful.")
                    break
        finally:
            self._reconnecting = False

    async def close(self):
        await self._cleanup()

    def isActive(self):
        return self.ws is not None and not self.ws.closed

    async def sendMsgByServerId(self,
                                serverId,
                                type: str,
                                msg: dict,
                                unique_id=None):
        if unique_id is None:
            unique_id = str(uuid.uuid4())
        try:
            ret = await self.send_and_wait(botClientSendEvent.sendMsgByServerId,{"serverId":serverId,"type":type,"data":msg},unique_id)
        except Exception as e:
            logger.error(f"[Websocket] {e}")
            return False
        return ret.get('status', False)


    async def queryClientList(self,serverIdList):
        try:
            ret = await self.send_and_wait(botClientSendEvent.queryClientList,{"serverIdList":serverIdList})
            return ret.get('clientList', [])
        except Exception as e:
            logger.error(f"[Websocket] {e}")
            return []

    #添加Callback事件
    def addCallbackFunc(self,id,cbfunc):
        self.callback[id] = cbfunc
        return True

    async def callBackFunc(self,callbackId:str,args):
        if callbackId in self.callback:
            try:
                shouldDelete = await self.callback[callbackId](args)
                if shouldDelete:
                    del self.callback[callbackId]
            except Exception as e:
                logger.error(f"[Websocket] Callback执行异常: {e}")
                del self.callback[callbackId]
            return True
        else:
            logger.error("[Websocket] Callback Id不存在")
            return False

# 使用WebSocket客户端
async def main():
    client = WebsocketClient("HuHoBot",'ws://127.0.0.1:8888')
    await client.connect()


if __name__ == "__main__":
    asyncio.run(main())
