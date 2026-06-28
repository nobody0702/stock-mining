from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NoticeItem:
    date: str
    title: str
    category: str


@dataclass(frozen=True)
class SearchHit:
    query: str
    title: str
    snippet: str
    url: str


@dataclass(frozen=True)
class DividendRecord:
    date: str
    payout: str
    status: str


@dataclass(frozen=True)
class RepurchaseRecord:
    announce_date: str
    status: str
    amount_range: str
    repurchased_amount: str


@dataclass(frozen=True)
class PledgeSummary:
    ratio_pct: str
    detail: str


@dataclass(frozen=True)
class ClassifiedNotice:
    tag: str
    date: str
    title: str
