# -*- coding: utf-8 -*-
"""
知乎爬虫 —— 开发者一（开发 A）主力数据源之一

依据《MDD 工程操作手册》4.2 节：
  入口   问题页 https://www.zhihu.com/question/<id>
  抓什么 高赞回答正文 + 回答下的评论（优先长文本回答）
  方式   页面 HTML 解析（内嵌 JSON），或手动复制

合规（手册红线，务必遵守）：
  Q-01 只抓公开内容，不绕过登录验证、不破解加密。
       —— 知乎多数页面需登录态。本脚本【只使用你自己在浏览器登录后的 Cookie】，
          不尝试破解签名 / 绕过风控；无 Cookie 时直接降级，不伪造数据（Q-05）。
  Q-02 1–2 秒/次。

使用方法：
  1) 浏览器登录知乎，F12 -> Network -> 任选一个请求 -> 复制 Request Headers 里的 Cookie。
  2) 填入 config.py 的 ZHIHU_COOKIE（或设置环境变量 ZHIHU_COOKIE）。
  3) 把已核验的问题 ID 填入 config.py 的 ZHIHU_QUESTION_IDS。
  4) 运行：python main.py --platform zhihu

作者提示：若仍被 403/429 拦截，按手册 4.4 兜底——切手动复制，
          把评论按同样字段录入 01_raw/zhihu/*.jsonl，并在 crawl_log 记录原因。
"""

import json
import os
import re

import requests
from bs4 import BeautifulSoup

import config
from utils import common


QUESTION_URL = "https://www.zhihu.com/question/{qid}"
ANSWER_COMMENTS_API = "https://www.zhihu.com/api/v4/answers/{aid}/comments"


def _build_session():
    session = requests.Session()
    headers = dict(config.HEADERS)
    cookie = os.environ.get("ZHIHU_COOKIE") or getattr(config, "ZHIHU_COOKIE", "")
    if cookie:
        headers["Cookie"] = cookie
    session.headers.update(headers)
    return session, bool(cookie)


def _extract_initial_data(html):
    """从问题页 HTML 里抽取 window.__INITIAL_STATE__ / js-initialData。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script"):
        text = tag.string or tag.get_text() or ""
        if "js-initialData" in (tag.get("id") or "") or "__INITIAL_STATE__" in text:
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    continue
    return {}


def _walk_answers(data):
    """从知乎内嵌状态里尽量找出回答列表（不同版本结构不同，做多层兼容）。"""
    found = []

    def rec(obj):
        if isinstance(obj, dict):
            # 常见结构：entities.answers.<id>
            if "content" in obj and "author" in obj and ("voteupCount" in obj or "created" in obj):
                found.append(obj)
            for v in obj.values():
                rec(v)
        elif isinstance(obj, list):
            for v in obj:
                rec(v)

    rec(data)
    # 去重
    uniq = {}
    for a in found:
        key = a.get("id") or id(a)
        uniq[key] = a
    answers = list(uniq.values())
    answers.sort(key=lambda a: a.get("voteupCount", 0) or 0, reverse=True)
    return answers


def _html_to_text(html):
    """回答正文 HTML -> 纯文本（保留原文语义，不改写）。"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for p in soup.find_all("p"):
        p.append("\n")
    text = soup.get_text(separator="")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def fetch_answer_comments(session, aid, content_url, question_id, question_title,
                          account_name, account_id, limit, logger):
    """抓单个回答下的评论（手册 4.2 要求）。失败返回空并记录，不中断整体。"""
    records = []
    offset = 0
    errors = 0
    while len(records) < limit:
        common.polite_delay()
        try:
            resp = session.get(
                ANSWER_COMMENTS_API.format(aid=aid),
                params={"limit": 20, "offset": offset, "order": "default"},
                timeout=config.REQUEST_TIMEOUT,
            )
            if resp.status_code in (403, 429):
                raise RuntimeError(f"HTTP {resp.status_code}（风控/需登录），降级跳过该回答评论")
            data = resp.json()
        except Exception as e:
            errors += 1
            common.log_event(logger, "zhihu", account_name, len(records), f"回答评论异常: {e}")
            if errors >= 3:
                break
            continue
        items = data.get("data") or []
        if not items:
            break
        for c in items:
            if len(records) >= limit:
                break
            cid = c.get("id")
            rec = common.base_record(
                platform="zhihu",
                account_name=account_name,
                account_id=account_id,
                follower_count=0,
                content_id=question_id,
                content_title=question_title,
                content_url=content_url,
                comment_id=cid,
                text=c.get("content", ""),
                publish_time=common.ts_to_str(c.get("created_time")),
                like_count=c.get("vote_count", 0),
                reply_count=0,
                source_type="api",
            )
            records.append(rec)
        offset += len(items)
        if data.get("paging", {}).get("is_end"):
            break
    return records


