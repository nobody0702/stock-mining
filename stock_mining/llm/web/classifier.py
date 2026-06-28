from __future__ import annotations

from stock_mining.llm.web.models import ClassifiedNotice, NoticeItem

# (tag_label, keywords) — first match wins
_NOTICE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("监管/处罚", ("立案", "处罚", "警示", "违规", "问询函", "监管函", "纪律处分")),
    ("回购/分红", ("回购", "分红", "派息", "利润分配", "权益分派", "分配方案")),
    ("关联交易", ("关联交易", "对外担保", "资金占用")),
    ("激励/薪酬", ("股权激励", "薪酬", "考核", "管理办法", "激励计划")),
    ("管理层变动", ("高管", "董事", "聘任", "辞职", "离职", "监事", "总裁", "董秘")),
    ("质押/冻结", ("质押", "冻结", "解押")),
    ("业绩披露", ("年报", "半年报", "季报", "业绩预告", "业绩说明会")),
)


def classify_notices(
    notices: list[NoticeItem],
    *,
    limit_per_tag: int = 3,
) -> list[ClassifiedNotice]:
    buckets: dict[str, list[ClassifiedNotice]] = {}
    for item in notices:
        text = f"{item.category} {item.title}"
        tag = _match_tag(text)
        if tag is None:
            continue
        bucket = buckets.setdefault(tag, [])
        if len(bucket) >= limit_per_tag:
            continue
        bucket.append(ClassifiedNotice(tag=tag, date=item.date, title=item.title))

    ordered: list[ClassifiedNotice] = []
    for tag, _keywords in _NOTICE_RULES:
        ordered.extend(buckets.get(tag, []))
    return ordered


def _match_tag(text: str) -> str | None:
    for tag, keywords in _NOTICE_RULES:
        if any(keyword in text for keyword in keywords):
            return tag
    return None
