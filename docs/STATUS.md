# Status

_Last updated: 2026-10-08._ Current phase: **2 (Analytics)**, started; Phase 1 partially complete.

## Done (implemented and tested)

- Versioned event contracts (`packages/schemas`), shared domain primitives
  (`packages/shared`: money, time windows, injectable clock, UUIDv7, RBAC).
- Deterministic synthetic generator with faults, distractor deployments, counterfactual
  ground truth (`data/generators`); one scenario file (`data/scenarios/ref-001…`).
- FastAPI app: settings, JWT → principal auth, health/readiness, batched event
  ingestion with idempotency keys, funnel metrics endpoint.
- Anomaly engine (`services/anomaly-engine`): rate series, proportion-shift and robust
  z-score detectors, slice monitoring, episode merging, segment localisation.
- Detector calibration script and artifacts (`scripts/`, `docs/eval-runs/`, see
  `docs/EVALUATION.md`).

## Stubbed / not real yet

- Event storage is **in-memory and process-local** (`InMemoryEventStore`); no
  PostgreSQL schema or migrations yet, although dependencies are declared.
- The anomaly engine is a library only: no API route, no persisted anomaly records,
  no scheduled detection runs, no cross-metric incident creation.
- No frontend, no `docker compose`, no CI workflow, no import-linter contracts.
- Docs referenced by code comments (`ARCHITECTURE.md`, `DATA_MODEL.md`) do not exist yet.

## Known issues

- Held-out calibration found 1 false-positive world in 20 for the payment-failure
  monitor (low-volume windows; see `docs/EVALUATION.md`).
- Trailing baselines absorb a sustained fault: an episode ends a few hours after
  detection and re-fires later. The baseline should be frozen while an episode is open.
- New slices (e.g. an app version released mid-window) have no history and are
  suppressed, so `app_version=2.8.0` cannot be flagged directly.
- `mypy` across `tests/` reports pre-existing annotation errors; source packages pass.

## Next steps

1. Fix the small-count false positive (exact/overdispersed tail test) and re-run both
   calibration splits; add more clean seeds.
2. Freeze baselines during open episodes; merge slice episodes into incidents.
3. PostgreSQL schema + migrations for events, metric definitions, anomalies.
4. API route to run detection and list anomalies; `docs/ARCHITECTURE.md`,
   `docs/DATA_MODEL.md`.
