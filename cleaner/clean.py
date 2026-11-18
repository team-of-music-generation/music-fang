# -*- coding: utf-8 -*-
"""
数据清洗 —— 开发者一顺手完成（手册第 6 节本属开发者B，此处按规则实现 O-02）

依据《MDD 工程操作手册》6.1 清洗规则：
  C-01 去重：按 uid，保留最早一条
  C-02 去纯表情/灌水：长度 <5 字或纯符号，删除
  C-03 去广告：含“接歌/编曲联系我/加V”等，删除
  C-04 去无意义夸赞：纯“好听”“666”，删除但计数
  C-05 保留原始文本：text 不改写，仅新增清洗标记列
  C-06 记录清洗量：原始 N 条 → 有效 M 条，写进日志
  C-07 去“三连”互动套话（用户 2026-11-17 新增）：已三连/一键三连/三连了等无意义刷屏

导出（用户 2026-11-17 要求，中文表头，7 列）：
  视频来源, 评论id, 原始评论, 评论时间, 点赞数, 是否楼中楼, 楼中楼评论数
  - 仅导出清洗后有效数据（is_valid=1）
  - 被删记录另存 comments_removed.csv（含删除原因）便于复核
"""

import csv
import glob
import os
import re

import config
from utils import common

# 用户要求的中文导出表头（7 列）
EXPORT_FIELDS = [
    "视频来源", "评论id", "原始评论", "评论时间",
    "点赞数", "是否楼中楼", "楼中楼评论数",
]

# 复核文件字段（被删除的记录）
REMOVED_FIELDS = ["视频来源", "评论id", "原始评论", "评论时间", "点赞数", "删除原因"]

# C-03 广告关键词
AD_PATTERNS = ["接歌", "编曲联系我", "加V", "加v", "加微", "微信", "vx", "V我",
               "私信我", "联系我", "约稿", "接单", "代做"]

# C-04 无意义夸赞（纯这些短句）
MEANINGLESS = re.compile(r"^(好听|666+|牛|牛逼|赞|好棒|厉害|支持|期待|来了|第一|前排|太强了|绝了|好听吧)[!！~。.、 ]*$")

# C-07 “三连”互动套话：以三连为核心的无意义刷屏（含“求文档/求教程”等也一并清掉，用户要求）
SANLIAN = re.compile(r"三连|一键|已关注|已赞|已收藏")

# 纯符号/表情
SYMBOL_ONLY = re.compile(r"^[\W_]+$", re.UNICODE)


def _has_cjk_or_alnum(s):
    """是否含有中文/字母/数字（用于判定纯符号灌水）。"""
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", s))


def clean_reason(text):
    """返回 (是否保留, 删除原因)。不改写原文（C-05）。"""
    t = (text or "").strip()
    # C-02：长度 <5 字 或 纯符号
    if len(t) < 5 or not _has_cjk_or_alnum(t) or SYMBOL_ONLY.match(t):
        return False, "C-02 灌水/纯符号"
    # C-03：广告
    for kw in AD_PATTERNS:
        if kw in t:
            return False, "C-03 广告"
    # C-04：无意义夸赞（纯短句）
    if MEANINGLESS.match(t):
        return False, "C-04 无意义夸赞"
    # C-07：三连互动套话（用户新增）
    if SANLIAN.search(t):
        return False, "C-07 三连互动套话"
    return True, ""


def load_raw():
    """读取 01_raw 下所有 .jsonl（R-02 一条一记录）。"""
    rows = []
    paths = []
    for sub in ("bilibili", "zhihu", "douyin"):
        d = os.path.join(config.RAW_DIR, sub)
        if os.path.isdir(d):
            paths.extend(glob.glob(os.path.join(d, "*.jsonl")))
    import json
    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def clean_all():
    """执行清洗，写出中文表头 comments_clean.csv，返回统计信息。"""
    raw = load_raw()
    total_n = len(raw)

    # C-01 去重：按 uid 保留最早一条（collect_time 最早）
    by_uid = {}
    for r in raw:
        uid = r.get("uid")
        if not uid:
            continue
        prev = by_uid.get(uid)
        if prev is None or (r.get("collect_time", "") < prev.get("collect_time", "")):
            by_uid[uid] = r
    deduped = list(by_uid.values())
    dup_removed = total_n - len(deduped)

    # C-02/03/04/07 逐条判定 + C-06 计数
    valid_rows = []
    removed_rows = []
    reason_count = {}
    for r in deduped:
        text = r.get("text", "")
        keep, reason = clean_reason(text)
        is_sub = int(r.get("is_sub_reply", 0) or 0)
        src = r.get("content_url", "") or r.get("account_name", "")
        base = {
            "视频来源": src,
            "评论id": r.get("comment_id", ""),
            "原始评论": text,
            "评论时间": r.get("publish_time", ""),
            "点赞数": r.get("like_count", 0),
        }
        if keep:
            valid_rows.append({
                **base,
                "是否楼中楼": "是" if is_sub else "否",
                "楼中楼评论数": r.get("reply_count", 0) or 0,
            })
        else:
            reason_count[reason] = reason_count.get(reason, 0) + 1
            removed_rows.append({**base, "删除原因": reason})

    config.ensure_dirs()
    removed_file = os.path.join(config.CLEAN_DIR, "comments_removed.csv")

    def dump(path, fields, rows):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    dump(config.RAW_FILE, EXPORT_FIELDS, valid_rows)
    dump(removed_file, REMOVED_FIELDS, removed_rows)

    valid_m = len(valid_rows)
    # C-06 清洗日志
    lines = [
        "# 清洗日志 clean_log\n",
        f"- 原始记录 N = {total_n} 条",
        f"- 去重移除（C-01）= {dup_removed} 条",
        f"- 去重后 = {len(deduped)} 条",
        f"- 有效记录 M = {valid_m} 条",
        f"- 删除明细：",
    ]
    for k, v in sorted(reason_count.items()):
        lines.append(f"    - {k}: {v} 条")
    lines.append(f"- 楼中楼有效数：{sum(1 for x in valid_rows if x['是否楼中楼']=='是')} 条")
    lines.append(f"- 产出：{config.RAW_FILE}（中文表头，仅有效数据）")
    lines.append(f"- 复核：{removed_file}（被删记录+原因）")
    lines.append(f"- 时间：{common.now_str()}\n")
    with open(config.CLEAN_LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))

    stats = {
        "raw": total_n,
        "dedup_removed": dup_removed,
        "deduped": len(deduped),
        "valid": valid_m,
        "removed_detail": reason_count,
        "sub_valid": sum(1 for x in valid_rows if x["是否楼中楼"] == "是"),
        "output": config.RAW_FILE,
    }
    print("[CLEAN] 统计:", stats)
    return stats


if __name__ == "__main__":
    clean_all()
