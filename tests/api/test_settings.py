from niglas_api.settings import Settings


def test_settings_read_prefixed_environment(monkeypatch) -> None:
    monkeypatch.setenv("NIGLAS_ENVIRONMENT", "test")
    monkeypatch.setenv("NIGLAS_MAX_EVENTS_PER_BATCH", "17")

    settings = Settings()

    assert settings.environment == "test"
    assert settings.max_events_per_batch == 17
