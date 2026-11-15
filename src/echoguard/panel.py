"""패널층: 여러 모델을 같은 입력으로 반복 호출하고 응답을 기록한다.

모델 회사마다 호출 방법이 다르므로, 각 모델은 ModelClient 모양만 맞추면 된다.
이 층은 응답을 해석하지 않는다. 형식 검사만 하고 그대로 저장한다.
"""

from datetime import datetime, timezone
from typing import Protocol

from pydantic import ValidationError

from .perturb import PanelInput
from .schema import InstitutionalOutput, RunRecord

MAX_RETRIES = 2


class ModelClient(Protocol):
    name: str      # 패널 안에서의 이름
    family: str    # 개발사. 같은 회사 모델끼리 더 겹치는지(H2) 볼 때 쓴다
    version: str   # 실제 모델 버전 문자열

    def complete(self, system: str, inp: PanelInput, run: int) -> str:
        """응답 원문(JSON 문자열)을 돌려준다."""
        ...


def call_once(client: ModelClient, system: str, inp: PanelInput, run: int, data_version: str) -> RunRecord:
    """한 번 호출한다. 형식이 틀리면 MAX_RETRIES번까지 다시 묻고, 그래도 안 되면 실패로 남긴다."""
    output = None
    for _ in range(1 + MAX_RETRIES):
        try:
            output = InstitutionalOutput.model_validate_json(client.complete(system, inp, run))
            break
        except ValidationError:
            continue
    return RunRecord(
        item_id=inp.item_id,
        perturbation=inp.perturbation,
        model=client.name,
        run=run,
        track="institutional",
        output=output,
        data_version=data_version,
        model_version=client.version,
        called_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def run_panel(
    clients: list[ModelClient],
    inputs: list[PanelInput],
    system: str,
    n_runs: int,
    data_version: str,
) -> list[RunRecord]:
    return [
        call_once(client, system, inp, run, data_version)
        for client in clients
        for inp in inputs
        for run in range(n_runs)
    ]
