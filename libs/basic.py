# -*- coding: utf-8 -*-

import hashlib
import json
import random
import re
import secrets
import string


def SplitCommandParams(params: str):
    """按空格切分命令参数，并支持英文双引号包裹的内容。"""
    if not params:
        return []

    result = []
    current_quote = ""
    for word in params.split():
        if current_quote:
            current_quote += " " + word
            if word.endswith('"'):
                current_quote = current_quote.rstrip('"')
                result.append(current_quote.strip('"'))
                current_quote = ""
        else:
            if word.startswith('"') and word.endswith('"'):
                result.append(word[1:-1])
            elif word.startswith('"'):
                current_quote = word
            else:
                result.append(word)

    if current_quote:
        for word in current_quote.split():
            result.append(word)

    result = [item.replace('"', "") for item in result]
    return [ExtractMentionId(item) for item in result]


def IsValidQQ(qq_str: str):
    """校验输入是否为合法 QQ 号。"""
    return re.match(r"^\d{5,12}$", qq_str) is not None


def IsValidXboxId(xbox_id: str):
    """校验输入是否为合法 Xbox Id。"""
    pattern = r"^[a-zA-Z_][a-zA-Z0-9_ ]{2,14}[a-zA-Z0-9_]$"
    return re.match(pattern, xbox_id) is not None


def IsNumber(data: str):
    """判断字符串是否为非负整数。"""
    return data.isdigit() and int(data) >= 0


def IsValidServerId(data: str):
    """判断字符串是否为 32 位十六进制标识。"""
    return re.match(r"^(?=.*[a-f])(?=.*[0-9])[a-f0-9]{32}$", data) is not None

def IsValidOpenId(open_id: str):
    """校验输入是否为合法 OpenId。"""
    return re.match(r'^(?=.*[A-F])(?=.*[0-9])[A-F0-9]{32}$', open_id) is not None

def GenerateRandomCode():
    """生成四位数字验证码。"""
    return "".join(random.choices(string.digits, k=4))


def TryParseJson(input_str: str):
    """尝试把字符串解析为 JSON，返回 `(是否成功, 结果)`。"""
    try:
        return True, json.loads(input_str)
    except json.JSONDecodeError:
        return False, input_str


def GenerateHashKey(input_string: str, salt_length=16):
    """为输入内容生成带随机盐值的 SHA-256 哈希。"""
    salt = secrets.token_hex(salt_length)
    combined = input_string + salt
    hash_object = hashlib.sha256(combined.encode("utf-8"))
    return hash_object.hexdigest()


def GetServerConfig(server_id: str):
    """生成新服务器首次绑定时使用的默认配置。"""
    hash_key = GenerateHashKey(server_id)
    return {
        "serverId": server_id,
        "hashKey": hash_key,
        "serverName": "server",
        "addSimulatedPlayerTip": True,
        "motdUrl": "play.easecation.net:19132",
        "chatFormat": {
            "game": "<{name}> {msg}",
            "group": "群:<{nick}> {msg}",
        },
    }


def GetQLogoUrl(app_id: str, open_id: str, size: int = 640):
    """按 OpenID 构造 QQ 官方头像地址。"""
    return f"https://q.qlogo.cn/qqapp/{app_id}/{open_id}/{size}"


def ExtractMentionId(text: str):
    """从 `<@ID>` 格式中提取中间的 ID，无匹配时返回原文本。"""
    m = re.match(r"^<@([A-Fa-f0-9]+)>$", text.strip())
    return m.group(1) if m else text


__all__ = [
    "ExtractMentionId",
    "GenerateHashKey",
    "GenerateRandomCode",
    "GetQLogoUrl",
    "GetServerConfig",
    "IsValidServerId",
    "IsNumber",
    "IsValidOpenId",
    "IsValidQQ",
    "IsValidXboxId",
    "SplitCommandParams",
    "TryParseJson",
]
