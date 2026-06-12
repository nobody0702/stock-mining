# stock-mining

每日 A 股选股：模块化筛选框架。规则写在 YAML，逻辑拆成独立 Filter，各模块有 unit test。

> 数据来自 AkShare 公开接口，仅供研究，不构成投资建议。

## 安装

```bash
git clone git@github.com:<你的用户名>/stock-mining.git
cd stock-mining
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 每日运行

```bash
python3 scripts/daily_screen.py
```

输出示例（仅代码和名称）：

```
688001	优质样本
600xxx	某某股份
已写入: data/results/daily_screen.csv
```

调试：

```bash
python3 scripts/daily_screen.py --max-stocks 50
python3 scripts/daily_screen.py --codes 600519 688001
```

## 当前规则（config/daily_screen.yaml）

| 条件 | 实现 |
|------|------|
| 52 周新低附近 | 现价 / 52 周最低 ≤ 1.05 |
| 非 ST | 名称不含 ST |
| 非持续衰退行业 | 所属行业 3 年板块收益 ≥ -15% |
| 排除银行/保险/白酒/铁路/交通/地产 | 行业关键词黑名单 |
| 过去 3 年毛利率>40% **或** 净利率>20% | 每年满足其一 |
| 过去 3 年经营现金流为正 | 每股经营现金流 > 0 |
| 股息率 > 2% | 行情字段 |
| 年盈利 ≥1 亿 → PE<20；<1 亿 → PB<2 或 PS<3 | 分档估值 |
| 资产负债率 < 40% | 最新年报 |

修改 `config/daily_screen.yaml` 的 `filters` 列表即可调整，无需改 Python。

## 架构

```
filters/     每个 Filter 独立、可单测
pipeline/    两阶段：先行情过滤，再拉财务
data/        AkShare 数据源 + SQLite 缓存
tests/       pytest 单元测试
```

## 测试

```bash
pytest -q
```

## 规则审计

逐条复核某只股票是否满足 YAML 中全部 filter（含数据缺失说明）：

```bash
python3 scripts/audit_screen.py --from-csv data/results/daily_screen.csv --limit 10
python3 scripts/audit_screen.py --codes 600519 000423
```

## 定时任务（cron 示例）

```cron
30 18 * * 1-5 cd /path/to/stock-mining && .venv/bin/python3 scripts/daily_screen.py >> logs/daily.log 2>&1
```

## 说明

- **数据源容错**：全量东财行情易断连，已改用 `stock_fhps_em`（股息）+ `stock_value_em`（估值/52周低）+ `stock_profile_cninfo`（行业）+ 同花顺财务摘要；带重试与 SQLite 缓存。
- **全市场较慢**：候选股每只约 3 次 API，建议先 `--max-stocks 50` 验证。
- 行业走势接口不可用时自动跳过（`skip_if_unavailable: true`）。
