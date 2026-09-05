from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Campaign:
    id: str
    project_id: str
    name: str
    status: str = "active"
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def create(cls, project_id: str, name: str, config: Optional[Dict[str, Any]] = None) -> "Campaign":
        return cls(
            id=f"camp_{uuid.uuid4().hex[:10]}",
            project_id=project_id,
            name=name,
            config=config or {}
        )
