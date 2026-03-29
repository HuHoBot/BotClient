import os
import glob
import requests


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
    """基于在线API的违禁词检测"""
    API_URL = "https://uapis.cn/api/v1/text/profanitycheck"

    @staticmethod
    def check(text):
        """调用在线违禁词检测API，返回响应JSON"""
        resp = requests.post(
            ApiSensitiveFilter.API_URL,
            json={"text": text},
            timeout=5
        )
        return resp.json()

    @staticmethod
    def replace(text):
        """检测并返回屏蔽后的文本，API异常时回退到本地Trie过滤"""
        try:
            result = ApiSensitiveFilter.check(text)
            if result.get("status") == "forbidden":
                return result.get("masked_text", text)
        except Exception:
            return SimpleSensitiveFilter().replace(text)
        return text

