"""Calibrate the default payment-failure monitor against clean and faulted worlds.

Runs the slice monitor (with detector thresholds disabled, so every window is scored)
on the reference scenario and on N clean worlds that differ only by seed, and writes
the maximum slice score per world plus the default detector's outcome. The output is
the evidence behind the threshold choice documented in docs/EVALUATION.md.

Seeds 1-20 were used to choose the threshold (tuning split); seeds 1001-1020 were
not looked at before the threshold was fixed (held-out split).

Usage:
    uv run python scripts/detector_calibration.py --seeds 20 --seed-offset 0 \
        --out docs/eval-runs/detector_calibration_tuning.json
"""

import argparse
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from niglas_anomaly.detectors import ProportionShiftDetector
from niglas_anomaly.monitor import monitor
from niglas_anomaly.series import RateMetric, observations
from niglas_generator.config import GENERATOR_VERSION
from niglas_generator.dataset import GeneratedDataset, generate
from niglas_generator.scenarios import load_scenario

SCENARIO = Path("data/scenarios/ref-001-android-visa-payment-regression.json")
METRIC = RateMetric.PAYMENT_FAILURE_RATE
DEFAULT = ProportionShiftDetector()
SCORE_ALL = ProportionShiftDetector(z_threshold=float("-inf"), min_relative_change=0.0)


def evaluate(ds: GeneratedDataset) -> dict[str, object]:
    cfg = ds.config
    observed = observations(METRIC, ds.events)
    end = cfg.start + timedelta(hours=cfg.duration_hours)
    scored = monitor(METRIC, observed, start=cfg.start, end=end, detector=SCORE_ALL)
    best_score, best_slice = max(
        ((max((a.score for a in r.run.anomalies), default=0.0), dict(r.filters)) for r in scored),
        key=lambda item: item[0],
    )
    flagged = [
        a
        for r in monitor(METRIC, observed, start=cfg.start, end=end, detector=DEFAULT)
        for a in r.run.anomalies
    ]
    first = min(flagged, key=lambda a: a.detected_at) if flagged else None
    return {
        "seed": cfg.seed,
        "max_slice_score": round(best_score, 3),
        "max_slice": best_slice,
        "default_detector_flagged": bool(flagged),
        "first_detected_at": first.detected_at.isoformat() if first else None,
        "first_detected_slice": dict(first.filters) if first else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    spec = load_scenario(SCENARIO)
    faulted = spec.generate()
    clean = [
        evaluate(generate(config=spec.world.model_copy(update={"seed": seed})))
        for seed in range(args.seed_offset + 1, args.seed_offset + args.seeds + 1)
    ]
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607 - fixed argv, PATH lookup is fine
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    onset = faulted.ground_truth.incident_start
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": sha,
        "generator_version": GENERATOR_VERSION,
        "scenario_id": spec.scenario_id,
        "metric": METRIC.value,
        "detector": {k: v for k, v in asdict(DEFAULT).items() if not callable(v)},
        "faulted": {**evaluate(faulted), "incident_start": onset.isoformat() if onset else None},
        "clean": clean,
        "clean_false_positive_worlds": sum(c["default_detector_flagged"] is True for c in clean),
        "clean_max_slice_score": max(float(str(c["max_slice_score"])) for c in clean),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("faulted", "clean_false_positive_worlds", "clean_max_slice_score")
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
