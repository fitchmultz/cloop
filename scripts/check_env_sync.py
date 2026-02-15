#!/usr/bin/env python3
"""
Purpose: Validate .env.example contains all non-sensitive settings from settings.py
Responsibilities:
  - Parse settings.py for os.getenv() calls with CLOOP_ prefix
  - Parse .env.example for documented variable names
  - Compare and report missing/extra variables
  - Allowlist sensitive vars that only need placeholders
Non-scope: Does not validate default values match

Exit Codes:
  0 - All non-sensitive settings are documented in .env.example
  1 - Missing settings or file not found

Examples:
  # Run from repo root
  uv run python scripts/check_env_sync.py

  # As part of make check
  make env-sync
"""

import argparse
import re
import sys
from pathlib import Path

# Variables that only need placeholder entries (sensitive or external)
SENSITIVE_VARS = {
    "CLOOP_OPENAI_API_KEY",
    "CLOOP_GOOGLE_API_KEY",
    "LITELLM_API_KEY",
}


def extract_env_vars_from_settings(settings_path: Path) -> set[str]:
    """Extract all CLOOP_* env var names from settings.py os.getenv() calls."""
    content = settings_path.read_text()
    # Match os.getenv("VAR_NAME" or os.getenv('VAR_NAME'
    pattern = r'os\.getenv\(["\']([A-Z_][A-Z0-9_]*)["\']'
    return set(re.findall(pattern, content))


def extract_env_vars_from_example(example_path: Path) -> set[str]:
    """Extract all variable names from .env.example (lines with =, commented or not)."""
    content = example_path.read_text()
    # Match VAR_NAME= at start of line (ignoring # comment prefix and whitespace)
    pattern = r"^[\s#]*([A-Z_][A-Z0-9_]*)="
    return set(re.findall(pattern, content, re.MULTILINE))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate .env.example sync with settings.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit Codes:
  0 - All non-sensitive settings documented
  1 - Missing settings or file errors

Examples:
  uv run python scripts/check_env_sync.py
  make env-sync
        """,
    )
    parser.parse_args()

    repo_root = Path(__file__).parent.parent
    settings_path = repo_root / "src" / "cloop" / "settings.py"
    example_path = repo_root / ".env.example"

    if not settings_path.exists():
        print(f"ERROR: {settings_path} not found", file=sys.stderr)
        return 1
    if not example_path.exists():
        print(f"ERROR: {example_path} not found", file=sys.stderr)
        return 1

    settings_vars = extract_env_vars_from_settings(settings_path)
    example_vars = extract_env_vars_from_example(example_path)

    # Filter out sensitive vars from the check (they only need placeholders)
    required_vars = settings_vars - SENSITIVE_VARS

    missing = required_vars - example_vars
    if missing:
        print("ERROR: The following settings are missing from .env.example:", file=sys.stderr)
        for var in sorted(missing):
            print(f"  - {var}", file=sys.stderr)
        print(f"\nTotal: {len(missing)} missing variable(s)", file=sys.stderr)
        print("Please add them to .env.example with their default values.", file=sys.stderr)
        return 1

    # Check that sensitive vars at least have placeholder entries
    missing_sensitive = SENSITIVE_VARS - example_vars
    if missing_sensitive:
        print("WARNING: Sensitive vars missing placeholder entries:", file=sys.stderr)
        for var in sorted(missing_sensitive):
            print(f"  - {var}", file=sys.stderr)

    count = len(required_vars)
    print(f"OK: .env.example contains all {count} non-sensitive settings from settings.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
