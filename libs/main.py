# -*- coding: utf-8 -*-
import botpy
import asyncio
import websockets
import uuid

import ymbotpy
from ymbotpy.interaction import Interaction
from ymbotpy.manage import GroupManageEvent
from ymbotpy.message import Message,GroupMessage,MessageAudit
from ymbotpy.types.message import Keyboard, KeyboardPayload, MarkdownPayload
from ymbotpy.ext.command_util import *
from ymbotpy import logging, WebHookClient, Client
from decimal import Decimal, getcontext

from libs.basic import *
from libs.switchAvatars import *
from libs.websocketClient import *

_log = logging.get_logger()    #Botpy Logger
#server_instance = None         #websocketServer全局变量
class ServerManager:
    def __init__(self) -> None:
        self.wsServer = None

    def setWsServer(self,wsServerObj:WebsocketClient) -> None:
        self.wsServer = wsServerObj

    def getWsServer(self) -> WebsocketClient:
        return self.wsServer
    
serverManager = ServerManager()

async def postImages(api: BotAPI, message: GroupMessage, imgUrl:str,text:str = "",failedText:str = "图片发送失败"):
    try:
        uploadMedia = await api.post_group_file(
            message.group_openid,
            1,
            imgUrl,
            False
        )
        await api.post_group_message(
            group_openid=message.group_openid,
            msg_type=7,
            msg_id=message.id,
            content=text,
            media=uploadMedia,
            msg_seq=1
        )
    except:
        await message.reply(content=failedText)

@Commands("帮助")
async def getHelp(api: BotAPI, message: GroupMessage, params=None):
    if (not params) or ("文档" in params):
        await postImages(api,message,"https://pic.txssb.cn/docQrCode.png","HuHoBot 文档站请扫描二维码或手动输入网址",'图片发送失败，请稍后再试.')
    elif "管理" in params:
        await postImages(api,message,"https://pic.txssb.cn/adminHelp.jpeg","HuHoBot 管理帮助如图，更多详情请前往文档站查看",'图片发送失败，请使用"/帮助 文档"获取文档链接')
    elif "指令" in params:
        await postImages(api,message,"https://pic.txssb.cn/commandHelp.jpeg","HuHoBot 指令列表如图，更多详情请前往文档站查看",'图片发送失败，请使用"/帮助 文档"获取文档链接')
    elif "快速开始" in params:
        await postImages(api,message,"https://pic.txssb.cn/quickStartQrCode.png","HuHoBot 文档站快速开始请扫描二维码或手动输入网址",'图片发送失败，请稍后再试.')

    return True

@Commands("添加白名单")
async def addAllowList(api: BotAPI, message: GroupMessage, params=None):
    server_instance = serverManager.getWsServer()
    adminRet = await queryIsAdmin(message.group_openid,message.author.member_openid)
    if(not adminRet):
        await message.reply(content="你没有足够的权限.")
        return True
    if(not params):
        await message.reply(content=f"参数不正确")
        return True

    unique_id = str(uuid.uuid4())
    async def wlReply(msg):
        ret = await message.reply(content=msg,msg_seq=2)
    server_instance.addCallbackFunc(unique_id,wlReply)
    
    ret = await queryBindServerByGroup(message.group_openid)
    if(ret == None):
        await message.reply(content=f"您还未绑定服务器，请按说明进行绑定.")
        return True
    wsRet = await server_instance.sendMsgByServerId(ret[1],websocketEvent.addWhiteList,{"xboxid":params},unique_id)
    if(wsRet):
        await message.reply(content=f"已请求添加白名单.\nXbox Id:{params}\n请管理员核对.如有错误,请输入/删除白名单 {params}")
    else:
        await message.reply(content=f"无法向Id为{ret[1]}的服务器发送请求，请管理员检查连接状态")
    return True

