"""Event emission: every simulated fact becomes exactly one contract-valid event."""

from niglas_generator.dataset import generate
from niglas_schemas.enums import EventType, PaymentStatus


def events_by_type(events, event_type):
    return [event for event in events if event.event_type is event_type]


def test_one_session_event_per_simulated_session(config):
    dataset = generate(config=config)
    session_events = events_by_type(dataset.events, EventType.SESSION)
    assert len(session_events) == len(dataset.result.sessions)
    assert {event.payload.session_id for event in session_events} == {
        session.session_id for session in dataset.result.sessions
    }


def test_one_payment_event_per_attempt(config, android_visa_fault):
    dataset = generate(config=config, faults=[android_visa_fault])
    expected = sum(len(session.attempts) for session in dataset.result.sessions)
    assert len(events_by_type(dataset.events, EventType.PAYMENT)) == expected


def test_one_order_event_per_conversion_and_none_otherwise(config):
    dataset = generate(config=config)
    order_events = events_by_type(dataset.events, EventType.ORDER)
    converted = [session for session in dataset.result.sessions if session.converted]
    assert len(order_events) == len(converted)
    assert {event.payload.order_id for event in order_events} == {
        session.order_id for session in converted
    }


def test_failed_payments_carry_an_amount_so_revenue_at_risk_is_computable(
    config, android_visa_fault
):
    dataset = generate(config=config, faults=[android_visa_fault])
    failed = [
        event
        for event in events_by_type(dataset.events, EventType.PAYMENT)
        if event.payload.status is PaymentStatus.FAILED
    ]
    assert failed
    assert all(event.payload.amount_minor > 0 for event in failed)
    assert all(event.payload.failure_code for event in failed)
    assert all(event.payload.order_id is None for event in failed)


def test_deployments_are_emitted_once_each(config):
    dataset = generate(config=config)
    deployment_events = events_by_type(dataset.events, EventType.DEPLOYMENT)
    assert len(deployment_events) == len(config.deployments)
    assert {event.payload.version for event in deployment_events} == {
        spec.version for spec in config.deployments
    }


def test_product_events_mark_funnel_progress(config):
    dataset = generate(config=config)
    names = {
        event.payload.name for event in events_by_type(dataset.events, EventType.PRODUCT_EVENT)
    }
    assert names == {"checkout_started", "payment_submitted"}
    checkout_events = sum(
        1
        for event in events_by_type(dataset.events, EventType.PRODUCT_EVENT)
        if event.payload.name == "checkout_started"
    )
    assert checkout_events == sum(1 for s in dataset.result.sessions if s.reached_checkout)


def test_every_event_is_scoped_to_the_configured_organization(config):
    dataset = generate(config=config)
    assert {event.organization_id for event in dataset.events} == {config.organization_id}


def test_every_event_lands_inside_the_simulated_window(config):
    from datetime import timedelta

    dataset = generate(config=config)
    end = config.start + timedelta(hours=config.duration_hours, minutes=5)
    assert all(config.start <= event.occurred_at < end for event in dataset.events)
