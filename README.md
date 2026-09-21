# stock-mining：寻找被错杀优质股票的研究工作台

> **投资哲学 / Investment philosophy**：本项目参考巴菲特、芒格、段永平、李录等长期价值投资者公开分享的思想，关注企业质量、长期成长、商业模式与安全边际，尝试从市场波动中找到“被错杀”的优质股票。

> **项目目的 / Purpose**：把上述理念转化为一套可配置、可复核、可交接的开源研究流程。它先用公开数据筛选可能被错杀的成长型白马，再用人工或大模型补充商业模式、护城河和风险判断，帮助你更快建立自己的研究清单。
>
> 本项目仅供学习和研究，不构成任何投资建议。数据来自公开接口，质量和可用性可能随服务商变化。

English documentation: [docs/README_EN.md](docs/README_EN.md)

## 适合谁？

- 想从零开始做 A 股 / 港股候选池的小白：按“安装 → 生成候选 → 打开网页”三步即可上手。
- 已有筛选规则、想把规则配置化的研究者：直接修改 `config/*.yaml`，无需改核心代码。
- 想参与开源的开发者：`filters/`、`markets/`、`scoring/`、`web/` 都有清晰边界，欢迎提交 Issue 和 PR。

## 投资定义

| 维度 | 量化（Python） | 定性（Cursor 粘贴回 Web） |
|------|----------------|---------------------------|
| 便宜 | 52 周新低附近 + 距高点回撤 | 为什么现在便宜 |
| 成长 | 收入/利润趋势、ROE/毛利率 | 未来还能不能长大 |
| 白马 | 多年财务质量 | 商业模式、护城河、管理层 |
| 非陷阱 | 业绩未持续恶化 | 一次性利空 vs 基本面变坏 |

## 安装

```bash
cd stock-mining
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

先用少量股票做一次检查（只会访问你主动运行的数据流程）：

```bash
python scripts/daily_screen.py --strategy mispriced_growth --market a --codes a:600519 --skip-dedup
python scripts/serve_review.py --host 127.0.0.1
```

默认审阅页为 `http://localhost:8501`；单股 Prompt 查询页使用 `python scripts/serve_prompt_query.py --host 127.0.0.1`（端口 `8502`）。服务器或局域网访问时，把 `--host` 改为 `0.0.0.0`，并通过 `--port` 指定端口。两个启动脚本都支持 `--help`。

## 一日工作流

```bash
# 1a. 被错杀的白马股（A 股 → candidates.json）
python3 scripts/daily_screen.py --strategy mispriced_growth --market a

# 1b. 正常估值不下滑（A 股 → normal_value_candidates.json）
python3 scripts/daily_screen.py --strategy normal_value --market a

# 1c. 港股通·被错杀的白马股（→ hk_candidates.json）
python3 scripts/daily_screen.py --strategy mispriced_growth_hk --market h

# 1d. 所有策略 + 所有市场（→ 各策略 JSON + all_candidates.json）
python3 scripts/daily_screen.py --strategy all --market all

# 股票代码带市场前缀，避免撞码：a:600519  h:00700
python3 scripts/daily_screen.py --strategy all --codes a:600519 h:00700 --market all --skip-dedup

# 2. Web 审阅（侧边栏可切换策略；默认打开最近更新的结果）
python3 scripts/serve_review.py
python3 scripts/serve_review.py --strategy normal_value   # 指定默认策略

# 3. 批量导出 Cursor Prompt（可选）
python3 scripts/export_prompts.py --limit 10

# 4. 单股规则审计
python3 scripts/audit_screen.py --codes 600519 --market a
python3 scripts/audit_screen.py --from-csv data/results/candidates.csv --limit 5
```

审阅页三种数据源（侧边栏「筛选策略」）：

| 策略 | 数据文件 | 产生方式 |
|------|----------|----------|
| 被错杀的白马股 | `data/results/candidates.json` | `--strategy mispriced_growth --market a` |
| 正常估值不下滑 | `data/results/normal_value_candidates.json` | `--strategy normal_value --market a` |
| 港股·被错杀的白马股 | `data/results/hk_candidates.json` | `--strategy mispriced_growth_hk --market h` |
| 所有策略合并 | `data/results/all_candidates.json` | `--strategy all --market all` |
| 正常估值·商业模式≥4 | `data/results/normal_value_review.json` | `apply_business_model_triage.py` |

股票唯一标识：`a:600519`（A股）、`h:00700`（港股）、`u:`（美股预留）。历史 `hk:` 会自动视为 `h:`。

## 双轨筛选（config/screen.yaml）

- **profitable_growth**：盈利型成长白马（ROE、股息、现金流、估值等）
- **loss_tolerant_growth**：暂亏型成长（3 年内至少 1 年盈利，高毛利，收入未连续下滑）

公共条件：非 ST、行业过滤、52 周低附近、高点回撤、行业非持续衰退。

## 架构

```
markets/       A 股 + 港股通 Provider
filters/       可配置 Filter 插件
scoring/       打分排序（与 pass/fail 分离）
pipeline/      筛股 + 去重
state/         黑名单 / 已研究 / LLM 缓存（SQLite）
llm/           Prompt 生成 + Markdown 表格解析
web/           Streamlit 审阅
```

## 用户状态

| 机制 | 默认 | 说明 |
|------|------|------|
| 黑名单 | 180 天 | Web 默许后生效，到期自动释放 |
| 已研究冷却 | 30 天 | 标记后短期内不再推荐 |
| 定性缓存 | 按维度 TTL | 默许后生效（商业模式 90 天等） |

数据分离：`data/cache/`（行情缓存） vs `data/state/`（用户状态）。

## 网页怎么用？

1. **今日候选**：查看分数和指标，可按代码/名称、轨道过滤；卡片中可复制或下载 Prompt。
2. **粘贴分析**：选择股票，粘贴 Markdown 表格，系统会校验维度并保存有效缓存。
3. **我的标记**：三类标记互斥；加入自选的股票可随时移除，过期标记会自动释放。

首次打开时点击页面顶部“第一次使用？先看这里”，页面会给出完整操作提示。结果文件在 `data/results/`，个人状态在 `data/state/`，缓存和状态都不会进入 Git。

## 配置与扩展

- `config/screen*.yaml`：市场、过滤条件、线程数、输出目录和状态策略。
- `config/analysis_dimensions.yaml`：定性分析维度和缓存 TTL。
- `stock_mining/filters/`：可注册新的过滤器；通过 YAML 参数复用，不把个人条件写死在 UI 中。
- `stock_mining/markets/`：数据提供商和市场适配层。
- `.env.example`：需要 LLM 接口时复制为 `.env`，密钥只放在本地，绝不提交。

## 测试

```bash
pytest -q
```

默认的单元测试不要求联网；涉及真实数据源的测试会显式标记为 network。

## 贡献与联系作者

欢迎提交 Issue、补充数据源、增加测试、改进文档和网页交互。提交前请说明改动目的、验证方式、是否需要联网数据。LLM 流程见 `docs/llm_analyze.md` / `docs/llm_analyze_en.md`。

作者：370170920@qq.com

欢迎更多小伙伴加入，也欢迎社会各界朋友完善这个项目，让它更标准、更通用、更容易被后来者使用。

## 定时任务

```cron
30 18 * * 1-5 cd /path/to/stock-mining && .venv/bin/python3 scripts/daily_screen.py >> logs/daily.log 2>&1
```

## 调试

```bash
python3 scripts/daily_screen.py --max-stocks 50 --markets a
python3 scripts/daily_screen.py --skip-dedup --top-n 5
```