@Commands("删除白名单")
async def reCall(api: BotAPI, message: GroupMessage, params=None):
    server_instance = serverManager.getWsServer()
    adminRet = await queryIsAdmin(message.group_openid,message.author.member_openid)
    if(not adminRet):
        await message.reply(content="你没有足够的权限.")
        return True
    if(not params):
        await message.reply(content=f"参数不正确")
        return True
    
    unique_id = str(uuid.uuid4())
    async def wlReply(msg):
        ret = await message.reply(content=msg,msg_seq=2)
    server_instance.addCallbackFunc(unique_id,wlReply)

    ret = await queryBindServerByGroup(message.group_openid)
    if(ret == None):
        await message.reply(content=f"您还未绑定服务器，请按说明进行绑定.")
        return True
    wsRet = await server_instance.sendMsgByServerId(ret[1],websocketEvent.delWhiteList,{"xboxid":params},unique_id)
    if(wsRet):
        await message.reply(content=f"已请求删除Xboxid为{params}的白名单.")
    else:
        await message.reply(content=f"无法向Id为{ret[1]}的服务器发送请求，请管理员检查连接状态")
    return True

@Commands("绑定")
async def bind(api: BotAPI, message: GroupMessage, params=None):
    paramsList = splitCommandParams(params)
    if len(paramsList) < 1 or len(paramsList) > 2:  # 参数数量校验
        await message.reply(content="参数不正确，格式应为：/命令 <serverId> [多群]")
        return True

    # 判断是否包含多群参数
    isMoreGroup = False
    if len(paramsList) == 2:
        if paramsList[1] != "多群":  # 严格校验第二个参数
            await message.reply(content="第二个参数只能是「多群」")
            return True
        isMoreGroup = True
    serverId = paramsList[0]

    #查询是否已经绑定过
    bindRet = await queryBindServerByGroup(message.group_openid)
    if bindRet is not None:
        #查询是否是管理员
        adminRet = await queryIsAdmin(message.group_openid,message.author.member_openid)
        if not adminRet:
            await message.reply(content="你没有足够的权限.")
            return True
    
    unique_id = str(uuid.uuid4())
    async def Reply(msg,msg_seq=2):
        ret = await message.reply(content=msg,msg_seq=2)
    server_instance = serverManager.getWsServer()
    server_instance.addCallbackFunc(unique_id,Reply)

    if isGuid(serverId):
        #发送bindRequest请求
        bindCode = generate_randomCode()
        bindReq_Data = {"bindCode":bindCode}
        bindReq_Ret = await server_instance.sendMsgByServerId(serverId,websocketEvent.bindRequest,bindReq_Data,unique_id)
        if(bindReq_Ret):
            #存储到temp中
            bindServerTemp[unique_id] = {
                "serverId":serverId,
                "groupId":message.group_openid,
                "author":message.author.member_openid,
                "isMoreGroup":isMoreGroup,
            }
            await message.reply(content=f"已向服务端下发绑定请求，本次绑定校验码为:{bindCode}，请查看服务端控制台出现的信息。")
        else:
            await message.reply(content=f"无法向Id为{serverId}的服务器下发绑定请求，请管理员检查连接状态")
    else:
        await postImages(api,message,"https://pic.txssb.cn/quickStartQrCode.png",
                         "你发送的内容不是一个合法的绑定Key，请重新确认（绑定Key应为32个字符长度的十六进制字符串）\n详情请查看文档中的快速开始，扫描二维码查看",
                         "你发送的内容不是一个合法的绑定Key，请重新确认（绑定Key应为32个字符长度的十六进制字符串）\n详情请查看文档中的快速开始(请使用 /帮助 来获取文档)")
    return True


@Commands("查信息")
async def queryInfo(api: BotAPI, message: GroupMessage, params=None):
    if params:
        adminRet = await queryIsAdmin(message.group_openid, message.author.member_openid)
        if (not adminRet):
            await message.reply(content="你没有足够的权限.")
            return True
        ret = await queryBindQQ(message.group_openid, params)
        if ret:
            await message.reply(content=f"此用户已绑定QQ:{ret}")
        else:
            await message.reply(content=f"此用户未绑定QQ")
        return True
    await message.reply(content=f"你的OpenId:{message.author.member_openid}\n群的OpenId:{message.group_openid}")
    return True

