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
    with path.open("rb") as f:
        try:
            data = tomllib.load(f).get("project", {})
        except Exception:
            return False, "failed to parse pyproject.toml"

    if canonical_name == "MIT License":
        license_info = data.get("license", {})
        classifiers = data.get("classifiers", [])
        has_license = isinstance(license_info, dict) and license_info.get("text") == "MIT"
        has_classifier = "License :: OSI Approved :: MIT License" in classifiers

        if not (has_license and has_classifier):
            return False, "missing or incorrect MIT license metadata in [project]"
        return True, "ok"

    return "license" in data, "expected a `license` entry in [project]"


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
