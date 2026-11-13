"""Deterministic helpers. Contract interpretation remains reviewer-owned."""
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

@dataclass(frozen=True)
class ReviewedDeadline:
    agreement_id: str
    due_date: date | None
    reviewed: bool
    rule_revision: int

    def alert_date(self, days_before: int) -> date | None:
        if days_before < 0:
            raise ValueError("days_before must be nonnegative")
        if not self.reviewed or self.due_date is None:
            return None
        return self.due_date - timedelta(days=days_before)

    def alert_key(self, days_before: int) -> str | None:
        scheduled = self.alert_date(days_before)
        if scheduled is None:
            return None
        return f"{self.agreement_id}:{self.rule_revision}:{days_before}:{scheduled.isoformat()}"

def add_calendar_months(value: date, months: int) -> date:
    """Clamp to month end; use only when the reviewer approved this convention."""
    ordinal = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(ordinal, 12)
    month = month_zero + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))

