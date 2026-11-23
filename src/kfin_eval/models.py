"""모델 어댑터.

mock-*  API 없이 파이프라인을 점검하는 가짜 모델
eg:이름  EchoGuard 설정(config/experiment.yaml)의 패널 모델. 세 회사 호출·재시도 코드를 그대로 쓴다. eg:all 은 전부
claude-* Anthropic 직접 호출
"""
import hashlib

from . import bridges

SYSTEM = (
    "당신은 한국 금융 실무 문제에 답하는 전문가입니다. 풀이 과정을 간결히 쓰고, "
    "마지막 줄은 반드시 '최종답: ' 으로 시작하세요. 수치 문제는 문항이 요구한 단위의 "
    "숫자만, 객관식은 선택지 라벨만 적습니다. 서술형은 마지막 줄에 한 문장 요약을 적습니다."
)


def build_prompt(item):
    p = item["question"]
    if item["answer_type"] == "choice":
        p += "\n\n" + "\n".join(f"{k}. {v}" for k, v in item["choices"].items())
    return p


class MockModel:
    """mock-perfect: 모범답안 그대로 / mock-noisy: 수치 5% 오차, 서술 절반 / mock-blank: 무응답."""

    def __init__(self, name):
        self.name = name

    def complete(self, system, prompt):  # 채점자(judge)로는 쓸 수 없음
        raise NotImplementedError("mock 모델은 LLM 채점자로 쓸 수 없습니다")

    def answer(self, item):
        if self.name == "mock-blank":
            return "모르겠습니다."
        a, t = item["answer"], item["answer_type"]
        if self.name.startswith("mock-level"):
            # 난도 n단 이상부터 틀리는 가짜 모델. mock-level3 은 3·4단을 틀린다(난도 보정 점검용).
            trap = item.get("meta", {}).get("level", item.get("difficulty", 1)) >= int(self.name[-1])
            if trap and t == "choice":
                return f"최종답: {next(l for l in sorted(item['choices']) if l != a['value'])}"
            noisy = trap
        elif self.name.startswith("mock-herd"):
            # 무리 모델: 문항의 약 1/3에서 모두 같은 오답을 낸다(함께 틀리는 상황 흉내). 나머지는 정답.
            trap = int(hashlib.sha256(item["id"].encode()).hexdigest(), 16) % 3 == 0
            if trap and t == "choice":
                return f"최종답: {next(l for l in sorted(item['choices']) if l != a['value'])}"
            noisy = trap
        else:
            noisy = self.name == "mock-noisy"
        if t == "numeric":
            v = a["value"] * (1.05 if noisy else 1)
            return f"풀이 생략.\n최종답: {v:.10g}"
        if t == "choice":
            return f"최종답: {a['value']}"
        ref = a["reference"]
        if noisy:
            ref = ref[: len(ref) // 2]
        return f"{ref}\n최종답: 위 설명과 같습니다."


class AnthropicModel:
    """pip install anthropic, 환경변수 ANTHROPIC_API_KEY 필요."""

    def __init__(self, name, max_tokens=2000):
        import anthropic  # 실제 호출 때만 필요

        self.name, self.max_tokens = name, max_tokens
        self.client = anthropic.Anthropic()

    def complete(self, system, prompt):
        resp = self.client.messages.create(
            model=self.name, max_tokens=self.max_tokens, system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text")

    def answer(self, item):
        return self.complete(SYSTEM, build_prompt(item))


class EchoGuardModel:
    """EchoGuard의 모델 클라이언트를 감싼다. API 키는 각 회사 환경변수에서 읽는다."""

    def __init__(self, name):
        match = [m for m in bridges.echoguard_config()["panel"]["models"] if m["name"] == name]
        if not match:
            raise SystemExit(f"EchoGuard 설정에 없는 모델: {name}")
        self.name = name
        self._client = bridges.echoguard("clients").build_clients(match)[0]
        self._input = bridges.echoguard("perturb").PanelInput

    def complete(self, system, prompt):
        inp = self._input(item_id="kfin-eval", perturbation="original", text=prompt)
        return self._client.complete(system, inp, 0).text

    def answer(self, item):
        return self.complete(SYSTEM, build_prompt(item))


def family(name):
    """모델 계열. 'eg:claude-haiku' → 'claude', 'gpt-luna' → 'gpt'. 같은 회사 모델끼리 같은 값."""
    n = name.split(":", 1)[-1].lower()
    for fam, keys in (("claude", ("claude", "anthropic")), ("gpt", ("gpt", "openai", "o1", "o3", "o4")),
                      ("gemini", ("gemini", "google")), ("llama", ("llama", "meta")), ("qwen", ("qwen",))):
        if n.startswith(keys):
            return fam
    return n.split("-")[0]


def judge_conflicts(judge, models):
    """채점 모델과 같은 계열인 피평가 모델 목록.

    채점 모델은 자신과 관련된 모델(같은 모델, 같은 계열, 그 모델의 출력으로 학습한 모델)의 답에 점수를 더 주는 편향이 보고돼 있다
    (Li 외, "Preference Leakage: A Contamination Problem in LLM-as-a-judge", ICLR 2026).
    여기서는 이름으로 알 수 있는 '같은 회사 계열'만 잡는다. 학습 데이터로 이어진 관계는 이름만으로는 알 수 없다."""
    if not judge:
        return []
    f = family(judge)
    return sorted({m for m in models if family(m) == f})


def expand(spec):
    """'eg:all,mock-perfect' → 모델 이름 목록."""
    names = []
    for n in (x.strip() for x in spec.split(",") if x.strip()):
        names += [f"eg:{m['name']}" for m in bridges.echoguard_config()["panel"]["models"]] if n == "eg:all" else [n]
    return names


def get_model(name):
    if name.startswith("mock-"):
        return MockModel(name)
    if name.startswith("eg:"):
        return EchoGuardModel(name[3:])
    if name.startswith("claude"):
        return AnthropicModel(name)
    # 다른 회사 모델은 answer(item) / complete(system, prompt)를 가진 클래스를 추가하면 된다.
    raise SystemExit(f"지원하지 않는 모델: {name}")
