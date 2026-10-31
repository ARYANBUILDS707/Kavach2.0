"""Session cookie policy derived from the configured application origin."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CookiePolicy:
    name: str
    secure: bool


SECURE_COOKIE = CookiePolicy(name="__Host-kavach_session", secure=True)
# Only for an http://localhost-style origin in APP_ENV=development (enforced by Settings).
LOCAL_DEVELOPMENT_COOKIE = CookiePolicy(name="kavach_dev_session", secure=False)


def cookie_policy_for(app_origin: str) -> CookiePolicy:
    return SECURE_COOKIE if app_origin.startswith("https://") else LOCAL_DEVELOPMENT_COOKIE
