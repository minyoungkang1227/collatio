"""가짜 세계: API 없이 전체 흐름을 돌려 보기 위한 모의 뉴스와 모의 모델.

여기서 나오는 숫자는 아무 의미가 없다. 층과 층이 맞물리는지만 확인한다.
모의 모델에는 일부러 '함께 틀리는' 성질을 심어 두어, 측정 엔진이 그것을 찾아내는지 본다.
"""

import json
import random

from .dataset import NewsItem
from .perturb import PanelInput

FAMILIES = {"a-large": "A", "a-small": "A", "b-large": "B", "b-small": "B", "c-one": "C"}


class MockClient:
    def __init__(self, name: str, beliefs: dict, noise: float, fail_rate: float, seed: int):
        self.name, self.family, self.version = name, FAMILIES[name], "mock-0"
        self._beliefs, self._noise, self._fail, self._seed = beliefs, noise, fail_rate, seed

    def complete(self, system: str, inp: PanelInput, run: int) -> str:
        rng = random.Random(f"{self._seed}|{self.name}|{inp.item_id}|{inp.perturbation}|{run}")
        if rng.random() < self._fail:
            return "죄송하지만 투자 판단은 도와드리기 어렵습니다."  # 형식 위반
        intensity, direction = self._beliefs[(inp.item_id, inp.perturbation)]
        if rng.random() < self._noise:
            direction = rng.choice([-1, 0, 1])
        return json.dumps({"intensity": intensity, "direction": direction})


def make_world(seed: int = 0, n_items: int = 100):
    """모의 뉴스, 미리 써 둔 변형, 모의 모델 다섯 개를 만든다."""
    rng = random.Random(seed)
    items = [
        NewsItem(
            item_id=f"n{i:03d}",
            date="2026-11-01",
            type="stock" if i % 10 < 7 else "macro",
            source="mock",
            url="https://example.com",
            title=f"모의 뉴스 {i}",
            summary=f"모의 뉴스 {i}의 요약.",
            intensity_true=rng.randint(1, 5),
            direction_text=rng.choice([-1, 0, 1]),
            difficulty="ambiguous" if rng.random() < 0.2 else "clear",
            label_basis="mock",
            source_verified=rng.random() < 0.7,
            labeler="mock",
        )
        for i in range(n_items)
    ]
    written = {(it.item_id, kind): f"{it.summary} ({kind})" for it in items for kind in ("paraphrase", "ai_style", "fact_flip")}
    kinds = ("original", "source_swap", "paraphrase", "ai_style", "fact_flip")

    def wrong_of(d: int) -> int:
        return 1 if d <= 0 else -1

    # 모두가 함께 틀리는 뉴스: 출처가 확인되지 않은 뉴스에서 세 배 자주 생긴다
    weights = [1 if it.source_verified else 3 for it in items]
    shared = {it.item_id for it in rng.choices(items, weights=weights, k=n_items // 6)}
    # 문체가 바뀌면 다 같이 뒤집히는 뉴스
    fragile = {it.item_id for it in rng.sample(items, n_items // 8)}
    family_wrong = {fam: {it.item_id for it in rng.sample(items, n_items // 10)} for fam in "ABC"}

    clients = []
    for name, fam in FAMILIES.items():
        beliefs = {}
        for it in items:
            for kind in kinds:
                truth = -it.direction_text if kind == "fact_flip" else it.direction_text
                d = truth
                if it.item_id in shared or it.item_id in family_wrong[fam]:
                    d = wrong_of(truth)
                if it.item_id in fragile and kind in ("paraphrase", "ai_style"):
                    d = wrong_of(d)
                beliefs[(it.item_id, kind)] = (it.intensity_true, d)
        clients.append(MockClient(name, beliefs, noise=0.05, fail_rate=0.01, seed=seed))
    return items, written, clients
