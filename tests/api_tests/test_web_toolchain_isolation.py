"""INV-010 [integration] (B1) — the Node tree (web/) does not break the Python toolchain.

frontend-shell INV-010 decomposes into five individually-failing assertions; this
file implements all five as REAL assertions (PAT-013 / PRH-006). These run under
`uv run pytest` — a SEPARATE gate from the JS Vitest lane — which is correct for
INV-010 (it is a Python-toolchain-hygiene invariant).

These are regression guards: Phase 0 already configured .gitignore / pyproject.toml /
ruff exclude / detect-secrets exclude, so they are legitimately GREEN now and FAIL
only if that config regresses. They are not vacuous — each asserts the concrete
mechanism.

Naming for the task's selection: file matches `-k web` and `-k toolchain` and
`-k isolation`; tests carry `inv010` in their names too.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_PRECOMMIT = _REPO_ROOT / ".pre-commit-config.yaml"


def _uv() -> list[str]:
    """Resolve a runnable `uv` invocation, skipping if uv is unavailable."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not on PATH — toolchain test requires the uv runner")
    return [uv]


@pytest.fixture
def planted_web_file():
    """Provide a unique violating file without overwriting frontend work."""
    web_dir = _REPO_ROOT / "web"
    # Do not plant test artifacts outside this checkout through a linked tree.
    assert web_dir.resolve().parent == _REPO_ROOT.resolve(), "web/ must be inside the checkout"
    created_directory = not web_dir.exists()
    web_dir.mkdir(exist_ok=True)
    planted = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", prefix="inv010_", suffix=".py", dir=web_dir, encoding="utf-8", delete=False
        ) as handle:
            planted = Path(handle.name)
            # F401 + E711: deliberately invalid under the repository's E,F,I rules.
            handle.write("import os\nx = 1==None\n")
        yield planted
    finally:
        if planted is not None:
            planted.unlink(missing_ok=True)
        if created_directory:
            try:
                web_dir.rmdir()
            except OSError:
                # Another process may have added content; never remove its files.
                pass


# --- Clause (1): web/ artifact paths are gitignored ---------------------------
@pytest.mark.parametrize(
    "ignored_path",
    ["web/node_modules/", "web/.next/", "web/.env.local"],
)
def test_inv010_web_artifacts_gitignored(ignored_path):
    """Tests INV-010(1): `git check-ignore` succeeds for each web/ artifact path."""
    if shutil.which("git") is None:
        pytest.skip("git not on PATH")
    result = subprocess.run(
        ["git", "check-ignore", ignored_path],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # check-ignore exits 0 and echoes the path when it is ignored.
    assert result.returncode == 0, (
        f"{ignored_path} is NOT gitignored (git check-ignore exit "
        f"{result.returncode}); web/ build artifacts must never be committable"
    )
    assert ignored_path.replace("/", "") in result.stdout.replace("/", "").replace("\\", ""), (
        f"git check-ignore did not report {ignored_path}: {result.stdout!r}"
    )


# --- Clause (2): wheel packages is a hardcoded list NOT containing 'web' -------
def test_inv010_web_not_in_wheel_packages():
    """Tests INV-010(2): [tool.hatch.build.targets.wheel].packages is a hardcoded
    list (never glob/auto-detect, AP-024) and never includes 'web'."""
    with _PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    wheel = data["tool"]["hatch"]["build"]["targets"]["wheel"]
    packages = wheel.get("packages")
    assert isinstance(packages, list), (
        "wheel packages must be a hardcoded list (AP-024 — never glob/auto-detect)"
    )
    assert all(isinstance(p, str) for p in packages)
    assert "web" not in packages, "web/ must never be packaged into the Python wheel"
    # No globbing constructs that could sweep web/ in.
    assert not any("*" in p or p == "." for p in packages), (
        f"wheel packages must be explicit dir names, got: {packages}"
    )


# --- Clause (3): a uniquely planted web/ Python file is NOT flagged -----------
def test_inv010_ruff_excludes_web_tree(planted_web_file):
    """Tests INV-010(3): ruff `extend-exclude` covers web/, so a planted file with
    a deliberate violation is NOT flagged (web/ is out of Python lint scope)."""
    uv = _uv()
    result = subprocess.run(
        [
            *uv,
            "run",
            "--frozen",
            "python",
            "-m",
            "ruff",
            "check",
            planted_web_file.relative_to(_REPO_ROOT).as_posix(),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    # ruff exits 0 when the path is excluded (nothing to check). A nonzero exit
    # or any rule code in stdout means web/ re-entered Python lint scope.
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"ruff flagged a planted web/ file (exit {result.returncode}); web/ "
        f"must be excluded from Python lint scope:\n{combined}"
    )
    assert not re.search(r"\b[EFI]\d{3}\b", result.stdout), (
        f"ruff reported violations in excluded web/: {result.stdout!r}"
    )


# --- Clause (4): detect-secrets excludes web/ lockfiles/bundles ---------------
def test_inv010_detect_secrets_excludes_web():
    """Tests INV-010(4): the pre-commit detect-secrets `exclude` regex matches web/
    lockfiles and bundle paths so commits aren't blocked by web/ artifacts."""
    text = _PRECOMMIT.read_text(encoding="utf-8")
    # Find the detect-secrets hook block and its exclude regex.
    assert "detect-secrets" in text, "detect-secrets hook missing from pre-commit"
    m = re.search(r"id:\s*detect-secrets.*?exclude:\s*(.+)", text, re.DOTALL)
    assert m, "detect-secrets hook has no exclude regex"
    # The exclude line is the first line of the captured group.
    exclude_src = m.group(1).splitlines()[0].strip().strip("\"'")
    pattern = re.compile(exclude_src)
    # The exclude must match representative web/ paths that would otherwise trip
    # high-entropy/secret heuristics on commit.
    for sample in ("web/pnpm-lock.yaml", "web/node_modules/x/y.js", "web/.next/static/a.js"):
        assert pattern.search(sample), (
            f"detect-secrets exclude {exclude_src!r} does not match {sample}"
        )


# --- Clause (5): repo Ruff exits 0 with web/ independently provisioned --------
def test_inv010_ruff_check_repo_green_with_web_present(planted_web_file):
    """Tests INV-010(5): repo Ruff exits 0 with web/ on disk — web/
    must not pull the repo lint red."""
    uv = _uv()
    # The fixture works even when this test is selected alone on a clean checkout.
    assert planted_web_file.is_file()
    result = subprocess.run(
        [*uv, "run", "--frozen", "python", "-m", "ruff", "check", "."],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "`uv run --frozen python -m ruff check .` is not green with web/ present:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_inv010_python_version_has_tomllib():
    """Sanity: this gate parses pyproject with stdlib tomllib (py3.11+)."""
    assert sys.version_info >= (3, 11)
