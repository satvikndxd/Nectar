"""JSON serialisation for generator artefacts."""

import dataclasses
import json
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from niglas_generator.groundtruth import GroundTruth


def _default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"cannot serialise {type(value).__name__}")


def ground_truth_to_json(ground_truth: GroundTruth) -> str:
    """Render ground truth as stable, diffable JSON."""
    return json.dumps(dataclasses.asdict(ground_truth), default=_default, indent=2, sort_keys=True)
