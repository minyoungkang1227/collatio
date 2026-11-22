# 내 데이터와 내 모델로 돌려 보기

> 이 문서는 실험을 하기 전에 쓴 계획이다(2026-11-15~17). 실제로 한 것과 나온 결과는 [findings.md](findings.md)에 있다. 여기 적힌 본 실행(뉴스 100건, 모델 여섯 개)은 하지 않았고, 방어의 무게는 답의 대조에서 원문 대조로 옮겨졌다.

이 리포의 실험은 한국어 금융 뉴스 100건과 모델 여섯 개에 대한 것이다. 같은 방법을 다른 문서와 다른 모델 조합에 적용할 수 있다. 예를 들어 "우리 팀이 쓰는 모델 세 개가 우리 업무 문서에서 얼마나 같이 틀리는가"를 잴 수 있다.

> 2026-11-16 기준, 이 절차는 리포 작성자의 시범 실행(모델 여섯 개 연결 확인)까지만 검증됐다. 다른 환경에서 돌려 본 사람은 아직 없다. 막히는 곳이 있으면 이슈로 알려 주면 고친다.

## 바꿀 수 있는 것과 없는 것

| 항목 | 바꾸는 곳 | 비고 |
|---|---|---|
| 모델 조합 | `config/experiment.yaml`의 `panel.models` | OpenAI, Anthropic, Google 세 회사만 지원한다. 다른 회사는 `src/collatio/clients.py`에 클래스를 하나 추가해야 한다 |
| 반복 횟수 | `panel.n_runs` | 줄이면 비용이 준다. 3 미만이면 모델 내 분산을 못 잰다 |
| 문서 | `data/labels/news_labels.csv` | 아래 2번 |
| 문서 기준일 | `dataset.news_from` | 패널에서 가장 늦게 나온 모델보다 뒤여야 한다. 모델이 정답을 이미 알면 실험이 무의미하다 |
| 지시문과 채점 기준 | `prompts/institutional_system.txt` | 바꾸면 `data_version`을 올린다 |
| 출력 형식 | 바꿀 수 없다 | 강도(1~5)와 방향(-1/0/1) 고정이다. 다른 판단(승인·거절 등)에 쓰려면 `schema.py`와 `metrics.py`를 고쳐야 한다 |

## 순서

1. **설치와 키**: [setup.md](setup.md)를 따른다. 쓰지 않는 회사의 키는 없어도 된다. 그 회사 모델을 `panel.models`에서 지운다.
2. **문서와 정답 준비**: `data/labels/labeling_template.xlsx`를 복사해 채우고 `python scripts/xlsx_to_labels.py 파일.xlsx`로 변환한다. 열의 뜻은 [labeling_guide.md](labeling_guide.md).
   - 최소 건수: 흐름만 보려면 10건, 검정 결과를 읽으려면 60건 이상을 권한다. 건수가 적으면 신뢰구간이 넓어 아무 결론도 못 낸다.
   - 정답은 사람이 붙인다. 시험 대상인 AI에게 정답을 묻지 않는다.
   - `dataset.n_tune`과 `n_eval`의 합을 건수에 맞춘다.
3. **모의 실행으로 설치 확인**: `PYTHONPATH=src python -m collatio.pipeline --mock`
4. **시험 호출로 비용 확인**: `PYTHONPATH=src python -m collatio.check`. 모델별 예상 비용이 나온다.
5. **본 실행**: `PYTHONPATH=src python -m collatio.pipeline --run`. 응답은 `data/runs/<data_version>/`에 쌓이고, 멈춰도 다시 실행하면 이어서 한다.

Windows에서는 `PYTHONPATH=src` 대신 먼저 `set PYTHONPATH=src`를 실행한다.

## 결과에서 먼저 볼 숫자

- **쌍별 오답 상관과 순열검정 p값**: 난이도를 통제하고도 모델들이 같이 틀리는가
- **같은 회사 쌍과 다른 회사 쌍의 차이**: 회사를 섞으면 겹침이 줄어드는가
- **조작 입력에서의 가드 재현율**: 답의 일치만 보는 가드와 출처를 세는 가드의 차이

## 지금 안 되는 것

- 문체 변형(paraphrase, ai_style) 글을 만드는 도구가 없다. `data/labels/perturbations.csv`에 직접 넣지 않으면 그 변형은 건너뛴다.
- 독립 출처 대조 가드는 라벨에 적은 출처 수를 그대로 쓴다. 실제 검색으로 세지 않는다.
- 개인 트랙(매수·보유·매도)은 채점이 구현되지 않았다.

## 주의

- 사실을 뒤집은 글에 실제 회사명이 들어가면 그 파일을 공개하지 않는다. `perturbations.csv`는 `.gitignore`에 있다.
- 내부 문서를 외부 모델 API에 보내도 되는지는 소속 조직의 규정을 먼저 확인한다.
- 결과를 공유할 때 원문과 API 키를 넣지 않는다. 요약 통계만으로 충분하다.

## 결과와 의견 보내기

[이슈](https://github.com/minyoungkang1227/collatio/issues/new/choose)에 양식이 세 가지 있다: 돌려 본 결과, 막힌 곳, 방법에 대한 이의. 방법에 대한 이의를 가장 환영한다.
