import os
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = ROOT / 'tests' / 'fixture.duckdb'
os.environ['PERSONA_LAB_DB'] = str(TEST_DB)


def setup_module():
    if TEST_DB.exists():
        TEST_DB.unlink()
    con = duckdb.connect(str(TEST_DB))
    con.execute('''
        CREATE TABLE personas_summary (
          uuid VARCHAR, age INTEGER, sex VARCHAR, province VARCHAR, district VARCHAR,
          occupation VARCHAR, persona VARCHAR, professional_persona VARCHAR,
          culinary_persona VARCHAR
        )
    ''')
    con.execute('''
        INSERT INTO personas_summary VALUES
        ('u1', 35, '남자', '경기', '경기-안산시', '지게차 운전원', '현장직 페르소나', '물류 현장 전문가', '점심에는 한식당을 찾습니다'),
        ('u2', 42, '여자', '서울', '서울-구로구', '경리 사무원', '사무직 페르소나', '사무 지원 전문가', '동료와 외식합니다')
    ''')
    con.execute('CREATE VIEW personas_raw AS SELECT * FROM personas_summary')
    con.execute('CREATE TABLE persona_segments (id VARCHAR, business_context_id VARCHAR, segment_name VARCHAR, filter_sql VARCHAR, rationale VARCHAR, sample_size BIGINT)')
    con.execute("INSERT INTO persona_segments VALUES ('industrial_shift_workers','workplace_meal_discovery','Industrial candidates', 'SELECT * FROM personas_summary WHERE occupation LIKE ''%운전%''', 'fixture rationale', 1)")
    con.execute('CREATE TABLE persona_hypotheses (id VARCHAR, segment_id VARCHAR, hypothesis_type VARCHAR, hypothesis VARCHAR, why_it_matters VARCHAR, confidence_before_validation VARCHAR)')
    con.execute("INSERT INTO persona_hypotheses VALUES ('industrial_shift_workers_h1','industrial_shift_workers','behavior','Users need today-menu visibility','guides validation','medium')")
    con.execute('CREATE TABLE validation_questions (id VARCHAR, hypothesis_id VARCHAR, question VARCHAR, question_type VARCHAR, expected_signal VARCHAR)')
    con.execute("INSERT INTO validation_questions VALUES ('q1','industrial_shift_workers_h1','How do you check lunch menus?','interview','current behavior')")
    con.execute('CREATE TABLE validation_results (id VARCHAR, hypothesis_id VARCHAR, method VARCHAR, respondent_profile VARCHAR, result_summary VARCHAR, evidence_level VARCHAR, validated BOOLEAN, created_at TIMESTAMP DEFAULT now())')
    con.close()


def teardown_module():
    if TEST_DB.exists():
        TEST_DB.unlink()


def test_api_summary_and_search():
    from webapp.app import app
    client = TestClient(app)
    assert client.get('/').status_code == 200
    summary = client.get('/api/summary').json()
    assert summary['row_count'] == 2
    rows = client.get('/api/personas', params={'segment_id': 'industrial_shift_workers', 'q': '점심'}).json()['personas']
    assert len(rows) == 1
    assert rows[0]['uuid'] == 'u1'


def test_validation_result_roundtrip():
    from webapp.app import app
    client = TestClient(app)
    payload = {'hypothesis_id':'industrial_shift_workers_h1','method':'interview','respondent_profile':'fixture','result_summary':'uses signs','evidence_level':'medium','validated':True}
    created = client.post('/api/validation-results', json=payload)
    assert created.status_code == 200
    listed = client.get('/api/validation-results', params={'hypothesis_id':'industrial_shift_workers_h1'}).json()['results']
    assert any(row['respondent_profile'] == 'fixture' for row in listed)


def test_create_hypothesis_workspace_roundtrip():
    from webapp.app import app
    client = TestClient(app)
    payload = {
        'workspace_name': '공단 메뉴판 확인 가설',
        'hypothesis': '공단 근로자는 출근 직후 오늘 메뉴를 확인하면 점심 선택 시간을 줄인다.',
        'rationale': '새 가설 워크스페이스 추가 버튼이 DB에 세그먼트와 가설을 만들어야 한다.',
        'question': '오늘 메뉴를 언제 확인하나요?',
        'province': '경기',
        'query': '점심',
    }

    created = client.post('/api/workspaces', json=payload)

    assert created.status_code == 200
    body = created.json()
    assert body['segment']['segment_name'] == payload['workspace_name']
    assert body['hypothesis']['hypothesis'] == payload['hypothesis']
    assert body['hypothesis']['questions'][0]['question'] == payload['question']

    segments = client.get('/api/segments').json()['segments']
    assert any(row['id'] == body['segment']['id'] for row in segments)
    hypotheses = client.get('/api/hypotheses', params={'segment_id': body['segment']['id']}).json()['hypotheses']
    assert hypotheses[0]['hypothesis'] == payload['hypothesis']


def test_business_idea_generates_customer_personas_from_search_matches():
    from webapp.app import app
    client = TestClient(app)
    payload = {
        'business_idea': '공단 근로자가 점심 메뉴를 빠르게 확인하고 한식당을 선택하는 서비스',
        'target_count': 2,
        'province': '경기',
    }

    response = client.post('/api/customer-personas', json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body['business_idea'] == payload['business_idea']
    assert body['search_basis']['keywords']
    assert body['search_basis']['matched_count'] == 1
    assert len(body['customer_personas']) == 1
    persona = body['customer_personas'][0]
    assert persona['source_uuid'] == 'u1'
    assert '점심' in persona['needs']
    assert 'interview_seed' in persona


def test_virtual_interview_answers_as_generated_persona():
    from webapp.app import app
    client = TestClient(app)
    persona_payload = {
        'business_idea': '공단 근로자가 점심 메뉴를 빠르게 확인하고 한식당을 선택하는 서비스',
        'target_count': 1,
        'province': '경기',
    }
    persona = client.post('/api/customer-personas', json=persona_payload).json()['customer_personas'][0]

    response = client.post('/api/virtual-interviews', json={
        'customer_persona': persona,
        'question': '오늘 점심 메뉴를 어디서 확인하나요?',
    })

    assert response.status_code == 200
    body = response.json()
    assert body['question'] == '오늘 점심 메뉴를 어디서 확인하나요?'
    assert body['answer']
    assert body['synthetic_disclaimer'].startswith('합성 페르소나 기반')
    assert 'follow_up_questions' in body