@Commands("查管理")
async def queryAdminCmd(api: BotAPI, message: GroupMessage, params=None):
    adminRet = await queryIsAdmin(message.group_openid,message.author.member_openid)
    if(not adminRet):
        await message.reply(content="你没有足够的权限.")
        return True
    ret = await queryIsAdmin(message.group_openid,params)
    if(ret):
        await message.reply(content=f"此人是管理员")
    else:
        await message.reply(content=f"此人不是管理员")
    return True

@Commands("加管理")
async def addAdminCmd(api: BotAPI, message: GroupMessage, params=None):
    #print(message)
    adminRet = await queryIsAdmin(message.group_openid,message.author.member_openid)
    if(not adminRet):
        await message.reply(content="你没有足够的权限.")
        return True
    ret = await addAdmin(message.group_openid,params)
    if(ret):
        await message.reply(content=f"已为本群添加OpenId:{params}的管理员")
    return True

@Commands("删管理")
async def delAdminCmd(api: BotAPI, message: GroupMessage, params=None):
    adminRet = await queryIsAdmin(message.group_openid,message.author.member_openid)
    if(not adminRet):
        await message.reply(content="你没有足够的权限.")
        return True
    ret = await delAdmin(message.group_openid,params)
    if(ret):
        await message.reply(content=f"已为本群删除OpenId:{params}的管理员")
    return True

@Commands("设置名称")
async def setGroupName(api: BotAPI, message: GroupMessage, params=None):
    await setNickName({
        "groupId":message.group_openid,
        "author":message.author.member_openid,
        "nick":params
    })
    await message.reply(content=f"已将您的群服互通昵称设置为{params}")
    return True
    
@Commands("发信息")
async def sendGameMsg(api: BotAPI, message: GroupMessage, params=None):
    nick = await queryName({
        "groupId":message.group_openid,
        "author":message.author.member_openid,
    })
    if nick is None:
        await message.reply(content="没有找到你的昵称数据，请使用/设置名称 <昵称>来设置")
    else:
        ret = await queryBindServerByGroup(message.group_openid)
        if(ret is None):
            await message.reply(content=f"您还未绑定服务器，请按说明进行绑定.")
            return True
        serverId = ret[1]

        unique_id = str(uuid.uuid4())

        #存储至ChatTemp
        chatManager.postBotApi(api)
        chatManager.saveTemp(serverId,message.group_openid,message.id,1)

        server_instance = serverManager.getWsServer()
        wsRet = await server_instance.sendMsgByServerId(serverId,websocketEvent.sendChat,{"msg":params,"nick":nick},unique_id) #发信息

        if(not wsRet):
            await message.reply(content=f"无法向Id为{serverId}的服务器发送请求，请管理员检查连接状态")
            
    return True

@Commands("执行命令")
async def sendCmd(api: BotAPI, message: GroupMessage, params=None):
    adminRet = await queryIsAdmin(message.group_openid,message.author.member_openid)
    if(not adminRet):
        await message.reply(content="你没有足够的权限.")
        return True
    unique_id = str(uuid.uuid4())
    async def cmdReply(wsRet):
        ret = await message.reply(content=wsRet,msg_seq=2)
        #ret = await send_commandReturn_keyboard(api,params,wsRet,message)
    server_instance = serverManager.getWsServer()
    server_instance.addCallbackFunc(unique_id,cmdReply)
    
    ret = await queryBindServerByGroup(message.group_openid)
    if(ret == None):
        await message.reply(content=f"您还未绑定服务器，请按说明进行绑定.")
        return True
    wsRet = await server_instance.sendMsgByServerId(ret[1],websocketEvent.sendCommand,{"cmd":params},unique_id)
    if(wsRet):
        await message.reply(content="已向服务器发送命令，请等待执行.")
    else:
        await message.reply(content=f"无法向Id为{ret[1]}的服务器发送请求，请管理员检查连接状态")
    return True

