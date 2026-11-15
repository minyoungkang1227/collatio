"""데이터층: 라벨 파일을 읽고 검증하고 설정용/평가용으로 나눈다."""

import csv
import random
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    item_id: str
    date: str
    type: Literal["stock", "macro"]
    source: str
    url: str
    title: str
    summary: str
    intensity_true: int = Field(ge=1, le=5)
    direction_text: Literal[-1, 0, 1]
    direction_realized: Literal[-1, 0, 1] | None = None
    difficulty: Literal["clear", "ambiguous"]
    label_basis: str = Field(min_length=1)
    source_verified: bool
    split: Literal["tune", "eval"] | None = None
    labeler: str


def load_labels(path: str | Path) -> list[NewsItem]:
    """라벨 CSV를 읽는다. 형식이 틀린 줄이 있으면 그 자리에서 멈춘다."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = [{k: (v if v != "" else None) for k, v in row.items()} for row in csv.DictReader(f)]
    items = [NewsItem.model_validate(row) for row in rows]
    ids = [it.item_id for it in items]
    if len(ids) != len(set(ids)):
        raise ValueError("item_id가 중복됩니다")
    return items


def assign_split(items: list[NewsItem], n_tune: int, seed: int) -> list[NewsItem]:
    """시드로 고정된 순서로 섞어 앞의 n_tune건을 설정용, 나머지를 평가용으로 표시한다."""
    order = sorted(it.item_id for it in items)
    random.Random(seed).shuffle(order)
    tune = set(order[:n_tune])
    return [it.model_copy(update={"split": "tune" if it.item_id in tune else "eval"}) for it in items]
