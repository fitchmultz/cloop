"""Purpose: Validate repository secret scanning safeguards.
Responsibilities:
  - Verify pattern-based detection for supported secret formats.
  - Verify tracked-file-only scanning behavior via CLI integration runs.
  - Verify JSON output contract for automation workflows.
Non-scope: Exhaustive secret taxonomy or git history rewrite validation.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


def _load_check_secrets_module() -> ModuleType:
    """Load scripts/check_secrets.py as a module for direct function tests."""
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"
    spec = importlib.util.spec_from_file_location("check_secrets", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _init_git_repo(path: Path) -> None:
    """Initialize a git repository suitable for ls-files based checks."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def _run_check_secrets(repo_root: Path) -> subprocess.CompletedProcess[str]:
    """Run check_secrets.py against an arbitrary repo root."""
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"
    return subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--repo-root",
            str(repo_root),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_scan_text_for_secrets_detects_google_key() -> None:
    module = _load_check_secrets_module()
    findings = module.scan_text_for_secrets(
        "CLOOP_GOOGLE_API_KEY=AIza" + ("A" * 35),
        "config.env",
    )

    assert len(findings) == 1
    assert findings[0].rule_id == "google_api_key"


def test_scan_text_for_secrets_detects_private_key_block() -> None:
    module = _load_check_secrets_module()
    private_key_header = "-----BEGIN " + "PRIVATE KEY-----"
    private_key_footer = "-----END " + "PRIVATE KEY-----"
    findings = module.scan_text_for_secrets(
        f"{private_key_header}\nabc\n{private_key_footer}",
        "secret.pem",
    )

    assert len(findings) == 1
    assert findings[0].rule_id == "private_key_block"


def test_scan_text_for_secrets_skips_clean_content() -> None:
    module = _load_check_secrets_module()
    findings = module.scan_text_for_secrets(
        "CLOOP_LLM_MODEL=ollama/llama3",
        "clean.env",
    )

    assert findings == []


def test_check_secrets_cli_ignores_untracked_files(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)

    (tmp_path / "tracked.txt").write_text("hello", encoding="utf-8")
    # Untracked secret should not be scanned.
    (tmp_path / "leak.txt").write_text(
        "CLOOP_GOOGLE_API_KEY=AIza" + ("B" * 35),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True)

    result = _run_check_secrets(tmp_path)
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["finding_count"] == 0


def test_check_secrets_cli_flags_tracked_secrets(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)

    fake_openai_key = "sk-" + ("1234567890" * 3)
    (tmp_path / "tracked_secret.txt").write_text(
        f"api={fake_openai_key}",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "tracked_secret.txt"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    result = _run_check_secrets(tmp_path)
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["ok"] is False
    assert payload["finding_count"] == 1
    assert payload["findings"][0]["path"] == "tracked_secret.txt"
    assert payload["findings"][0]["rule_id"] == "openai_like_key"
