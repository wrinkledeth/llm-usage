from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass(slots=True)
class UsageWindowSnapshot:
    percent: float | None
    resets_at: dt.datetime | None = None
    subtitle: str | None = None
    window_seconds: int | None = None


@dataclass(slots=True)
class CreditsSnapshot:
    kind: str
    enabled: bool
    unlimited: bool = False
    balance: float | None = None
    used: float | None = None
    limit: float | None = None
    utilization: float | None = None


@dataclass(slots=True)
class ProviderUsageSnapshot:
    provider_id: str
    display_name: str
    session: UsageWindowSnapshot | None
    weekly: UsageWindowSnapshot | None
    credits: CreditsSnapshot | None = None
    monthly: UsageWindowSnapshot | None = None
    error: str | None = None
    last_updated: dt.datetime | None = None

    @property
    def has_any_usage(self) -> bool:
        return bool(
            (self.session and self.session.percent is not None)
            or (self.weekly and self.weekly.percent is not None)
        )

    @classmethod
    def error_state(cls, provider_id: str, display_name: str, error: str) -> "ProviderUsageSnapshot":
        return cls(
            provider_id=provider_id,
            display_name=display_name,
            session=UsageWindowSnapshot(percent=None),
            weekly=UsageWindowSnapshot(percent=None),
            error=error,
            last_updated=dt.datetime.now(dt.timezone.utc),
        )
