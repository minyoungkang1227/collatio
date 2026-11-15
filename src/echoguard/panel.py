"""패널층: 여러 모델을 같은 입력으로 반복 호출하고 응답을 기록한다.

모델 회사마다 호출 방법이 다르므로, 각 모델은 ModelClient 모양만 맞추면 된다.
이 층은 응답을 해석하지 않는다. 형식 검사만 하고 그대로 저장한다.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from pydantic import ValidationError

from .perturb import PanelInput
from .schema import InstitutionalOutput, RunRecord

MAX_RETRIES = 2


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model_version: str = ""


class ModelClient(Protocol):
    name: str      # 패널 안에서의 이름
    family: str    # 개발사. 같은 회사 모델끼리 더 겹치는지(H2) 볼 때 쓴다

    def complete(self, system: str, inp: PanelInput, run: int) -> Completion: ...


def extract_json(text: str) -> str:
    """응답에서 JSON 객체 부분만 꺼낸다.

    모델이 ```json 울타리를 치거나 앞뒤에 한마디 붙이는 것은 형식 위반으로 치지 않는다.
    중괄호가 없으면 원문을 그대로 돌려주고, 그러면 뒤의 형식 검사에서 걸린다.
    """
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else text


def call_once(client: ModelClient, system: str, inp: PanelInput, run: int, data_version: str) -> RunRecord:
    """한 번 호출한다. 형식이 틀리면 MAX_RETRIES번까지 다시 묻고, 그래도 안 되면 실패로 남긴다."""
    output, tokens_in, tokens_out, last = None, 0, 0, Completion("")
    for _ in range(1 + MAX_RETRIES):
        last = client.complete(system, inp, run)
        tokens_in += last.input_tokens
        tokens_out += last.output_tokens
        try:
            output = InstitutionalOutput.model_validate_json(extract_json(last.text))
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
        model_version=last.model_version,
        called_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        raw=last.text,
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
