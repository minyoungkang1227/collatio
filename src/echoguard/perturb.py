"""변형층: 뉴스 한 건에서 모델에 넣을 입력 여러 개를 만든다.

규칙으로 만들 수 있는 것(original, source_swap)은 여기서 만든다.
사람이나 패널 밖 LLM이 쓰는 것(paraphrase, ai_style, fact_flip)은
미리 써 둔 글을 받아서 붙이기만 한다.
"""

from pydantic import BaseModel

from .dataset import NewsItem
from .schema import Perturbation

VERIFIED_TAG = "[출처: 금융감독원 전자공시·정부 발표]"
UNVERIFIED_TAG = "[출처: 익명 투자 커뮤니티 게시글]"


class PanelInput(BaseModel):
    """모델에 들어가는 입력 하나. 정답은 여기에 싣지 않는다."""

    item_id: str
    perturbation: Perturbation
    text: str


def _tagged(item: NewsItem, verified: bool, body: str | None = None) -> str:
    return f"{VERIFIED_TAG if verified else UNVERIFIED_TAG}\n{body or item.summary}"


def build_inputs(
    items: list[NewsItem],
    written: dict[tuple[str, Perturbation], str] | None = None,
) -> list[PanelInput]:
    """뉴스마다 original과 source_swap을 만들고, 미리 써 둔 변형이 있으면 함께 넣는다.

    written의 키는 (item_id, 변형 이름), 값은 변형된 본문이다.
    """
    written = written or {}
    inputs = []
    for it in items:
        inputs.append(PanelInput(item_id=it.item_id, perturbation="original", text=_tagged(it, it.source_verified)))
        inputs.append(
            PanelInput(item_id=it.item_id, perturbation="source_swap", text=_tagged(it, not it.source_verified))
        )
        for kind in ("paraphrase", "ai_style", "fact_flip"):
            body = written.get((it.item_id, kind))
            if body:
                inputs.append(
                    PanelInput(item_id=it.item_id, perturbation=kind, text=_tagged(it, it.source_verified, body))
                )
    return inputs