@Commands("查白名单")
async def queryWl(api: BotAPI, message: GroupMessage, params=None):
    server_instance = serverManager.getWsServer()
    adminRet = await queryIsAdmin(message.group_openid,message.author.member_openid)
    if(not adminRet):
        await message.reply(content="你没有足够的权限.")
        return True
    unique_id = str(uuid.uuid4())
    ret = await queryBindServerByGroup(message.group_openid)
    if(ret == None):
        await message.reply(content=f"您还未绑定服务器，请按说明进行绑定.")
        return True
    # 判断参数是否为空
    if not params:
        payload = {}
    elif isNumber(params):
        payload = {"page": int(params)}
    else:
        payload = {"key": params}

    # 向服务器发送消息
    wsRet = await server_instance.sendMsgByServerId(ret[1], websocketEvent.queryWhiteList, payload, unique_id)

    # 检查发送结果
    if not wsRet:
        await message.reply(content=f"无法向Id为{ret[1]}的服务器发送请求，请管理员检查连接状态")
    else:    
        async def wlReply(msg):
            await message.reply(content=msg)
        server_instance.addCallbackFunc(unique_id,wlReply)
    return True

@Commands("查在线")
async def queryOnline(api: BotAPI, message: GroupMessage, params=None):
    unique_id = str(uuid.uuid4())
    ret = await queryBindServerByGroup(message.group_openid)
    if(ret == None):
        await message.reply(content=f"您还未绑定服务器，请按说明进行绑定.")
        return True
    server_instance = serverManager.getWsServer()
    aaa = websocketEvent.queryOnlineList
    wsRet = await server_instance.sendMsgByServerId(ret[1],aaa,{},unique_id)
    if(not wsRet):
        await message.reply(content=f"无法向Id为{ret[1]}的服务器发送请求，请管理员检查连接状态")
    async def onlineReply(data: dict):
        #获取data内消息
        msg = data['msg']
        rpMsg = msg.replace("\u200b","\n")

        #检测是否有imgUrl，若有则优先使用
        if (data.get('imgUrl') is not None) and (data.get('imgUrl') != "") :
            if data.get('post_img',False):
                url = data.get("url", "")
                preTip = ""
                if ("easecation" in url) or ("hypixel" in url):
                    preTip = "(若发现查询出来的图片不是本服务器，请先修改config中的motd字段，或修改post_img使其不推送图片)\n"
                try:
                    uploadMedia = await api.post_group_file(message.group_openid,1,data['imgUrl'],False)
                    await api.post_group_message(
                        group_openid=message.group_openid,
                        msg_type=7,
                        msg_id=message.id,
                        content=f'{preTip}{rpMsg}',
                        media=uploadMedia
                    )
                except:
                    await message.reply(content=f'(图片上传失败)\n{preTip}{rpMsg}',)

            else:
                await message.reply(content=f'{rpMsg}')
            return
        else:
            url = data.get("url","")
            serverType = data.get('serverType',"bedrock")

            if serverType == 'java':
                reqUrl = f'https://motdbe.blackbe.work/status_img/java?host={url}'
            else:
                reqUrl = f"https://motdbe.blackbe.work/status_img?host={url}"

            preTip = ""
            if("easecation" in url) or ("hypixel" in url):
                preTip = "(若发现查询出来的图片不是本服务器，请先修改config中的motdUrl字段)\n"

            if url != "" and is_valid_domain_port(url):
                try:
                    uploadMedia = await api.post_group_file(message.group_openid,1,reqUrl,False)
                    await api.post_group_message(
                        group_openid=message.group_openid,
                        msg_type=7,
                        msg_id=message.id,
                        content=f'{preTip}在线玩家列表:\n{rpMsg}',
                        media=uploadMedia
                    )
                except:
                    await message.reply(content=f'(图片上传失败)\n{preTip}在线玩家列表:\n{rpMsg}',)
            else:
                await message.reply(content=f"{preTip}在线玩家列表:\n{rpMsg}")


    server_instance.addCallbackFunc(unique_id,onlineReply)
    return True

