"""Processing-approval policy primitives. Not a substitute for an organization's own vendor approval."""
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class ProcessingApproval:
    provider: str
    deployment: str
    endpoint: str
    evidence_reference: str
    expires_on: date

    def valid_on(self, today: date) -> bool:
        return all(s.strip() for s in (self.provider, self.deployment, self.endpoint, self.evidence_reference)) and self.expires_on >= today

def require_external_processing(mode: str, approval: ProcessingApproval | None, today: date) -> None:
    if mode != "approved_cloud" or approval is None or not approval.valid_on(today):
        raise PermissionError("External processing is not approved")
    # Caller must additionally enforce the exact approved destination at the network boundary.

def can_view(user_groups: set[str], record_groups: set[str]) -> bool:
    """Demo group-intersection rule. Production needs fresh source authorization."""
    return bool(user_groups & record_groups)

