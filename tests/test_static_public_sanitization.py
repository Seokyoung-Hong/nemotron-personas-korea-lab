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


def test_new_workspace_button_is_wired_to_api():
    index_html = (ROOT / 'webapp' / 'static' / 'index.html').read_text(encoding='utf-8')
    app_js = (ROOT / 'webapp' / 'static' / 'app.js').read_text(encoding='utf-8')
    assert 'id="newWorkspaceBtn"' in index_html
    assert 'id="workspaceForm"' in index_html
    assert 'id="workspaceNameInput"' in index_html
    assert 'id="workspaceHypothesisInput"' in index_html
    assert "$('newWorkspaceBtn').addEventListener('click'" in app_js
    assert "$('workspaceForm').addEventListener('submit'" in app_js
    assert "api('/api/workspaces'" in app_js
    assert 'window.prompt' not in app_js
