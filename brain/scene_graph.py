from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from brain.knowledge_database import KnowledgeDatabase


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CameraDirection(str, Enum):
    WIDE_ESTABLISHING = "WIDE_ESTABLISHING"
    MEDIUM_SHOT = "MEDIUM_SHOT"
    CLOSE_UP = "CLOSE_UP"
    EXTREME_CLOSE_UP = "EXTREME_CLOSE_UP"
    OVER_THE_SHOULDER = "OVER_THE_SHOULDER"
    TRACKING_SHOT = "TRACKING_SHOT"
    DOLLY_IN = "DOLLY_IN"
    DOLLY_OUT = "DOLLY_OUT"
    HANDHELD = "HANDHELD"
    STATIC = "STATIC"
    LOW_ANGLE = "LOW_ANGLE"
    HIGH_ANGLE = "HIGH_ANGLE"
    POV = "POV"
    ORBIT = "ORBIT"
    SLOW_PUSH_IN = "SLOW_PUSH_IN"
    AERIAL = "AERIAL"
    TILT_UP = "TILT_UP"
    TILT_DOWN = "TILT_DOWN"


@dataclass
class CameraPlan:
    shot_type: str = "MEDIUM_SHOT"
    lens: str = "35mm"
    depth_of_field: str = ""
    movement: str = ""
    framing: str = ""
    lighting: str = ""
    time_of_day: str = ""
    composition_notes: str = ""
    foreground: Optional[str] = None
    background: Optional[str] = None


@dataclass
class ActionPlan:
    character_id: str = ""
    starting_position: str = ""
    movement: str = ""
    interaction: str = ""
    object_manipulation: str = ""
    facial_expression: str = ""
    emotional_state: str = ""
    ending_position: str = ""
    dialogue: Optional[str] = None


class SceneTransition(str, Enum):
    CUT = "CUT"
    DISSOLVE = "DISSOLVE"
    FADE_TO_BLACK = "FADE_TO_BLACK"
    FADE_FROM_BLACK = "FADE_FROM_BLACK"
    MATCH_CUT = "MATCH_CUT"
    SMASH_CUT = "SMASH_CUT"
    WHIP_PAN = "WHIP_PAN"
    JUMP_CUT = "JUMP_CUT"


@dataclass
class SceneNode:
    scene_id: str
    episode_id: str
    scene_number: int
    scene_name: str = ""
    description: str = ""
    character_ids: List[str] = field(default_factory=list)
    location_id: str = ""
    camera: CameraPlan = field(default_factory=CameraPlan)
    actions: List[ActionPlan] = field(default_factory=list)
    dialogue_lines: List[Dict[str, Any]] = field(default_factory=list)
    transition_in: str = "CUT"
    transition_out: str = "CUT"
    previous_scene_state: str = ""
    current_state: str = ""
    next_scene_intent: str = ""
    prompt_text: str = ""
    prompt_version: str = ""
    duration_target_sec: float = 5.0
    created_at: str = field(default_factory=_now_iso)
    generation_job_id: Optional[str] = None
    selected_candidate_id: Optional[str] = None


