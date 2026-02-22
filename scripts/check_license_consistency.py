#!/usr/bin/env python3
"""Verify license references in docs and package metadata match LICENSE."""

from __future__ import annotations

from pathlib import Path
import tomllib
import sys

ROOT = Path(__file__).resolve().parents[1]
LICENSE_FILE = ROOT / "LICENSE"
README_FILE = ROOT / "README.md"
CONTRIBUTING_FILE = ROOT / "CONTRIBUTING.md"
PYPROJECT_FILE = ROOT / "pyproject.toml"


def canonical_license_name() -> str:
    lines = LICENSE_FILE.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].strip():
        raise ValueError("LICENSE file is empty or missing header")
    return lines[0].strip()


def contains_license_reference(path: Path, canonical_name: str) -> bool:
    text = path.read_text(encoding="utf-8")
    return canonical_name in text


def pyproject_matches_mit(path: Path, canonical_name: str) -> tuple[bool, str]:
    text = path.read_text(encoding="utf-8")
    expected_text_value = 'license = { text = "MIT" }'
    expected_classifier = '"License :: OSI Approved :: MIT License"'

    has_license = expected_text_value in text
    has_classifier = expected_classifier in text

    if canonical_name == "MIT License":
        ok = has_license and has_classifier
        msg = (
            f"expected `{expected_text_value}` and classifier {expected_classifier}"
            if not ok
            else "ok"
        )
        return ok, msg

    # Fallback for non-MIT repos: ensure a license field exists at least.
    has_any_license_field = bool(re.search(r"^license\s*=\s*", text, flags=re.MULTILINE))
    return has_any_license_field, "expected a `license = ...` entry"


def main() -> int:
    canonical_name = canonical_license_name()
    checks = [
        (README_FILE, contains_license_reference(README_FILE, canonical_name), f"must mention `{canonical_name}`"),
        (
            CONTRIBUTING_FILE,
            contains_license_reference(CONTRIBUTING_FILE, canonical_name),
            f"must mention `{canonical_name}`",
        ),
    ]

    py_ok, py_message = pyproject_matches_mit(PYPROJECT_FILE, canonical_name)
    checks.append((PYPROJECT_FILE, py_ok, py_message))

    failures = []
    for path, ok, message in checks:
        status = "OK" if ok else "FAIL"
        print(f"{status}: {path.relative_to(ROOT)}")
        if not ok:
            failures.append(f"{path.relative_to(ROOT)}: {message}")

    if failures:
        print("\nLicense consistency check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"\nLicense references are consistent with {LICENSE_FILE.name} ({canonical_name}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