@Commands("在线服务器")
async def queryClientList(api: BotAPI, message: GroupMessage, params=None):
    ret = await queryBindServerByGroup(message.group_openid)
    if ret is None:
        await message.reply(content=f"您还未绑定服务器，请按说明进行绑定.")
        return True
    server_instance = serverManager.getWsServer()
    clientList = await server_instance.queryClientList([ret[1]])
    clientText = ""
    for i in clientList:
        clientText += i+'\n'
    await message.reply(content=f"已连接{BotName}的服务器:\n{clientText}")
    return True

async def customRun(isAdmin: bool,api: BotAPI, message: GroupMessage,params=None):
    paramsList = splitCommandParams(params)

    if len(paramsList) < 1:
        await message.reply(content="参数不正确")
        return True
    keyWord = paramsList.pop(0)
    
    unique_id = str(uuid.uuid4())
    async def cmdReply(msg):
        is_json, parsed_data = try_parse_json(msg)
        if is_json:
            #发送图片
            if parsed_data.get("imgUrl") is not None:
                try:
                    uploadMedia = await api.post_group_file(
                        message.group_openid,
                        1,
                        parsed_data.get("imgUrl",""),
                        False
                    )
                    await api.post_group_message(
                        group_openid=message.group_openid,
                        msg_type=7,
                        msg_id=message.id,
                        content=f"[消息回报]\n{parsed_data.get('text','无消息')}",
                        media=uploadMedia,
                        msg_seq=2
                    )
                except Exception as e:
                    await message.reply(content=f"[消息回报]\n发送图片失败:{e}\n{parsed_data.get('text','无消息')}")
            else:
                await message.reply(content=f"[消息回报]\n{parsed_data.get('text','无消息')}",msg_seq=2)
        else:
            await message.reply(content=f"[消息回报]\n{msg}",msg_seq=2)
    server_instance = serverManager.getWsServer()
    server_instance.addCallbackFunc(unique_id,cmdReply)
    
    ret = await queryBindServerByGroup(message.group_openid)
    if ret is None:
        await message.reply(content=f"您还未绑定服务器，请按说明进行绑定.")
        return True
    #是否是管理员
    sendEvent = websocketEvent.customRun
    if isAdmin:
        sendEvent = websocketEvent.customRun_Admin
    nick = await queryName({
        "groupId": message.group_openid,
        "author": message.author.member_openid,
    })

    bindQQ = await queryBindQQ(message.group_openid,message.author.member_openid)

    wsRet = await server_instance.sendMsgByServerId(
        ret[1],
        sendEvent,
        {
            "key":keyWord,
            "runParams":paramsList,
            "author":{
                "qlogoUrl":getQLogoUrl(message.author.member_openid),
                "bindNick":nick,
                "openId":message.author.member_openid,
                "bindQQ":bindQQ
            },
            "group":{
                "openId":message.group_openid,
            }
        },
        unique_id)
    if(wsRet):
        adminText = ""
        if isAdmin:
            adminText = "(管理员)"
        await message.reply(content=f"已向服务器发送自定义执行{adminText}请求，请等待执行.")
    else:
        await message.reply(content=f"无法向Id为{ret[1]}的服务器发送请求，请管理员检查连接状态")

@Commands("管理员执行")
async def adminRunCommand(api: BotAPI, message: GroupMessage, params=None):
    adminRet = await queryIsAdmin(message.group_openid,message.author.member_openid)
    if(not adminRet):
        await message.reply(content="你没有足够的权限.")
        return True
    await customRun(True,api,message,params)
    return True

@Commands("执行")
async def runCommand(api: BotAPI, message: GroupMessage, params=None):
    await customRun(False,api,message,params)
    return True