class SceneGraph:
    def __init__(self, db: KnowledgeDatabase) -> None:
        self.db = db
        self._lock = threading.RLock()
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS scenes (
            scene_id TEXT PRIMARY KEY,
            episode_id TEXT NOT NULL,
            scene_number INTEGER NOT NULL,
            scene_name TEXT NOT NULL,
            description TEXT NOT NULL,
            character_ids_json TEXT NOT NULL,
            location_id TEXT NOT NULL,
            camera_json TEXT NOT NULL,
            actions_json TEXT NOT NULL,
            dialogue_lines_json TEXT NOT NULL,
            transition_in TEXT NOT NULL,
            transition_out TEXT NOT NULL,
            previous_scene_state TEXT NOT NULL,
            current_state TEXT NOT NULL,
            next_scene_intent TEXT NOT NULL,
            prompt_text TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            duration_target_sec REAL NOT NULL,
            generation_job_id TEXT,
            selected_candidate_id TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_scenes_episode ON scenes(episode_id, scene_number);
        """
        conn = self.db._get_connection()
        conn.executescript(schema)

    def _row_to_scene(self, row: sqlite3.Row) -> SceneNode:
        return SceneNode(
            scene_id=row["scene_id"],
            episode_id=row["episode_id"],
            scene_number=row["scene_number"],
            scene_name=row["scene_name"],
            description=row["description"],
            character_ids=json.loads(row["character_ids_json"]),
            location_id=row["location_id"],
            camera=CameraPlan(**json.loads(row["camera_json"])),
            actions=[ActionPlan(**a) for a in json.loads(row["actions_json"])],
            dialogue_lines=json.loads(row["dialogue_lines_json"]),
            transition_in=row["transition_in"],
            transition_out=row["transition_out"],
            previous_scene_state=row["previous_scene_state"],
            current_state=row["current_state"],
            next_scene_intent=row["next_scene_intent"],
            prompt_text=row["prompt_text"],
            prompt_version=row["prompt_version"],
            duration_target_sec=row["duration_target_sec"],
            generation_job_id=row["generation_job_id"],
            selected_candidate_id=row["selected_candidate_id"],
            created_at=row["created_at"],
        )

    def create_scene(self, **kwargs: Any) -> SceneNode:
        with self._lock:
            # Normalize camera to CameraPlan if dict
            if isinstance(kwargs.get("camera"), dict):
                kwargs["camera"] = CameraPlan(**kwargs["camera"])
            elif "camera" not in kwargs:
                kwargs["camera"] = CameraPlan()

            # Normalize actions to list of ActionPlan
            if kwargs.get("actions"):
                norm_actions = []
                for a in kwargs["actions"]:
                    if isinstance(a, dict):
                        norm_actions.append(ActionPlan(**a))
                    elif isinstance(a, ActionPlan):
                        norm_actions.append(a)
                kwargs["actions"] = norm_actions
            else:
                kwargs["actions"] = []

            if "created_at" not in kwargs:
                kwargs["created_at"] = _now_iso()

            scene = SceneNode(**kwargs)
            cam_dict = asdict(scene.camera) if isinstance(scene.camera, CameraPlan) else (scene.camera or {})
            act_list = [asdict(a) if isinstance(a, ActionPlan) else a for a in scene.actions]

            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO scenes (
                        scene_id, episode_id, scene_number, scene_name, description,
                        character_ids_json, location_id, camera_json, actions_json,
                        dialogue_lines_json, transition_in, transition_out,
                        previous_scene_state, current_state, next_scene_intent,
                        prompt_text, prompt_version, duration_target_sec,
                        generation_job_id, selected_candidate_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scene.scene_id, scene.episode_id, scene.scene_number, scene.scene_name,
                        scene.description, json.dumps(scene.character_ids), scene.location_id,
                        json.dumps(cam_dict), json.dumps(act_list),
                        json.dumps(scene.dialogue_lines), scene.transition_in, scene.transition_out,
                        scene.previous_scene_state, scene.current_state, scene.next_scene_intent,
                        scene.prompt_text, scene.prompt_version, scene.duration_target_sec,
                        scene.generation_job_id, scene.selected_candidate_id, scene.created_at
                    )
                )
            return scene

    def get_scene(self, scene_id: str) -> Optional[SceneNode]:
        row = self.db.execute_single("SELECT * FROM scenes WHERE scene_id = ?", (scene_id,))
        if row:
            return self._row_to_scene(row)
        return None

    def get_scenes_for_episode(self, episode_id: str) -> List[SceneNode]:
        rows = self.db.execute(
            "SELECT * FROM scenes WHERE episode_id = ? ORDER BY scene_number ASC",
            (episode_id,)
        )
        return [self._row_to_scene(row) for row in rows]

    def update_scene(self, scene_id: str, **changes: Any) -> SceneNode:
        with self._lock:
            scene = self.get_scene(scene_id)
            if not scene:
                raise ValueError(f"Scene {scene_id} not found")
            
            scene_dict = asdict(scene)
            for k, v in changes.items():
                if k in scene_dict:
                    scene_dict[k] = v
            
            # Reconstruct and validate
            if isinstance(scene_dict.get("camera"), dict):
                scene_dict["camera"] = CameraPlan(**scene_dict["camera"])
            if scene_dict.get("actions") and isinstance(scene_dict["actions"][0], dict):
                scene_dict["actions"] = [ActionPlan(**a) for a in scene_dict["actions"]]
            
            updated_scene = SceneNode(**scene_dict)
            cam_dict = asdict(updated_scene.camera) if isinstance(updated_scene.camera, CameraPlan) else (updated_scene.camera or {})
            act_list = [asdict(a) if isinstance(a, ActionPlan) else a for a in updated_scene.actions]
            
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    UPDATE scenes SET
                        episode_id=?, scene_number=?, scene_name=?, description=?,
                        character_ids_json=?, location_id=?, camera_json=?, actions_json=?,
                        dialogue_lines_json=?, transition_in=?, transition_out=?,
                        previous_scene_state=?, current_state=?, next_scene_intent=?,
                        prompt_text=?, prompt_version=?, duration_target_sec=?,
                        generation_job_id=?, selected_candidate_id=?
                    WHERE scene_id=?
                    """,
                    (
                        updated_scene.episode_id, updated_scene.scene_number, updated_scene.scene_name,
                        updated_scene.description, json.dumps(updated_scene.character_ids),
                        updated_scene.location_id, json.dumps(cam_dict),
                        json.dumps(act_list),
                        json.dumps(updated_scene.dialogue_lines), updated_scene.transition_in,
                        updated_scene.transition_out, updated_scene.previous_scene_state,
                        updated_scene.current_state, updated_scene.next_scene_intent,
                        updated_scene.prompt_text, updated_scene.prompt_version,
                        updated_scene.duration_target_sec, updated_scene.generation_job_id,
                        updated_scene.selected_candidate_id, scene_id
                    )
                )
            return updated_scene

    def validate_continuity(self, episode_id: str) -> List[str]:
        scenes = self.get_scenes_for_episode(episode_id)
        warnings = []
        for i in range(1, len(scenes)):
            prev = scenes[i-1]
            curr = scenes[i]
            if prev.next_scene_intent != curr.previous_scene_state:
                warnings.append(
                    f"Continuity mismatch between scene {prev.scene_number} and {curr.scene_number}: "
                    f"Expected '{prev.next_scene_intent}', got '{curr.previous_scene_state}'"
                )
        return warnings

    def get_scene_context(self, scene_id: str) -> str:
        scene = self.get_scene(scene_id)
        if not scene:
            return ""
        
        context = f"Scene {scene.scene_number}: {scene.scene_name}\n"
        context += f"Description: {scene.description}\n"
        context += f"Camera: {scene.camera.shot_type}, {scene.camera.movement}\n"
        for act in scene.actions:
            context += f"Action: {act.character_id} {act.movement} - {act.interaction}\n"
        return context
