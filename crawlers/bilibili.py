# -*- coding: utf-8 -*-
"""
B站评论爬虫 —— 开发者一（开发 A）主力数据源

依据《MDD 工程操作手册》4.1 节：
  入口   视频页 https://www.bilibili.com/video/<BV号>
  接口   https://api.bilibili.com/x/v2/reply/main（主评论，游标分页）
         https://api.bilibili.com/x/v2/reply/reply（楼中楼/二级评论，root=rpid 按页）
  前提   oid 是 aid，BV 号需先通过 view 接口转换
  频率   1–2 秒/次

用户需求（2026-11-17 更新）：
  - 主评论目标约 5000 条，不足则全抓
  - 楼中楼很重要，一并抓取（主评论内嵌的 + 回复多的额外抓完整）
  - 标记“是否楼中楼”“楼中楼评论数”

合规：只抓接口公开返回的一级/二级评论；不破解签名、不伪造数据（Q-01/Q-05）。
"""

import math
import os
import requests

import config
from utils import common


VIEW_API = "https://api.bilibili.com/x/web-interface/view"
REPLY_API = "https://api.bilibili.com/x/v2/reply/main"
SUB_REPLY_API = "https://api.bilibili.com/x/v2/reply/reply"


def _http_get(session, url, params):
    """带限速的 GET，返回 dict 或 None。"""
    common.polite_delay()
    resp = session.get(url, params=params, headers=config.HEADERS,
                       timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def get_video_info(session, bvid):
    """BV 号 -> 视频信息（aid / 标题 / UP 主 mid）/ 评论总数。"""
    data = _http_get(session, VIEW_API, {"bvid": bvid})
    if not data or data.get("code") != 0:
        raise RuntimeError(f"view 接口失败 bvid={bvid} code={data.get('code') if data else 'None'}")
    d = data["data"]
    return {
        "aid": d["aid"],
        "title": d.get("title", ""),
        "owner_name": (d.get("owner") or {}).get("name", ""),
        "owner_mid": (d.get("owner") or {}).get("mid", ""),
        "reply_count": (d.get("stat") or {}).get("reply", 0),
    }


def decide_limit(total_replies, cap):
    """用户要求：以 cap 为准尽量多抓，评论总数不足则全抓。"""
    return max(1, min(total_replies if total_replies > 0 else cap, cap))


def _make_record(rp, info, target, bvid, content_url, is_sub, root_id):
    """把接口返回的一条评论 dict 转成标准记录。"""
    content = rp.get("content") or {}
    member = rp.get("member") or {}
    rec = common.base_record(
        platform="bilibili",
        account_name=info["owner_name"],
        account_id=info["owner_mid"],
        follower_count=target.get("follower_count", 0),
        content_id=bvid,
        content_title=info["title"],
        content_url=content_url,
        comment_id=rp.get("rpid"),
        text=content.get("message", ""),
        publish_time=common.ts_to_str(rp.get("ctime")),
        like_count=rp.get("like", 0),
        reply_count=rp.get("rcount", 0),
        source_type="api",
        is_sub_reply=is_sub,
        root_comment_id=root_id,
    )
    # 评论者昵称仅作源数据冗余保留（R-03），报告中须匿名化（Q-04）
    rec["commenter"] = member.get("uname", "")
    return rec


def crawl_video(session, target, cap, logger, remaining_budget):
    """抓取单个视频：主评论 + 楼中楼。

    返回 (records, info)。records 含主评论(is_sub_reply=0)与楼中楼(is_sub_reply=1)。
    remaining_budget 为全局主评论剩余额度，避免总量超过目标。
    """
    bvid = target["bvid"]
    info = get_video_info(session, bvid)
    account = target["account_name"]
    info["owner_name"] = info["owner_name"] or account
    info["owner_mid"] = info["owner_mid"] or target.get("account_id", "")

    total = info["reply_count"]
    per_video_cap = min(cap, remaining_budget)
    limit = decide_limit(total, per_video_cap)
    content_url = f"https://www.bilibili.com/video/{bvid}/"
    common.log_event(logger, "bilibili", account, 0,
                     f"开始抓取 BV={bvid} aid={info['aid']} 评论总数={total} 计划主评论={limit}")

    main_records = []
    sub_records = []
    next_cursor = 0
    errors = 0
    seen_ids = set()
    sub_request_count = 0  # 完整楼中楼请求计数（控时长）

    while len(main_records) < limit:
        params = {
            "type": 1,
            "oid": info["aid"],
            "mode": 2,          # 按时间排序，游标分页稳定
            "next": next_cursor,
            "ps": config.BILI_PS,
        }
        try:
            data = _http_get(session, REPLY_API, params)
            if not data or data.get("code") != 0:
                raise RuntimeError(f"reply 接口 code={data.get('code') if data else 'None'}")
            d = data["data"] or {}
            replies = d.get("replies") or []
            cursor = d.get("cursor") or {}
            new_cursor = cursor.get("next", next_cursor + len(replies))
        except Exception as e:
            errors += 1
            common.log_event(logger, "bilibili", account, len(main_records), f"异常#{errors}: {e}")
            if errors >= config.MAX_CONSECUTIVE_ERRORS:
                break
            continue

        if not replies:
            break

        for rp in replies:
            if len(main_records) >= limit:
                break
            cid = rp.get("rpid")
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            rcount = rp.get("rcount", 0) or 0

            # 主评论
            main_records.append(_make_record(rp, info, target, bvid, content_url,
                                             is_sub=False, root_id=""))

            if not config.BILI_FETCH_SUB:
                continue

            # 楼中楼来源1：主评论接口内嵌的 replies（通常 1~3 条高赞回复，免费）
            embedded = rp.get("replies") or []
            for sub in embedded:
                sid = sub.get("rpid")
                if not sid or sid in seen_ids:
                    continue
                seen_ids.add(sid)
                sub_records.append(_make_record(sub, info, target, bvid, content_url,
                                                is_sub=True, root_id=cid))

            # 楼中楼来源2：回复数较多时，额外调用楼中楼接口抓完整（受预算限制）
            if (rcount >= config.BILI_SUB_MIN_ROUND
                    and sub_request_count < config.BILI_SUB_REQ_BUDGET_PER_VIDEO):
                subs = _fetch_full_sub(session, info["aid"], cid, content_url,
                                       info, target, bvid, seen_ids)
                sub_request_count += 1
                sub_records.extend(subs)

        if new_cursor == next_cursor:
            break
        next_cursor = new_cursor
        if cursor.get("is_end"):
            break

    all_records = main_records + sub_records
    common.log_event(logger, "bilibili", account, len(all_records),
                     f"完成 BV={bvid} 主评论={len(main_records)} 楼中楼={len(sub_records)} "
                     f"楼中楼请求={sub_request_count} 异常={errors}")
    return all_records, info


def _fetch_full_sub(session, aid, root_id, content_url, info, target, bvid, seen_ids):
    """抓某条主评论的完整楼中楼，返回记录列表。失败返回空并记录，不中断。"""
    subs = []
    page = 1
    while len(subs) < config.BILI_SUB_MAX_PER_MAIN:
        params = {"type": 1, "oid": aid, "root": root_id,
                  "ps": config.BILI_PS, "pn": page}
        try:
            data = _http_get(session, SUB_REPLY_API, params)
            if not data or data.get("code") != 0:
                break
            replies = (data.get("data") or {}).get("replies") or []
        except Exception:
            break
        if not replies:
            break
        for rp in replies:
            sid = rp.get("rpid")
            if not sid or sid in seen_ids:
                continue
            seen_ids.add(sid)
            subs.append(_make_record(rp, info, target, bvid, content_url,
                                     is_sub=True, root_id=root_id))
        page_info = (data.get("data") or {}).get("page") or {}
        if page >= page_info.get("count", 1):
            break
        page += 1
    return subs


def crawl_all(logger, cap=None, target_total=None):
    """遍历大V清单抓取所有 B站目标，按账号写入 01_raw/bilibili/。

    主评论总量达到 target_total 后停止抓取后续视频。
    """
    cap = cap or config.BILI_MAX_PER_VIDEO
    target_total = target_total or config.BILI_TARGET_TOTAL
    session = requests.Session()
    summary = []
    main_total = 0

    for target in config.BILI_TARGETS:
        remaining = target_total - main_total
        if remaining <= 0:
            common.log_event(logger, "bilibili", target["account_name"], 0,
                             f"跳过：主评论已达目标 {main_total} 条")
            break
        try:
            records, info = crawl_video(session, target, cap, logger, remaining)
            n_main = sum(1 for r in records if r["is_sub_reply"] == 0)
            main_total += n_main
            fname = f"{target['account_name']}_{common.today_str()}.jsonl"
            path = os.path.join(config.BILI_RAW_DIR, fname)
            common.append_jsonl(path, records)
            n_sub = len(records) - n_main
            summary.append((target["account_name"], info["title"], n_main, n_sub))
        except Exception as e:
            common.log_event(logger, "bilibili", target["account_name"], 0, f"目标失败: {e}")

    common.log_event(logger, "bilibili", "合计", main_total,
                     f"主评论合计={main_total} 目标={target_total}")
    return summary
