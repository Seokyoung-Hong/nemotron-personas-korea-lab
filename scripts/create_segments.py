from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

SEGMENTS = [
    {
        'id': 'workplace_meal_repeat_users',
        'segment_name': 'Workplace meal repeat users',
        'filter_sql': """SELECT * FROM personas_summary
WHERE age BETWEEN 20 AND 64
  AND occupation IS NOT NULL
  AND (
    culinary_persona LIKE '%점심%' OR culinary_persona LIKE '%식당%'
    OR culinary_persona LIKE '%한식%' OR culinary_persona LIKE '%외식%'
    OR culinary_persona LIKE '%배달%'
  )""",
        'rationale': 'People whose food/lifestyle personas mention lunch, restaurants, Korean meals, dining out, or delivery.',
        'hypothesis': 'Workplace meal repeat users choose restaurants by combining today menu, distance, price, and peer preference.',
        'questions': [
            'When choosing lunch, what do you check first: menu, price, distance, or waiting time?',
            'Would seeing today menu in advance make the decision faster?',
        ],
    },
    {
        'id': 'industrial_shift_workers',
        'segment_name': 'Industrial and shift-work candidates',
        'filter_sql': """SELECT * FROM personas_summary
WHERE age BETWEEN 20 AND 64
  AND occupation IS NOT NULL
  AND (
    occupation LIKE '%기계%' OR occupation LIKE '%생산%' OR occupation LIKE '%운전%'
    OR occupation LIKE '%하역%' OR occupation LIKE '%정비%' OR occupation LIKE '%안전%'
    OR occupation LIKE '%전기%' OR occupation LIKE '%용접%' OR occupation LIKE '%공장%'
  )""",
        'rationale': 'Operational, logistics, maintenance, driving, and industrial candidates who may have repeated workplace meal routines.',
        'hypothesis': 'Industrial and shift-work users experience friction because today menu information is scattered across signs, messages, and coworkers.',
        'questions': [
            'How do you usually check today menu before lunch?',
            'In the last week, did missing menu information change where you ate?',
        ],
    },
    {
        'id': 'office_group_decision_users',
        'segment_name': 'Office group-decision candidates',
        'filter_sql': """SELECT * FROM personas_summary
WHERE age BETWEEN 20 AND 64
  AND occupation IS NOT NULL
  AND (
    occupation LIKE '%사무%' OR occupation LIKE '%경리%' OR occupation LIKE '%비서%'
    OR occupation LIKE '%상담%' OR occupation LIKE '%영업%'
  )""",
        'rationale': 'Office and support roles that may decide lunch with coworkers and need shareable options.',
        'hypothesis': 'Office users want a shareable today-menu list to quickly align with coworkers.',
        'questions': [
            'Do you decide lunch alone or with coworkers?',
            'Would you share a today-menu link or image with coworkers?',
        ],
    },
]


def create_tables(db_path: Path) -> None:
    con = duckdb.connect(str(db_path))
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS business_contexts (
              id VARCHAR PRIMARY KEY,
              business_name VARCHAR,
              problem_statement VARCHAR,
              service_description VARCHAR,
              created_at TIMESTAMP DEFAULT now()
            );
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS persona_segments (
              id VARCHAR PRIMARY KEY,
              business_context_id VARCHAR,
              segment_name VARCHAR,
              filter_sql VARCHAR,
              rationale VARCHAR,
              sample_size BIGINT,
              created_at TIMESTAMP DEFAULT now()
            );
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS persona_hypotheses (
              id VARCHAR PRIMARY KEY,
              segment_id VARCHAR,
              hypothesis_type VARCHAR,
              hypothesis VARCHAR,
              why_it_matters VARCHAR,
              confidence_before_validation VARCHAR,
              created_at TIMESTAMP DEFAULT now()
            );
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS validation_questions (
              id VARCHAR PRIMARY KEY,
              hypothesis_id VARCHAR,
              question VARCHAR,
              question_type VARCHAR,
              expected_signal VARCHAR,
              created_at TIMESTAMP DEFAULT now()
            );
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS validation_results (
              id VARCHAR PRIMARY KEY,
              hypothesis_id VARCHAR,
              method VARCHAR,
              respondent_profile VARCHAR,
              result_summary VARCHAR,
              evidence_level VARCHAR,
              validated BOOLEAN,
              created_at TIMESTAMP DEFAULT now()
            );
        """)
        con.execute("""
            INSERT OR REPLACE INTO business_contexts
            (id, business_name, problem_statement, service_description)
            VALUES (
              'workplace_meal_discovery',
              'Workplace meal discovery',
              'People in recurring workplace lunch contexts may not know today menu before choosing a restaurant.',
              'A generic discovery workflow for finding meal-choice pain points and validating them with real interviews.'
            );
        """)
        con.execute("DELETE FROM validation_questions")
        con.execute("DELETE FROM persona_hypotheses")
        con.execute("DELETE FROM persona_segments WHERE business_context_id = 'workplace_meal_discovery'")
        for seg in SEGMENTS:
            sample_size = con.execute(f"SELECT COUNT(*) FROM ({seg['filter_sql']})").fetchone()[0]
            con.execute("""
                INSERT INTO persona_segments
                (id, business_context_id, segment_name, filter_sql, rationale, sample_size)
                VALUES (?, 'workplace_meal_discovery', ?, ?, ?, ?)
            """, [seg['id'], seg['segment_name'], seg['filter_sql'], seg['rationale'], sample_size])
            hyp_id = f"{seg['id']}_h1"
            con.execute("""
                INSERT INTO persona_hypotheses
                (id, segment_id, hypothesis_type, hypothesis, why_it_matters, confidence_before_validation)
                VALUES (?, ?, 'behavior', ?, 'This guides interview recruiting and validation design.', 'medium')
            """, [hyp_id, seg['id'], seg['hypothesis']])
            for i, question in enumerate(seg['questions'], 1):
                con.execute("""
                    INSERT INTO validation_questions
                    (id, hypothesis_id, question, question_type, expected_signal)
                    VALUES (?, ?, ?, 'interview', 'Look for repeated current behavior, workaround strength, and willingness to change.')
                """, [f"{hyp_id}_q{i}", hyp_id, question])
        for row in con.execute("SELECT id, sample_size FROM persona_segments ORDER BY sample_size DESC").fetchall():
            print(row[0], row[1])
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--db-path', type=Path, default=Path('./db/nemotron_personas_ko.duckdb'))
    args = parser.parse_args()
    create_tables(args.db_path.resolve())


if __name__ == '__main__':
    main()
