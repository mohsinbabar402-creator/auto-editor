"""
Persistent world/location/style system.
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
class Location:
    location_id: str
    name: str
    description: str = ""
    architecture: str = ""
    walls: str = ""
    windows: str = ""
    furniture: str = ""
    lighting: str = ""
    time_of_day: str = ""
    weather: str = ""
    props: List[str] = field(default_factory=list)
    visual_constraints: List[str] = field(default_factory=list)
    version: int = 1
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "location_id": self.location_id,
            "name": self.name,
            "description": self.description,
            "architecture": self.architecture,
            "walls": self.walls,
            "windows": self.windows,
            "furniture": self.furniture,
            "lighting": self.lighting,
            "time_of_day": self.time_of_day,
            "weather": self.weather,
            "props": self.props,
            "visual_constraints": self.visual_constraints,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

@dataclass
class StyleBible:
    style_id: str
    name: str
    lens: str = "35mm"
    color_palette: str = ""
    lighting_style: str = ""
    camera_defaults: str = ""
    depth_of_field: str = ""
    grain_texture: str = ""
    aspect_ratio: str = "9:16"
    negative_style: List[str] = field(default_factory=list)
    version: int = 1
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "style_id": self.style_id,
            "name": self.name,
            "lens": self.lens,
            "color_palette": self.color_palette,
            "lighting_style": self.lighting_style,
            "camera_defaults": self.camera_defaults,
            "depth_of_field": self.depth_of_field,
            "grain_texture": self.grain_texture,
            "aspect_ratio": self.aspect_ratio,
            "negative_style": self.negative_style,
            "version": self.version,
            "created_at": self.created_at,
        }


class WorldBible:
    def __init__(self, db: KnowledgeDatabase):
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        create_sql = """
        CREATE TABLE IF NOT EXISTS locations (
            id TEXT PRIMARY KEY,
            location_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            architecture TEXT,
            walls TEXT,
            windows TEXT,
            furniture TEXT,
            lighting TEXT,
            time_of_day TEXT,
            weather TEXT,
            props_json TEXT,
            visual_constraints_json TEXT,
            version INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_locations_lid ON locations(location_id);
        
        CREATE TABLE IF NOT EXISTS style_bibles (
            id TEXT PRIMARY KEY,
            style_id TEXT NOT NULL,
            name TEXT NOT NULL,
            lens TEXT,
            color_palette TEXT,
            lighting_style TEXT,
            camera_defaults TEXT,
            depth_of_field TEXT,
            grain_texture TEXT,
            aspect_ratio TEXT DEFAULT '9:16',
            negative_style_json TEXT,
            version INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_styles_sid ON style_bibles(style_id);
        """
        conn = self.db._get_connection()
        conn.executescript(create_sql)

    def _row_to_location(self, row: Any) -> Location:
        return Location(
            location_id=row["location_id"],
            name=row["name"],
            description=row["description"],
            architecture=row["architecture"],
            walls=row["walls"],
            windows=row["windows"],
            furniture=row["furniture"],
            lighting=row["lighting"],
            time_of_day=row["time_of_day"],
            weather=row["weather"],
            props=json.loads(row["props_json"] or "[]"),
            visual_constraints=json.loads(row["visual_constraints_json"] or "[]"),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )

    def create_location(self, **kwargs: Any) -> Location:
        loc = Location(**kwargs)
        loc.version = 1
        now = _now_iso()
        loc.created_at = now
        loc.updated_at = now
        row_id = f"loc_{uuid.uuid4().hex}"
        
        insert_sql = """
        INSERT INTO locations (
            id, location_id, name, description, architecture, walls, windows,
            furniture, lighting, time_of_day, weather, props_json, visual_constraints_json,
            version, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """
        params = (
            row_id, loc.location_id, loc.name, loc.description, loc.architecture,
            loc.walls, loc.windows, loc.furniture, loc.lighting, loc.time_of_day,
            loc.weather, json.dumps(loc.props), json.dumps(loc.visual_constraints),
            loc.version, loc.created_at, loc.updated_at
        )
        with self.db.transaction() as cur:
            cur.execute(insert_sql, params)
        return loc

    def get_location(self, location_id: str, version: Optional[int] = None) -> Optional[Location]:
        if version is not None:
            query = "SELECT * FROM locations WHERE location_id = ? AND version = ?"
            row = self.db.execute_single(query, (location_id, version))
        else:
            query = "SELECT * FROM locations WHERE location_id = ? ORDER BY version DESC LIMIT 1"
            row = self.db.execute_single(query, (location_id,))
            
        if row:
            return self._row_to_location(row)
        return None

    def get_all_locations(self) -> List[Location]:
        query = """
        SELECT l.* FROM locations l
        INNER JOIN (
            SELECT location_id, MAX(version) as max_version
            FROM locations
            GROUP BY location_id
        ) max_l ON l.location_id = max_l.location_id AND l.version = max_l.max_version
        """
        rows = self.db.execute(query)
        return [self._row_to_location(r) for r in rows]

    def update_location(self, location_id: str, **changes: Any) -> Location:
        latest = self.get_location(location_id)
        if not latest:
            raise ValueError(f"Location {location_id} not found")
            
        kwargs = latest.to_dict()
        kwargs.update(changes)
        kwargs["version"] += 1
        kwargs["updated_at"] = _now_iso()
        
        loc = Location(**kwargs)
        row_id = f"loc_{uuid.uuid4().hex}"
        
        insert_sql = """
        INSERT INTO locations (
            id, location_id, name, description, architecture, walls, windows,
            furniture, lighting, time_of_day, weather, props_json, visual_constraints_json,
            version, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """
        params = (
            row_id, loc.location_id, loc.name, loc.description, loc.architecture,
            loc.walls, loc.windows, loc.furniture, loc.lighting, loc.time_of_day,
            loc.weather, json.dumps(loc.props), json.dumps(loc.visual_constraints),
            loc.version, loc.created_at, loc.updated_at
        )
        with self.db.transaction() as cur:
            cur.execute(insert_sql, params)
        return loc

    def get_location_context(self, location_id: str) -> str:
        loc = self.get_location(location_id)
        if not loc:
            return ""
            
        context = []
        context.append(f"Location: {loc.name}")
        context.append(f"Description: {loc.description}")
        context.append(f"Lighting & Weather: {loc.lighting}, {loc.time_of_day}, {loc.weather}")
        context.append(f"Furniture & Props: {loc.furniture}")
        
        if loc.visual_constraints:
            context.append(f"Constraints: {', '.join(loc.visual_constraints)}")
            
        return "\n".join(context)

    def _row_to_style(self, row: Any) -> StyleBible:
        return StyleBible(
            style_id=row["style_id"],
            name=row["name"],
            lens=row["lens"],
            color_palette=row["color_palette"],
            lighting_style=row["lighting_style"],
            camera_defaults=row["camera_defaults"],
            depth_of_field=row["depth_of_field"],
            grain_texture=row["grain_texture"],
            aspect_ratio=row["aspect_ratio"],
            negative_style=json.loads(row["negative_style_json"] or "[]"),
            version=row["version"],
            created_at=row["created_at"]
        )

    def create_style(self, **kwargs: Any) -> StyleBible:
        style = StyleBible(**kwargs)
        style.version = 1
        style.created_at = _now_iso()
        row_id = f"sty_{uuid.uuid4().hex}"
        
        insert_sql = """
        INSERT INTO style_bibles (
            id, style_id, name, lens, color_palette, lighting_style, camera_defaults,
            depth_of_field, grain_texture, aspect_ratio, negative_style_json,
            version, created_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """
        params = (
            row_id, style.style_id, style.name, style.lens, style.color_palette,
            style.lighting_style, style.camera_defaults, style.depth_of_field,
            style.grain_texture, style.aspect_ratio, json.dumps(style.negative_style),
            style.version, style.created_at
        )
        with self.db.transaction() as cur:
            cur.execute(insert_sql, params)
        return style

    def get_style(self, style_id: str) -> Optional[StyleBible]:
        query = "SELECT * FROM style_bibles WHERE style_id = ? ORDER BY version DESC LIMIT 1"
        row = self.db.execute_single(query, (style_id,))
        if row:
            return self._row_to_style(row)
        return None

    def get_all_styles(self) -> List[StyleBible]:
        query = """
        SELECT s.* FROM style_bibles s
        INNER JOIN (
            SELECT style_id, MAX(version) as max_version
            FROM style_bibles
            GROUP BY style_id
        ) max_s ON s.style_id = max_s.style_id AND s.version = max_s.max_version
        """
        rows = self.db.execute(query)
        return [self._row_to_style(r) for r in rows]
