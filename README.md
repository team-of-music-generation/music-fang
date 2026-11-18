# MDD 阶段一 · 爬虫与数据清洗（开发者一）

哼唱生成音乐软件项目 · 阶段一 MDD 的「抓取 → 清洗」环节代码。

## 依据

- **《MDD 工程操作手册》**：数据源与规模（第 3 节）、分平台抓取方案（第 4 节）、
  存储规范与 16 字段定义（第 5 节）、清洗规则 C-01~C-06（第 6 节）、质量红线 Q-01~Q-05（第 9 节）。
- **《竞品调研-大v数据源》**：大V清单（B站 3 个已核验 BV 号）、筛选标准
  （每条须标注 平台/账号/粉丝量/视频链接/评论原文/采集时间）。

## 分工说明

手册分工中，**开发者一 = 开发 A**，负责 **B站 + 知乎 脚本抓取**；抖音为开发者 C 手动采集，
本工程预留 `mdd/01_raw/douyin/` 目录，手动录入的评论也会被清洗脚本统一处理。

## 目录结构

```
mdd_crawler/
├── config.py            # 全局配置：大V清单、知乎问题ID/Cookie、频率、路径
├── main.py              # 主入口（抓取 + 清洗）
├── crawlers/
│   ├── bilibili.py      # B站评论爬虫（view + reply/main 接口，游标分页）
│   └── zhihu.py         # 知乎回答/评论爬虫（需自己的登录 Cookie，否则降级）
├── cleaner/clean.py     # 清洗脚本（C-01~C-06）
├── utils/common.py      # uid/限速/日志/字段构造
├── requirements.txt
└── mdd/                 # 数据产出（按手册 5.1 目录）
    ├── 00_meta/source_list.csv, crawl_log.md, clean_log.md
    ├── 01_raw/bilibili/*.jsonl, zhihu/*.jsonl, douyin/*.jsonl
    ├── 02_clean/comments_clean.csv     # ★ 清洗后统一表
    ├── 03_llm/                          # 开发者B：三元组/聚类/机会（后续环节）
    ├── 04_report/
    └── _backup_old/                     # 旧数据本地留底（已忽略，不上传）
```

## 在 PyCharm 中运行

1. PyCharm 打开本目录（`D:\pycharm\PyCharm 2024.1.7` 已安装）。
2. 设置解释器为 Python 3.13，安装依赖：`pip install -r requirements.txt`（已安装可跳过）。
3. 右键 `main.py` → Run，或用命令行：

```bash
python main.py                       # 抓 B站+知乎 并清洗
python main.py --platform bili       # 只抓 B站
python main.py --clean-only          # 只对已有原始数据做清洗
python main.py --bili-cap 100        # 临时限制单视频抓取条数
```

## 知乎抓取说明（重要）

知乎页面需登录态。本脚本**只使用你自己的 Cookie**，不绕过验证（红线 Q-01）：

1. 浏览器登录知乎 → F12 → Network → 复制任一请求的 `Cookie` 请求头。
2. 填入 `config.py` 的 `ZHIHU_COOKIE`，或设置环境变量 `ZHIHU_COOKIE`。
3. 在 `config.py` 的 `ZHIHU_QUESTION_IDS` 填入已核验的问题 ID（如「怎么把哼唱写成歌」相关问题）。

未配置时脚本会记录日志并**跳过知乎**——抓不到就降级，不伪造数据（Q-05）。
抖音同样按手册建议手动采集，把数据按字段录入 `01_raw/douyin/*.jsonl` 即可被一并清洗。

## 输出字段（2026-11-17 更新）

**抓取规模**：主评论目标 5000 条（每个视频上限 `BILI_MAX_PER_VIDEO=1700`，不足则全抓），
并抓楼中楼（主评论内嵌的回复 + 回复数多时额外抓完整楼中楼）。楼中楼接口：
`https://api.bilibili.com/x/v2/reply/reply`（root=主评论 rpid，按页）。

**清洗导出表**（`02_clean/comments_clean.csv`，中文表头，仅有效数据）：

| 视频来源 | 评论id | 原始评论 | 评论时间 | 点赞数 | 是否楼中楼 | 楼中楼评论数 |
|---|---|---|---|---|---|---|

- `是否楼中楼`：是/否（楼中楼 = 对主评论的回复）
- `楼中楼评论数`：该评论下的回复条数
- 被删记录另存 `02_clean/comments_removed.csv`（含删除原因），便于复核

**清洗规则**：手册 C-01~C-06 + 新增 C-07（去"已三连/一键三连/三连了"等互动套话）。

**原始数据**（`01_raw/*.jsonl`，手册 5.3 字段 + 楼中楼扩展字段）：
uid, platform, account_name, account_id, follower_count, content_id, content_title,
content_url, comment_id, text, publish_time, like_count, reply_count,
is_sub_reply, root_comment_id, collect_time, collector, source_type, error

**旧版清洗统一表字段（已被中文表头替代）**：
uid, platform, account_name, content_url, text, publish_time, like_count,
is_valid, clean_reason, collector

## 关于 `mdd/_backup_old/`

该目录用于**本地留底**，存放阶段一早期的旧版抓取/清洗结果，例如
`*_20261117.jsonl`（按账号归档的原始评论）和 `comments_clean_old.csv`（旧字段版清洗表）。
它不参与当前脚本的读写：现行流程以 `mdd/01_raw/` → `mdd/02_clean/` 为准，
`config.py` 的 `ensure_dirs()` 只重建 `00_meta`、`01_raw/bilibili`、`01_raw/zhihu`、
`02_clean`、`03_llm`、`04_report`，**不会**自动重建 `_backup_old/`。

- **内容敏感度**：含评论原文和账号昵称，属于不应对外传播的数据。
- **上传策略**：`.gitignore` 中已通过 `mdd/_backup_old/` 忽略该目录，
  因此它**不会被提交到 GitHub**，公开分支只保留代码和 `mdd/00_meta/` 元数据。
- **使用方式**：仅在本地回溯、对照旧结果时手动取用；不要 `git add -f` 强制加入。

## 合规

仅抓公开评论、限速 1–2 秒、数据仅用于课程研究、报告引用匿名化账号、抓不到就降级不伪造。
详见 `config.py` 顶部红线说明。
