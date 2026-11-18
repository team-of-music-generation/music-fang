# -*- coding: utf-8 -*-
"""通用工具：uid、限速、日志、时间、字段构造。

字段定义严格对齐《MDD 工程操作手册》5.3 源数据字段定义（16 字段），
并额外补充竞品调研“筛选标准”要求的粉丝量 follower_count。
"""

import hashlib
import json
import os
import random
import time
import datetime

import config


def make_uid(platform, comment_id):
    """R-04 幂等去重唯一键 = md5(平台+评论ID)。"""
    return hashlib.md5(
        (str(platform) + "|" + str(comment_id)).encode("utf-8")
    ).hexdigest()


def polite_delay():
    """Q-02：每次请求间隔 1–2 秒。"""
    time.sleep(random.uniform(config.MIN_DELAY, config.MAX_DELAY))


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return datetime.datetime.now().strftime("%Y%m%d")


def ts_to_str(ts):
    """Unix 秒级时间戳 -> 'YYYY-MM-DD HH:MM:SS'。"""
    if not ts:
        return ""
    try:
        return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OSError):
        return ""


def new_log():
    """返回一个内存日志收集器，最后统一落盘 crawl_log.md。"""
    return []


def log_event(logger, platform, account, count, note=""):
    """O-06 抓取日志：记录平台、账号、数量、异常。"""
    line = f"| {now_str()} | {platform} | {account} | {count} | {note} |"
    logger.append(line)
    print("[LOG]", line)
    return line


def write_crawl_log(logger):
    """把抓取日志写入 mdd/00_meta/crawl_log.md（追加，遵循 R-01 只增不改）。"""
    config.ensure_dirs()
    header = (
        "# 抓取日志 crawl_log\n\n"
        "> 记录平台 / 账号 / 数量 / 异常。原始只增不改（R-01）。\n\n"
        "| 时间 | 平台 | 账号 | 数量 | 备注/异常 |\n"
        "|---|---|---|---|---|\n"
    )
    exists = os.path.exists(config.CRAWL_LOG_FILE) and os.path.getsize(config.CRAWL_LOG_FILE) > 0
    with open(config.CRAWL_LOG_FILE, "a", encoding="utf-8") as f:
        if not exists:
            f.write(header)
        f.write("\n".join(logger) + "\n" if logger else "")


def append_jsonl(path, records):
    """R-02 一条一记录：一行一条 JSON 写入 .jsonl。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def base_record(platform, account_name, account_id, follower_count,
                content_id, content_title, content_url, comment_id,
                text, publish_time, like_count, reply_count, source_type,
                is_sub_reply=False, root_comment_id="", error=None):
    """构造符合手册 5.3 字段定义的原始记录 dict。

    扩展字段（用户要求）：
      is_sub_reply    是否楼中楼（二级评论）
      root_comment_id 楼中楼所属的主评论 id
    """
    return {
        "uid": make_uid(platform, comment_id),
        "platform": platform,
        "account_name": account_name,
        "account_id": str(account_id) if account_id else "",
        "follower_count": follower_count,
        "content_id": str(content_id),
        "content_title": content_title or "",
        "content_url": content_url,
        "comment_id": str(comment_id),
        "text": text,                       # C-05：原文不改写
        "publish_time": publish_time,
        "like_count": like_count or 0,
        "reply_count": reply_count or 0,     # 楼中楼评论数（主评论的回复数）
        "is_sub_reply": 1 if is_sub_reply else 0,  # 是否楼中楼
        "root_comment_id": str(root_comment_id) if root_comment_id else "",
        "collect_time": now_str(),
        "collector": config.COLLECTOR,
        "source_type": source_type,         # api / manual / screenshot
        "error": error,
    }
