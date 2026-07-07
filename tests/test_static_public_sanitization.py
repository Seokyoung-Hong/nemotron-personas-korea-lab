from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_repo_does_not_contain_private_project_terms():
    forbidden = ['my' + 'moo', '\\ub9c8\\uc774\\ubb34'.encode().decode('unicode_escape'), '\\ubaa8\\ub450\\uc758 \\ucc3d\\uc5c5'.encode().decode('unicode_escape'), '\\ubaa8\\ub450\\uc758\\ucc3d\\uc5c5'.encode().decode('unicode_escape')]
    for path in ROOT.rglob('*'):
        if path.is_file() and '.git' not in path.parts and '.venv' not in path.parts and '__pycache__' not in path.parts:
            text = path.read_text(encoding='utf-8', errors='ignore').lower()
            assert not any(term.lower() in text for term in forbidden), path


def test_gitignore_excludes_large_and_private_outputs():
    gitignore = (ROOT / '.gitignore').read_text(encoding='utf-8')
    for pattern in ['*.parquet', 'data/', 'db/', 'exports/', '.env']:
        assert pattern in gitignore


def test_static_ui_files_exist():
    assert (ROOT / 'webapp' / 'static' / 'index.html').is_file()
    assert (ROOT / 'webapp' / 'static' / 'app.css').is_file()
    assert (ROOT / 'webapp' / 'static' / 'app.js').is_file()
