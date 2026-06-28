# LLM 股票分析 CLI（jiquer / DeepSeek）

## 配置

1. 复制 `.env.example` 为 `.env`，填入 `JIQUER_API_KEY`（勿提交 git）。**脚本启动时会自动读取项目根目录的 `.env`**
2. 可选编辑 `config/llm.yaml`（模型、timeout、联网检索关键词）

## 用法

```bash
source .venv/bin/activate

# 探测 API + 深度思考
python3 scripts/analyze_stock.py --probe

# 普通分析
python3 scripts/analyze_stock.py 600519

# 联网分析：自动拉公告 + 网络检索，注入 prompt 后再打分
python3 scripts/analyze_stock.py 600519 --web-search

# 深度思考 + 联网
python3 scripts/analyze_stock.py 600519 --web-search --thinking --show-reasoning

# 只看注入 prompt 长什么样（不调 API）
python3 scripts/analyze_stock.py 600519 --web-search --dry-run
```

## `--web-search` 做什么？

**不是**依赖 jiquer 内置联网（通常无效），而是本机在调用 DeepSeek **之前**自动搜集：

| 来源 | 内容 |
|------|------|
| AkShare 公告 | 近一年东方财富公告标题（管理层/文化/重大事项） |
| 公告分类 | 规则标注：回购分红、关联交易、监管处罚、激励薪酬等 |
| 分红 / 回购 | 近年分红记录、回购进展（资本配置） |
| 股权质押 | 质押比例概况 |
| DuckDuckGo 检索 | 按 `config/llm.yaml` 里 3 组关键词搜公开报道摘要 |

搜集结果附在 prompt 末尾，模型据此打 6 维分。请安装依赖：

```bash
pip install duckduckgo-search
```

（已在 `requirements.txt`；未安装时会尝试 HTML 备用通道，可能不稳定。）

可在 `config/llm.yaml` 的 `web_context` 段调整 `search_queries`、`max_notices`、`enable_dividends` 等。某一数据源失败时会打印 `[web-search] ... 失败:` 到 stderr，**不会中断**分析流程。

## 深度思考

`--thinking` 向 jiquer 传 `thinking.type=enabled`；若响应含 `reasoning_content` 则成功（可用 `--show-reasoning` 查看）。

## 退出码

- `0`：成功且 6 维齐全
- `1`：有输出但缺少部分维度
- `2`：拉数/解析股票失败
- `3`：API 认证或调用失败
