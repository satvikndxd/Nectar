# Evaluation

All data is **synthetic**, produced by `data/generators` (generator version 1.0.0).
Performance on synthetic data does not imply real-world performance.

The full benchmark harness (Section 16 of `instructions.md`) is **not built yet**. This
file currently records only the detector calibration runs below.

## Payment-failure detector calibration

Configuration: `ProportionShiftDetector` defaults (6 h current window, 72 h trailing
baseline, z ≥ 5.0, relative change ≥ 25%, ≥ 30 observations per window), run via
`monitor()` over the metric and every single-dimension slice (platform, payment
method, app version), hourly buckets.

Worlds: the reference scenario `ref-001-android-visa-payment-regression`, plus clean
worlds with the same configuration and no faults, differing only by seed.

Reproduce:

```bash
uv run python scripts/detector_calibration.py --seeds 20 --seed-offset 0 \
    --out docs/eval-runs/detector_calibration_tuning.json
uv run python scripts/detector_calibration.py --seeds 20 --seed-offset 1000 \
    --out docs/eval-runs/detector_calibration_heldout.json
```

| Split | Seeds | Clean worlds with ≥1 detection | Max slice score in a clean world | Artifact |
|---|---|---|---|---|
| Tuning (threshold chosen by looking at these) | 1–20 | 0 / 20 | 4.424 | [`detector_calibration_tuning.json`](eval-runs/detector_calibration_tuning.json) |
| Held-out | 1001–1020 | **1 / 20** (seed 1020, `platform=android`) | 7.196 | [`detector_calibration_heldout.json`](eval-runs/detector_calibration_heldout.json) |

Reference scenario (both runs): fault onset 2026-09-06T14:00Z; first detection at
2026-09-06T19:00Z (5 h time-to-detect, bounded below by the 6 h window design) on the
`payment_method=visa` slice; peak slice score 6.521 (`platform=android`).

### What these numbers do and do not say

- 20 clean worlds per split is a tiny sample: "1 / 20" is consistent with a false-world
  rate anywhere from roughly 0.1% to 25% (exact binomial 95% interval). Neither split
  supports a precise false-positive-rate claim.
- The margin between clean and faulted scores is small (tuning max 4.42 vs. faulted
  peak 6.52), and the held-out false positive *exceeds* the faulted peak.
- **Known weakness (open):** the held-out false positive occurs in overnight windows
  with 31–47 android attempts and ~0.5 expected failures. In that regime the normal
  approximation behind the z-test overstates significance, and the slice baseline
  (1.45%, estimated from ~800 attempts) is itself noisy; the test treats it as exact
  in the variance only through pooling. Candidate fixes, not yet implemented: an exact
  binomial / beta-binomial tail test for small expected counts, and accounting for
  retry clustering (a failed attempt raises the chance of a second failed attempt).
- The metric-level series alone does not separate faulted from clean worlds at this
  traffic level (the fault touches ~14% of attempts); this is why slice monitoring is
  the default.
- `RobustZScoreDetector` is not used for this metric: at ~30 attempts/hour a single
  failure moves an hourly rate by ~3 percentage points, so per-bucket rate scores are
  dominated by count noise. It is unit-tested but not yet benchmarked.
