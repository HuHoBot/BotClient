# -*- coding: utf-8 -*-

import asyncio
import contextvars
import csv
import os
import glob
from datetime import datetime
from pathlib import Path

from uapi import UapiClient
from uapi.errors import UapiError

from openai import OpenAI

from zoneinfo import ZoneInfo

from libs.configManager import ConfigManager

_config_manager = ConfigManager()

AUDIT_LOG_DIR = "data"
AUDIT_LOG_PREFIX = "audit_log"
FALSE_POSITIVE_LOG_PREFIX = "false_positive_log"
# 定义固定的 UTC+8 时区
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

current_audit_group_id: contextvars.ContextVar = contextvars.ContextVar(
    "current_audit_group_id", default=""
)


def _is_cjk(char):
    """判断字符是否为中日韩字符"""
    cp = ord(char)
    return (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
            or 0xF900 <= cp <= 0xFAFF or 0x2F800 <= cp <= 0x2FA1F)


class SimpleSensitiveFilter:
    # 匹配时跳过的干扰字符（空格、特殊符号等）
    SKIP_CHARS = set(" \t\r\n\u3000*·.,-_—–=+!@#$%^&()[]{}|/\\~`'\"""''；;：:，。、？?！!…")
    # 纯ASCII词的最小长度（过滤掉 "b"、"test" 这类过短的英文敏感词）
    MIN_ASCII_LEN = 5

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
            if not isinstance(node, dict):
                node = {}
            if char not in node:
                node[char] = {}
            node = node[char]
        if not isinstance(node, dict):
            node = {}
        node["#"] = True  # 结束标记

    def find_hits(self, text):
        """查找文本中命中的敏感词，返回命中的词和对应原始子串列表。

        Returns:
            list[tuple[str, str]]: [(敏感词, 原始匹配子串), ...]
        """
        if not isinstance(text, str):
            text = str(text)
        hits = []
        n = len(text)
        i = 0

        while i < n:
            max_end = -1
            matched_word = None
            current_node = self.trie
            matched_chars = []
            j = i
            while j < n:
                char = text[j]
                if char in current_node:
                    current_node = current_node[char]
                    matched_chars.append(char)
                    if "#" in current_node:
                        max_end = j
                        matched_word = "".join(matched_chars)
                    j += 1
                elif char in self.SKIP_CHARS:
                    if current_node is self.trie:
                        break
                    j += 1
                else:
                    break

            if max_end >= 0:
                original = text[i:max_end + 1]
                hits.append((matched_word, original))
                i = max_end + 1
            else:
                i += 1

        return hits

    def replace(self, text, mask="*"):
        """直接替换敏感词，支持跳过干扰字符（如空格、符号等）"""
        if not isinstance(text, str):
            text = str(text)
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

    _openai_client = None
    _openai_config_key = None
    _openai_semaphore = None

    MAX_OPENAI_CONCURRENT = 5

    @classmethod
    def _get_semaphore(cls):
        """懒加载 asyncio.Semaphore，控制 OpenAI 并发数。"""
        if cls._openai_semaphore is None:
            cls._openai_semaphore = asyncio.Semaphore(cls.MAX_OPENAI_CONCURRENT)
        return cls._openai_semaphore

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
    def _get_openai_client(cls):
        """懒加载 OpenAI 兼容客户端，配置变化时重建。"""
        config_key = (
            _config_manager.Get("OpenAIApiKey", ConfigManager.DEFAULT_OPENAI_API_KEY) +
            _config_manager.Get("OpenAIBaseUrl", ConfigManager.DEFAULT_OPENAI_BASE_URL)
        )
        if cls._openai_config_key != config_key or cls._openai_client is None:
            api_key = _config_manager.Get("OpenAIApiKey", ConfigManager.DEFAULT_OPENAI_API_KEY)
            base_url = _config_manager.Get("OpenAIBaseUrl", ConfigManager.DEFAULT_OPENAI_BASE_URL)
            cls._openai_client = OpenAI(api_key=api_key, base_url=base_url or None)
            cls._openai_config_key = config_key
        return cls._openai_client

    OPENAI_SYSTEM_PROMPT = (
        "你是一个敏感词过滤工具。你的任务是对用户输入的文本进行检测，"
        "将其中所有违禁词、敏感词用等量的星号（*）替换，"
        "然后只输出替换后的完整文本。"
        "不要添加任何解释、备注或额外的文字，只输出处理后的最终结果。"
    )

    @classmethod
    def _do_openai_call_sync(cls, text: str) -> str | None:
        """同步执行 OpenAI API 调用（在线程池中运行）。"""
        client = cls._get_openai_client()
        model = _config_manager.Get("OpenAIModel", ConfigManager.DEFAULT_OPENAI_MODEL)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": cls.OPENAI_SYSTEM_PROMPT},
                {"role": "user", "content": f'请处理以下文本："{text}"'},
            ],
            max_tokens=512,
            temperature=0.1,
        )
        return response.choices[0].message.content.strip()

    @classmethod
    async def _audit_via_openai(cls, text: str) -> str | None:
        """通过 OpenAI 兼容 API 审核并替换敏感词（异步，受 semaphore 并发限制）。

        Returns:
            str | None: AI 处理后的文本，异常时返回 None
        """
        client = cls._get_openai_client()
        if client is None:
            return None

        model = _config_manager.Get("OpenAIModel", ConfigManager.DEFAULT_OPENAI_MODEL)
        if not model:
            return None

        try:
            async with cls._get_semaphore():
                return await asyncio.to_thread(cls._do_openai_call_sync, text)
        except Exception as exc:
            cls._log_audit(text, [], "OpenAI异常", str(exc)[:500])
            return None

    @classmethod
    def _log_audit(cls, text: str, local_hits: list[str], uapi_status: str,
                   uapi_detail: str) -> None:
        """将审核结果写入当日 CSV 日志。"""
        try:
            log_dir = Path(AUDIT_LOG_DIR)
            log_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d")
            filepath = log_dir / f"{AUDIT_LOG_PREFIX}_{today}.csv"
            file_exists = filepath.is_file()

            text_safe = text[:500].replace("\n", "\\n")
            local_hits_str = "|".join(local_hits)[:1000]
            group_id = current_audit_group_id.get()

            with filepath.open("a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["时间", "群ID", "文本摘要", "本地命中词", "UAPI状态", "UAPI详情"])
                writer.writerow([
                    datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                    group_id,
                    text_safe,
                    local_hits_str,
                    uapi_status,
                    uapi_detail[:1000],
                ])
        except Exception:
            pass

    @classmethod
    def _log_false_positive(cls, word: str, text: str, backend: str) -> None:
        """记录误判词（本地命中但在线审核放行）到当日 CSV。"""
        try:
            log_dir = Path(AUDIT_LOG_DIR)
            log_dir.mkdir(parents=True, exist_ok=True)
            today = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d")
            filepath = log_dir / f"{FALSE_POSITIVE_LOG_PREFIX}_{today}.csv"
            file_exists = filepath.is_file()

            text_safe = text[:200].replace("\n", "\\n")

            with filepath.open("a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["时间", "命中词", "审核后端", "文本摘要"])
                writer.writerow([
                    datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                    word,
                    backend,
                    text_safe,
                ])
        except Exception:
            pass

    @classmethod
    async def replace(cls, text: str) -> str:
        """检测文本中的敏感词，命中时返回屏蔽后文本。

        流程：
        1. 先用本地 Trie 做第一轮检测，未命中直接放行
        2. 命中后根据 AuditProvider 配置选择在线二审后端
           - "uapi" → UAPI 在线检测
           - "openai" → OpenAI 兼容 API 在线审核（Semaphore 控制并发 ≤5）
        3. 以在线审核结果为准：forbidden → 返回屏蔽文本；通过 → 放行原文
        4. 在线审核不可用或异常时回退到本地 Trie 结果
        """
        local_filter = cls._get_local_filter()
        local_result = local_filter.replace(text)
        if local_result == text:
            return text

        local_hits = [hit[0] for hit in local_filter.find_hits(text)]
        provider = _config_manager.Get("AuditProvider", ConfigManager.DEFAULT_AUDIT_PROVIDER)

        if provider == "openai":
            return await cls._replace_via_openai(text, local_hits, local_result)
        return cls._replace_via_uapi(text, local_hits, local_result)

    @classmethod
    def _replace_via_uapi(cls, text: str, local_hits: list[str],
                          local_result: str) -> str:
        """通过 UAPI 进行在线二审。"""
        client = cls._get_client()
        if client is None:
            cls._log_audit(text, local_hits, "UAPI不可用", "未配置AuditApiKey")
            return local_result

        try:
            result = client.min_gan_ci_shi_bie.post_sensitive_word_quick_check(text=text)
            status = result.get("status", "unknown")
            if status == "forbidden":
                masked = result.get("masked_text", text)
                cls._log_audit(text, local_hits, "forbidden", masked)
                return masked
            cls._log_audit(text, local_hits, "通过", str(result))
            for hit in local_hits:
                cls._log_false_positive(hit, text, "UAPI")
            return text
        except UapiError as exc:
            cls._log_audit(text, local_hits, "UAPI异常", str(exc)[:500])
            return local_result

    @classmethod
    async def _replace_via_openai(cls, text: str, local_hits: list[str],
                                  local_result: str) -> str:
        """通过 OpenAI 兼容 API 进行在线二审（异步），AI 直接输出替换后的文本。"""
        filtered = await cls._audit_via_openai(text)
        if filtered is None:
            cls._log_audit(text, local_hits, "OpenAI不可用", "Semaphore排队超时/请求异常")
            return local_result

        if filtered != text:
            cls._log_audit(text, local_hits, "OpenAI-已替换", filtered)
            return filtered
        cls._log_audit(text, local_hits, "OpenAI-通过", filtered)
        for hit in local_hits:
            cls._log_false_positive(hit, text, "OpenAI")
        return text