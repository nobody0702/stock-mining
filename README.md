# stock-mining

每日 A 股 + 港股通选股：量化筛「错杀的成长型白马」，Web 审阅 + Cursor 大模型定性分析。

> 数据来自 AkShare 公开接口，仅供研究，不构成投资建议。

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

## 一日工作流

```bash
# 1a. 错杀成长白马（默认 → candidates.json）
python3 scripts/daily_screen.py

# 1b. 正常估值不下滑（→ normal_value_candidates.json）
python3 scripts/daily_screen.py --strategy normal_value

# 1c. 港股通 · 错杀成长白马（→ hk_candidates.json）
python3 scripts/daily_screen.py --strategy mispriced_growth_hk

# 单股 prompt（港股示例）
python3 scripts/print_prompt.py 00700 --market hk -c config/screen_hk.yaml --meta

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
| 错杀成长白马 | `data/results/candidates.json` | `daily_screen.py` |
| 正常估值不下滑 | `data/results/normal_value_candidates.json` | `daily_screen.py --strategy normal_value` |
| 正常估值·商业模式≥4 | `data/results/normal_value_review.json` | `apply_business_model_triage.py` |
| 港股·错杀成长白马 | `data/results/hk_candidates.json` | `daily_screen.py --strategy mispriced_growth_hk` |

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

## 测试

```bash
pytest -q
```

## 定时任务

```cron
30 18 * * 1-5 cd /path/to/stock-mining && .venv/bin/python3 scripts/daily_screen.py >> logs/daily.log 2>&1
```

## 调试

```bash
python3 scripts/daily_screen.py --max-stocks 50 --markets a
python3 scripts/daily_screen.py --skip-dedup --top-n 5
```
