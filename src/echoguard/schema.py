"""모델 패널의 입출력 형식. 모델 응답은 이 형식으로만 받는다."""

from typing import Literal

from pydantic import BaseModel, Field

Perturbation = Literal["original", "paraphrase", "fact_flip", "ai_style"]


class InstitutionalOutput(BaseModel):
    """기관 트랙: 뉴스 → 사건 강도와 방향."""

    intensity: int = Field(ge=1, le=5)
    direction: Literal[-1, 0, 1]


class RetailOutput(BaseModel):
    """개인 트랙: 투자 질문 → 행동과 확신."""

    action: Literal[-1, 0, 1]  # -1 매도, 0 보유, 1 매수
    confidence: int = Field(ge=1, le=5)


class RunRecord(BaseModel):
    """모델 호출 한 번의 기록. data/runs/에 JSONL로 쌓는다."""

    item_id: str
    perturbation: Perturbation
    model: str
    run: int
    track: Literal["institutional", "retail"]
    output: InstitutionalOutput | RetailOutput
    data_version: str
