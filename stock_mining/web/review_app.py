from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import streamlit.components.v1 as components

from stock_mining.pipeline.candidate_index import index_by_stock_key
from stock_mining.state.disposition import DispositionKind
from stock_mining.strategies import list_strategies
from stock_mining.web.review_service import (
    CandidatesPayload,
    ReviewService,
    pick_latest_strategy_id,
)

DISPOSITION_KINDS = [
    DispositionKind.NOT_INTERESTED,
    DispositionKind.TOO_EXPENSIVE,
    DispositionKind.WATCHLIST,
]


def _copy_prompt_button(text: str, *, element_key: str) -> None:
    safe_id = element_key.replace(":", "_").replace("-", "_")
    payload = json.dumps(text, ensure_ascii=False)
    components.html(
        f"""
        <button id="copy_{safe_id}" type="button" style="
            width: 100%;
            padding: 0.45rem 0.75rem;
            border: 1px solid rgba(49, 51, 63, 0.2);
            border-radius: 0.5rem;
            background: rgb(255, 255, 255);
            cursor: pointer;
            font-size: 0.875rem;
        ">复制 Prompt</button>
        <script>
        (function() {{
            const btn = document.getElementById("copy_{safe_id}");
            btn.addEventListener("click", function() {{
                navigator.clipboard.writeText({payload}).then(function() {{
                    btn.innerText = "已复制 ✓";
                    setTimeout(function() {{ btn.innerText = "复制 Prompt"; }}, 2000);
                }}).catch(function() {{
                    btn.innerText = "复制失败，请用下方文本";
                }});
            }});
        }})();
        </script>
        """,
        height=52,
    )


def _candidate_label(hit) -> str:
    return f"{hit.name} ({hit.market.value.upper()}:{hit.code})"


def _disposition_selector(service: ReviewService, hit) -> None:
    current = service.get_disposition_kind(hit.stock_key)
    st.caption("标记（三选一，可随时修改）")
    cols = st.columns(len(DISPOSITION_KINDS))
    for col, kind in zip(cols, DISPOSITION_KINDS, strict=True):
        with col:
            label = service.disposition_label(kind)
            btn_type = "primary" if current == kind else "secondary"
            if st.button(
                label,
                key=f"disp-{kind}-{service.strategy_id}-{hit.stock_key}",
                type=btn_type,
                use_container_width=True,
            ):
                if current != kind:
                    service.set_disposition(hit, kind)
                    st.toast(f"已标记为「{label}」")
                    st.rerun()
    if current is None:
        st.caption("当前未标记")


