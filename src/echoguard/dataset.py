"""데이터층: 라벨 파일을 읽고 검증하고 설정용/평가용으로 나눈다."""

import csv
import random
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
    n_independent_sources: int = Field(ge=0)  # 같은 사실을 따로 확인해 준 1차 출처·주요 매체 수
    n_reports: int = Field(ge=1, le=5)  # 같은 내용을 실은 글의 수. 받아쓴 글도 센다. 5건 이상은 5
    split: Literal["tune", "eval"] | None = None
    labeler: str

    @field_validator("direction_text", "direction_realized", mode="before")
    @classmethod
    def _direction_from_text(cls, v):
        """파일에서 읽은 "-1", "0", "1"을 숫자로 바꾼다. 그 밖의 값은 그대로 두어 검사에서 걸리게 한다."""
        return int(v) if isinstance(v, str) and v.strip() in ("-1", "0", "1") else v


def load_labels(path: str | Path) -> list[NewsItem]:
    """라벨 CSV를 읽는다. 형식이 틀린 줄이 있으면 그 자리에서 멈춘다."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = [{k: (v if v != "" else None) for k, v in row.items()} for row in csv.DictReader(f)]
    items = [NewsItem.model_validate(row) for row in rows]
    ids = [it.item_id for it in items]
    if len(ids) != len(set(ids)):
        raise ValueError("item_id가 중복됩니다")
    return items


def load_written(path: str | Path) -> dict[tuple[str, str], str]:
    """미리 써 둔 변형 글을 읽는다. 키는 (item_id, 변형 이름), 값은 본문."""
    if not Path(path).exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {(row["item_id"], row["perturbation"]): row["text"] for row in csv.DictReader(f) if row["text"]}


def assign_split(items: list[NewsItem], n_tune: int, seed: int) -> list[NewsItem]:
    """시드로 고정된 순서로 섞어 앞의 n_tune건을 설정용, 나머지를 평가용으로 표시한다."""
    order = sorted(it.item_id for it in items)
    random.Random(seed).shuffle(order)
    tune = set(order[:n_tune])
    return [it.model_copy(update={"split": "tune" if it.item_id in tune else "eval"}) for it in items]
