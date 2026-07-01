# -*- coding: utf-8 -*-

import csv
import os
import re
import contextvars
from datetime import datetime, timedelta
from pathlib import Path

LOG_DIR = "data"
LOG_FILE_PREFIX = "message_log"
MAX_RETENTION_DAYS = 14

# msg_type 数字 → 文本描述
_MSG_TYPE_TEXT: dict[int, str] = {
    0: "Text",
    1: "ImageText",
    2: "MD",
    3: "Ark",
    4: "Embed",
    7: "Media",
}

# 用于追踪当前消息处理上下文中关联的 ServerId
current_server_id: contextvars.ContextVar = contextvars.ContextVar(
    "current_server_id", default=""
)


def _today_log_path() -> str:
    """返回当天日志文件的完整路径。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(LOG_DIR, f"{LOG_FILE_PREFIX}_{today}.csv")


def _ensure_dir() -> None:
    """确保日志目录存在。"""
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)


def CleanOldMessages(max_days: int = MAX_RETENTION_DAYS) -> None:
    """删除超过 max_days 天的日志文件。通过文件名中的日期判断。"""
    if not os.path.isdir(LOG_DIR):
        return

    cutoff = datetime.now() - timedelta(days=max_days)
    pattern = re.compile(rf"^{re.escape(LOG_FILE_PREFIX)}_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$")

    for filename in os.listdir(LOG_DIR):
        match = pattern.match(filename)
        if not match:
            continue
        try:
            file_date = datetime.strptime(match.group(1), "%Y-%m-%d")
            if file_date <= cutoff:
                filepath = os.path.join(LOG_DIR, filename)
                os.remove(filepath)
        except (ValueError, OSError):
            pass


def LogSentMessage(
    group_openid: str,
    msg_type: int = 0,
    content: str = "",
    title: str = "",
    server_id: str = "",
) -> None:
    """追加一条机器人发往群的消息记录到当天 CSV 文件。"""
    _ensure_dir()

    filepath = _today_log_path()
    file_exists = os.path.exists(filepath)

    # 如果不是独立调用，尝试从上下文获取 ServerId
    if not server_id:
        try:
            server_id = current_server_id.get()
        except LookupError:
            pass

    # 组合 title 和 content，用于 msg_type=2 (Markdown) 等场景
    if title and content:
        full_content = f"{title}\n{content}"
    elif title:
        full_content = title
    else:
        full_content = content or ""

    # 截断过长的内容，避免 CSV 行过大
    content_safe = full_content[:2000]

    try:
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["时间", "群ID", "ServerId", "消息类型", "消息内容"])
            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                group_openid,
                server_id,
                _MSG_TYPE_TEXT.get(msg_type, str(msg_type)),
                content_safe,
            ])
    except Exception:
        pass  # 日志写入失败不应影响主流程