@Commands("motd")
async def motd(api: BotAPI, message: GroupMessage, params=None):
    adminRet = await queryIsAdmin(message.group_openid, message.author.member_openid)
    motdRet = await queryIsBlockMotd(message.group_openid)
    if (not adminRet) and motdRet:
        await message.reply(content="本群已屏蔽Motd")
        return True

    paramsList = splitCommandParams(params)
    url=""
    platform="auto"

    if(len(paramsList) == 1): #纯地址
        url = paramsList[0]
    elif(len(paramsList) == 2): #地址+平台
        url = paramsList[0]
        platform = paramsList[1]
    else:
        await message.reply(content="Motd参数不正确\n使用方法:/motd <url> <platform>\nurl(必填):指定的服务器地址\nplatform(选填):<je|be>")
        return True
    
    motd = Motd(url)
    if not motd.is_valid():
        await message.reply(content=f"服务器地址参数不正确")
        return True
    

    motdData = motd.motd(platform)
    failedText= ('❌无法获取服务器状态信息。\n'
                '⚠️原因可能有以下几种：\n'
                '1.服务器没有开启或已经关闭或不允许获取motd\n'
                '2.描述(motd)中含有链接，官方机器人不允许发送没有授权的链接\n'
                '3.指定的平台错误(je,be,auto)(不填默认auto)\n'
                '4.ip或端口输入错误，或者接口维护这个可以问问机器人主人😝')
    offLineFailedText = ('❌无法获取服务器状态信息。\n'
                  '⚠️状态检测为Offline：\n'
                  '1.服务器没有开启或已经关闭或不允许获取motd\n'
                  '2.指定的平台错误(je,be,auto)(不填默认auto)\n'
                  '3.ip或端口输入错误，或者接口维护这个可以问问机器人主人😝')
    
    if motdData.get('online'):
        try:
            uploadMedia = await api.post_group_file(message.group_openid,1,motdData.get("imgUrl"),False)
            await api.post_group_message(
                group_openid=message.group_openid,
                msg_type=7,
                msg_id=message.id, 
                content=motdData.get('text'),
                media=uploadMedia
            )
        except Exception as e:
            _log.error(f"Error sending MOTD data: {e}")
            await message.reply(content=failedText)

    else:
        await message.reply(content=offLineFailedText)
    return True

@Commands("unblockMotd")
async def unblockMotd(api: BotAPI, message: GroupMessage, params=None):
    adminRet = await queryIsAdmin(message.group_openid, message.author.member_openid)
    if not adminRet:
        await message.reply(content="你没有足够的权限.")
        return True
    ret = await delBlockMotd(message.group_openid)
    if ret:
        await message.reply(content=f"本群已设置为:解除屏蔽Motd.")
    return True

@Commands("blockMotd")
async def blockMotd(api: BotAPI, message: GroupMessage, params=None):
    adminRet = await queryIsAdmin(message.group_openid, message.author.member_openid)
    if not adminRet:
        await message.reply(content="你没有足够的权限.")
        return True
    ret = await addBlockMotd(message.group_openid)
    if ret:
        await message.reply(content=f"本群已设置为:屏蔽Motd.")
    return True

@Commands("解除认证")
async def unauthQQAvatar(api: BotAPI, message: GroupMessage, params=None):
    targetOpenId = params
    adminRet = await queryIsAdmin(message.group_openid, message.author.member_openid)
    if not adminRet:
        await message.reply(content="你没有足够的权限.")
        return True

    if targetOpenId != "":
        ret = await delBindQQById(message.group_openid,targetOpenId)
        if ret:
            await message.reply(content=f"✅ 解除认证成功！已为{targetOpenId}解除绑定QQ账号")
        else:
            await message.reply(content=f"❌ 解除认证失败！请检查输入的OpenId是否正确")
    else:
        await message.reply(content=f"请输入要解除认证的OpenId")


    return True

