"""Streamlit page: query a live Cursor analysis prompt by stock code or name."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from stock_mining.web.clipboard_button import (
    COPY_BUTTON_IFRAME_HEIGHT,
    build_copy_prompt_html,
)
from stock_mining.web.prompt_query_service import (
    PromptQueryError,
    PromptQueryResult,
    query_live_prompt,
)

_RESULT_KEY = "prompt_query_result"
_ERROR_KEY = "prompt_query_error"
_COUNTER_KEY = "prompt_query_counter"


def _copy_prompt_button(text: str, *, element_key: str) -> None:
    st.iframe(
        build_copy_prompt_html(text, element_key=element_key),
        height=COPY_BUTTON_IFRAME_HEIGHT,
        width="stretch",
    )


def _render_result(result: PromptQueryResult, *, copy_seq: int) -> None:
    st.success(result.meta_line)
    st.caption("复制 Prompt 到 Cursor（Windows / iPhone 可用）")
    _copy_prompt_button(
        result.prompt,
        element_key=f"live-prompt-copy-{result.stock_key}-{copy_seq}",
    )
    st.download_button(
        "下载 Prompt (.txt)",
        data=result.prompt.encode("utf-8"),
        file_name=f"{result.stock_key.replace(':', '_')}_prompt.txt",
        mime="text/plain",
        key=f"live-prompt-dl-{result.stock_key}-{copy_seq}",
        use_container_width=True,
        on_click="ignore",
    )
    with st.expander("查看 / 手动复制 Prompt", expanded=False):
        st.text_area(
            "Prompt 文本",
            result.prompt,
            height=320,
            key=f"live-prompt-view-{result.stock_key}-{copy_seq}",
            label_visibility="collapsed",
        )
        st.caption("若一键复制无效：点开文本 → 长按全选复制（iPhone）或 Ctrl+A / Ctrl+C")


def _run_query(market: str, query: str) -> None:
    progress_box = st.status("查询中…", expanded=True)

    def _progress(message: str) -> None:
        progress_box.write(message)

    try:
        result = query_live_prompt(
            ROOT,
            market=market,
            query=query,
            progress=_progress,
        )
    except PromptQueryError as exc:
        progress_box.update(label="查询失败", state="error")
        st.session_state[_ERROR_KEY] = str(exc)
        st.session_state[_RESULT_KEY] = None
        return
    except Exception as exc:  # pragma: no cover - defensive UI path
        progress_box.update(label="查询失败", state="error")
        st.session_state[_ERROR_KEY] = f"未预期错误: {exc}"
        st.session_state[_RESULT_KEY] = None
        return

    progress_box.update(label="查询完成", state="complete")
    st.session_state[_ERROR_KEY] = None
    st.session_state[_RESULT_KEY] = result
    st.session_state[_COUNTER_KEY] = int(st.session_state.get(_COUNTER_KEY, 0)) + 1


def main() -> None:
    st.set_page_config(page_title="单股 Prompt 查询", layout="wide")
    st.title("单股 Prompt 查询")
    st.caption(
        "选择市场后输入股票代码或名称，生成与 "
        "`scripts/print_prompt.py` 相同的 Cursor 分析提示词。"
    )

    market = st.radio(
        "市场",
        options=["a", "h"],
        format_func=lambda m: "A股 (a)" if m == "a" else "港股 (h)",
        horizontal=True,
        key="prompt_query_market",
    )
    query = st.text_input(
        "股票代码或名称",
        placeholder="例如 600519 / 贵州茅台，或 00700 / 腾讯控股",
        key="prompt_query_input",
    )

    cols = st.columns([1, 1, 4])
    with cols[0]:
        submitted = st.button("查询", type="primary", use_container_width=True)
    with cols[1]:
        if st.button("清空结果", use_container_width=True):
            st.session_state[_RESULT_KEY] = None
            st.session_state[_ERROR_KEY] = None

    if submitted:
        _run_query(market, query)

    error = st.session_state.get(_ERROR_KEY)
    if error:
        st.error(error)

    result = st.session_state.get(_RESULT_KEY)
    if isinstance(result, PromptQueryResult):
        st.divider()
        _render_result(result, copy_seq=int(st.session_state.get(_COUNTER_KEY, 1)))
        if result.progress_log:
            with st.expander("本次查询步骤", expanded=False):
                for line in result.progress_log:
                    st.write(f"- {line}")
    else:
        st.info("输入代码或名称后点击「查询」。可反复查询不同股票。")


if __name__ == "__main__":
    main()
