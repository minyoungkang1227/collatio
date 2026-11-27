# 데이터 사전

Collatio·kfin-eval·ShockLens·ModelAudit이 주고받는 데이터의 공통 규칙. BCBS 239 원칙 2(데이터 아키텍처: 메타데이터, 명명 규칙, 소유권)와 원칙 5(적시성: 기준일)를 기준으로 정했다. 작성 2026-11-27.

이 문서는 규칙을 정한다. 기존 필드 이름을 바꾸지는 않는다. 이름이 다른 필드는 아래 대응표로 묶는다.

## 공통 필드

모든 데이터 한 건(문항, 라벨, 사건, 예측)은 아래 다섯 가지를 가져야 한다.

| 공통 이름 | 뜻 | 형식 |
|---|---|---|
| id | 저장소 안에서 유일한 식별자 | `접두어-번호` 또는 `접두어_설명`. 아래 접두어 표 |
| source | 근거가 어디서 왔는지 | 제목 + (가능하면) URL·조문 번호 |
| as_of | 근거를 확인한 기준일 | YYYY-MM-DD |
| author | 만든 사람 또는 코드 | 사람 이름, `seed`, `gen-*`, `claude-draft` |
| verified | 원문과 대조했는지 | date·by·level(`primary`/`secondary`)·method |

`claude-draft`는 Claude가 만들거나 고친 것이다. 사람 검수 전까지 승인된 것으로 치지 않는다.

## 저장소별 대응표

| 공통 이름 | kfin-eval 문항 (`data/items/*.jsonl`) | Collatio 라벨 (`data/labels/*.csv`) | ShockLens 사건 (`data/library/events.yaml`) | ShockLens 예측 (`data/forecasts/*.jsonl`) | ModelAudit |
|---|---|---|---|---|---|
| id | `id` | `item_id` | `id` | `id` | 없음(공개 데이터셋 행 번호) |
| source | `sources[].title`, `ref` | `source`, `url` | `sources` | `source` | 데이터셋 이름(`data.py`) |
| as_of | `sources[].as_of` | `date` | `date`(발표일) | `data_version`, `recorded_at` | 없음 |
| author | `author` | `labeler`, `label_method` | 파일 머리 주석(손으로 정리) | `source` | 없음 |
| verified | `sources[].verified` | `source_verified`, `n_independent_sources` | `clean`(다른 충격과 겹치는지) | 없음 | 없음 |

빈 칸이 이 사전으로 드러난 부족분이다. ModelAudit은 공개 데이터셋(German Credit, Home Credit)만 읽으므로 데이터셋 단위로 출처·내려받은 날짜를 보고서에 적는 것으로 대신한다.

## ID 접두어

| 접두어 | 뜻 | 예 |
|---|---|---|
| `risk-` | kfin-eval 리스크 문항 | risk-0001 |
| `prod-` | kfin-eval 상품 문항 | prod-0001 |
| `reg-` | kfin-eval 규제 문항 | reg-0001 |
| `dart-` | 공시에서 만든 문항 | dart-d001-H |
| `calc_` | ShockLens 예측 기록 | calc_20261107_… |
| 소문자_연도 | ShockLens 사건 | us_301_2018 |

새 접두어는 이 표에 먼저 적고 쓴다. 저장소가 달라도 같은 접두어를 다른 뜻으로 쓰지 않는다.

## 기준일과 갱신

- kfin-eval 문항의 `as_of`가 365일을 넘으면 `validate`가 재검증 경고를 낸다.
- 규제 문항은 `verified.level`이 `primary`가 될 때까지 경고가 남는다. 원문은 국가법령정보센터(law.go.kr)에서 확인한다.

## 수작업 수정 기록

사람이나 Claude가 문항 내용을 손으로 고치면 문항에 `changes`를 붙인다(BCBS 239 원칙 3: 수작업은 사유를 남긴다).

```json
"changes": [{"date": "2026-11-27", "by": "claude-draft", "reason": "조문 번호 수정: 제18조 제6항 → 제7항"}]
```

`changes`는 내용 해시(`CONTENT_FIELDS`)에 들어가지 않는다. 내용 자체가 바뀌면 해시가 바뀌어 기존 검수가 무효가 되고, `changes`는 그 이유를 남긴다.

## 커버리지

계획 범위는 `config/coverage_plan.json`, 실제 현황은 `python -m kfin_eval coverage`가 `docs/coverage.md`로 만든다.
