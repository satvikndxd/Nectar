"""Enumerations shared by the database, the API and the web application.

These values are mirrored by CHECK constraints in the database (see
``docs/DATA_MODEL.md``). Changing a member here without a matching migration will
allow the database to reject rows the application considers valid.
"""

from enum import StrEnum


class EventType(StrEnum):
    """Type of an ingested business event. Selects the payload model."""

    SESSION = "session"
    PRODUCT_EVENT = "product_event"
    ORDER = "order"
    PAYMENT = "payment"
    DEPLOYMENT = "deployment"


class Platform(StrEnum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class PaymentMethod(StrEnum):
    VISA = "visa"
    MASTERCARD = "mastercard"
    AMEX = "amex"
    PAYPAL = "paypal"


class PaymentStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Region(StrEnum):
    NA = "na"
    EU = "eu"
    APAC = "apac"
    LATAM = "latam"


class PlanTier(StrEnum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class Currency(StrEnum):
    """ISO-4217 currencies Niglas understands, with their minor-unit exponent."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"

    @property
    def minor_unit_exponent(self) -> int:
        """Number of decimal places in the currency's minor unit."""
        return 0 if self is Currency.JPY else 2


class DeploymentStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class Severity(StrEnum):
    """Severity of an anomaly or incident, ordered low -> critical."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OperatingStage(StrEnum):
    """The five stages every recommendation and action moves through.

    Only ``EXECUTE`` mutates business state; the stage is enforced by application
    code, never by a language model.
    """

    OBSERVE = "observe"
    RECOMMEND = "recommend"
    APPROVE = "approve"
    EXECUTE = "execute"
    VERIFY = "verify"


class Role(StrEnum):
    """RBAC roles, ordered from least to most privileged."""

    VIEWER = "viewer"
    ANALYST = "analyst"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"


class AuditAction(StrEnum):
    """Security- and business-relevant actions written to the append-only audit log."""

    EVENTS_INGESTED = "events_ingested"
    EVENTS_REJECTED = "events_rejected"
    AUTHENTICATION_FAILED = "authentication_failed"
    AUTHORIZATION_DENIED = "authorization_denied"
