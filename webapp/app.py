from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get('PERSONA_LAB_DB', ROOT / 'db' / 'nemotron_personas_ko.duckdb'))
STATIC_DIR = ROOT / 'webapp' / 'static'
INDEX_PATH = STATIC_DIR / 'index.html'

app = FastAPI(title='Persona Lab', version='0.1.0')
app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')


class ValidationResultIn(BaseModel):
    hypothesis_id: str = Field(..., min_length=1)
    method: str = Field(..., min_length=1)
    respondent_profile: str = Field(..., min_length=1)
    result_summary: str = Field(..., min_length=1)
    evidence_level: str = Field(..., min_length=1)
    validated: bool


class WorkspaceIn(BaseModel):
    workspace_name: str = Field(..., min_length=1, max_length=120)
    hypothesis: str = Field(..., min_length=1, max_length=1000)
    rationale: str = Field(default='User-created hypothesis workspace.', max_length=1000)
    question: str | None = Field(default=None, max_length=500)
    hypothesis_type: str = Field(default='behavior', min_length=1, max_length=80)
    why_it_matters: str = Field(default='This guides interview recruiting and validation design.', max_length=1000)
    confidence_before_validation: str = Field(default='medium', min_length=1, max_length=80)
    query: str | None = Field(default=None, max_length=120)
    province: str | None = Field(default=None, max_length=40)
    min_age: int = Field(default=20, ge=0, le=120)
    max_age: int = Field(default=64, ge=0, le=120)


class CustomerPersonaRequest(BaseModel):
    business_idea: str = Field(..., min_length=5, max_length=1200)
    target_count: int = Field(default=5, ge=1, le=20)
    province: str | None = Field(default=None, max_length=40)
    min_age: int = Field(default=20, ge=0, le=120)
    max_age: int = Field(default=64, ge=0, le=120)
    extra_keywords: list[str] = Field(default_factory=list, max_length=20)


class VirtualInterviewRequest(BaseModel):
    customer_persona: dict[str, Any]
    question: str = Field(..., min_length=1, max_length=500)


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    if not DB_PATH.is_file():
        raise HTTPException(status_code=500, detail=f'DB not found: {DB_PATH}')
    return duckdb.connect(str(DB_PATH), read_only=read_only)


