from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from stock_mining.models import CandidateHit
from stock_mining.web.review_service import ReviewService


def main() -> None:
    st.set_page_config(page_title="stock-mining 审阅", layout="wide")
    service = ReviewService.from_project_root(ROOT)
    service.release_expired_blacklist()

    page = st.sidebar.radio(
        "页面",
        ["今日候选", "粘贴分析", "待默许队列", "黑名单", "已研究"],
    )

    if page == "今日候选":
        _page_candidates(service)
    elif page == "粘贴分析":
        _page_paste(service)
    elif page == "待默许队列":
        _page_pending(service)
    elif page == "黑名单":
        _page_blacklist(service)
    else:
        _page_studied(service)


def _page_candidates(service: ReviewService) -> None:
    st.header("今日候选")
    candidates = service.load_candidates()
    if not candidates:
        st.info("暂无候选，请先运行 daily_screen.py")
        return

    for hit in candidates:
        cols = st.columns([3, 1, 1, 1])
        with cols[0]:
            st.subheader(f"{hit.name} ({hit.market.value.upper()}:{hit.code})")
            st.write(f"轨道: {hit.track} | 分数: {hit.score:.1f}")
            st.json(hit.metrics, expanded=False)
            cached = service.get_cached_analysis_table(hit)
            if cached:
                st.success("已有有效定性缓存")
                st.table(cached)
        with cols[1]:
            if st.button("复制 Prompt", key=f"prompt-{hit.stock_key}"):
                st.session_state["selected_hit"] = hit.to_dict()
                st.session_state["prompt_text"] = service.build_prompt(hit)
        with cols[2]:
            reason = st.text_input("黑名单原因", key=f"reason-{hit.stock_key}")
            if st.button("加入黑名单", key=f"black-{hit.stock_key}"):
                service.add_blacklist(hit, reason or "手动加入")
                st.warning("已加入黑名单")
        with cols[3]:
            if st.button("标记已研究", key=f"study-{hit.stock_key}"):
                service.mark_studied(hit)
                st.info("已标记，30天内不再推荐")


def _page_paste(service: ReviewService) -> None:
    st.header("粘贴分析")
    candidates = service.load_candidates()
    if not candidates:
        st.info("暂无候选")
        return

    labels = [f"{hit.name} ({hit.market.value}:{hit.code})" for hit in candidates]
    selected = st.selectbox("选择股票", labels)
    hit = candidates[labels.index(selected)]

    prompt = service.build_prompt(hit)
    st.text_area("Prompt（复制到 Cursor）", prompt, height=220)
    pasted = st.text_area("粘贴 LLM 返回的 Markdown 表格", height=220)

    if st.button("提交待默许"):
        entry_ids, missing = service.submit_analysis(hit, pasted)
        st.success(f"已提交 {len(entry_ids)} 条待默许记录")
        if missing:
            st.error(f"缺少维度: {', '.join(missing)}")


def _page_pending(service: ReviewService) -> None:
    st.header("待默许队列")
    pending = service.pending_analysis()
    if not pending:
        st.info("暂无待默许记录")
        return

    grouped: dict[str, list] = {}
    for entry in pending:
        grouped.setdefault(entry.stock_key, []).append(entry)

    for stock_key, entries in grouped.items():
        st.subheader(stock_key)
        for entry in entries:
            st.write(f"**{entry.dimension_id}**: {entry.content}")
            cols = st.columns(2)
            if cols[0].button("默许", key=f"approve-{entry.id}"):
                service.approve_analysis_entries([entry.id])
                st.rerun()
            if cols[1].button("驳回", key=f"reject-{entry.id}"):
                service.reject_analysis_entries([entry.id])
                st.rerun()


def _page_blacklist(service: ReviewService) -> None:
    st.header("黑名单")
    entries = service.blacklist_entries()
    if not entries:
        st.info("黑名单为空")
        return
    for entry in entries:
        st.write(
            f"{entry.name} ({entry.stock_key}) | 状态: {entry.status} | "
            f"释放: {entry.release_at.date()} | 原因: {entry.reason}"
        )


def _page_studied(service: ReviewService) -> None:
    st.header("已研究记录")
    entries = service.recommendation_entries()
    if not entries:
        st.info("暂无记录")
        return
    for entry in entries:
        cooldown = entry.cooldown_until.date() if entry.cooldown_until else "无"
        st.write(
            f"{entry.name} ({entry.stock_key}) | 推荐时间: {entry.recommended_at.date()} | "
            f"冷却至: {cooldown} | 状态: {entry.status}"
        )


if __name__ == "__main__":
    main()
