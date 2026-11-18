# -*- coding: utf-8 -*-
"""
MDD 阶段一 · 全局配置
负责人：开发者一（开发 A）— 负责 B站 + 知乎 脚本抓取

依据文档：
- 《MDD 工程操作手册》第 3/4/5 节（数据源、抓取方案、存储规范）
- 《竞品调研-大v数据源》大V清单 + 筛选标准

合规红线（手册 Q-01~Q-05，务必遵守）：
  Q-01 只抓公开评论，不绕过登录验证、不破解加密
  Q-02 控制频率 1–2 秒/次，不对平台造成压力
  Q-03 数据仅用于课程研究，不对外传播原始评论
  Q-04 报告引用时匿名化账号
  Q-05 抓不到就降级，不伪造、不编造数据
"""

import os

# ---------- 路径 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MDD_DIR = os.path.join(BASE_DIR, "mdd")
RAW_DIR = os.path.join(MDD_DIR, "01_raw")
META_DIR = os.path.join(MDD_DIR, "00_meta")
CLEAN_DIR = os.path.join(MDD_DIR, "02_clean")

BILI_RAW_DIR = os.path.join(RAW_DIR, "bilibili")
ZHIHU_RAW_DIR = os.path.join(RAW_DIR, "zhihu")

RAW_FILE = os.path.join(CLEAN_DIR, "comments_clean.csv")
SOURCE_LIST_FILE = os.path.join(META_DIR, "source_list.csv")
CRAWL_LOG_FILE = os.path.join(META_DIR, "crawl_log.md")
CLEAN_LOG_FILE = os.path.join(META_DIR, "clean_log.md")

# ---------- 抓取频率（秒）----------
# 手册 Q-02：每次请求间隔 1–2 秒，别并发轰炸
MIN_DELAY = 1.0
MAX_DELAY = 2.0

# ---------- 请求头 ----------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ---------- 单条内容抓取上限 ----------
# 用户要求：总共抓约 5000 条主评论，评论不足则全抓；楼中楼很重要，一并抓。
# 三个视频分摊：1700/视频 × 3 ≈ 5100 条主评论（不足则全抓）。
BILI_MAX_PER_VIDEO = 1700     # 单个 B站视频最多抓的主评论数（不足则全抓）
BILI_TARGET_TOTAL = 5000      # 主评论目标总量（达到后停止）
ZHIHU_MAX_PER_QUESTION = 150  # 单个知乎问题最多抓的回答/评论数

# ---------- 楼中楼（二级评论）抓取 ----------
BILI_FETCH_SUB = True             # 是否抓楼中楼
BILI_SUB_MIN_ROUND = 5            # 只对 rcount >= 该值的主评论额外请求完整楼中楼
BILI_SUB_REQ_BUDGET_PER_VIDEO = 80  # 每个视频最多发起的“完整楼中楼”接口请求数（控时长）
BILI_SUB_MAX_PER_MAIN = 50        # 单条主评论最多抓的楼中楼条数

# B站评论接口游标分页每页条数（官方 ps 最大 20）
BILI_PS = 20

# 采集人标记（手册字段 collector，开发者一=A）
COLLECTOR = "A"

# ---------- 大V清单（来源：《竞品调研-大v数据源》大V清单）----------
# 筛选标准：每条记录须标注 平台/账号/粉丝量/视频链接/评论原文/采集时间
# 说明：账号状态与粉丝量以调研表为准，实际抓取时以接口返回为准并记录异常。
BILI_TARGETS = [
    {
        "account_name": "阿张RayZhang",
        "account_id": "",            # 抓取时由 view 接口补全（owner.mid）
        "follower_count": 2151000,   # 215.1w
        "bvid": "BV1ft421g7pb",
        "content_title_hint": "Suno Ai令人破防！Ai对音乐行业会有多大影响？",
    },
    {
        "account_name": "AI先生李豪",
        "account_id": "",
        "follower_count": 144000,    # 14.4w
        "bvid": "BV1y9Q1BeEpV",
        "content_title_hint": "一口气带你学会全球最强AI音乐软件Suno！",
    },
    {
        "account_name": "莫逆iMoNe",
        "account_id": "",
        "follower_count": 116000,    # 11.6w
        "bvid": "BV1Hx411S7zm",
        "content_title_hint": "【你还不会编曲吗？】B站首个从零开始的完整编曲教程",
    },
]

# ---------- 知乎问题清单 ----------
# 来源：《竞品调研-大v数据源》—“直接搜索‘怎么把哼唱写成歌’类问题答主”
# 手册 4.2：问题页 https://www.zhihu.com/question/<id>，抓高赞回答正文 + 回答下评论。
# 知乎反爬较强：把已核验的问题链接填入下方即可抓取（支持完整 URL 或纯数字 ID）。
# 留空时脚本会尝试用关键词搜索定位问题；若搜索被拦截，则记录日志并降级（Q-05，不伪造）。
ZHIHU_KEYWORDS = ["怎么把哼唱写成歌", "编曲入门", "哼唱记谱"]

ZHIHU_QUESTION_IDS = [
    # 示例（请替换为实际核验过的问题 ID）：
    # "123456789",
]

# 单个知乎问题抓取时，是否同时抓“回答下的评论”（手册 4.2 要求）
ZHIHU_FETCH_ANSWER_COMMENTS = True

# ---------- 兜底 ----------
# 接口连续失败 N 次即停止该目标，写入 error 日志并切换下一个（手册 4.4 / 10 节）
MAX_CONSECUTIVE_ERRORS = 5
REQUEST_TIMEOUT = 15


def ensure_dirs():
    """确保 mdd/ 目录结构存在（手册 5.1，对应产出物 O-01~O-06 存放位置）。"""
    for d in (META_DIR, BILI_RAW_DIR, ZHIHU_RAW_DIR, CLEAN_DIR,
              os.path.join(MDD_DIR, "03_llm"), os.path.join(MDD_DIR, "04_report")):
        os.makedirs(d, exist_ok=True)
