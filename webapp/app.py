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
