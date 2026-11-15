"""저장층: 응답 기록을 파일에 쌓고, 측정 엔진이 쓰는 배열로 바꾼다.

지표는 항상 저장된 기록에서 다시 계산한다. 그래야 같은 기록에서 같은 숫자가 나온다.
"""

from pathlib import Path

import numpy as np

from .schema import Perturbation, RunRecord


def save(records: list[RunRecord], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(r.model_dump_json() + "\n")


def key(r: RunRecord) -> tuple[str, str, str, int]:
    """기록 하나를 가리키는 이름. 이어서 실행할 때 이미 받은 응답인지 판단하는 데 쓴다."""
    return (r.model, r.item_id, r.perturbation, r.run)


def load(path: str | Path) -> list[RunRecord]:
    with open(path, encoding="utf-8") as f:
        return [RunRecord.model_validate_json(line) for line in f if line.strip()]


def to_array(
    records: list[RunRecord],
    field: str,
    perturbation: Perturbation,
    models: list[str],
    item_ids: list[str],
    n_runs: int,
) -> np.ndarray:
    """기록을 (모델, 뉴스, 반복) 배열로 바꾼다. 실패했거나 없는 칸은 NaN이다."""
    m_index = {m: i for i, m in enumerate(models)}
    i_index = {it: i for i, it in enumerate(item_ids)}
    arr = np.full((len(models), len(item_ids), n_runs), np.nan)
    for r in records:
        if r.perturbation != perturbation or r.model not in m_index or r.item_id not in i_index:
            continue
        if r.output is not None:
            arr[m_index[r.model], i_index[r.item_id], r.run] = getattr(r.output, field)
    return arr
