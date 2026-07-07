# Nemotron Personas Korea Lab

공개 NVIDIA/Hugging Face `nvidia/Nemotron-Personas-Korea` 데이터셋을 DuckDB와 FastAPI 웹앱으로 탐색하고, 합성 페르소나를 **고객 발견·현장 검증 가설**로 전환하기 위한 경량 분석 도구입니다.

이 저장소는 의도적으로 **코드와 운영 문서만** 포함합니다. 원본 데이터셋, 생성된 DuckDB 파일, 내보내기 결과, 로컬 인터뷰 노트, 비공개 사업 맥락은 포함하지 않습니다.

## 용도

- 한국어 페르소나 Parquet 조각을 DuckDB 뷰로 연결합니다.
- 인구통계, 직업, 지역, 식생활/라이프스타일 관련 페르소나 텍스트를 탐색합니다.
- 범용 직장 식사/고객 발견 세그먼트를 생성합니다.
- 실제 인터뷰나 현장 실험에서 얻은 검증 결과를 기록합니다.
- OpenWebUI 스타일의 3단 화면을 사용합니다.
  - 왼쪽: 세그먼트/워크스페이스 사이드바
  - 가운데: 채팅형 페르소나 탐색 영역
  - 오른쪽: 가설·질문·검증 결과 확인 패널

## 중요한 한계

합성 페르소나는 아이디어를 만들고 가설을 정리하는 데 유용하지만, **실제 수요의 증거가 아닙니다**. 이 앱의 결과는 인터뷰, 설문, 관찰, 현장 테스트로 검증하기 전까지는 가설로만 다뤄야 합니다.

## 데이터셋 준비

데이터셋은 저장소에 포함하지 않고 별도로 내려받습니다.

```bash
hf download nvidia/Nemotron-Personas-Korea \
  --repo-type dataset \
  --local-dir ./data \
  --max-workers 4
```

예상 디렉터리 구조:

```text
data/
  README.md
  data/train-00000-of-00009.parquet
  ...
  data/train-00008-of-00009.parquet
```

## 설치

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## DuckDB 메타데이터와 뷰 생성

```bash
python scripts/create_duckdb.py --dataset-dir ./data --db-path ./db/nemotron_personas_ko.duckdb
python scripts/create_segments.py --db-path ./db/nemotron_personas_ko.duckdb
```

기본 설계는 원본 Parquet 파일을 DB 밖에 두고, DuckDB에서 해당 파일을 바라보는 뷰를 만드는 방식입니다. 따라서 대용량 데이터를 중복으로 실체화하지 않습니다.

## 웹앱 실행

```bash
python -m uvicorn webapp.app:app --host 0.0.0.0 --port 8787
```

브라우저에서 다음 주소를 엽니다.

```text
http://localhost:8787/
```

로컬 기본 경로가 아닌 DB를 사용할 때는 실행 전에 `PERSONA_LAB_DB`를 지정합니다.

```bash
export PERSONA_LAB_DB=/absolute/path/to/db/nemotron_personas_ko.duckdb
```

## 검증 워크스페이스 사용 문서

새 가설 워크스페이스 생성, 페르소나 필터 설정, 검증 노트 기록, 문제 해결 절차는 아래 문서에 정리되어 있습니다.

```text
docs/validation-workspace-guide.md
```

## API

```text
GET  /api/health
GET  /api/summary
GET  /api/segments
GET  /api/personas?segment_id=...&q=점심&province=경기&limit=20
GET  /api/hypotheses?segment_id=...
POST /api/workspaces
GET  /api/validation-results?hypothesis_id=...
POST /api/validation-results
```

## 테스트

```bash
pytest tests -q
```

테스트는 작은 고정 샘플 DB를 사용하므로 전체 데이터셋이 없어도 실행됩니다.

## 공개 저장소와 개인정보 주의사항

- 원본 Parquet 조각이나 생성된 내보내기 파일을 커밋하지 않습니다.
- 생성된 DuckDB 파일을 커밋하지 않습니다.
- `.env`, 토큰, API 키, 비밀번호, 연결 문자열을 커밋하지 않습니다.
- 인터뷰 원문, 연락처, 실명, 회사 내부 정보, 비공개 사업 맥락을 커밋하지 않습니다.
- 특정 프로젝트 전용 가설과 검증 노트는 공개 저장소가 아닌 비공개 시스템에 보관합니다.

문서나 테스트에 예시가 필요하면 일반화된 더미 값을 사용하고, 민감한 값은 `[REDACTED]`로 표기합니다.
