"""
brain/production_factory.py — Master Character-Consistent AI Video Production Factory

Top-level coordinator orchestrating the full Phase 18/19 autonomous lifecycle:
1. Niche Selection & Template Resolution
2. Character, World & Story Bible Setup / Continuity Retrieval
3. Knowledge Base Query (Pattern Retrieval for optimal hooks & visuals)
4. Scene Graph Generation & Cinematic Planning
5. Prompt Compilation with inlined character/world consistency constraints
6. Account Selection & Credit Protection
7. Batch Generation via Google Flow Provider (with DRY_RUN support)
8. Artifact Download & Forensic FFprobe Verification
9. Candidate Selection & Scene Assembly
10. Learning Feedback loop (Bayesian Pattern Recording)
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from brain.knowledge_database import KnowledgeDatabase
from brain.knowledge_repository import KnowledgeRepository
from brain.character_bible import CharacterBible, Character
from brain.world_bible import WorldBible, Location, StyleBible
from brain.story_bible import StoryBibleStore, StoryBible, EpisodeBible
from brain.scene_graph import SceneGraph, SceneNode, CameraPlan, ActionPlan, CameraDirection, SceneTransition
from brain.prompt_compiler import PromptCompiler
from brain.generation_provider import (
    GenerationJob,
    GenerationJobState,
    GenerationAccount,
    GenerationArtifact,
    _now_iso
)
from brain.generation_account_manager import GenerationAccountManager
from brain.flow_provider import GoogleFlowProvider
from brain.candidate_manager import CandidateSelector, SceneCandidate
from brain.artifact_verifier import ArtifactVerifier
from brain.niche_profile import NicheRegistry, NicheProfile


@dataclass
class ProductionRunResult:
    """Result of an end-to-end factory production run."""
    run_id: str
    story_id: str
    episode_id: str
    niche_id: str
    character_ids: List[str]
    scene_count: int
    artifacts_downloaded: int
    artifacts_verified: int
    account_used: Optional[str]
    total_credits_used: int
    status: str  # COMPLETED, PARTIAL, FAILED
    errors: List[str] = field(default_factory=list)
    output_dir: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)


class AIVideoProductionFactory:
    """Master AI Video Production Factory for Character-Consistent Shorts."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        base_dir: Optional[Path] = None,
        dry_run: bool = True
    ):
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent
        self.db_path = db_path or (self.base_dir / "knowledge_base.db")
        self.dry_run = dry_run

        # Core database & stores
        self.db = KnowledgeDatabase(self.db_path)
        self.knowledge_repo = KnowledgeRepository(self.db)
        self.character_bible = CharacterBible(self.db)
        self.world_bible = WorldBible(self.db)
        self.story_bible = StoryBibleStore(self.db)
        self.scene_graph = SceneGraph(self.db)
        self.candidate_selector = CandidateSelector(self.db)

        # Verification & compilation
        self.verifier = ArtifactVerifier()
        self.prompt_compiler = PromptCompiler(
            character_bible=self.character_bible,
            world_bible=self.world_bible,
            story_bible_store=self.story_bible
        )

        # Provider & account management
        self.flow_provider = GoogleFlowProvider(
            base_dir=self.base_dir,
            dry_run=self.dry_run,
            verifier=self.verifier
        )
        self.account_manager = GenerationAccountManager(
            config_path=self.base_dir / "mission_control.json"
        )
        self.niche_registry = NicheRegistry()

    def produce_episode(
        self,
        niche_id: str = "01_scifi",
        series_name: Optional[str] = None,
        episode_title: Optional[str] = None,
        character_name: str = "Maya",
        scene_count: int = 5,
        output_dir: Optional[Path] = None
    ) -> ProductionRunResult:
        """Execute the full autonomous production loop for a coherent multi-scene short."""
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        output_dir = output_dir or (self.base_dir / "projects" / f"prod_{run_id}")
        output_dir.mkdir(parents=True, exist_ok=True)

        nprofile = self.niche_registry.get_profile(niche_id)
        if not nprofile:
            raise ValueError(f"Unknown niche profile: {niche_id}")

        # 1. Setup / Retrieve Character
        char_id = character_name.lower().replace(" ", "_")
        existing_char = self.character_bible.get_character(char_id)
        if not existing_char:
            existing_char = self.character_bible.create_character(
                character_id=char_id,
                name=character_name,
                age_range="26-30",
                gender_presentation="Female",
                physical_description="Athletic build, sharp intelligent eyes, calm demeanor",
                face_description="Oval face, high cheekbones, small scar over left eyebrow",
                hair="Dark shoulder-length wavy hair",
                eyes="Hazel green",
                wardrobe="Tactical pilot jacket over dark reinforced tunic",
                personality="Analytical, quick-thinking, resilient",
                speech_style="Direct, calm under extreme pressure",
                voice_id=nprofile.default_voice_id,
                visual_style=nprofile.visual_style_prompt,
                negative_constraints=nprofile.negative_constraints
            )

        # 2. Setup / Retrieve Location & Style
        loc_id = f"loc_{niche_id}_main"
        existing_loc = self.world_bible.get_location(loc_id)
        if not existing_loc:
            existing_loc = self.world_bible.create_location(
                location_id=loc_id,
                name="Research Core Command Deck",
                description="High-tech command center overlooking vast orbital nexus",
                architecture="Brutalist near-future metallic interior with cyan ambient glow",
                walls="Reinforced titanium plating with hexagonal holographic data panels",
                windows="Panoramic view of planet atmosphere and orbital ring",
                furniture="Central holographic console table, dual pilot navigation stations",
                lighting="Atmospheric volumetric rim lighting, cool cyan and amber accents",
                time_of_day="Deep space night",
                weather="Clear void with distant solar nebula flare"
            )

        style_id = f"style_{niche_id}"
        existing_style = self.world_bible.get_style(style_id)
        if not existing_style:
            existing_style = self.world_bible.create_style(
                style_id=style_id,
                name="Cinematic SciFi Anamorphic",
                lens="35mm Anamorphic",
                color_palette="Teal, cyan, deep shadow blacks, warm amber keylight",
                lighting_style="High-contrast volumetric rim lighting",
                camera_defaults="Smooth steadycam with slow push-in",
                depth_of_field="Cinematic shallow depth of field",
                grain_texture="Subtle 35mm film grain",
                aspect_ratio="9:16",
                negative_style=["cartoon", "cgi toy look", "amateur lighting", "blurry"]
            )

        # 3. Setup Story & Episode
        story_id = f"story_{niche_id}_{series_name or 'chronicles'}"
        story = self.story_bible.get_story(story_id)
        if not story:
            story = self.story_bible.create_story(
                story_id=story_id,
                series_name=series_name or f"{nprofile.display_name} Universes",
                genre="Sci-Fi Thriller",
                premise="Chronicles of temporal anomalies across orbital sectors",
                tone=nprofile.tone,
                themes=["Time dilation", "Human survival", "Technological singularity"],
                world_rules=["Time echoes repeat at 5-minute intervals", "Gravity dampeners fail near event horizons"],
                character_ids=[existing_char.character_id],
                location_ids=[existing_loc.location_id],
                visual_style_id=existing_style.style_id,
                audio_style="Dark cinematic synth score with intense bass drops"
            )

        ep_id = f"ep_{uuid.uuid4().hex[:8]}"
        episode = self.story_bible.create_episode(
            episode_id=ep_id,
            story_id=story.story_id,
            episode_number=1,
            title=episode_title or "Anomaly at Sector 7",
            story_arc="Discovery of an unauthorized time beacon",
            previous_episode_summary="Initial anomaly detected in outer sensory perimeter.",
            current_conflict="Power grid failing while unknown signal approaches.",
            character_states={existing_char.character_id: "Alert, investigating sensor discrepancy"},
            location_states={existing_loc.location_id: "Emergency standby mode, amber warning pulses"}
        )

        # 4. Generate Structured Scene Graph
        scenes = []
        shot_types = [
            (CameraDirection.WIDE_ESTABLISHING, "Overview of command deck as emergency warnings activate"),
            (CameraDirection.MEDIUM_SHOT, "Protagonist entering central console, reviewing telemetry"),
            (CameraDirection.CLOSE_UP, "Intense focus on face as sensor readout spikes unexpectedly"),
            (CameraDirection.SLOW_PUSH_IN, "Hands manipulating holographic coordinate controls"),
            (CameraDirection.EXTREME_CLOSE_UP, "The anomaly horizon visible through observation glass")
        ]

        for idx, (cam_dir, desc) in enumerate(shot_types[:scene_count], start=1):
            sc_id = f"{ep_id}_sc_{idx:02d}"
            scene = self.scene_graph.create_scene(
                scene_id=sc_id,
                episode_id=ep_id,
                scene_number=idx,
                scene_name=f"Scene {idx} - {cam_dir.value}",
                description=desc,
                character_ids=[existing_char.character_id],
                location_id=existing_loc.location_id,
                camera=CameraPlan(
                    shot_type=cam_dir.value,
                    lens=existing_style.lens,
                    lighting=existing_loc.lighting,
                    movement=existing_style.camera_defaults,
                    time_of_day=existing_loc.time_of_day
                ),
                actions=[
                    ActionPlan(
                        character_id=existing_char.character_id,
                        starting_position="Left frame",
                        movement="Approaches console",
                        facial_expression="Tense and focused",
                        emotional_state="Determined",
                        interaction="Operating console dials"
                    )
                ],
                transition_in=SceneTransition.DISSOLVE.value if idx > 1 else SceneTransition.CUT.value,
                transition_out=SceneTransition.CUT.value,
                duration_target_sec=5.0
            )

            # Compile Google Flow prompt
            flow_prompt = self.prompt_compiler.compile_google_flow_prompt(
                scene=scene,
                episode=episode,
                story=story,
                style=existing_style
            )
            prompt_v = self.prompt_compiler.get_prompt_version(flow_prompt)
            scene = self.scene_graph.update_scene(scene.scene_id, prompt_text=flow_prompt, prompt_version=prompt_v)
            scenes.append(scene)

        # 5. Account Selection & Generation
        account = self.account_manager.select_generation_account(provider="google_flow")
        account_id = account.account_id if account else "dry_run_acc"

        downloaded_count = 0
        verified_count = 0
        errors = []

        for scene in scenes:
            job = GenerationJob(
                job_id=f"job_{uuid.uuid4().hex[:10]}",
                account_id=account_id,
                project_id=niche_id,
                episode_id=ep_id,
                scene_id=scene.scene_id,
                prompt_text=scene.prompt_text,
                prompt_version=scene.prompt_version,
                character_bible_version=f"{existing_char.character_id}:v{existing_char.version}",
                state=GenerationJobState.PLANNED.value,
                provider_name="google_flow"
            )

            # Submit -> Download -> Verify
            try:
                job = self.flow_provider.submit_job(job)
                artifact = self.flow_provider.download_artifact(job, output_dir)
                downloaded_count += 1

                # Create & Score candidate
                cand = self.candidate_selector.create_candidate(
                    candidate_id=f"cand_{uuid.uuid4().hex[:8]}",
                    scene_id=scene.scene_id,
                    job_id=job.job_id,
                    artifact_path=artifact.file_path,
                    artifact_hash=artifact.sha256_hash,
                    file_size=artifact.file_size,
                    duration_sec=artifact.duration_sec,
                    width=artifact.width,
                    height=artifact.height,
                    status="VERIFIED" if artifact.verified else "DOWNLOADED"
                )

                if artifact.verified:
                    verified_count += 1
                    self.candidate_selector.accept_candidate(cand.candidate_id)
                else:
                    errors.extend(artifact.verification_errors)

            except Exception as e:
                errors.append(f"Scene {scene.scene_id} generation error: {str(e)}")

        # 6. Report Success to Account Manager
        if account:
            self.account_manager.report_success(account.account_id, credits_used=scene_count * 10)

        # 7. Record Learning Event in Knowledge Base
        self.knowledge_repo.record_learning_event(
            event_type="CHARACTER_CONTINUITY_EPISODE_GENERATED",
            source_type="FACTORY_PRODUCTION",
            source_id=ep_id,
            project_id=niche_id,
            account_id=account_id,
            payload={
                "character_id": existing_char.character_id,
                "scenes_count": scene_count,
                "verified_count": verified_count,
                "errors_count": len(errors)
            },
            confidence_weight=1.0
        )

        return ProductionRunResult(
            run_id=run_id,
            story_id=story.story_id,
            episode_id=ep_id,
            niche_id=niche_id,
            character_ids=[existing_char.character_id],
            scene_count=scene_count,
            artifacts_downloaded=downloaded_count,
            artifacts_verified=verified_count,
            account_used=account_id,
            total_credits_used=scene_count * 10 if not self.dry_run else 0,
            status="COMPLETED" if verified_count == scene_count else ("PARTIAL" if verified_count > 0 else "FAILED"),
            errors=errors,
            output_dir=str(output_dir)
        )
