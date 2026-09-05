"""
Series-level narrative continuity.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from brain.knowledge_database import KnowledgeDatabase


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StoryBible:
    story_id: str
    series_name: str
    genre: str = "Sci-Fi"
    premise: str = ""
    tone: str = ""
    themes: List[str] = field(default_factory=list)
    world_rules: List[str] = field(default_factory=list)
    character_ids: List[str] = field(default_factory=list)
    location_ids: List[str] = field(default_factory=list)
    visual_style_id: str = ""
    audio_style: str = ""
    canon_events: List[Dict[str, Any]] = field(default_factory=list)
    open_threads: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "story_id": self.story_id,
            "series_name": self.series_name,
            "genre": self.genre,
            "premise": self.premise,
            "tone": self.tone,
            "themes": self.themes,
            "world_rules": self.world_rules,
            "character_ids": self.character_ids,
            "location_ids": self.location_ids,
            "visual_style_id": self.visual_style_id,
            "audio_style": self.audio_style,
            "canon_events": self.canon_events,
            "open_threads": self.open_threads,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

@dataclass
class EpisodeBible:
    episode_id: str
    story_id: str
    episode_number: int = 1
    title: str = ""
    story_arc: str = ""
    previous_episode_summary: str = ""
    current_conflict: str = ""
    character_states: Dict[str, str] = field(default_factory=dict)
    location_states: Dict[str, str] = field(default_factory=dict)
    important_props: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    resolved_questions: List[str] = field(default_factory=list)
    visual_continuity: str = ""
    audio_continuity: str = ""
    canon_status: str = "CANON" # CANON, OPTIONAL, NON_CANON
    scene_ids: List[str] = field(default_factory=list)
    final_artifact_path: str = ""
    analytics_snapshot_id: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "story_id": self.story_id,
            "episode_number": self.episode_number,
            "title": self.title,
            "story_arc": self.story_arc,
            "previous_episode_summary": self.previous_episode_summary,
            "current_conflict": self.current_conflict,
            "character_states": self.character_states,
            "location_states": self.location_states,
            "important_props": self.important_props,
            "open_questions": self.open_questions,
            "resolved_questions": self.resolved_questions,
            "visual_continuity": self.visual_continuity,
            "audio_continuity": self.audio_continuity,
            "canon_status": self.canon_status,
            "scene_ids": self.scene_ids,
            "final_artifact_path": self.final_artifact_path,
            "analytics_snapshot_id": self.analytics_snapshot_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

class StoryBibleStore:
    def __init__(self, db: KnowledgeDatabase):
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        create_sql = """
        CREATE TABLE IF NOT EXISTS stories (
            story_id TEXT PRIMARY KEY,
            series_name TEXT NOT NULL,
            genre TEXT,
            premise TEXT,
            tone TEXT,
            themes_json TEXT,
            world_rules_json TEXT,
            character_ids_json TEXT,
            location_ids_json TEXT,
            visual_style_id TEXT,
            audio_style TEXT,
            canon_events_json TEXT,
            open_threads_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS episodes (
            episode_id TEXT PRIMARY KEY,
            story_id TEXT NOT NULL,
            episode_number INTEGER,
            title TEXT,
            story_arc TEXT,
            previous_episode_summary TEXT,
            current_conflict TEXT,
            character_states_json TEXT,
            location_states_json TEXT,
            important_props_json TEXT,
            open_questions_json TEXT,
            resolved_questions_json TEXT,
            visual_continuity TEXT,
            audio_continuity TEXT,
            canon_status TEXT,
            scene_ids_json TEXT,
            final_artifact_path TEXT,
            analytics_snapshot_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(story_id) REFERENCES stories(story_id)
        );
        CREATE INDEX IF NOT EXISTS idx_episodes_story ON episodes(story_id, episode_number);
        """
        conn = self.db._get_connection()
        conn.executescript(create_sql)

    def _row_to_story(self, row: Any) -> StoryBible:
        return StoryBible(
            story_id=row["story_id"],
            series_name=row["series_name"],
            genre=row["genre"],
            premise=row["premise"],
            tone=row["tone"],
            themes=json.loads(row["themes_json"] or "[]"),
            world_rules=json.loads(row["world_rules_json"] or "[]"),
            character_ids=json.loads(row["character_ids_json"] or "[]"),
            location_ids=json.loads(row["location_ids_json"] or "[]"),
            visual_style_id=row["visual_style_id"],
            audio_style=row["audio_style"],
            canon_events=json.loads(row["canon_events_json"] or "[]"),
            open_threads=json.loads(row["open_threads_json"] or "[]"),
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )

    def _row_to_episode(self, row: Any) -> EpisodeBible:
        return EpisodeBible(
            episode_id=row["episode_id"],
            story_id=row["story_id"],
            episode_number=row["episode_number"],
            title=row["title"],
            story_arc=row["story_arc"],
            previous_episode_summary=row["previous_episode_summary"],
            current_conflict=row["current_conflict"],
            character_states=json.loads(row["character_states_json"] or "{}"),
            location_states=json.loads(row["location_states_json"] or "{}"),
            important_props=json.loads(row["important_props_json"] or "[]"),
            open_questions=json.loads(row["open_questions_json"] or "[]"),
            resolved_questions=json.loads(row["resolved_questions_json"] or "[]"),
            visual_continuity=row["visual_continuity"],
            audio_continuity=row["audio_continuity"],
            canon_status=row["canon_status"],
            scene_ids=json.loads(row["scene_ids_json"] or "[]"),
            final_artifact_path=row["final_artifact_path"],
            analytics_snapshot_id=row["analytics_snapshot_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )

    def create_story(self, **kwargs: Any) -> StoryBible:
        story = StoryBible(**kwargs)
        now = _now_iso()
        story.created_at = now
        story.updated_at = now
        if not story.story_id:
            story.story_id = f"story_{uuid.uuid4().hex}"
            
        insert_sql = """
        INSERT INTO stories (
            story_id, series_name, genre, premise, tone, themes_json,
            world_rules_json, character_ids_json, location_ids_json,
            visual_style_id, audio_style, canon_events_json, open_threads_json,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """
        params = (
            story.story_id, story.series_name, story.genre, story.premise,
            story.tone, json.dumps(story.themes), json.dumps(story.world_rules),
            json.dumps(story.character_ids), json.dumps(story.location_ids),
            story.visual_style_id, story.audio_style, json.dumps(story.canon_events),
            json.dumps(story.open_threads), story.created_at, story.updated_at
        )
        with self.db.transaction() as cur:
            cur.execute(insert_sql, params)
        return story

    def get_story(self, story_id: str) -> Optional[StoryBible]:
        query = "SELECT * FROM stories WHERE story_id = ?"
        row = self.db.execute_single(query, (story_id,))
        if row:
            return self._row_to_story(row)
        return None

    def get_all_stories(self) -> List[StoryBible]:
        query = "SELECT * FROM stories"
        rows = self.db.execute(query)
        return [self._row_to_story(r) for r in rows]

    def update_story(self, story_id: str, **changes: Any) -> StoryBible:
        story = self.get_story(story_id)
        if not story:
            raise ValueError(f"Story {story_id} not found")
            
        kwargs = story.to_dict()
        kwargs.update(changes)
        kwargs["updated_at"] = _now_iso()
        
        updated_story = StoryBible(**kwargs)
        update_sql = """
        UPDATE stories SET
            series_name = ?, genre = ?, premise = ?, tone = ?, themes_json = ?,
            world_rules_json = ?, character_ids_json = ?, location_ids_json = ?,
            visual_style_id = ?, audio_style = ?, canon_events_json = ?, open_threads_json = ?,
            updated_at = ?
        WHERE story_id = ?
        """
        params = (
            updated_story.series_name, updated_story.genre, updated_story.premise,
            updated_story.tone, json.dumps(updated_story.themes), json.dumps(updated_story.world_rules),
            json.dumps(updated_story.character_ids), json.dumps(updated_story.location_ids),
            updated_story.visual_style_id, updated_story.audio_style, json.dumps(updated_story.canon_events),
            json.dumps(updated_story.open_threads), updated_story.updated_at,
            story_id
        )
        with self.db.transaction() as cur:
            cur.execute(update_sql, params)
        return updated_story
        
    def add_canon_event(self, story_id: str, event: Dict[str, Any]) -> None:
        story = self.get_story(story_id)
        if not story:
            raise ValueError(f"Story {story_id} not found")
            
        events = story.canon_events + [event]
        self.update_story(story_id, canon_events=events)

    def create_episode(self, **kwargs: Any) -> EpisodeBible:
        episode = EpisodeBible(**kwargs)
        now = _now_iso()
        episode.created_at = now
        episode.updated_at = now
        if not episode.episode_id:
            episode.episode_id = f"ep_{uuid.uuid4().hex}"
            
        insert_sql = """
        INSERT INTO episodes (
            episode_id, story_id, episode_number, title, story_arc,
            previous_episode_summary, current_conflict, character_states_json,
            location_states_json, important_props_json, open_questions_json,
            resolved_questions_json, visual_continuity, audio_continuity,
            canon_status, scene_ids_json, final_artifact_path, analytics_snapshot_id,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """
        params = (
            episode.episode_id, episode.story_id, episode.episode_number,
            episode.title, episode.story_arc, episode.previous_episode_summary,
            episode.current_conflict, json.dumps(episode.character_states),
            json.dumps(episode.location_states), json.dumps(episode.important_props),
            json.dumps(episode.open_questions), json.dumps(episode.resolved_questions),
            episode.visual_continuity, episode.audio_continuity, episode.canon_status,
            json.dumps(episode.scene_ids), episode.final_artifact_path,
            episode.analytics_snapshot_id, episode.created_at, episode.updated_at
        )
        with self.db.transaction() as cur:
            cur.execute(insert_sql, params)
        return episode

    def get_episode(self, episode_id: str) -> Optional[EpisodeBible]:
        query = "SELECT * FROM episodes WHERE episode_id = ?"
        row = self.db.execute_single(query, (episode_id,))
        if row:
            return self._row_to_episode(row)
        return None

    def get_episodes_for_story(self, story_id: str) -> List[EpisodeBible]:
        query = "SELECT * FROM episodes WHERE story_id = ? ORDER BY episode_number ASC"
        rows = self.db.execute(query, (story_id,))
        return [self._row_to_episode(r) for r in rows]

    def get_latest_episode(self, story_id: str) -> Optional[EpisodeBible]:
        query = "SELECT * FROM episodes WHERE story_id = ? ORDER BY episode_number DESC LIMIT 1"
        row = self.db.execute_single(query, (story_id,))
        if row:
            return self._row_to_episode(row)
        return None

    def update_episode(self, episode_id: str, **changes: Any) -> EpisodeBible:
        episode = self.get_episode(episode_id)
        if not episode:
            raise ValueError(f"Episode {episode_id} not found")
            
        kwargs = episode.to_dict()
        kwargs.update(changes)
        kwargs["updated_at"] = _now_iso()
        
        updated = EpisodeBible(**kwargs)
        update_sql = """
        UPDATE episodes SET
            story_id = ?, episode_number = ?, title = ?, story_arc = ?,
            previous_episode_summary = ?, current_conflict = ?, character_states_json = ?,
            location_states_json = ?, important_props_json = ?, open_questions_json = ?,
            resolved_questions_json = ?, visual_continuity = ?, audio_continuity = ?,
            canon_status = ?, scene_ids_json = ?, final_artifact_path = ?,
            analytics_snapshot_id = ?, updated_at = ?
        WHERE episode_id = ?
        """
        params = (
            updated.story_id, updated.episode_number, updated.title, updated.story_arc,
            updated.previous_episode_summary, updated.current_conflict, json.dumps(updated.character_states),
            json.dumps(updated.location_states), json.dumps(updated.important_props), json.dumps(updated.open_questions),
            json.dumps(updated.resolved_questions), updated.visual_continuity, updated.audio_continuity,
            updated.canon_status, json.dumps(updated.scene_ids), updated.final_artifact_path,
            updated.analytics_snapshot_id, updated.updated_at, episode_id
        )
        with self.db.transaction() as cur:
            cur.execute(update_sql, params)
        return updated

    def get_episode_context(self, episode_id: str) -> str:
        ep = self.get_episode(episode_id)
        if not ep:
            return ""
        
        context = []
        context.append(f"Episode {ep.episode_number}: {ep.title}")
        context.append(f"Story Arc: {ep.story_arc}")
        context.append(f"Previous Summary: {ep.previous_episode_summary}")
        context.append(f"Current Conflict: {ep.current_conflict}")
        if ep.character_states:
            states = [f"{k}: {v}" for k, v in ep.character_states.items()]
            context.append(f"Character States: {'; '.join(states)}")
        return "\n".join(context)
