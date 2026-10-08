"""Deterministic anomaly detection for Niglas.

Pipeline: raw events -> bucketed rate series (:mod:`series`) -> per-bucket detectors
(:mod:`detectors`) -> merged episodes (:mod:`episodes`) -> dimension localisation
(:mod:`localize`). No LLM is involved anywhere in this package.
"""
