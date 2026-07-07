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