def rows_as_dicts(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    result = con.execute(sql, params or [])
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def get_segment_filter(con: duckdb.DuckDBPyConnection, segment_id: str) -> str:
    row = con.execute('SELECT filter_sql FROM persona_segments WHERE id = ?', [segment_id]).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f'Unknown segment_id: {segment_id}')
    match = re.search(r'\bWHERE\b(.+)$', row[0], flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise HTTPException(status_code=500, detail=f'Segment has invalid filter_sql: {segment_id}')
    return match.group(1).strip()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_workspace_filter(payload: WorkspaceIn) -> str:
    if payload.min_age > payload.max_age:
        raise HTTPException(status_code=400, detail='min_age must be <= max_age')
    where_parts = [f'age BETWEEN {payload.min_age} AND {payload.max_age}']
    province = payload.province.strip() if payload.province else ''
    query = payload.query.strip() if payload.query else ''
    if province:
        where_parts.append(f'province = {sql_literal(province)}')
    if query:
        like = sql_literal(f'%{query}%')
        where_parts.append(
            '(persona LIKE {like} OR professional_persona LIKE {like} OR '
            'culinary_persona LIKE {like} OR occupation LIKE {like} OR '
            'district LIKE {like} OR province LIKE {like})'.format(like=like)
        )
    return ' AND '.join(where_parts)


KEYWORD_STOPWORDS = {
    '서비스', '사업', '아이디어', '고객', '사용자', '위한', '하는', '하고', '에서', '으로', '에게', '빠르게',
    '확인하고', '선택하는', '생성', '기반', '검증', '가설', '데이터', '페르소나',
}


def extract_keywords(text: str, extra_keywords: list[str] | None = None, limit: int = 8) -> list[str]:
    raw_terms = re.findall(r'[0-9A-Za-z가-힣]{2,}', text)
    raw_terms.extend(extra_keywords or [])
    keywords: list[str] = []
    for term in raw_terms:
        cleaned = term.strip().lower()
        if len(cleaned) < 2 or cleaned in KEYWORD_STOPWORDS:
            continue
        if cleaned not in keywords:
            keywords.append(cleaned)
        if len(keywords) >= limit:
            break
    return keywords


def persona_match_clause(keywords: list[str]) -> tuple[str, list[Any]]:
    if not keywords:
        return '1=1', []
    clauses: list[str] = []
    params: list[Any] = []
    fields = ['persona', 'professional_persona', 'culinary_persona', 'occupation', 'district', 'province']
    for keyword in keywords:
        like = f'%{keyword}%'
        clauses.append('(' + ' OR '.join(f'{field} LIKE ?' for field in fields) + ')')
        params.extend([like] * len(fields))
    return '(' + ' OR '.join(clauses) + ')', params


def build_customer_persona(row: dict[str, Any], business_idea: str, rank: int, keywords: list[str]) -> dict[str, Any]:
    matched_keywords = [
        keyword for keyword in keywords
        if any(keyword in str(row.get(field, '')).lower() for field in ['persona', 'professional_persona', 'culinary_persona', 'occupation', 'district', 'province'])
    ]
    label = f"{row['province']} {row['district']} {row['occupation']} 고객"
    needs = f"{', '.join(matched_keywords) or '생활 패턴'} 맥락에서 {business_idea}의 필요성을 확인할 후보"
    pain_points = [
        '현재 행동과 우회 방법을 실제 인터뷰에서 확인해야 합니다.',
        f"직업/지역 맥락: {row['occupation']} · {row['province']} {row['district']}",
    ]
    if row.get('culinary_persona'):
        pain_points.append(str(row['culinary_persona']))
    return {
        'id': f"cp_{hashlib.sha1((business_idea + row['uuid']).encode('utf-8')).hexdigest()[:12]}",
        'rank': rank,
        'name': label,
        'source_uuid': row['uuid'],
        'demographics': {
            'age': row['age'],
            'sex': row['sex'],
            'province': row['province'],
            'district': row['district'],
            'occupation': row['occupation'],
        },
        'needs': needs,
        'pain_points': pain_points,
        'behavioral_clues': [row.get('persona') or '', row.get('professional_persona') or ''],
        'matched_keywords': matched_keywords,
        'interview_seed': f"{label}에게 '{business_idea}'와 관련된 최근 실제 행동, 대안, 비용/불편을 묻습니다.",
        'source_excerpt': row.get('culinary_persona') or row.get('persona') or '',
    }


def answer_as_persona(persona: dict[str, Any], question: str) -> str:
    demographics = persona.get('demographics', {})
    occupation = demographics.get('occupation') or '해당 직군'
    region = ' '.join(str(demographics.get(key, '')).strip() for key in ['province', 'district']).strip()
    clue = persona.get('source_excerpt') or '기존 생활 패턴을 기준으로 판단합니다.'
    needs = persona.get('needs') or '불편을 줄이는 방법을 찾고 있습니다.'
    return (
        f"저는 {region}에서 일하는 {occupation} 관점으로 답하면, '{question}'에 대해 먼저 평소 행동부터 떠올릴 것 같습니다. "
        f"제 상황에서는 {needs}가 중요하고, 관련 단서는 '{clue}'입니다. "
        "다만 이 답변은 합성 페르소나 기반 가상 응답이므로 실제 인터뷰에서 같은 질문으로 확인해야 합니다."
    )


@app.get('/', response_class=HTMLResponse)
def index() -> str:
    return INDEX_PATH.read_text(encoding='utf-8')


@app.get('/api/health')
def health() -> dict[str, Any]:
    return {'ok': True, 'db_path': str(DB_PATH)}


@app.get('/api/summary')
def summary() -> dict[str, Any]:
    con = connect()
    try:
        row_count = con.execute('SELECT COUNT(*) FROM personas_raw').fetchone()[0]
        uuid_count = con.execute('SELECT COUNT(DISTINCT uuid) FROM personas_raw').fetchone()[0]
        segment_count = con.execute('SELECT COUNT(*) FROM persona_segments').fetchone()[0]
        persona_candidate_count = con.execute('SELECT COALESCE(MAX(sample_size), 0) FROM persona_segments').fetchone()[0]
        hypothesis_count = con.execute('SELECT COUNT(*) FROM persona_hypotheses').fetchone()[0]
        question_count = con.execute('SELECT COUNT(*) FROM validation_questions').fetchone()[0]
    finally:
        con.close()
    return {
        'row_count': row_count,
        'distinct_uuid_count': uuid_count,
        'segment_count': segment_count,
        'persona_candidate_count': persona_candidate_count,
        'hypothesis_count': hypothesis_count,
        'question_count': question_count,
        'positioning': 'Synthetic personas help generate hypotheses; real validation still requires field evidence.',
    }


@app.get('/api/segments')
def segments() -> dict[str, Any]:
    con = connect()
    try:
        rows = rows_as_dicts(con, 'SELECT id, segment_name, rationale, sample_size FROM persona_segments ORDER BY sample_size DESC')
    finally:
        con.close()
    return {'segments': rows}


@app.post('/api/workspaces')
def create_workspace(payload: WorkspaceIn) -> dict[str, Any]:
    workspace_name = payload.workspace_name.strip()
    hypothesis_text = payload.hypothesis.strip()
    if not workspace_name or not hypothesis_text:
        raise HTTPException(status_code=422, detail='workspace_name and hypothesis are required')

    where_clause = build_workspace_filter(payload)
    filter_sql = f'SELECT * FROM personas_summary WHERE {where_clause}'
    seed = '|'.join([workspace_name, hypothesis_text, where_clause])
    segment_id = 'ws_' + hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]
    hypothesis_id = f'{segment_id}_h1'
    question_text = payload.question.strip() if payload.question else ''
    question_id = f'{hypothesis_id}_q1'

    con = connect(read_only=False)
    try:
        sample_size = con.execute(f'SELECT COUNT(*) FROM personas_summary WHERE {where_clause}').fetchone()[0]
        con.execute('DELETE FROM validation_questions WHERE hypothesis_id = ?', [hypothesis_id])
        con.execute('DELETE FROM persona_hypotheses WHERE id = ?', [hypothesis_id])
        con.execute('DELETE FROM persona_segments WHERE id = ?', [segment_id])
        con.execute('''
            INSERT INTO persona_segments
            (id, business_context_id, segment_name, filter_sql, rationale, sample_size)
            VALUES (?, 'user_created_workspace', ?, ?, ?, ?)
        ''', [segment_id, workspace_name, filter_sql, payload.rationale.strip() or 'User-created hypothesis workspace.', sample_size])
        con.execute('''
            INSERT INTO persona_hypotheses
            (id, segment_id, hypothesis_type, hypothesis, why_it_matters, confidence_before_validation)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', [
            hypothesis_id,
            segment_id,
            payload.hypothesis_type.strip(),
            hypothesis_text,
            payload.why_it_matters.strip(),
            payload.confidence_before_validation.strip(),
        ])
        if question_text:
            con.execute('''
                INSERT INTO validation_questions
                (id, hypothesis_id, question, question_type, expected_signal)
                VALUES (?, ?, ?, 'interview', 'Look for repeated current behavior, workaround strength, and willingness to change.')
            ''', [question_id, hypothesis_id, question_text])
    finally:
        con.close()

    return {
        'segment': {
            'id': segment_id,
            'segment_name': workspace_name,
            'rationale': payload.rationale,
            'sample_size': sample_size,
        },
        'hypothesis': {
            'segment_id': segment_id,
            'hypothesis_id': hypothesis_id,
            'hypothesis_type': payload.hypothesis_type,
            'hypothesis': hypothesis_text,
            'why_it_matters': payload.why_it_matters,
            'confidence_before_validation': payload.confidence_before_validation,
            'questions': ([{'id': question_id, 'question': question_text, 'expected_signal': 'Look for repeated current behavior, workaround strength, and willingness to change.'}] if question_text else []),
        },
    }


@app.get('/api/personas')
def personas(
    segment_id: str | None = None,
    q: str | None = Query(default=None, min_length=1),
    province: str | None = None,
    min_age: int = Query(default=20, ge=0, le=120),
    max_age: int = Query(default=64, ge=0, le=120),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    if min_age > max_age:
        raise HTTPException(status_code=400, detail='min_age must be <= max_age')
    con = connect()
    try:
        where_parts = ['age BETWEEN ? AND ?']
        params: list[Any] = [min_age, max_age]
        if segment_id:
            where_parts.append(f'({get_segment_filter(con, segment_id)})')
        if province:
            where_parts.append('province = ?')
            params.append(province)
        if q:
            like = f'%{q}%'
            where_parts.append('(persona LIKE ? OR professional_persona LIKE ? OR culinary_persona LIKE ? OR occupation LIKE ? OR district LIKE ? OR province LIKE ?)')
            params.extend([like, like, like, like, like, like])
        params.append(limit)
        rows = rows_as_dicts(con, f'''
            SELECT uuid, age, sex, province, district, occupation,
                   persona, professional_persona, culinary_persona
            FROM personas_summary
            WHERE {' AND '.join(where_parts)}
            ORDER BY random()
            LIMIT ?
        ''', params)
    finally:
        con.close()
    return {'personas': rows}


@app.post('/api/persona-search')
def persona_search(payload: CustomerPersonaRequest) -> dict[str, Any]:
    if payload.min_age > payload.max_age:
        raise HTTPException(status_code=400, detail='min_age must be <= max_age')
    keywords = extract_keywords(payload.business_idea, payload.extra_keywords)
    match_sql, match_params = persona_match_clause(keywords)
    where_parts = ['age BETWEEN ? AND ?', match_sql]
    params: list[Any] = [payload.min_age, payload.max_age, *match_params]
    if payload.province:
        where_parts.append('province = ?')
        params.append(payload.province.strip())
    params.append(max(payload.target_count * 5, 20))
    con = connect()
    try:
        rows = rows_as_dicts(con, f'''
            SELECT uuid, age, sex, province, district, occupation,
                   persona, professional_persona, culinary_persona
            FROM personas_summary
            WHERE {' AND '.join(where_parts)}
            LIMIT ?
        ''', params)
    finally:
        con.close()
    scored = []
    for row in rows:
        haystack = ' '.join(str(row.get(field, '')).lower() for field in ['persona', 'professional_persona', 'culinary_persona', 'occupation', 'district', 'province'])
        score = sum(1 for keyword in keywords if keyword in haystack)
        scored.append({'score': score, **row})
    scored.sort(key=lambda item: (-item['score'], item['uuid']))
    return {
        'business_idea': payload.business_idea,
        'search_basis': {
            'keywords': keywords,
            'province': payload.province,
            'age_range': [payload.min_age, payload.max_age],
            'matched_count': len(scored),
        },
        'matches': scored[:payload.target_count],
    }


@app.post('/api/customer-personas')
def create_customer_personas(payload: CustomerPersonaRequest) -> dict[str, Any]:
    search_result = persona_search(payload)
    keywords = search_result['search_basis']['keywords']
    personas_generated = [
        build_customer_persona(row, payload.business_idea, rank=index + 1, keywords=keywords)
        for index, row in enumerate(search_result['matches'])
    ]
    return {
        'business_idea': payload.business_idea,
        'search_basis': search_result['search_basis'],
        'customer_personas': personas_generated,
        'synthetic_disclaimer': '합성 페르소나 기반 생성 결과이며 실제 고객 수요 증거가 아닙니다.',
    }


@app.post('/api/virtual-interviews')
def virtual_interview(payload: VirtualInterviewRequest) -> dict[str, Any]:
    persona = payload.customer_persona
    answer = answer_as_persona(persona, payload.question.strip())
    return {
        'persona_id': persona.get('id'),
        'persona_name': persona.get('name'),
        'question': payload.question.strip(),
        'answer': answer,
        'follow_up_questions': [
            '최근 실제로 같은 상황을 겪은 사례를 하나만 말해주실 수 있나요?',
            '현재는 어떤 대안이나 우회 방법을 쓰고 있나요?',
            '그 대안을 바꾸려면 어떤 조건이 필요할까요?',
        ],
        'synthetic_disclaimer': '합성 페르소나 기반 가상 인터뷰입니다. 실제 검증으로 확정해야 합니다.',
    }


@app.get('/api/hypotheses')
def hypotheses(segment_id: str | None = None) -> dict[str, Any]:
    con = connect()
    try:
        params: list[Any] = []
        where = '1=1'
        if segment_id:
            where += ' AND s.id = ?'
            params.append(segment_id)
        rows = rows_as_dicts(con, f'''
            SELECT s.id AS segment_id, s.segment_name, h.id AS hypothesis_id,
                   h.hypothesis_type, h.hypothesis, h.why_it_matters,
                   h.confidence_before_validation, q.id AS question_id,
                   q.question, q.expected_signal
            FROM persona_segments s
            JOIN persona_hypotheses h ON h.segment_id = s.id
            LEFT JOIN validation_questions q ON q.hypothesis_id = h.id
            WHERE {where}
            ORDER BY s.sample_size DESC, h.id, q.id
        ''', params)
    finally:
        con.close()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = grouped.setdefault(row['hypothesis_id'], {
            'segment_id': row['segment_id'],
            'segment_name': row['segment_name'],
            'hypothesis_id': row['hypothesis_id'],
            'hypothesis_type': row['hypothesis_type'],
            'hypothesis': row['hypothesis'],
            'why_it_matters': row['why_it_matters'],
            'confidence_before_validation': row['confidence_before_validation'],
            'questions': [],
        })
        if row['question_id']:
            item['questions'].append({'id': row['question_id'], 'question': row['question'], 'expected_signal': row['expected_signal']})
    return {'segment_id': segment_id, 'hypotheses': list(grouped.values())}


@app.get('/api/validation-results')
def list_validation_results(hypothesis_id: str | None = None) -> dict[str, Any]:
    con = connect()
    try:
        params: list[Any] = []
        where = '1=1'
        if hypothesis_id:
            where += ' AND hypothesis_id = ?'
            params.append(hypothesis_id)
        rows = rows_as_dicts(con, f'''
            SELECT id, hypothesis_id, method, respondent_profile, result_summary,
                   evidence_level, validated, created_at
            FROM validation_results
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT 100
        ''', params)
    finally:
        con.close()
    return {'results': rows}


@app.post('/api/validation-results')
def create_validation_result(payload: ValidationResultIn) -> dict[str, Any]:
    seed = '|'.join([payload.hypothesis_id, payload.method, payload.respondent_profile, payload.result_summary, datetime.now(timezone.utc).isoformat()])
    result_id = 'vr_' + hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]
    con = connect(read_only=False)
    try:
        exists = con.execute('SELECT COUNT(*) FROM persona_hypotheses WHERE id = ?', [payload.hypothesis_id]).fetchone()[0]
        if not exists:
            raise HTTPException(status_code=404, detail=f'Unknown hypothesis_id: {payload.hypothesis_id}')
        con.execute('''
            INSERT INTO validation_results
            (id, hypothesis_id, method, respondent_profile, result_summary, evidence_level, validated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', [result_id, payload.hypothesis_id, payload.method, payload.respondent_profile, payload.result_summary, payload.evidence_level, payload.validated])
    finally:
        con.close()
    return {'id': result_id, **payload.model_dump()}
