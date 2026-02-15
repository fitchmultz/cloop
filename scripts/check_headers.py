#!/usr/bin/env python3
"""Validate that Python source files have proper documentation headers.

Purpose:
    Ensure all Python source files in src/cloop have Purpose/Responsibilities/Non-scope
    headers for improved code comprehension and onboarding.

Responsibilities:
    - Scan Python files for module docstrings
    - Check for presence of "Purpose" section in docstring
    - Report files missing required headers

Non-scope:
    - Enforcing specific header format (flexible matching)
    - Checking test files (different conventions)
    - Checking __init__.py files (often just imports)

Exit codes:
    0: All files have valid headers
    1: One or more files missing required header sections

Examples:
    # Run from repo root (default)
    uv run python scripts/check_headers.py

    # Verbose output showing all files
    uv run python scripts/check_headers.py -v

    # As part of make check
    make header-check
"""

import argparse
import ast
import sys
from pathlib import Path

REQUIRED_SECTIONS = ["Purpose:", "Responsibilities:", "Non-scope:"]

# Directories/files to skip
SKIP_PATTERNS = [
    "__pycache__",
    ".venv",
    "node_modules",
    "tests/",  # Tests have different conventions
]


def has_valid_header(filepath: Path) -> tuple[bool, str]:
    """Check if file has a valid documentation header."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"Could not read file: {e}"

    # Parse AST to get docstring
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"

    docstring = ast.get_docstring(tree)
    if not docstring:
        return False, "Missing module docstring"

    # Check for required sections (flexible matching)
    doc_lower = docstring.lower()
    has_purpose = "purpose" in doc_lower

    if not has_purpose:
        return False, "Missing 'Purpose' section in docstring"

    return True, "OK"


def should_check(filepath: Path) -> bool:
    """Determine if file should be checked."""
    # Skip non-Python files
    if not filepath.suffix == ".py":
        return False

    # Skip patterns
    path_str = str(filepath)
    for pattern in SKIP_PATTERNS:
        if pattern in path_str:
            return False

    # Skip __init__.py (often just imports)
    if filepath.name == "__init__.py":
        return False

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Python file headers")
    parser.add_argument(
        "paths",
        nargs="*",
        default=["src/cloop"],
        help="Paths to scan (default: src/cloop)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all files")
    args = parser.parse_args()

    all_files = []
    for path_str in args.paths:
        path = Path(path_str)
        if path.is_file():
            all_files.append(path)
        else:
            all_files.extend(path.rglob("*.py"))

    files_to_check = [f for f in all_files if should_check(f)]
    errors = []

    for filepath in files_to_check:
        valid, message = has_valid_header(filepath)
        if args.verbose:
            status = "OK" if valid else "FAIL"
            print(f"[{status}] {filepath}: {message}")
        if not valid:
            errors.append((filepath, message))

    if errors:
        print(f"\n{len(errors)} file(s) missing valid headers:\n", file=sys.stderr)
        for filepath, message in errors:
            print(f"  {filepath}: {message}", file=sys.stderr)
        return 1

    print(f"All {len(files_to_check)} files have valid headers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
