"""Reproducibility: a seed and a generator version fully determine a dataset."""

from dataclasses import replace

from niglas_generator.dataset import generate
from niglas_generator.simulator import simulate


def test_same_seed_produces_identical_events(config):
    first = generate(config=config)
    second = generate(config=config)
    assert [event.model_dump_json() for event in first.events] == [
        event.model_dump_json() for event in second.events
    ]


def test_different_seed_produces_different_data(config):
    first = generate(config=config)
    second = generate(config=config.model_copy(update={"seed": config.seed + 1}))
    assert len(first.events) != len(second.events) or [
        event.model_dump_json() for event in first.events
    ] != [event.model_dump_json() for event in second.events]


def test_simulation_is_pure(config, android_visa_fault):
    """Running twice with the same faults must not depend on any hidden state."""
    first = simulate(config, [android_visa_fault])
    second = simulate(config, [android_visa_fault])
    assert first == second


def test_sessions_are_emitted_in_time_order(config):
    sessions = simulate(config).sessions
    assert list(sessions) == sorted(sessions, key=lambda s: (s.started_at, s.session_id))


def test_events_are_emitted_in_time_order(config):
    events = generate(config=config).events
    assert [event.occurred_at for event in events] == sorted(event.occurred_at for event in events)


def test_event_ids_and_idempotency_keys_are_unique(config):
    events = generate(config=config).events
    assert len({event.idempotency_key for event in events}) == len(events)
    assert len({event.event_id for event in events}) == len(events)


def test_event_ids_are_derived_from_the_idempotency_key(config):
    """Regenerating a dataset must yield the same ids, so re-ingestion is a no-op."""
    first = {event.idempotency_key: event.event_id for event in generate(config=config).events}
    second = {event.idempotency_key: event.event_id for event in generate(config=config).events}
    assert first == second


def test_changing_traffic_does_not_change_the_fault_definition(config, android_visa_fault):
    """A fault is a declaration; nothing about it depends on the world it lands in."""
    assert replace(android_visa_fault, ramp_minutes=30.0).fault_id == android_visa_fault.fault_id
