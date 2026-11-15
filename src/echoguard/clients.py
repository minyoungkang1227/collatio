"""실제 모델 클라이언트: Anthropic, OpenAI, Google.

API 키는 코드나 설정 파일에 적지 않는다. 각 회사 라이브러리가 환경변수에서 읽는다.
    ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY

온도 등 생성 설정은 건드리지 않는다. 각 모델의 기본값 그대로 잰다(experiment_spec.md 4장).
"""

import time

from .panel import Completion
from .perturb import PanelInput

ATTEMPTS = 4  # 네트워크 오류나 속도 제한에 걸렸을 때 다시 시도하는 횟수


class _Base:
    def __init__(self, name: str, family: str, model_id: str):
        self.name, self.family, self.model_id = name, family, model_id
        self._sdk = None

    def complete(self, system: str, inp: PanelInput, run: int) -> Completion:
        if self._sdk is None:
            self._sdk = self._connect()  # 키가 없으면 여기서 바로 멈춘다. 재시도 대상이 아니다
        for attempt in range(ATTEMPTS):
            try:
                return self._call(system, inp.text)
            except Exception:
                if attempt == ATTEMPTS - 1:
                    raise
                time.sleep(2 ** (attempt + 1))  # 2, 4, 8초
        raise AssertionError("unreachable")

    def _connect(self):
        raise NotImplementedError

    def _call(self, system: str, text: str) -> Completion:
        raise NotImplementedError


class AnthropicClient(_Base):
    def _connect(self):
        import anthropic

        return anthropic.Anthropic()

    def _call(self, system: str, text: str) -> Completion:
        r = self._sdk.messages.create(
            model=self.model_id,
            max_tokens=4000,  # 생각 토큰까지 포함한 상한
            system=system,
            messages=[{"role": "user", "content": text}],
        )
        answer = "".join(block.text for block in r.content if block.type == "text")
        return Completion(answer, r.usage.input_tokens, r.usage.output_tokens, r.model)


class OpenAIClient(_Base):
    def _connect(self):
        import openai

        return openai.OpenAI()

    def _call(self, system: str, text: str) -> Completion:
        r = self._sdk.responses.create(model=self.model_id, instructions=system, input=text)
        return Completion(r.output_text, r.usage.input_tokens, r.usage.output_tokens, r.model)


class GoogleClient(_Base):
    def _connect(self):
        from google import genai

        return genai.Client()

    def _call(self, system: str, text: str) -> Completion:
        from google.genai import types

        r = self._sdk.models.generate_content(
            model=self.model_id,
            contents=text,
            config=types.GenerateContentConfig(system_instruction=system),
        )
        u = r.usage_metadata
        out = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)  # 생각 토큰도 출력으로 과금된다
        return Completion(r.text or "", u.prompt_token_count or 0, out, r.model_version or self.model_id)


PROVIDERS = {"anthropic": AnthropicClient, "openai": OpenAIClient, "google": GoogleClient}


def build_clients(models: list[dict]) -> list[_Base]:
    """설정 파일의 panel.models 목록으로 클라이언트를 만든다. 이 시점에는 네트워크를 쓰지 않는다."""
    return [PROVIDERS[m["provider"]](m["name"], m["provider"], m["model_id"]) for m in models]


def cost_usd(model: dict, input_tokens: int, output_tokens: int) -> float:
    """토큰 수를 달러로 바꾼다. 단가는 설정 파일의 100만 토큰당 가격이다."""
    return (input_tokens * model["usd_in"] + output_tokens * model["usd_out"]) / 1_000_000