def crawl_question(session, qid, cap, logger):
    """抓取单个知乎问题：高赞回答正文 + 回答下评论。"""
    url = QUESTION_URL.format(qid=qid)
    common.log_event(logger, "zhihu", qid, 0, f"开始抓取问题 {url}")
    common.polite_delay()
    resp = session.get(url, timeout=config.REQUEST_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"问题页 HTTP {resp.status_code}（需登录 Cookie 或被风控）")

    data = _extract_initial_data(resp.text)
    answers = _walk_answers(data)
    if not answers:
        raise RuntimeError("未从页面解析出回答（结构变化或需登录）")

    # 问题标题
    question_title = ""
    soup = BeautifulSoup(resp.text, "html.parser")
    h1 = soup.find("h1")
    if h1:
        question_title = h1.get_text(strip=True)

    records = []
    for ans in answers:
        if len(records) >= cap:
            break
        aid = ans.get("id")
        author = ans.get("author") or {}
        account_name = author.get("name") or "知乎答主"
        account_id = author.get("id") or ""
        answer_text = _html_to_text(ans.get("content"))
        # 优先长文本回答（手册 4.2）
        if len(answer_text) < 5:
            continue
        rec = common.base_record(
            platform="zhihu",
            account_name=account_name,
            account_id=account_id,
            follower_count=0,
            content_id=qid,
            content_title=question_title,
            content_url=url,
            comment_id=f"answer_{aid}",
            text=answer_text,
            publish_time=common.ts_to_str(ans.get("created")),
            like_count=ans.get("voteupCount", 0),
            reply_count=ans.get("commentCount", 0),
            source_type="api",
        )
        records.append(rec)

        if config.ZHIHU_FETCH_ANSWER_COMMENTS and aid and len(records) < cap:
            cs = fetch_answer_comments(
                session, aid, url, qid, question_title,
                account_name, account_id, cap - len(records), logger,
            )
            records.extend(cs)

    common.log_event(logger, "zhihu", qid, len(records), f"完成问题 {qid} 实抓={len(records)}")
    return records


def crawl_all(logger, cap=None):
    """遍历问题清单抓取知乎数据。无 Cookie / 无问题 ID 时降级，不伪造。"""
    cap = cap or config.ZHIHU_MAX_PER_QUESTION
    session, has_cookie = _build_session()
    summary = []

    qids = list(config.ZHIHU_QUESTION_IDS)
    if not qids:
        common.log_event(logger, "zhihu", "-", 0,
                  "降级：未配置 ZHIHU_QUESTION_IDS 且无 Cookie，跳过知乎（Q-05 不伪造数据）")
        return summary
    if not has_cookie:
        common.log_event(logger, "zhihu", "-", 0,
                  "降级：未配置 ZHIHU_COOKIE，知乎页面需登录态，跳过抓取（Q-01 不绕过登录）")
        return summary

    for qid in qids:
        try:
            records = crawl_question(session, str(qid), cap, logger)
            fname = f"question_{str(qid)}_{common.today_str()}.jsonl"
            path = os.path.join(config.ZHIHU_RAW_DIR, fname)
            common.append_jsonl(path, records)
            summary.append((str(qid), len(records)))
        except Exception as e:
            common.log_event(logger, "zhihu", str(qid), 0, f"目标失败: {e}")
    return summary
