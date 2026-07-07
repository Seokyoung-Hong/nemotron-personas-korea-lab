# AI 연결용 페르소나 생성·가상 인터뷰 도구 가이드

이 문서는 Hermes 같은 AI 에이전트가 Persona Lab을 도구처럼 호출해 다음 기능을 수행하는 방법을 설명합니다.

1. 사업 아이디어에 맞는 페르소나 검색 기반 만들기
2. 검색된 원천 페르소나를 고객 페르소나 카드로 생성하기
3. 생성된 고객 페르소나와 가상 인터뷰하기

> 주의: 여기서 생성되는 페르소나와 인터뷰 답변은 합성 데이터 기반 추론입니다. 실제 고객 검증 결과가 아니며, 인터뷰 질문 설계와 가설 정리에만 사용해야 합니다.

## 서버 전제

Persona Lab 서버가 실행 중이어야 합니다.

```bash
export PERSONA_LAB_DB=/absolute/path/to/db/nemotron_personas_ko.duckdb
python -m uvicorn webapp.app:app --host 0.0.0.0 --port 8787
```

상태 확인:

```bash
curl -sS http://127.0.0.1:8787/api/health
```

## 1. 검색 기반 만들기

`POST /api/persona-search`는 사업 아이디어에서 키워드를 추출하고, 페르소나 원천 데이터에서 관련 후보를 검색합니다.

```bash
curl -sS http://127.0.0.1:8787/api/persona-search \
  -H 'Content-Type: application/json' \
  -d '{
    "business_idea": "공단 근로자가 점심 메뉴를 빠르게 확인하고 한식당을 선택하는 서비스",
    "target_count": 5,
    "province": "경기",
    "min_age": 20,
    "max_age": 64,
    "extra_keywords": ["공단", "점심", "메뉴"]
  }'
```

응답의 핵심 필드:

- `search_basis.keywords`: 사업 아이디어와 추가 키워드에서 만든 검색 키워드
- `search_basis.matched_count`: 검색 조건에 맞은 후보 수
- `matches`: 실제 원천 페르소나 후보 목록

## 2. 고객 페르소나 생성

`POST /api/customer-personas`는 검색 후보를 기반으로 고객 페르소나 카드를 생성합니다.

```bash
curl -sS http://127.0.0.1:8787/api/customer-personas \
  -H 'Content-Type: application/json' \
  -d '{
    "business_idea": "공단 근로자가 점심 메뉴를 빠르게 확인하고 한식당을 선택하는 서비스",
    "target_count": 3,
    "province": "경기",
    "extra_keywords": ["공단", "점심", "메뉴"]
  }'
```

응답의 `customer_personas`는 다음 구조를 갖습니다.

```json
{
  "id": "cp_...",
  "name": "경기 ... 고객",
  "source_uuid": "...",
  "demographics": {
    "age": 35,
    "sex": "남자",
    "province": "경기",
    "district": "...",
    "occupation": "..."
  },
  "needs": "...",
  "pain_points": ["..."],
  "behavioral_clues": ["..."],
  "matched_keywords": ["점심"],
  "interview_seed": "...",
  "source_excerpt": "..."
}
```

AI 에이전트는 이 결과를 사용자에게 바로 결론처럼 말하지 말고, “검증 후보 페르소나”로 제시해야 합니다.

## 3. 가상 인터뷰

`POST /api/virtual-interviews`는 생성된 고객 페르소나 하나와 질문 하나를 받아 합성 응답을 만듭니다.

```bash
curl -sS http://127.0.0.1:8787/api/virtual-interviews \
  -H 'Content-Type: application/json' \
  -d '{
    "customer_persona": {
      "id": "cp_example",
      "name": "경기 안산시 현장직 고객",
      "demographics": {
        "province": "경기",
        "district": "경기-안산시",
        "occupation": "지게차 운전원"
      },
      "needs": "점심 메뉴 확인 맥락에서 서비스 필요성을 확인할 후보",
      "source_excerpt": "점심에는 한식당을 찾습니다"
    },
    "question": "오늘 점심 메뉴를 어디서 확인하나요?"
  }'
```

응답에는 다음 필드가 포함됩니다.

- `answer`: 가상 인터뷰 답변
- `follow_up_questions`: 실제 인터뷰에서 이어서 물어볼 질문
- `synthetic_disclaimer`: 합성 응답 주의 문구

## 4. Hermes skill 연결 방식

Hermes에서는 별도 MCP 서버를 새로 띄우지 않아도, 이 HTTP API를 호출하는 skill을 통해 자연어 작업을 수행할 수 있습니다.

권장 skill 동작:

1. 사용자의 사업 아이디어를 정리한다.
2. `/api/customer-personas`를 호출해 후보 페르소나를 생성한다.
3. 사용자가 특정 페르소나를 고르면 `/api/virtual-interviews`를 호출한다.
4. 모든 결과에 “합성 기반이며 실제 검증 필요” 문구를 붙인다.
5. 인터뷰 결과를 실제 검증 결과처럼 저장하지 않는다. 실제 사람에게 확인한 결과만 `POST /api/validation-results`에 저장한다.

## 5. MCP로 확장할 때의 권장 형태

나중에 MCP 서버로 분리한다면 도구는 아래 3개면 충분합니다.

- `search_persona_basis(business_idea, filters)`
- `generate_customer_personas(business_idea, filters, target_count)`
- `virtual_interview(customer_persona, question)`

현재는 FastAPI HTTP API와 Hermes skill 연결로 같은 기능을 수행합니다.
