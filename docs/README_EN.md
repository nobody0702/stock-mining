# stock-mining: a workbench for finding mispriced quality businesses

> **Investment philosophy**: inspired by the publicly shared ideas of long-term value investors such as Warren Buffett, Charlie Munger, Duan Yongping and Li Lu. The project focuses on business quality, durable growth, business models and margin of safety, and looks for high-quality companies that may have been mispriced by the market.
>
> **Purpose**: turn these ideas into a configurable, reviewable and shareable open-source workflow. The project first screens A-share and HK stocks with public data, then leaves room for human or LLM review of business models, moats and risks.
>
> This project is for education and research only. It is not investment advice. Public data providers may change or become unavailable.

## Quick start

```bash
git clone https://github.com/nobody0702/stock-mining.git
cd stock-mining
python3 -m venv .venv
source .venv/bin/activate                 # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# Run a small smoke check first
python scripts/daily_screen.py --strategy mispriced_growth --market a --codes a:600519 --skip-dedup

# Open the review UI at http://localhost:8501
python scripts/serve_review.py --host 127.0.0.1
```

For a single-stock Prompt lookup, run `python scripts/serve_prompt_query.py --host 127.0.0.1` (default port `8502`). On a server or LAN, use `--host 0.0.0.0` and choose a port with `--port`.

## Typical workflow

```bash
python scripts/daily_screen.py --strategy all --market all
python scripts/serve_review.py
```

The web workbench lets you switch strategies, filter candidates, copy/download prompts, paste Markdown analysis, and maintain mutually exclusive labels: watchlist, too expensive, or not interested. Generated results live in `data/results/`; local state lives in `data/state/` and should not be committed.

Available strategies include `mispriced_growth`, `normal_value`, `mispriced_growth_hk`, and `quality_roe_margin`. Prefix stock codes with the market (`a:600519`, `h:00700`) to avoid collisions.

## Configuration and extension points

- `config/screen*.yaml`: markets, filters, workers, outputs and state policy.
- `config/analysis_dimensions.yaml`: qualitative dimensions and cache TTLs.
- `stock_mining/filters/`: reusable YAML-driven filters.
- `stock_mining/markets/`: market and provider adapters.
- `.env.example`: copy to `.env` only when an LLM API key is needed; never commit secrets.

## Tests and contribution

```bash
pytest -q -m 'not network'
```

Please include the motivation, validation steps and whether network access is required in Issues and Pull Requests. Contributions to code, tests, documentation, data adapters and UI are welcome.

## Contact and community

Author: 370170920@qq.com

Contributors and members of the wider community are warmly invited to join and help make this project more standard, reusable and beginner-friendly.

## License

MIT License. See [LICENSE](../LICENSE).
