from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from niglas_api.auth import create_access_token, decode_principal
from niglas_api.settings import Settings
from niglas_schemas.enums import Role
from niglas_shared.rbac import Principal


def settings() -> Settings:
    return Settings(
        environment="test",
        jwt_secret=SecretStr("unit-test-signing-key-32-bytes-ok"),
        jwt_issuer="niglas-test",
    )


def test_access_token_round_trips_to_a_principal() -> None:
    original = Principal(
        subject_id=uuid4(),
        organization_id=uuid4(),
        roles=frozenset({Role.OPERATOR}),
        is_service_account=True,
    )
    token = create_access_token(original, settings=settings())

    decoded = decode_principal(token, settings=settings())

    assert decoded == original


def test_invalid_token_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        decode_principal("not-a-token", settings=settings())

    assert exc.value.status_code == 401
