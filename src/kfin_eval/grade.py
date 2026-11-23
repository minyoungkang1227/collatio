"""채점. 수치·객관식은 자동, 서술형은 키워드(기본) 또는 LLM 채점자."""
import json
import re

FINAL_RE = re.compile(r"최종답\s*[:：]\s*(.+)")
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")   # 1.4673e+06 같은 표기도 읽는다


def final_answer(response):
    m = FINAL_RE.findall(response or "")
    return m[-1].strip() if m else ""


def grade_numeric(item, response):
    fa = final_answer(response).replace(",", "").replace("−", "-")
    m = NUM_RE.search(fa)
    if not m:
        return 0.0, "최종답에서 숫자를 찾지 못함"
    got, exp = float(m.group()), item["answer"]["value"]
    tol = item["answer"].get("rel_tol", 0.01)
    ok = abs(got - exp) <= tol * abs(exp) + 1e-12
    return (1.0 if ok else 0.0), f"응답 {got} / 정답 {exp} (허용 ±{tol:.1%})"


def grade_choice(item, response):
    fa = final_answer(response)
    labels = sorted(item["choices"], key=len, reverse=True)
    got = next((l for l in labels if fa.upper().startswith(l.upper())), None)
    return (1.0 if got == item["answer"]["value"] else 0.0), f"응답 {got} / 정답 {item['answer']['value']}"


def grade_rubric_keywords(item, response):
    """기준별로 키워드가 하나라도 나오면 배점 인정. 싸고 재현 가능하지만 거칠다."""
    text, pts, detail = response or "", 0, []
    for c in item["rubric"]:
        hit = any(k in text for k in c.get("keywords", []))
        pts += c["points"] if hit else 0
        detail.append(f"{'O' if hit else 'X'} {c['criterion']}")
    return pts / 100, "; ".join(detail)


JUDGE_SYSTEM = (
    "당신은 한국 금융 실무 답안의 채점자입니다. 채점 기준별로 부여 점수를 정하고, "
    "기준 순서대로 점수만 담은 JSON 배열 하나만 출력하세요. 예: [20, 0, 10]"
)


def grade_rubric_llm(item, response, judge):
    crit = "\n".join(f"{i+1}. {c['criterion']} (배점 {c['points']})" for i, c in enumerate(item["rubric"]))
    prompt = (f"[문항]\n{item['question']}\n\n[모범답안]\n{item['answer']['reference']}\n\n"
              f"[채점 기준]\n{crit}\n\n[채점할 답안]\n{response}")
    raw = judge.complete(JUDGE_SYSTEM, prompt)
    m = re.search(r"\[[^\[\]]*\]", raw)
    try:
        scores = json.loads(m.group()) if m else []
    except json.JSONDecodeError:
        scores = []
    if len(scores) != len(item["rubric"]):
        return grade_rubric_keywords(item, response)[0], "LLM 채점 형식 오류 → 키워드 채점으로 대체"
    pts = sum(max(0, min(float(s), c["points"])) for s, c in zip(scores, item["rubric"]))
    return pts / 100, f"LLM 채점 {scores}"


def grade(item, response, judge=None):
    t = item["answer_type"]
    if t == "numeric":
        return grade_numeric(item, response)
    if t == "choice":
        return grade_choice(item, response)
    if judge is not None:
        return grade_rubric_llm(item, response, judge)
    return grade_rubric_keywords(item, response)