@Commands("认证")
async def authQQAvatar(api: BotAPI, message: GroupMessage, params=None):
    openId = message.author.member_openid
    paramList = splitCommandParams(params)
    if len(paramList) == 0:
        ret = await queryBindQQ(message.group_openid, openId)

        if ret is not None:
            await message.reply(content=f'您已绑定QQ:{ret}\n如需解除请联系机器人管理员使用"/解除认证 {openId}"以解除认证')
        else:
            await message.reply(content=f'您暂未绑定QQ，请使用"/认证 <qq号>"进行绑定，例如"/认证 123456789"')

        return True
    elif len(paramList) == 1:
        qqNum = paramList[0]
        if is_valid_QQ(params):
            #检测是否绑定过
            ret = await queryBindQQ(message.group_openid, openId)
            if ret is not None:
                await message.reply(content=f"您已绑定QQ:{ret}")
                return True

            result = compare_qq_avatars(params, openId)
            if result[1] == 0:
                getcontext().prec = 6
                threshold = Decimal('0.9995')
                similarity = Decimal(str(result[0]))

                # 新增百分比转换逻辑
                similarity_percent = similarity * 100  # 转换为百分数
                epsilon = Decimal('0.00001')

                if abs(similarity - threshold) <= epsilon or similarity >= threshold:
                    # 显示两位小数（99.99% 格式）
                    await message.reply(content=f'✅ 认证通过！绑定信息如下\nOpenId:{openId}\nQQ账号:{qqNum}\n如绑定有误，请管理员输入"/解除认证 {openId}"')
                    await addBindQQ(message.group_openid, openId, qqNum)
                else:
                    # 显示两位小数，并添加阈值提示
                    await message.reply(
                        content=f'❌ 认证失败，当前匹配度：{similarity_percent:.2f}%（需≥{threshold * 100:.2f}%）\n管理员可手动使用"/认证 {qqNum} {openId}"进行人工确认'
                    )
            else:
                await message.reply(content=f'图像比对失败: 错误 ({result[1]}): {result[2]}\n管理员可手动使用"/认证 {qqNum} {openId}"进行人工确认')
        else:
            await message.reply(content=f"认证失败，请检查输入的QQ号是否正确")
    elif len(paramList) > 1:
        adminRet = await queryIsAdmin(message.group_openid, message.author.member_openid)
        if not adminRet:
            await message.reply(content="你没有足够的权限.")
            return True
        qqNum = paramList[0]
        targetOpenId = paramList[1]

        await message.reply(content=f"✅ 认证通过！已为{openId}绑定为QQ账号:{qqNum}")
        await addBindQQ(message.group_openid, targetOpenId, qqNum)

        #await message.reply(msg_type=2,markdown={},keyboard=KeyboardPayload(id="xxx"),msg_seq=2)

    return True

