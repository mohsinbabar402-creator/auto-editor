from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


from enum import Enum


class Provenance(str, Enum):
    VERIFIED = "VERIFIED"
    USER_PROVIDED = "USER_PROVIDED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


@dataclass
class CampaignField:
    value: Any
    provenance: Provenance = Provenance.UNKNOWN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "provenance": self.provenance.value if isinstance(self.provenance, Provenance) else str(self.provenance)
        }

    @classmethod
    def from_dict(cls, data: Any) -> "CampaignField":
        if isinstance(data, dict) and "provenance" in data:
            return cls(value=data.get("value"), provenance=Provenance(data.get("provenance", "UNKNOWN")))
        if isinstance(data, cls):
            return data
        return cls(value=data, provenance=Provenance.USER_PROVIDED if data is not None else Provenance.UNKNOWN)


@dataclass
class StructuredCampaignRequirements:
    campaign_name: CampaignField
    campaign_id: CampaignField
    platform: CampaignField
    content_type: CampaignField
    duration_min: CampaignField
    duration_max: CampaignField
    aspect_ratio: CampaignField
    required_mentions: CampaignField
    required_hashtags: CampaignField
    required_text: CampaignField
    prohibited_content: CampaignField
    submission_method: CampaignField
    quality_gate: CampaignField
    output_count: CampaignField
    source_requirements: CampaignField
    notes: CampaignField

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaign_name": self.campaign_name.to_dict(),
            "campaign_id": self.campaign_id.to_dict(),
            "platform": self.platform.to_dict(),
            "content_type": self.content_type.to_dict(),
            "duration_min": self.duration_min.to_dict(),
            "duration_max": self.duration_max.to_dict(),
            "aspect_ratio": self.aspect_ratio.to_dict(),
            "required_mentions": self.required_mentions.to_dict(),
            "required_hashtags": self.required_hashtags.to_dict(),
            "required_text": self.required_text.to_dict(),
            "prohibited_content": self.prohibited_content.to_dict(),
            "submission_method": self.submission_method.to_dict(),
            "quality_gate": self.quality_gate.to_dict(),
            "output_count": self.output_count.to_dict(),
            "source_requirements": self.source_requirements.to_dict(),
            "notes": self.notes.to_dict(),
        }


def parse_campaign_intake(raw_input: str | Dict[str, Any]) -> StructuredCampaignRequirements:
    """
    Parses campaign intake requirements preserving strict provenance.
    If information is not provided, it is marked UNKNOWN.
    Never invents unsupplied constraints.
    """
    import json
    if isinstance(raw_input, str):
        raw_str = raw_input.strip()
        if raw_str.startswith("{"):
            try:
                data = json.loads(raw_str)
            except Exception:
                data = {"notes": raw_str}
        else:
            # Parse key-value lines: "key: value"
            data = {}
            for line in raw_str.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    data[k.strip().lower().replace(" ", "_")] = v.strip()
            if not data:
                data = {"notes": raw_str}
    elif isinstance(raw_input, dict):
        data = raw_input
    else:
        data = {}

    def _field(keys: List[str], default: Any = None) -> CampaignField:
        for k in keys:
            if k in data and data[k] is not None:
                val = data[k]
                if isinstance(val, dict) and "provenance" in val:
                    return CampaignField.from_dict(val)
                return CampaignField(value=val, provenance=Provenance.USER_PROVIDED)
        return CampaignField(value=default, provenance=Provenance.UNKNOWN)

    return StructuredCampaignRequirements(
        campaign_name=_field(["campaign_name", "name", "title"]),
        campaign_id=_field(["campaign_id", "id"]),
        platform=_field(["platform", "destination_platform"], default="youtube_shorts"),
        content_type=_field(["content_type", "type"], default="short_form"),
        duration_min=_field(["duration_min", "min_duration", "duration_minimum"]),
        duration_max=_field(["duration_max", "max_duration", "duration_maximum"]),
        aspect_ratio=_field(["aspect_ratio", "ratio"], default="9:16"),
        required_mentions=_field(["required_mentions", "mentions"], default=[]),
        required_hashtags=_field(["required_hashtags", "hashtags"], default=[]),
        required_text=_field(["required_text", "mandatory_text"], default=[]),
        prohibited_content=_field(["prohibited_content", "prohibited", "banned"], default=[]),
        submission_method=_field(["submission_method", "submission"]),
        quality_gate=_field(["quality_gate", "target_score", "min_score"], default=7.0),
        output_count=_field(["output_count", "count", "videos_needed"], default=1),
        source_requirements=_field(["source_requirements", "sources"]),
        notes=_field(["notes", "description"])
    )


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