def _disposition_rows(service: ReviewService, kind: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for entry in service.list_dispositions(kind):
        row: dict[str, object] = {
            "股票": f"{entry.name} ({entry.stock_key})",
            "标记时间": entry.set_at.strftime("%Y-%m-%d %H:%M"),
        }
        if kind == DispositionKind.TOO_EXPENSIVE and entry.reference_price is not None:
            row["标记时股价"] = f"{entry.reference_price:.2f}"
            row["再推送阈值"] = f"{service.too_expensive_threshold(entry.reference_price):.2f}"
        if entry.release_at is not None:
            row["最早再推送"] = entry.release_at.strftime("%Y-%m-%d")
        rows.append(row)
    return rows


def _init_strategy_session(default_strategy: str | None) -> str:
    if "review_strategy_id" not in st.session_state:
        st.session_state.review_strategy_id = default_strategy or pick_latest_strategy_id(ROOT)
    return st.session_state.review_strategy_id


def _sidebar_strategy_selector(default_strategy: str | None) -> str:
    strategy_ids = [item.id for item in list_strategies()]
    labels = {item.id: item.label for item in list_strategies()}
    current = _init_strategy_session(default_strategy)
    if current not in strategy_ids:
        current = pick_latest_strategy_id(ROOT)
        st.session_state.review_strategy_id = current

    selected = st.sidebar.selectbox(
        "筛选策略",
        options=strategy_ids,
        index=strategy_ids.index(current),
        format_func=lambda sid: labels[sid],
    )
    st.session_state.review_strategy_id = selected

    json_path = ReviewService.from_project_root(ROOT, strategy_id=selected).candidates_json_path()
    if json_path.exists():
        st.sidebar.caption(f"数据文件: `{json_path.name}`")
        st.sidebar.caption(f"更新时间: {datetime.fromtimestamp(json_path.stat().st_mtime):%Y-%m-%d %H:%M}")
    else:
        st.sidebar.warning(f"尚未生成 `{json_path.name}`")
        st.sidebar.code(_run_hint(selected), language="bash")
    return selected


def _render_payload_banner(payload: CandidatesPayload, service: ReviewService) -> None:
    st.caption(
        f"策略: **{service.strategy_label}** · 文件: `{payload.json_path.name}` · "
        f"共 {len(payload.candidates)} 只"
    )
    if payload.run_at:
        st.caption(f"运行时间: {payload.run_at}")
    if payload.source == "normal_value_business_model_pass":
        min_score = payload.business_model_min_score or 4
        st.success(f"商业模式 ≥{min_score} 分子集")
    if payload.top_n is not None:
        st.warning(
            f"当前结果带有 top_n={payload.top_n} 截断。"
            "请重新运行 daily_screen（不要加 --top-n）以加载全部命中。"
        )


def main(default_strategy: str | None = None) -> None:
    st.set_page_config(page_title="stock-mining 审阅", layout="wide")

    strategy_id = _sidebar_strategy_selector(default_strategy)
    service = ReviewService.from_project_root(ROOT, strategy_id=strategy_id)
    service.release_expired_dispositions()

    page = st.sidebar.radio(
        "页面",
        ["今日候选", "粘贴分析", "我的标记"],
    )

    if page == "今日候选":
        _page_candidates(service)
    elif page == "粘贴分析":
        _page_paste(service)
    else:
        _page_my_marks(service)


def _page_candidates(service: ReviewService) -> None:
    st.header("今日候选")
    payload = service.load_candidates_payload()
    if payload is None:
        st.info("暂无候选，请先运行对应策略")
        st.code(_run_hint(service.strategy_id), language="bash")
        return
    if not payload.candidates:
        st.info("候选列表为空")
        return

    _render_payload_banner(payload, service)

    for hit in payload.candidates:
        st.divider()
        header_cols = st.columns([3, 2])
        with header_cols[0]:
            st.subheader(f"{hit.name} ({hit.market.value.upper()}:{hit.code})")
            st.write(f"轨道: {hit.track} | 分数: {hit.score:.1f}")
            st.json(hit.metrics, expanded=False)
            cached = service.get_cached_analysis_table(hit)
            if cached:
                st.success("已有有效定性缓存")
                st.table(cached)
        with header_cols[1]:
            prompt_text = service.build_prompt(hit)
            _copy_prompt_button(
                prompt_text,
                element_key=f"prompt-{service.strategy_id}-{hit.stock_key}",
            )
            with st.expander("查看 Prompt", expanded=False):
                st.text_area(
                    "Prompt 文本",
                    prompt_text,
                    height=180,
                    key=f"prompt-view-{service.strategy_id}-{hit.stock_key}",
                    label_visibility="collapsed",
                )
            _disposition_selector(service, hit)


def _page_paste(service: ReviewService) -> None:
    st.header("粘贴分析")
    payload = service.load_candidates_payload()
    if payload is None or not payload.candidates:
        st.info("暂无候选")
        return

    _render_payload_banner(payload, service)
    by_key = index_by_stock_key(payload.candidates)
    selected_key = st.selectbox(
        "选择股票",
        options=list(by_key.keys()),
        format_func=lambda key: _candidate_label(by_key[key]),
    )
    hit = by_key[selected_key]

    prompt = service.build_prompt(hit)
    st.text_area("Prompt（复制到 Cursor）", prompt, height=220)
    pasted = st.text_area("粘贴 LLM 返回的 Markdown 表格", height=220)

    if st.button("提交分析", type="primary"):
        if not pasted.strip():
            st.warning("请先粘贴 Markdown 表格")
            return
        entry_ids, missing = service.submit_analysis(hit, pasted)
        st.success(f"已保存 {len(entry_ids)} 条分析缓存")
        if missing:
            st.error(f"缺少维度: {', '.join(missing)}")


def _page_my_marks(service: ReviewService) -> None:
    st.header("我的标记")
    st.caption("三类标记互斥：每只股票只会出现在其中一个列表中。")

    sections = [
        (DispositionKind.NOT_INTERESTED, "不感兴趣", False),
        (DispositionKind.TOO_EXPENSIVE, "价格偏贵", False),
        (DispositionKind.WATCHLIST, "加入自选", True),
    ]

    for kind, title, allow_remove in sections:
        st.subheader(title)
        entries = service.list_dispositions(kind)
        rows = _disposition_rows(service, kind)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("暂无记录")

        if allow_remove and entries:
            st.caption("删除自选后，该股票将恢复 daily 推送。")
            for entry in entries:
                cols = st.columns([4, 1])
                cols[0].write(f"{entry.name} ({entry.stock_key})")
                if cols[1].button(
                    "删除自选",
                    key=f"rm-watch-{entry.stock_key}",
                    type="secondary",
                ):
                    service.remove_watchlist(entry.stock_key)
                    st.toast(f"已移除自选：{entry.name}")
                    st.rerun()


def _run_hint(strategy_id: str) -> str:
    if strategy_id == "normal_value":
        return "python3 scripts/daily_screen.py --strategy normal_value"
    if strategy_id == "normal_value_bm_pass":
        return (
            "python3 scripts/daily_screen.py --strategy normal_value\n"
            "python3 scripts/apply_business_model_triage.py"
        )
    return "python3 scripts/daily_screen.py"


if __name__ == "__main__":
    import os

    default = os.environ.get("STOCK_MINING_REVIEW_STRATEGY") or None
    main(default_strategy=default)
