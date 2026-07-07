from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

EXPECTED_COLUMNS = [
    'uuid', 'professional_persona', 'sports_persona', 'arts_persona',
    'travel_persona', 'culinary_persona', 'family_persona', 'persona',
    'cultural_background', 'skills_and_expertise', 'skills_and_expertise_list',
    'hobbies_and_interests', 'hobbies_and_interests_list',
    'career_goals_and_ambitions', 'sex', 'age', 'marital_status',
    'military_status', 'family_type', 'housing_type', 'education_level',
    'bachelors_field', 'occupation', 'district', 'province', 'country',
]


def build(dataset_dir: Path, db_path: Path) -> dict:
    parquet_dir = dataset_dir / 'data'
    shards = sorted(parquet_dir.glob('*.parquet'))
    if len(shards) != 9:
        raise SystemExit(f'Expected 9 parquet shards under {parquet_dir}, found {len(shards)}')
    db_path.parent.mkdir(parents=True, exist_ok=True)
    parquet_glob = str(parquet_dir / '*.parquet')
    con = duckdb.connect(str(db_path))
    try:
        con.execute(f"""
            CREATE OR REPLACE VIEW personas_raw AS
            SELECT * FROM read_parquet('{parquet_glob}');
        """)
        columns = [row[1] for row in con.execute('PRAGMA table_info(personas_raw)').fetchall()]
        missing = [col for col in EXPECTED_COLUMNS if col not in columns]
        if missing:
            raise SystemExit(f'Missing expected columns: {missing}')
        con.execute("""
            CREATE OR REPLACE VIEW personas_summary AS
            SELECT
              uuid, sex, age,
              CASE
                WHEN age BETWEEN 0 AND 19 THEN '0-19'
                WHEN age BETWEEN 20 AND 29 THEN '20-29'
                WHEN age BETWEEN 30 AND 39 THEN '30-39'
                WHEN age BETWEEN 40 AND 49 THEN '40-49'
                WHEN age BETWEEN 50 AND 59 THEN '50-59'
                WHEN age BETWEEN 60 AND 69 THEN '60-69'
                ELSE '70+'
              END AS age_band,
              marital_status, military_status, family_type, housing_type,
              education_level, bachelors_field, occupation, district,
              province, country, persona, professional_persona,
              culinary_persona, hobbies_and_interests,
              career_goals_and_ambitions
            FROM personas_raw;
        """)
        report = {
            'created_at': datetime.now(timezone.utc).isoformat(),
            'dataset_dir': str(dataset_dir),
            'db_path': str(db_path),
            'parquet_files': len(shards),
            'row_count': con.execute('SELECT COUNT(*) FROM personas_raw').fetchone()[0],
            'distinct_uuid_count': con.execute('SELECT COUNT(DISTINCT uuid) FROM personas_raw').fetchone()[0],
            'columns': columns,
        }
        (db_path.parent / 'build_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset-dir', type=Path, default=Path('./data'))
    parser.add_argument('--db-path', type=Path, default=Path('./db/nemotron_personas_ko.duckdb'))
    args = parser.parse_args()
    print(json.dumps(build(args.dataset_dir.resolve(), args.db_path.resolve()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
