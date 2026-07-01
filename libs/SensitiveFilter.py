# -*- coding: utf-8 -*-

import os
import glob

from uapi import UapiClient
from uapi.errors import UapiError

from libs.configManager import ConfigManager

_config_manager = ConfigManager()


def _is_cjk(char):
    """判断字符是否为中日韩字符"""
    cp = ord(char)
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
            or 0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F)


class SimpleSensitiveFilter:
    # 匹配时跳过的干扰字符（空格、特殊符号等）
    SKIP_CHARS = set(" \t\r\n\u3000*·.,-_—–=+!@#$%^&()[]{}|/\\~`'\"""''；;：:，。、？?！!…")
    # 纯ASCII词的最小长度（过滤掉 "b"、"test" 这类过短的英文敏感词）
    MIN_ASCII_LEN = 2

    def __init__(self, dir_path="sensitive-words"):
        self.trie = {}
        # 加载所有敏感词
        for txt_file in glob.glob(os.path.join(dir_path, "*.txt")):
            with open(txt_file, "r", encoding="utf-8") as f:
                for line in f:
                    word = line.strip()
                    if word and self._should_add(word):
                        self._add_word(word)
        print(f"Loaded {len(self.trie)} words")

    def _should_add(self, word):
        """判断敏感词是否应被加载，过滤不合理的词条"""
        # 纯ASCII词（英文/数字）要求最小长度
        if word.isascii():
            return len(word) >= self.MIN_ASCII_LEN
        # 含CJK字符的词，至少需要2个CJK字符
        cjk_count = sum(1 for c in word if _is_cjk(c))
        return cjk_count >= 2

    def _add_word(self, word):
        """构建字典树"""
        node = self.trie
        for char in word:
            if char not in node:
                node[char] = {}
            node = node[char]
        node["#"] = True  # 结束标记

    def replace(self, text, mask="*"):
        """直接替换敏感词，支持跳过干扰字符（如空格、符号等）"""
        result = list(text)
        n = len(text)
        i = 0

        while i < n:
            # 寻找最长匹配
            max_end = -1
            current_node = self.trie
            j = i
            while j < n:
                char = text[j]
                if char in current_node:
                    current_node = current_node[char]
                    if "#" in current_node:
                        max_end = j
                    j += 1
                elif char in self.SKIP_CHARS:
                    # 跳过干扰字符，但仅在已经开始匹配trie时才跳过
                    if current_node is self.trie:
                        break
                    j += 1
                else:
                    break

            # 执行替换
            if max_end >= 0:
                for k in range(i, max_end + 1):
                    result[k] = mask
                i = max_end + 1
            else:
                i += 1

        return "".join(result)


class ApiSensitiveFilter:
    """基于 UAPI SDK 的违禁词检测，未配置 API key 或异常时回退到本地 Trie 过滤。"""

    _client = None
    _token = None
    _local_filter = None

    @classmethod
    def _get_local_filter(cls):
        """懒加载本地 SimpleSensitiveFilter 单例。"""
        if cls._local_filter is None:
            cls._local_filter = SimpleSensitiveFilter()
        return cls._local_filter

    @classmethod
    def _get_client(cls):
        """懒加载 UapiClient，token 变化时重建。"""
        token = _config_manager.Get("AuditApiKey", ConfigManager.DEFAULT_AUDIT_API_KEY)
        if not token:
            return None
        if cls._token != token or cls._client is None:
            cls._client = UapiClient("https://uapis.cn", token=token)
            cls._token = token
        return cls._client

    @classmethod
    def replace(cls, text: str) -> str:
        """检测文本中的敏感词，命中时返回屏蔽后文本。

        - 已配置 AuditApiKey 且 API 正常 → 使用在线检测
        - 未配置 AuditApiKey 或 API 异常 → 回退到本地 Trie 过滤
        """
        client = cls._get_client()
        if client is not None:
            try:
                result = client.min_gan_ci_shi_bie.post_sensitive_word_quick_check(text=text)
                if result.get("status") == "forbidden":
                    return result.get("masked_text", text)
                return text
            except UapiError:
                pass
        return cls._get_local_filter().replace(text)
