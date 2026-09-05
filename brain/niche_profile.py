"""
brain/niche_profile.py — Niche Vertical Configuration & Templates

Defines pluggable niche profiles (Sci-Fi, Movie Recaps, Kids Stories, Viral Podcasts, etc.)
Allows dynamic creation of character/location/story templates without modifying code.
Integrates with KnowledgeRepository for niche-scoped patterns.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone


@dataclass
class NicheProfile:
    """Configuration profile for a content niche/channel vertical."""
    niche_id: str
    display_name: str
    target_audience: str
    tone: str
    visual_style_prompt: str
    default_aspect_ratio: str = "9:16"
    target_scene_count: int = 5
    target_duration_range_sec: tuple[float, float] = (30.0, 60.0)
    hook_mechanisms: List[str] = field(default_factory=lambda: ["curiosity_gap", "open_loop", "conflict_first"])
    default_voice_id: str = "pNInz6obpgDQGcFmaJgB"  # Adam
    default_voice_model: str = "eleven_turbo_v2_5"
    negative_constraints: List[str] = field(default_factory=lambda: [
        "blurry", "low quality", "distorted faces", "watermark", "text overlay"
    ])
    story_templates: List[Dict[str, Any]] = field(default_factory=list)
    character_archetypes: List[Dict[str, Any]] = field(default_factory=list)
    location_archetypes: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NicheProfile:
        return cls(**data)


class NicheRegistry:
    """Registry of available content vertical profiles."""

    def __init__(self, config_dir: Optional[Path] = None):
        self._profiles: Dict[str, NicheProfile] = {}
        self._config_dir = config_dir
        self._load_builtins()

    def register_profile(self, profile: NicheProfile):
        self._profiles[profile.niche_id] = profile

    def get_profile(self, niche_id: str) -> Optional[NicheProfile]:
        return self._profiles.get(niche_id)

    def list_profiles(self) -> List[NicheProfile]:
        return list(self._profiles.values())

    def _load_builtins(self):
        """Register built-in content profiles."""
        # 1. Sci-Fi Story Universe
        self.register_profile(NicheProfile(
            niche_id="01_scifi",
            display_name="Sci-Fi Chrono Stories",
            target_audience="Fans of dystopian, futuristic & hard sci-fi narratives",
            tone="Cinematic, tense, mysterious, philosophical",
            visual_style_prompt="cinematic 35mm anamorphic, volumetric lighting, gritty cyberpunk and near-future aesthetic, hyper-detailed, 8k resolution, Unreal Engine 5 render style",
            hook_mechanisms=["curiosity_gap", "contrarian", "open_loop", "outcome_first"],
            default_voice_id="pNInz6obpgDQGcFmaJgB",
            story_templates=[
                {
                    "template_id": "time_paradox",
                    "title": "The Time Loop Signal",
                    "acts": ["Discovery of anomalous signal", "First temporal shift", "The horrifying realization", "Final choice"]
                },
                {
                    "template_id": "alien_contact",
                    "title": "First Artifact",
                    "acts": ["Excavation in deep space", "Activation sequence", "Cognitive resonance", "Transmission home"]
                }
            ],
            character_archetypes=[
                {
                    "role": "protagonist_pilot",
                    "name": "Commander Ethan Cross",
                    "description": "32-year-old deep space pilot, rugged features, short crop dark hair, weathered pressurized flight suit",
                    "voice_id": "pNInz6obpgDQGcFmaJgB"
                }
            ],
            location_archetypes=[
                {
                    "name": "Orbital Station Alpha",
                    "description": "Decommissioned orbital research station overlooking neon-lit mega city below, holographic displays flickering"
                }
            ]
        ))

        # 2. Movie Recaps
        self.register_profile(NicheProfile(
            niche_id="04_movie_recaps",
            display_name="Cinematic Movie Recaps",
            target_audience="Thriller, horror, and mystery film lovers",
            tone="Intense, fast-paced, suspenseful, dark narrative",
            visual_style_prompt="dark cinematic lighting, film grain, suspense atmosphere, dramatic shadows",
            hook_mechanisms=["conflict_first", "question_hook", "curiosity_gap"],
            default_voice_id="pNInz6obpgDQGcFmaJgB"
        ))

        # 3. Kids Educational Stories
        self.register_profile(NicheProfile(
            niche_id="03_kids_stories",
            display_name="Whimsical Tales for Kids",
            target_audience="Children aged 5-10 and families",
            tone="Playful, magical, heartwarming, curious",
            visual_style_prompt="Pixar 3D animation style, vibrant saturated colors, soft whimsical lighting, charming character designs",
            hook_mechanisms=["curiosity_gap", "humor", "empathy"],
            default_voice_id="EXAVITQu4vr4xnSDxMaL"  # Bella / Soft voice
        ))
