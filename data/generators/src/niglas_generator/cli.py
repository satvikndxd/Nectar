"""Command-line entry point for generating datasets.

Usage::

    python -m niglas_generator --scenario data/scenarios/<id>.json --out-dir /tmp/run

Writes ``events.jsonl`` (what Niglas may see) and ``ground_truth.json`` (what the
evaluation harness compares against) and prints a short summary to stderr.
"""

import argparse
import sys
from pathlib import Path

from niglas_generator.config import GENERATOR_VERSION
from niglas_generator.dataset import GeneratedDataset
from niglas_generator.scenarios import load_scenario
from niglas_generator.serialization import ground_truth_to_json


def _write_dataset(dataset: GeneratedDataset, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as handle:
        for event in dataset.events:
            handle.write(event.model_dump_json() + "\n")
    (out_dir / "ground_truth.json").write_text(
        ground_truth_to_json(dataset.ground_truth) + "\n", encoding="utf-8"
    )


def _summarise(dataset: GeneratedDataset) -> str:
    truth = dataset.ground_truth
    lines = [
        f"scenario        {dataset.scenario_id}",
        f"generator       {GENERATOR_VERSION} (seed {dataset.config.seed})",
        f"events          {len(dataset.events)}",
        f"sessions        {len(dataset.result.sessions)}",
        f"incident        {truth.has_incident}",
    ]
    if truth.has_incident:
        lines += [
            f"root cause      {truth.root_cause_category.value} - {truth.root_cause_detail}",
            f"true lost orders {truth.lost_orders} (gained back {truth.gained_orders})",
            f"true revenue loss {truth.true_revenue_loss_minor} minor units {truth.currency.value}",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="niglas-generate", description=__doc__)
    parser.add_argument("--scenario", required=True, type=Path, help="scenario JSON file")
    parser.add_argument("--out-dir", type=Path, help="directory for events and ground truth")
    args = parser.parse_args(argv)

    dataset = load_scenario(args.scenario).generate()
    if args.out_dir is not None:
        _write_dataset(dataset, args.out_dir)
    print(_summarise(dataset), file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
