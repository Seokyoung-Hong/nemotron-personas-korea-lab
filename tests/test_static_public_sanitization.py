from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_repository_keeps_generated_private_artifacts_untracked():
    gitignore = (ROOT / '.gitignore').read_text(encoding='utf-8')
    for pattern in ['data/', 'dataset/', 'datasets/', 'db/', 'exports/', '.env']:
        assert pattern in gitignore


def test_gitignore_excludes_large_and_private_outputs():
    gitignore = (ROOT / '.gitignore').read_text(encoding='utf-8')
    for pattern in ['*.parquet', 'data/', 'db/', 'exports/', '.env']:
        assert pattern in gitignore


def test_static_ui_files_exist():
    assert (ROOT / 'webapp' / 'static' / 'index.html').is_file()
    assert (ROOT / 'webapp' / 'static' / 'app.css').is_file()
    assert (ROOT / 'webapp' / 'static' / 'app.js').is_file()
