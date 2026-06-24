# -*- coding: utf-8 -*-
import re
from functools import wraps
from ymbotpy.message import BaseMessage


class Commands:
    """
    指令装饰器

    Args:
      args (tuple): 字符串元组。
    """

    def __init__(self, *args):
        self.commands = args

    def __call__(self, func):
        @wraps(func)
        async def decorated(*args, **kwargs):
            message: BaseMessage = kwargs["message"]
            # 去掉 @提及（支持 <@id> 和 <@!id> 格式），再去掉前导空白和 /
            content = re.sub(r'<@!?[^>]+>', '', message.content).strip().lstrip('/')
            for command in self.commands:
                if content.startswith(command):
                    # 分割指令后面的指令参数
                    params = content.split(command)[1].strip()
                    kwargs["params"] = params
                    return await func(*args, **kwargs)
            return False

        return decorated
