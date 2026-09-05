"""
Persistent character identity system with immutable versioning.
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
class Character:
    character_id: str
    name: str
    age_range: str = ""
    gender_presentation: str = ""
    physical_description: str = ""
    face_description: str = ""
    hair: str = ""
    eyes: str = ""
    skin_description: str = ""
    body_type: str = ""
    wardrobe: str = ""
    signature_items: List[str] = field(default_factory=list)
    personality: str = ""
    speech_style: str = ""
    voice_id: str = ""
    voice_provider: str = "elevenlabs"
    voice_version: str = ""
    visual_style: str = ""
    negative_constraints: List[str] = field(default_factory=list)
    reference_asset_paths: List[str] = field(default_factory=list)
    version: int = 1
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "character_id": self.character_id,
            "name": self.name,
            "age_range": self.age_range,
            "gender_presentation": self.gender_presentation,
            "physical_description": self.physical_description,
            "face_description": self.face_description,
            "hair": self.hair,
            "eyes": self.eyes,
            "skin_description": self.skin_description,
            "body_type": self.body_type,
            "wardrobe": self.wardrobe,
            "signature_items": self.signature_items,
            "personality": self.personality,
            "speech_style": self.speech_style,
            "voice_id": self.voice_id,
            "voice_provider": self.voice_provider,
            "voice_version": self.voice_version,
            "visual_style": self.visual_style,
            "negative_constraints": self.negative_constraints,
            "reference_asset_paths": self.reference_asset_paths,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_active": self.is_active,
        }

class CharacterBible:
    def __init__(self, db: KnowledgeDatabase):
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        create_sql = """
        CREATE TABLE IF NOT EXISTS characters (
            id TEXT PRIMARY KEY,
            character_id TEXT NOT NULL,
            name TEXT NOT NULL,
            age_range TEXT,
            gender_presentation TEXT,
            physical_description TEXT,
            face_description TEXT,
            hair TEXT,
            eyes TEXT,
            skin_description TEXT,
            body_type TEXT,
            wardrobe TEXT,
            signature_items_json TEXT,
            personality TEXT,
            speech_style TEXT,
            voice_id TEXT,
            voice_provider TEXT DEFAULT 'elevenlabs',
            voice_version TEXT,
            visual_style TEXT,
            negative_constraints_json TEXT,
            reference_asset_paths_json TEXT,
            version INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_characters_cid ON characters(character_id);
        CREATE INDEX IF NOT EXISTS idx_characters_active ON characters(is_active);
        """
        conn = self.db._get_connection()
        conn.executescript(create_sql)

    def _row_to_character(self, row: Any) -> Character:
        return Character(
            character_id=row["character_id"],
            name=row["name"],
            age_range=row["age_range"],
            gender_presentation=row["gender_presentation"],
            physical_description=row["physical_description"],
            face_description=row["face_description"],
            hair=row["hair"],
            eyes=row["eyes"],
            skin_description=row["skin_description"],
            body_type=row["body_type"],
            wardrobe=row["wardrobe"],
            signature_items=json.loads(row["signature_items_json"] or "[]"),
            personality=row["personality"],
            speech_style=row["speech_style"],
            voice_id=row["voice_id"],
            voice_provider=row["voice_provider"],
            voice_version=row["voice_version"],
            visual_style=row["visual_style"],
            negative_constraints=json.loads(row["negative_constraints_json"] or "[]"),
            reference_asset_paths=json.loads(row["reference_asset_paths_json"] or "[]"),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_active=bool(row["is_active"]),
        )

    def create_character(self, **kwargs: Any) -> Character:
        c = Character(**kwargs)
        c.version = 1
        now = _now_iso()
        c.created_at = now
        c.updated_at = now
        row_id = f"char_{uuid.uuid4().hex}"
        
        insert_sql = """
        INSERT INTO characters (
            id, character_id, name, age_range, gender_presentation, physical_description,
            face_description, hair, eyes, skin_description, body_type, wardrobe,
            signature_items_json, personality, speech_style, voice_id, voice_provider,
            voice_version, visual_style, negative_constraints_json, reference_asset_paths_json,
            version, is_active, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """
        params = (
            row_id, c.character_id, c.name, c.age_range, c.gender_presentation,
            c.physical_description, c.face_description, c.hair, c.eyes, c.skin_description,
            c.body_type, c.wardrobe, json.dumps(c.signature_items), c.personality,
            c.speech_style, c.voice_id, c.voice_provider, c.voice_version,
            c.visual_style, json.dumps(c.negative_constraints),
            json.dumps(c.reference_asset_paths), c.version, int(c.is_active),
            c.created_at, c.updated_at
        )
        with self.db.transaction() as cur:
            cur.execute(insert_sql, params)
        return c

    def get_character(self, character_id: str, version: Optional[int] = None) -> Optional[Character]:
        if version is not None:
            query = "SELECT * FROM characters WHERE character_id = ? AND version = ?"
            row = self.db.execute_single(query, (character_id, version))
        else:
            query = "SELECT * FROM characters WHERE character_id = ? ORDER BY version DESC LIMIT 1"
            row = self.db.execute_single(query, (character_id,))
            
        if row:
            return self._row_to_character(row)
        return None

    def get_all_characters(self, active_only: bool = True) -> List[Character]:
        # Get latest version for each character
        query = """
        SELECT c.* FROM characters c
        INNER JOIN (
            SELECT character_id, MAX(version) as max_version
            FROM characters
            GROUP BY character_id
        ) max_c ON c.character_id = max_c.character_id AND c.version = max_c.max_version
        """
        if active_only:
            query += " WHERE c.is_active = 1"
            
        rows = self.db.execute(query)
        return [self._row_to_character(r) for r in rows]

    def update_character(self, character_id: str, **changes: Any) -> Character:
        latest = self.get_character(character_id)
        if not latest:
            raise ValueError(f"Character {character_id} not found")
            
        kwargs = latest.to_dict()
        kwargs.update(changes)
        kwargs["version"] += 1
        kwargs["updated_at"] = _now_iso()
        
        c = Character(**kwargs)
        row_id = f"char_{uuid.uuid4().hex}"
        
        insert_sql = """
        INSERT INTO characters (
            id, character_id, name, age_range, gender_presentation, physical_description,
            face_description, hair, eyes, skin_description, body_type, wardrobe,
            signature_items_json, personality, speech_style, voice_id, voice_provider,
            voice_version, visual_style, negative_constraints_json, reference_asset_paths_json,
            version, is_active, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """
        params = (
            row_id, c.character_id, c.name, c.age_range, c.gender_presentation,
            c.physical_description, c.face_description, c.hair, c.eyes, c.skin_description,
            c.body_type, c.wardrobe, json.dumps(c.signature_items), c.personality,
            c.speech_style, c.voice_id, c.voice_provider, c.voice_version,
            c.visual_style, json.dumps(c.negative_constraints),
            json.dumps(c.reference_asset_paths), c.version, int(c.is_active),
            c.created_at, c.updated_at
        )
        with self.db.transaction() as cur:
            cur.execute(insert_sql, params)
        return c

    def get_character_context(self, character_id: str, version: Optional[int] = None) -> str:
        c = self.get_character(character_id, version)
        if not c:
            return ""
            
        context = []
        context.append(f"Character: {c.name}")
        context.append(f"Version: {c.version}")
        appearance = [
            f"{c.age_range}-year-old {c.gender_presentation}",
            c.hair,
            c.eyes,
            c.physical_description,
            c.body_type
        ]
        appearance = [a for a in appearance if a]
        context.append(f"Appearance: {', '.join(appearance)}")
        context.append(f"Wardrobe: {c.wardrobe}")
        context.append(f"Personality: {c.personality}")
        context.append(f"Speech Style: {c.speech_style}")
        context.append(f"Visual Style: {c.visual_style}")
        
        if c.negative_constraints:
            context.append(f"Do NOT: {', '.join(c.negative_constraints)}")
            
        return "\n".join(context)

    def get_character_history(self, character_id: str) -> List[Character]:
        query = "SELECT * FROM characters WHERE character_id = ? ORDER BY version ASC"
        rows = self.db.execute(query, (character_id,))
        return [self._row_to_character(r) for r in rows]
