"""모델 변경 감지: 같은 글에 대한 예전 답과 지금 답을 비교한다.

    python -m echoguard.drift 예전응답.jsonl 지금응답.jsonl

외부 모델은 공급사가 예고 없이 바꿀 수 있다. 같은 이름의 모델이 어제와 다르게 답하면 그동안의 검증이 무효가 된다.
정해 둔 글 묶음을 주기적으로 다시 묻고 이 비교를 돌린다. 원문 입력의 방향 답만 본다.

모델이 바뀌지 않아도 답은 반복마다 조금 흔들린다. 그래서 반복의 대표 답(가장 많이 나온 답)끼리 비교한다.
바뀐 비율이 평소 흔들림보다 큰지는 같은 날 두 번 돌린 결과와 견주어 판단한다. 기준값은 아직 정하지 않았다.
"""

import json
import sys
from collections import Counter, defaultdict

from . import store
from .schema import RunRecord


def _by_model(records: list[RunRecord]) -> dict:
    answers, versions = defaultdict(lambda: defaultdict(list)), defaultdict(set)
    for r in records:
        if r.perturbation != "original":
            continue
        if r.model_version:
            versions[r.model].add(r.model_version)
        if r.output is not None:
            answers[r.model][r.item_id].append(r.output.direction)
    rep = {m: {i: min(d for d, c in Counter(v).items() if c == max(Counter(v).values())) for i, v in items.items()} for m, items in answers.items()}
    return {"answers": rep, "versions": versions}


def compare(old: list[RunRecord], new: list[RunRecord]) -> dict:
    a, b = _by_model(old), _by_model(new)
    report = {}
    for model in sorted(set(a["answers"]) & set(b["answers"])):
        shared = sorted(set(a["answers"][model]) & set(b["answers"][model]))
        changed = [i for i in shared if a["answers"][model][i] != b["answers"][model][i]]
        before, after = sorted(a["versions"][model]), sorted(b["versions"][model])
        report[model] = {
            "n_items_compared": len(shared),
            "share_changed": round(len(changed) / len(shared), 3) if shared else None,
            "changed_items": changed[:20],
            "version_before": before,
            "version_after": after,
            "version_changed": before != after,
        }
    return report


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(json.dumps(compare(store.load(sys.argv[1]), store.load(sys.argv[2])), ensure_ascii=False, indent=2))
