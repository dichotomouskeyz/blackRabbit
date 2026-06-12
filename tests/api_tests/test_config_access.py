"""INV-011 [unit] — api/ reads config via config.settings, not os.environ/os.getenv.

PAT-002: no direct env access in application code. (NEXT_PUBLIC_* lives only in
the JS env, not in api/.)
"""

import pathlib
import re

_API_DIR = pathlib.Path(__file__).resolve().parents[2] / "api"
_FORBIDDEN = re.compile(r"\bos\.(environ|getenv)\b|\bload_dotenv\b")


def test_api_modules_do_not_access_env_directly():
    # Tests INV-011 [unit]: no os.environ/os.getenv/load_dotenv anywhere in api/.
    offenders = []
    for path in _API_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _FORBIDDEN.search(line):
                offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert not offenders, (
        "INV-011/PAT-002: api/ must read config via config.settings, not env directly:\n"
        + "\n".join(offenders)
    )
