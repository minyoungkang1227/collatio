"""모델 패널의 입출력 형식. 모델 응답은 이 형식으로만 받는다."""

from typing import Literal

from pydantic import BaseModel, Field

Perturbation = Literal["original", "paraphrase", "fact_flip", "ai_style", "source_swap", "fake_corroboration"]


# 모델이 방향 판단의 근거로 고를 수 있는 지표. 지시문(prompts/institutional_system.txt)의 목록과 같아야 한다
BasisMetric = Literal[
    "영업이익_전년동기대비",
    "영업이익_전기대비",
    "매출_전년동기대비",
    "매출_전기대비",
    "순이익_전년동기대비",
    "누계영업이익_전년동기대비",
    "기타",
]
PRESCRIBED_METRIC = "영업이익_전년동기대비"  # 지시문이 실적 글의 방향 판단 기준으로 정한 지표


class InstitutionalOutput(BaseModel):
    """기관 트랙: 뉴스 → 사건 강도와 방향, 그리고 방향을 정한 근거.

    근거 두 칸은 data_version 0.3부터 받는다. 그 전 기록에는 없으므로 비어 있어도 형식 위반이 아니다.
    """

    intensity: int = Field(ge=1, le=5)
    direction: Literal[-1, 0, 1]
    basis_metric: BasisMetric | None = None  # 어느 지표를 보고 방향을 정했는가
    basis_value: str | None = None           # 그 지표의 값. 글에 적힌 대로


class RetailOutput(BaseModel):
    """개인 트랙: 투자 질문 → 행동. 답을 피하는 것도 하나의 행동으로 기록한다."""

    action: Literal["sell", "hold", "buy", "abstain"]


class RunRecord(BaseModel):
    """모델 호출 한 번의 기록. data/runs/에 JSONL로 쌓는다."""

    item_id: str
    perturbation: Perturbation
    model: str
    run: int
    track: Literal["institutional", "retail"]
    output: InstitutionalOutput | RetailOutput | None  # None은 형식 위반으로 실패한 호출
    model_version: str
    called_at: str
    input_tokens: int = 0
    output_tokens: int = 0   # 모델의 '생각' 토큰 포함. 재요청이 있었으면 합계
    raw: str | None = None   # 마지막 응답 원문. 형식 위반의 원인을 나중에 보기 위해 남긴다
    data_version: str
