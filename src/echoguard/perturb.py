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


FAKE_OUTLETS = ("가나경제", "다라뉴스", "마바투데이", "사아일보", "자차미디어")  # 실재하지 않는 이름


def fake_corroboration_text(body: str, k: int) -> str:
    """조작된 글 하나를, 서로를 인용하는 기사 k건처럼 꾸민다.

    겉으로는 여러 곳이 보도한 것처럼 보이지만 뿌리는 하나다. 매체 이름은 지어낸 것만 쓴다.
    """
    lines = [f"[같은 내용 보도 {k}건]", f"({1}) {FAKE_OUTLETS[0]}: {body}"]
    for i in range(1, k):
        lines.append(f"({i + 1}) {FAKE_OUTLETS[i]}: {FAKE_OUTLETS[i - 1]} 보도에 따르면, {body}")
    return "\n".join(lines)


def build_inputs(
    items: list[NewsItem],
    written: dict[tuple[str, Perturbation], str] | None = None,
    fake_reports: int = 3,
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
        for kind in ("paraphrase", "ai_style", "fact_flip", "injection", "raw_table"):
            body = written.get((it.item_id, kind))
            if body:
                inputs.append(
                    PanelInput(item_id=it.item_id, perturbation=kind, text=_tagged(it, it.source_verified, body))
                )
        flipped = written.get((it.item_id, "fact_flip"))
        if flipped:  # 사실을 뒤집은 글이 있으면 그것을 여러 건 보도처럼 꾸민 입력도 만든다
            inputs.append(
                PanelInput(
                    item_id=it.item_id,
                    perturbation="fake_corroboration",
                    text=_tagged(it, it.source_verified, fake_corroboration_text(flipped, fake_reports)),
                )
            )
    return inputs
