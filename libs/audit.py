# -*- coding: utf-8 -*-
import os

import ymbotpy
from ymbotpy import logging, BotAPI

from ymbotpy.ext.command_util import Commands
from ymbotpy.message import GroupMessage
from ymbotpy.ext.cog_yaml import read
_log = logging.get_logger()


@Commands("添加白名单")
async def addAllowList(api: BotAPI, message: GroupMessage, params=None):
    _log.info(params)
    await message.reply(content=f"已添加白名单")
    return True

@Commands("删除白名单")
async def reCall(api: BotAPI, message: GroupMessage, params=None):
    _log.info(params)
    await message.reply(content=f"已删除白名单")
    return True

@Commands("绑定")
async def bind(api: BotAPI, message: GroupMessage, params=None):
    await message.reply(content='绑定成功')
    return True

@Commands("设置名称")
async def setGroupName(api: BotAPI, message: GroupMessage, params=None):
    await message.reply(content=f"已设置")
    return True

@Commands("发信息")
async def sendGameMsg(api: BotAPI, message: GroupMessage, params=None):
    await message.reply(content="你好呀，我是HuHoBot")
    return True

@Commands("执行命令")
async def sendCmd(api: BotAPI, message: GroupMessage, params=None):
    await message.reply(content=f"已执行命令")
    return True

@Commands("查白名单")
async def queryWl(api: BotAPI, message: GroupMessage, params=None):
    await message.reply(content="现在还没有白名单")
    return True

@Commands("查在线")
async def queryOnline(api: BotAPI, message: GroupMessage, params=None):
    await message.reply(content="在线玩家：0")
    return True

@Commands("在线服务器")
async def queryClientList(api: BotAPI, message: GroupMessage, params=None):
    await message.reply(content="暂时没有在线的服务器")
    return True

@Commands("执行")
async def runCommand(api: BotAPI, message: GroupMessage, params=None):
    await message.reply(content="执行成功")
    return True

@Commands("管理员执行")
async def adminRunCommand(api: BotAPI, message: GroupMessage, params=None):
    await message.reply(content="执行成功")
    return True

class MyClient(ymbotpy.Client):
    async def on_group_at_message_create(self, message):
        # 注册指令handler
        handlers = [
            addAllowList,
            bind,
            reCall,
            setGroupName,
            sendGameMsg,
            sendCmd,
            queryWl,
            queryOnline,
            queryClientList,
            runCommand,
            adminRunCommand
        ]
        for handler in handlers:
            if await handler(api=self.api, message=message):
                return

#订阅事件
def main(APPID,SECRET):
    intents = ymbotpy.Intents.none()
    intents.public_messages=True

    client = MyClient(intents=intents)
    client.run(appid=APPID, secret=SECRET)

if __name__ == '__main__':
    print("请使用index.py启动")
