"""Authentication helpers for operator and producer API calls."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pydantic import BaseModel, ConfigDict, ValidationError

from niglas_api.settings import Settings, get_settings
from niglas_schemas.enums import Role
from niglas_shared.errors import AuthorizationError
from niglas_shared.rbac import Permission, Principal

bearer_scheme = HTTPBearer(auto_error=False)


class TokenClaims(BaseModel):
    """JWT claims Niglas accepts at the HTTP boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sub: UUID
    org: UUID
    roles: tuple[Role, ...] = ()
    iss: str
    exp: datetime
    iat: datetime
    service: bool = False


def create_access_token(
    principal: Principal,
    *,
    settings: Settings,
    now: datetime | None = None,
) -> str:
    """Mint an HS256 access token for local development and tests."""
    issued_at = (now or datetime.now(UTC)).astimezone(UTC)
    expires_at = issued_at + timedelta(minutes=settings.token_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": str(principal.subject_id),
        "org": str(principal.organization_id),
        "roles": [role.value for role in sorted(principal.roles, key=lambda role: role.value)],
        "service": principal.is_service_account,
        "iss": settings.jwt_issuer,
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_principal(token: str, *, settings: Settings) -> Principal:
    """Decode and validate a bearer token into a domain principal."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "iss", "sub", "org"]},
        )
        claims = TokenClaims.model_validate(payload)
    except (InvalidTokenError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return Principal(
        subject_id=claims.sub,
        organization_id=claims.org,
        roles=frozenset(claims.roles),
        is_service_account=claims.service,
    )


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    """FastAPI dependency returning the authenticated principal."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_principal(credentials.credentials, settings=settings)


def require_permission(permission: Permission) -> Callable[[Principal], Principal]:
    """Build a dependency that enforces one RBAC permission."""

    def dependency(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        try:
            principal.require(permission)
        except AuthorizationError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing permission {permission.value}",
            ) from exc
        return principal

    return dependency
