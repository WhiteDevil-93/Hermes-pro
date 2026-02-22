"""Fail CI when Bandit findings are not triaged."""

from __future__ import annotations

import json
from pathlib import Path

RESULTS_PATH = Path("bandit-results.json")
TRIAGE_PATH = Path("security/bandit-triage.json")


def _key(result: dict) -> str:
    return f"{result.get('test_id')}|{result.get('filename')}|{result.get('line_number')}"


def main() -> int:
    results = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else {}
    triage_payload = (
        json.loads(TRIAGE_PATH.read_text())
        if TRIAGE_PATH.exists()
        else {"accepted": []}
    )

    triaged = {entry["finding"]: entry for entry in triage_payload.get("accepted", [])}
    findings = results.get("results", [])

    untriaged: list[str] = []
    expired: list[str] = []

    for finding in findings:
        finding_key = _key(finding)
        triage = triaged.get(finding_key)
        if not triage:
            untriaged.append(finding_key)
            continue
        expires_at = triage.get("expires_at", "")
        if expires_at and expires_at < "9999-12-31":
            expired.append(finding_key)

    if untriaged:
        print("Untriaged Bandit findings:")
        for item in untriaged:
            print(f"- {item}")
        return 1

    if expired:
        print("Triaged findings have explicit expiry dates. Review before merge:")
        for item in expired:
            print(f"- {item}")

    print(f"Bandit triage validated. Findings: {len(findings)}, triaged: {len(triaged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
