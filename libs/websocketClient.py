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

    async def connect(self):
        try:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            if not self.uri.startswith("wss://"):
                ssl_context = None

            self.ws = await websockets.connect(self.uri, ssl=ssl_context)
            logger.info("Connected to the server")
            await self._sendShakeHand()
            # 启动监听任务
            asyncio.create_task(self.listen())
            asyncio.create_task(self.send_heartbeat())
        except Exception as e:
            logger.error(f"Connection failed: {e}")


    async def listen(self):
        if self.ws is not None:
            try:
                async for message in self.ws:
                    await self.process_message(message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection with the server was closed")
                await self.reconnect()

    def onShaked(self, id, body):
        if body["code"] == 1:
            logger.info("握手完成!")
        elif body["code"] == 3:
            logger.error(f"握手失败!原因: {body['msg']}")
        else:
            logger.error(f"握手失败!原因: {body['msg']}")

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
        serverTempData = bindServerTemp[id]
        await self._sendMsg(botClientRecvEvent.getConfirmData,{'serverTempData':serverTempData},id)
        del bindServerTemp[id]

    async def onChat(self, id:str, body:dict):
        serverId = body.get("serverId","")
        msg = body.get("msg")
        await chatManager.postChat(serverId,msg)

    async def process_message(self, message):
        json_msg = json.loads(message)
        #print(json_msg)
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

    async def _sendShakeHand(self):
        await self._sendMsg(
            botClientSendEvent.shakeHand,
            {
                "serverId": "BotClient",
                "hashKey": self.wsKey,
                "name": "HuHoBot",
            }
        )

    async def send_and_wait(self, type_, body, uuid_ = str(uuid.uuid4()),timeout=10.):
        future = asyncio.Future()
        uuid_ = str(uuid_)
        self.pending_requests[uuid_] = future

        # 发送消息
        await self._sendMsg(type_, body, uuid_)

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
        while True:
            await asyncio.sleep(5)
            if self.ws is not None:
                try:
                    await self._sendMsg(botClientSendEvent.heart, {})
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("Connection closed while sending heartbeat")
                    await self.reconnect()

    async def _sendMsg(self, type_, body, uuid_=None):
        if uuid_ is None:
            uuid_ = str(uuid.uuid4())
        message = json.dumps({"header": {"type": type_, "id": uuid_}, "body": body})
        try:
            await self.ws.send(message)
            return True
        except Exception as e:
            logger.error(f"[Websocket] {e}")
            await self.reconnect()
            return False

    async def reconnect(self):
        logger.info("Attempting to reconnect...")
        await asyncio.sleep(3)
        await self.connect()

    async def close(self):
        if self.ws is not None:
            await self.ws.close()

    async def sendMsgByServerId(self,
                                serverId,
                                type: str,
                                msg: dict,
                                unique_id = str(uuid.uuid4())):
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
                await self.callback[callbackId](args)
            except Exception as e:
                logger.error(f"[Websocket] {e}")
                
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