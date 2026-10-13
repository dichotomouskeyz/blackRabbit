---
name: gen-test
description: >
  Scaffold test files for any module in this codebase — capture layer, batch/arc chain,
  or operator surface. Stubs six required test categories with dependency-injected fixtures
  and adversarial model separation. Trigger when the user says "gen-test", "scaffold tests
  for", "write tests for", or when rewriting an existing test file.
---

# gen-test

Scaffolds a complete test file for any module. Every file produced by this skill contains
the six required test categories, adversarial annotation blocks, and dependency-injected
fixtures only (no monkeypatching).

## Inputs

Before writing, collect or infer from the module source:

1. **Module path** — e.g. `batch/arc/baseline.py`
2. **DB tables written** — e.g. `session_baselines`
3. **Modalities processed** — subset of `eeg`, `hrv`, `eda`, `respiration`
4. **Constructor dependencies** — db connection factory, config loader, etc.
5. **Phase** — 2 (capture), 3b (baseline-in-batch), 4b (operator surface), 5b (ARC batch)

If the source file exists, read it to infer 2–5 rather than asking.

## Workflow

1. Read the module source and identify which of the six categories apply.
   (Category 5a applies only if the module does numerical signal computation.)
2. Read [`references/module-inventory.md`](references/module-inventory.md) to confirm
   table names and modality mappings.
3. Read [`references/fixtures.md`](references/fixtures.md) for the correct fixture chain.
4. Read [`references/categories.md`](references/categories.md) for the stub template
   for each applicable category.
5. Read [`references/adversarial-workflow.md`](references/adversarial-workflow.md) and
   embed the annotation block in every test class.
6. Output the complete test file. Do NOT fill in assertion values — leave `...` with
   `# TODO: fill via adversarial model`. Assertions come from the adversarial workflow.
7. If the module is in the `batch/arc/` chain, check whether
   `tests/capture_tests/arc/test_convergence_e2e.py` needs a corresponding update and
   flag it to the user.

## Six Test Categories (summary)

Full specs and stub templates in [`references/categories.md`](references/categories.md).

| # | Name | Scope | DB required |
|---|------|-------|-------------|
| 1 | Deterministic Baseline | known input → exact expected output | unit or integration |
| 2 | Missing Modality | graceful degradation when signals absent | unit or integration |
| 3 | Provenance Fields | every output row carries traceability metadata | integration |
| 4 | No Direct `audit_events` Writes | module never INSERTs to `audit_events` | integration |
| 5a | Component Convergence Accuracy | numerical output within ≤8% of ground truth | unit |
| 5b | End-to-End Pipeline Accuracy | full chain synthetic session → ECPs within tolerance | integration |

Skip 5a with a comment if the module does no numerical computation.
Category 5b lives in `tests/capture_tests/arc/test_convergence_e2e.py`, not in the
per-module file.

## Output Shape

```
tests/capture_tests/<domain>/test_<module>.py
```

Contents:
- Module docstring: what is tested, which phase
- Import block referencing the module under test and fixtures
- Six test class stubs (or five with a skip comment for 5a)
- `ASSERTION SOURCE` block in every class
- Fixtures defined in the file or pulled from conftest — see fixtures reference
