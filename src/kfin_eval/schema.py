"""문항 스키마, 검증, 내용 해시."""
import datetime
import hashlib
import json
from pathlib import Path

DOMAINS = {"risk", "product", "regulation", "disclosure"}
ANSWER_TYPES = {"numeric", "choice", "rubric"}
# 이 필드가 바뀌면 문항이 바뀐 것으로 보고 기존 검수를 무효화한다.
CONTENT_FIELDS = ("question", "answer_type", "answer", "choices", "rubric", "sources")
STALE_DAYS = 365
# 원문 대조 수준. primary: 법령 원문(국가법령정보센터 등) 직접 확인, secondary: 해설·보도자료 등 2차 자료로 확인
VERIFY_LEVELS = ("primary", "secondary")


def content_hash(item):
    core = {k: item.get(k) for k in CONTENT_FIELDS}
    raw = json.dumps(core, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def load_items(path):
    path = Path(path)
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    items = []
    for f in files:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{f}:{n} JSON 오류: {e}")
    return items


def _is_date(s):
    try:
        datetime.date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def validate_item(item, today=None):
    """(errors, warnings) 반환. errors가 있으면 실행 대상에서 제외된다."""
    today = today or datetime.date.today()
    err, warn = [], []

    for k in ("id", "domain", "answer_type", "question", "answer", "sources", "author", "difficulty"):
        if item.get(k) in (None, "", []):
            err.append(f"필수 필드 누락: {k}")
    if err:
        return err, warn

    if not isinstance(item["domain"], str) or not item["domain"].strip():
        err.append("domain은 비어 있지 않은 문자열")   # 분야 이름은 자유다. DOMAINS는 지금까지 쓴 이름의 목록일 뿐이다
    if item["answer_type"] not in ANSWER_TYPES:
        err.append(f"answer_type은 {sorted(ANSWER_TYPES)} 중 하나")
    if not isinstance(item["difficulty"], int) or not 1 <= item["difficulty"] <= 6:
        err.append("difficulty는 1~6 정수")
    if len(item["question"]) < 20:
        warn.append("문항이 너무 짧음(조건이 충분한지 확인)")

    # 출처: 근거 없는 문항은 받지 않는다.
    for i, s in enumerate(item["sources"]):
        if not isinstance(s, dict) or not s.get("title"):
            err.append(f"sources[{i}].title 누락")
            continue
        if not _is_date(s.get("as_of")):
            err.append(f"sources[{i}].as_of는 YYYY-MM-DD (근거를 확인한 기준일)")
        elif (today - datetime.date.fromisoformat(s["as_of"])).days > STALE_DAYS:
            warn.append(f"sources[{i}] 기준일이 {STALE_DAYS}일 초과: 재검증 필요")
        if item["domain"] == "regulation" and not s.get("ref"):
            warn.append(f"sources[{i}].ref(조문 번호) 없음")
        v = s.get("verified")
        if v is not None:
            if not isinstance(v, dict) or not _is_date(v.get("date")) or not v.get("by") or v.get("level") not in VERIFY_LEVELS:
                err.append(f"sources[{i}].verified는 date(YYYY-MM-DD)·by·level({'/'.join(VERIFY_LEVELS)}) 필요")
        if item["domain"] == "regulation":
            if v is None:
                warn.append(f"sources[{i}] 원문 대조 기록(verified) 없음")
            elif isinstance(v, dict) and v.get("level") != "primary":
                warn.append(f"sources[{i}] 2차 출처로만 대조됨: 국가법령정보센터 원문 확인 필요")

    # 수작업 수정 기록: 사람이 문항을 고치면 언제·누가·왜를 남긴다(BCBS 239 원칙 3).
    for j, c in enumerate(item.get("changes") or []):
        if not isinstance(c, dict) or not _is_date(c.get("date")) or not c.get("by") or not c.get("reason"):
            err.append(f"changes[{j}]는 date(YYYY-MM-DD)·by·reason 필요")

    a, t = item["answer"], item["answer_type"]
    if t == "numeric":
        if not isinstance(a, dict) or not isinstance(a.get("value"), (int, float)):
            err.append("numeric: answer.value는 숫자")
        elif not a.get("unit"):
            err.append("numeric: answer.unit 누락")
        elif a["unit"] not in item["question"]:
            warn.append(f"numeric: 문항에 답 단위({a['unit']})가 명시되지 않음")
    elif t == "choice":
        ch = item.get("choices") or {}
        if not isinstance(ch, dict) or len(ch) < 2:
            err.append("choice: choices는 {라벨: 내용} 2개 이상")
        elif not isinstance(a, dict) or a.get("value") not in ch:
            err.append("choice: answer.value는 choices의 라벨 중 하나")
    elif t == "rubric":
        if not isinstance(a, dict) or not a.get("reference"):
            err.append("rubric: answer.reference(모범답안) 누락")
        rb = item.get("rubric") or []
        if not rb:
            err.append("rubric: 채점 기준 누락")
        else:
            if sum(c.get("points", 0) for c in rb) != 100:
                err.append("rubric: 배점 합계는 100")
            for i, c in enumerate(rb):
                if not c.get("criterion"):
                    err.append(f"rubric[{i}].criterion 누락")
                if not c.get("keywords"):
                    warn.append(f"rubric[{i}] keywords 없음: 키워드 채점 불가(LLM 채점만 가능)")
    return err, warn


def validate_all(items, today=None):
    """{id: (errors, warnings)}. 중복 id와 중복 문항도 잡는다."""
    result, seen_id, seen_q = {}, set(), {}
    for idx, it in enumerate(items):
        key = it.get("id") or f"(id 없음 #{idx})"
        err, warn = validate_item(it, today)
        if key in seen_id:
            err.append("id 중복")
        seen_id.add(key)
        q = "".join(str(it.get("question", "")).split())
        if q and q in seen_q:
            err.append(f"문항 중복: {seen_q[q]}와 동일")
        elif q:
            seen_q[q] = key
        result[key] = (err, warn)
    return result
