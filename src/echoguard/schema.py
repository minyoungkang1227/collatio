"""모델 패널의 입출력 형식. 모델 응답은 이 형식으로만 받는다."""

from typing import Literal

from pydantic import BaseModel, Field

Perturbation = Literal["original", "paraphrase", "fact_flip", "ai_style", "source_swap", "fake_corroboration"]


class InstitutionalOutput(BaseModel):
    """기관 트랙: 뉴스 → 사건 강도와 방향."""

    intensity: int = Field(ge=1, le=5)
    direction: Literal[-1, 0, 1]


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