#BotPy主框架
class BaseBotMixin:
    @property
    def bot_api(self):
        """统一获取API实例的接口"""
        if isinstance(self, WebHookClient):
            return self.api
        elif isinstance(self, Client):
            return self.api
        else:
            raise AttributeError("无法获取API实例")
    async def on_group_at_message_create(self, message:GroupMessage):
        # 注册指令handler
        handlers = [
            getHelp,
            addAllowList,
            bind,
            reCall,
            setGroupName,
            sendGameMsg,
            sendCmd,
            queryWl,
            queryOnline,
            queryClientList,
            adminRunCommand,
            runCommand,
            queryInfo,
            queryAdminCmd,
            addAdminCmd,
            delAdminCmd,
            motd,
            unblockMotd,
            blockMotd,
            unauthQQAvatar,
            authQQAvatar,
        ]
        for handler in handlers:
            if await handler(api=self.bot_api, message=message):
                return

        #处理消息
        adminRet = await queryIsAdmin(message.group_openid, message.author.member_openid)
        content = message.content

        match = re.match(r"^\s*\/(\S+)(?:\s+(.*))?$", content)
        if match:
            command = match.group(1)
            params = match.group(2) or ""
            #_log.info(f"cmd:{command+' '+params.strip()}")
            await customRun(adminRet, self.bot_api, message, command+' '+params.strip())
            
        #无消息
    async def on_message_audit_reject(self, message: MessageAudit):
        if message.message_id is not None:
            _log.warning(f"消息：{message.audit_id} 审核未通过.")

    async def on_group_add_robot(self, event: GroupManageEvent):
        try:
            uploadMedia = await self.bot_api.post_group_file(
                event.group_openid,
                1,
                "https://pic.txssb.cn/docQrCode.png",
                False
            )
            await self.bot_api.post_group_message(
                group_openid=event.group_openid,
                msg_type=7,
                #msg_id=message.id,
                event_id=event.event_id,
                content=f"欢迎使用HuHoBot，首次使用请根据文档中的快速开始进行配置，文档可扫描上方二维码或手动输入网址.\n操作过程中需要@我，如:@HuHoBot /绑定 xxx\n欢迎加入交流群：1005746321",
                media=uploadMedia,
                msg_seq=1
            )
        except:
            await self.bot_api.post_group_message(
                group_openid=event.group_openid,
                msg_type=0,
                event_id=event.event_id,
                content=f'欢迎使用HuHoBot，首次使用请根据文档中的快速开始进行配置,(图片发送失败,请稍后使用"@HuHoBot /帮助"进行查询)\n操作过程中需要@我，如:@HuHoBot /绑定 xxx\n欢迎加入交流群：1005746321',
            )

    async def on_interaction_create(self, interaction: Interaction):
        #_log.info(interact
        pass



# 协议相关类定义
class WsBotClient(BaseBotMixin, ymbotpy.Client):
    """WebSocket模式客户端"""
    def __init__(self, *args, **kwargs):
        # 设置需要的权限
        self.intents = ymbotpy.Intents(
            public_messages=True,
            interaction=True,
            message_audit=True
        )
        super().__init__(intents=self.intents or ymbotpy.Intents.none(), *args, **kwargs)


class WebhookBotClient(BaseBotMixin, ymbotpy.WebHookClient):
    """Webhook模式客户端"""
    pass
    
# 开启BotPy客户端
async def startClient(APPID:str, SECRET:str, SANDBOX:bool, WEBHOOK:bool):
    ClientClass = WebhookBotClient if WEBHOOK else WsBotClient

    if WEBHOOK:
        client = ClientClass(is_sandbox=SANDBOX)
        ssl_keyfile = None
        ssl_certfile = None
        if os.path.exists('ssl/private.key') and os.path.exists('ssl/public.crt'):
            ssl_keyfile = 'ssl/private.key'
            ssl_certfile = 'ssl/public.crt'
            _log.info("使用SSL证书")

        await client.start(
            appid=APPID,
            secret=SECRET,
            port=8443,
            system_log=False,
            ssl_certfile=ssl_certfile,
            ssl_keyfile=ssl_keyfile,
        )
    else:
        client = ClientClass(is_sandbox=SANDBOX)
        await client.start(
            appid=APPID,
            secret=SECRET,
        )
    return client

# 创建服务器实例的协程
async def create_server(wskey: str):
    server_instance = WebsocketClient("HuHoBot",'ws://127.0.0.1:2087',wskey)
    serverManager.setWsServer(server_instance)
    return server_instance

# 启动WebSocket服务器的函数
async def start_server(wskey: str):
    server = await create_server(wskey)  # 获取服务器实例
    await server.connect()

# 主函数，用于启动WebSocket服务器
async def main(APPID, SECRET, WSKEY, SANDBOX, WEBHOOK):
    server_coroutine = start_server(WSKEY)  # 获取启动服务器的协程
    client_coroutine = startClient(APPID, SECRET, SANDBOX, WEBHOOK)  # 获取启动客户端的协程
    await asyncio.gather(server_coroutine, client_coroutine)  # 并发运行

if __name__ == '__main__':
    _log.info("请使用index.py启动")

    
    
