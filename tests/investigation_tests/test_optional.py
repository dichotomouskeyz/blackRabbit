"""RI-008: ordinary backend and help work with the entire agent SDK absent.

These tests intentionally do not importorskip. A fresh subprocess forbids SDK
and provider imports even when the parent environment installed the agent extra.
"""

import os
import subprocess
import sys
from pathlib import Path

_DENY_AGENT_IMPORTS = """
import importlib.abc
import sys

class NoAgentSDK(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'pydantic_ai', 'openai', 'anthropic'}:
            raise ModuleNotFoundError('optional SDK intentionally absent', name=fullname)

sys.meta_path.insert(0, NoAgentSDK())
"""


def _without_sdk(script):
    env = dict(os.environ, PYTHON_DOTENV_DISABLED="1")
    return subprocess.run(
        [sys.executable, "-c", _DENY_AGENT_IMPORTS + "\n" + script],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_base_imports_do_not_require_agent_sdk():
    result = _without_sdk("""
import api.app
import capture
import batch.arc
import investigation
assert not any(name.startswith(('pydantic_ai', 'openai', 'anthropic')) for name in sys.modules)
print('base imports succeeded')
""")
    assert result.returncode == 0, result.stderr
    assert "base imports succeeded" in result.stdout


def test_cli_help_without_agent_sdk():
    result = _without_sdk("""
import runpy
sys.argv = ['investigation', '--help']
runpy.run_module('investigation', run_name='__main__')
""")
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert "--session-id" in result.stdout


def test_agent_endpoint_returns_structured_503_without_sdk():
    result = _without_sdk("""
from fastapi.testclient import TestClient
from api import deps
from api.app import create_app
app = create_app()
app.dependency_overrides[deps.get_tenant_context] = lambda: deps.TenantContext(
    '00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002')
with TestClient(app) as client:
    response = client.post('/agent/chat', json={
        'message': 'Inspect', 'session_id': '00000000-0000-4000-8000-000000000003'})
assert response.status_code == 503, response.text
assert response.json()['error'] == 'agent_unavailable', response.text
print('structured optional SDK failure')
""")
    assert result.returncode == 0, result.stderr
    assert "structured optional SDK failure" in result.stdout
