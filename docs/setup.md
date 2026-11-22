# 실행 준비

실제 모델을 부르려면 세 회사의 API 키가 필요하다. 구독(ChatGPT Plus, Claude Max, Google AI Pro)과 API는 따로다.

## 1. API 키 만들기

| 회사 | 만드는 곳 | 환경변수 이름 |
|---|---|---|
| Anthropic | platform.claude.com → API keys | `ANTHROPIC_API_KEY` |
| OpenAI | platform.openai.com → API keys | `OPENAI_API_KEY` |
| Google | aistudio.google.com → API 키 | `GEMINI_API_KEY` |

키는 만들 때 한 번만 보인다. 메모장 같은 곳에 잠깐 옮겨 두었다가 아래 2번을 마치면 지운다.

**키를 리포에 올리지 않는다.** 이 리포는 공개다. 코드, 설정 파일, 커밋 메시지, 이슈 어디에도 키를 적지 않는다. 채팅에 붙여넣지도 않는다. 올라갔다면 그 키를 바로 폐기하고 새로 만든다.

## 2. 환경변수에 넣기 (Windows)

명령 프롬프트를 열고 한 줄씩 실행한다. `여기에_키`를 실제 키로 바꾼다.

```
setx ANTHROPIC_API_KEY "여기에_키"
setx OPENAI_API_KEY "여기에_키"
setx GEMINI_API_KEY "여기에_키"
```

창을 닫고 새로 연다. `setx`는 새로 연 창부터 적용된다.

macOS·Linux에서는 `~/.zshrc`나 `~/.bashrc`에 `export ANTHROPIC_API_KEY="..."` 형태로 적는다.

## 3. 설치

```
git clone https://github.com/minyoungkang1227/collatio
cd collatio
pip install -r requirements.txt
pytest
```

## 4. 시험 호출

```
set PYTHONPATH=src
python -m collatio.check
```

모델마다 지어낸 예문 하나를 3번씩 보낸다. 합쳐서 18회이고 비용은 몇 센트다. 모델별로 응답(강도/방향), 호출당 입력·출력 토큰, 본 실험 예상 비용이 나온다.

- `실패: ... credentials / API key`: 그 회사의 환경변수가 안 잡혔다. 창을 새로 열었는지 확인한다.
- `실패: ... not found / model`: 모델 이름이 바뀌었을 수 있다. `config/experiment.yaml`의 `model_id`를 그 회사의 모델 목록에서 확인한다.
- `형식위반`: 모델이 JSON이 아닌 답을 냈다. 아래에 원문 앞부분이 찍힌다.

출력에는 키가 들어가지 않으므로 그대로 공유해도 된다.

## 5. 지출 한도

- OpenAI: Billing에서 자동 충전을 끄고, Limits에서 월 예산을 건다.
- Anthropic: Max 플랜의 월 API 크레딧은 이월되지 않는다. 본 실험은 한 결제 주기 안에서 돌린다.
- Google: 무료 등급은 하루 호출 수 제한이 있다. 본 실험은 며칠에 나눠 돌리거나 결제를 연결한다.
