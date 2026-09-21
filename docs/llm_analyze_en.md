# LLM stock analysis CLI

This optional workflow uses a configured LLM provider to enrich a screened stock with qualitative analysis. It is separate from the quantitative screener, so the project still works without an API key.

## Configure

1. Copy `.env.example` to `.env` and set `JIQUER_API_KEY`. Never commit `.env` or API keys.
2. Review `config/llm.yaml` for model, timeout and web-context settings.

## Run

```bash
source .venv/bin/activate
python scripts/analyze_stock.py --probe
python scripts/analyze_stock.py 600519
python scripts/analyze_stock.py 600519 --web-search
python scripts/analyze_stock.py 600519 --web-search --thinking --show-reasoning
python scripts/analyze_stock.py 600519 --web-search --dry-run
```

`--web-search` collects public notices, dividends, buybacks, pledge information and search snippets before calling the model. A source failure is reported but does not stop the analysis. Use the Chinese guide in [llm_analyze.md](llm_analyze.md) for the full source and dimension table.

## Exit codes

- `0`: completed with all dimensions
- `1`: output exists but some dimensions are missing
- `2`: stock data or parsing failed
- `3`: authentication or API call failed

This tool is for research assistance only, not financial advice.
