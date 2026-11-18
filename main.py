# -*- coding: utf-8 -*-
"""
MDD 阶段一 · 主入口（开发者一：B站 + 知乎 抓取 + 数据清洗）

运行方式（PyCharm 中直接右键 Run，或命令行）：
    python main.py                      # 抓取 B站 + 知乎，然后清洗
    python main.py --platform bili      # 只抓 B站
    python main.py --platform zhihu     # 只抓 知乎
    python main.py --clean-only         # 只做清洗（已有 01_raw 数据时）
    python main.py --bili-cap 100       # 临时覆盖单视频抓取上限

数据流（对应手册验收产出 O-01/O-02/O-06）：
    抓取 -> mdd/01_raw/<平台>/*.jsonl   （原始，只增不改 R-01）
         -> mdd/00_meta/crawl_log.md    （抓取日志 O-06）
    清洗 -> mdd/02_clean/comments_clean.csv （统一表 O-02）
         -> mdd/00_meta/clean_log.md    （清洗量 C-06）

合规红线 Q-01~Q-05 见 config.py，务必阅读。
"""

import argparse
import csv
import os

import config
from utils import common
from crawlers import bilibili, zhihu
from cleaner import clean as cleaner


def write_source_list():
    """00_meta/source_list.csv：账号清单（平台/账号/ID/链接/粉丝量）。"""
    config.ensure_dirs()
    if os.path.exists(config.SOURCE_LIST_FILE) and os.path.getsize(config.SOURCE_LIST_FILE) > 0:
        return
    with open(config.SOURCE_LIST_FILE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["平台", "账号", "账号ID", "内容ID", "内容链接", "粉丝量", "备注"])
        for t in config.BILI_TARGETS:
            w.writerow(["bilibili", t["account_name"], t.get("account_id", ""),
                        t["bvid"], f"https://www.bilibili.com/video/{t['bvid']}/",
                        t.get("follower_count", 0), t.get("content_title_hint", "")])
        for qid in config.ZHIHU_QUESTION_IDS:
            w.writerow(["zhihu", f"问题{qid}", "", qid,
                        f"https://www.zhihu.com/question/{qid}", "", "竞品调研命中场景"])
    print("[META] 已写入 source_list.csv")


def print_summary(stats):
    print("\n" + "=" * 56)
    print("MDD 阶段一 · 抓取与清洗结果")
    print("=" * 56)
    print(f"  原始评论数 N      : {stats['raw']}")
    print(f"  去重移除 (C-01)   : {stats['dedup_removed']}")
    print(f"  去重后            : {stats['deduped']}")
    print(f"  有效评论数 M      : {stats['valid']}")
    print(f"  其中楼中楼有效    : {stats.get('sub_valid', 0)}")
    target_msg = "达标 ✅" if stats["valid"] >= 5000 else str(stats["valid"]) + "/5000 ⚠️"
    print(f"  5000 目标         : {target_msg}")
    if stats['removed_detail']:
        print(f"  删除明细          : {stats['removed_detail']}")
    print(f"  清洗后文件        : {stats['output']}")
    print("=" * 56 + "\n")


def main():
    parser = argparse.ArgumentParser(description="MDD 阶段一 爬虫 + 清洗（开发者一）")
    parser.add_argument("--platform", choices=["all", "bili", "zhihu"], default="all")
    parser.add_argument("--clean-only", action="store_true")
    parser.add_argument("--bili-cap", type=int, default=None, help="单视频抓取上限")
    parser.add_argument("--zhihu-cap", type=int, default=None, help="单问题抓取上限")
    args = parser.parse_args()

    config.ensure_dirs()
    write_source_list()
    logger = common.new_log()

    if not args.clean_only:
        if args.platform in ("all", "bili"):
            print("\n>>> 开始抓取 B站 评论（大V清单 3 个视频）...")
            try:
                bilibili.crawl_all(logger, cap=args.bili_cap)
            except Exception as e:
                common.log_event(logger, "bilibili", "-", 0, f"抓取阶段异常: {e}")
        if args.platform in ("all", "zhihu"):
            print("\n>>> 开始抓取 知乎 回答与评论...")
            try:
                zhihu.crawl_all(logger, cap=args.zhihu_cap)
            except Exception as e:
                common.log_event(logger, "zhihu", "-", 0, f"抓取阶段异常: {e}")

    common.write_crawl_log(logger)
    print(f"\n[META] 抓取日志已写入 {config.CRAWL_LOG_FILE}")

    print("\n>>> 开始清洗数据（C-01~C-06）...")
    stats = cleaner.clean_all()
    print_summary(stats)


if __name__ == "__main__":
    main()
