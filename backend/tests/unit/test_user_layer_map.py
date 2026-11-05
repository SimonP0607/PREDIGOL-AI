"""The user layer's switches: the code, the server's template and the owner's map say the same thing (plan de cierre UX, 0.1).

A switch that the code reads but the template never mentions is one the owner cannot find; a name in the owner's map that the code
no longer reads is a promise that does nothing. Neither may happen silently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
TEMPLATE = BACKEND / "deploy" / "vps" / "app.env.example"
MAP = BACKEND / "docs" / "owner" / "INTERRUPTORES_UX.md"

# Every variable of the readers' layer (plan UX A2 to B11) that the owner can set. Add a new switch here AND to the template AND to the map.
USER_LAYER = (
    "FBI_CONSENT_GATE",
    "FBI_EMAIL_SEND",
    "FBI_EMAIL_FROM",
    "FBI_EMAIL_REPLY_TO",
    "FBI_RESEND_API_KEY",
    "FBI_RESEND_WEBHOOK_SECRET",
    "FBI_EMAIL_DAILY_CAP",
    "FBI_SELF_SERVICE",
    "FBI_LINKS_PURGE",
    "FBI_PRODUCT_EVENTS",
    "FBI_EVENTS_PURGE",
    "FBI_PRODUCT_MIN_SUBJECTS",
    "FBI_EVENTS_RATE_LIMIT",
    "FBI_MEMBERSHIP_ENFORCE",
    "FBI_TRIAL_DAYS",
    "FBI_MEMBERSHIP_PRICE_COP",
    "FBI_MEMBERSHIP_PRICE_USD",
    "FBI_MEMBERSHIP_CURRENCY",
    "FBI_SUPPORT_WHATSAPP",
    "FBI_SUPPORT",
    "FBI_USER_NARRATIVE",
    "FBI_USER_NARRATIVE_MINUTES",
    "FBI_AI_USER_MONTHLY_BUDGET_USD",
    "FBI_TRANSPARENCY",
    "FBI_ONBOARDING",
    "FBI_PERSONALIZATION",
    "FBI_FEEDBACK",
    "FBI_PUSH",
    "FBI_VAPID_PRIVATE_KEY",
    "FBI_VAPID_SUBJECT",
    "FBI_DIGEST",
    "FBI_DIGEST_FROM",
    "FBI_DIGEST_DAILY_CAP",
    "FBI_EXPLAIN",
    "FBI_LIFECYCLE",
    "FBI_FORECAST_USERS",
    "FBI_CALENDAR_USERS",
    "FBI_KNOWLEDGE_USERS",
    "FBI_READING_USERS",
    "FBI_NEWS_USERS",
    "FBI_SENTRY_DSN",
    "FBI_SENTRY_WEB_DSN",
    "FBI_SENTRY_ENVIRONMENT",
    "FBI_MONITORING_RATE_LIMIT",
    "FBI_MONITORING_HOURLY_CAP",
    "FBI_MONITORING_DAILY_CAP",
    "FBI_SYNTHETIC_BASE_URL",
    "FBI_SYNTHETIC_EMAIL",
    "FBI_SYNTHETIC_PASSWORD",
    "FBI_TELEGRAM_BOT_TOKEN",
    "FBI_TELEGRAM_CHAT_ID",
)

# Set by the compose file or by the settings class (prefix + field name), not read as a literal in the code; the map names them anyway.
NOT_LITERAL_IN_CODE = {
    "FBI_EMAIL_REPLY_TO",
    "FBI_TELEGRAM_BOT_TOKEN",
    "FBI_TELEGRAM_CHAT_ID",
    "FBI_EMAIL_FROM",
}


def _code_names() -> set[str]:
    names: set[str] = set()
    for root in ("src", "apps"):
        for path in (BACKEND / root).rglob("*.py"):
            names.update(
                re.findall(r"\bFBI_[A-Z0-9_]+\b", path.read_text(encoding="utf-8", errors="ignore"))
            )
    return names


@pytest.fixture(scope="module")
def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def owner_map() -> str:
    return MAP.read_text(encoding="utf-8")


def test_every_user_layer_switch_is_in_the_servers_template(template: str) -> None:
    missing = [name for name in USER_LAYER if not re.search(rf"^#? ?{name}=", template, re.M)]
    assert not missing, (
        f"{missing}: add their line (commented if they are born off) to deploy/vps/app.env.example"
    )


def test_every_user_layer_switch_is_in_the_owners_map(owner_map: str) -> None:
    missing = [name for name in USER_LAYER if f"`{name}`" not in owner_map]
    assert not missing, f"{missing}: add them to docs/owner/INTERRUPTORES_UX.md"


def test_every_user_layer_switch_is_still_read_by_the_code() -> None:
    code = _code_names()
    gone = [name for name in USER_LAYER if name not in code and name not in NOT_LITERAL_IN_CODE]
    assert not gone, (
        f"{gone}: the code no longer reads them - remove them from the template, the map and this list"
    )


def test_the_template_never_carries_a_real_secret(template: str) -> None:
    for line in template.splitlines():
        match = re.match(
            r"^#? ?(FBI_[A-Z0-9_]*(?:KEY|SECRET|TOKEN|DSN|PASSWORD)[A-Z0-9_]*)=(.+)$", line
        )
        if match:
            assert match.group(2).strip() == "", (
                f"{match.group(1)} has a value in a file that goes to Git"
            )


def test_the_web_build_carries_its_version_into_the_bundle() -> None:
    """Sentry and support read the web version from the bundle: the compose file hands it to the build and the Dockerfile keeps it.

    Checked in production on 5-nov-2026: the served bundle holds VITE_APP_VERSION equal to the running image tag.
    """
    compose = (BACKEND / "deploy" / "vps" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "VITE_APP_VERSION: ${PREDIGOL_WEB_VERSION" in compose
    dockerfile = (BACKEND.parent / "web" / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG VITE_APP_VERSION" in dockerfile
    assert "VITE_APP_VERSION=${VITE_APP_VERSION}" in dockerfile
