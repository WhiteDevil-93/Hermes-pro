# Bandit Baseline Burn-down Plan

## Goal
- Move from baseline-assisted enforcement to full enforcement without baseline exceptions.

## Current rollout
- CI gate fails only on **new HIGH severity + HIGH confidence** findings.
- Existing findings can be tracked in `.github/security/bandit-baseline.json`.

## Burn-down phases
1. **Week 1-2**
   - Triage findings and assign owners by module.
   - Remove fixed entries from baseline in each PR.
2. **Week 3-4**
   - Expand gate to include `--severity-level medium` with `--confidence-level high`.
3. **Week 5+**
   - Enforce without baseline file for protected branches.
   - Keep baseline disabled except temporary emergency exceptions.

## Maintenance rules
- Any PR that fixes a baseline finding must update the baseline file in the same PR.
- Do not add new baseline entries without documenting justification in the PR description.
- Rebuild the baseline only after a reviewed security triage.
