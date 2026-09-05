from __future__ import annotations

import hashlib
from typing import Any, Optional
from brain.scene_graph import SceneNode


class PromptCompiler:
    def __init__(self, character_bible: Any, world_bible: Any, story_bible_store: Any) -> None:
        self.character_bible = character_bible
        self.world_bible = world_bible
        self.story_bible_store = story_bible_store

    def compile_scene_prompt(self, scene: SceneNode, episode: Any, story: Any, style: Any = None) -> str:
        prompt_parts = []
        prompt_parts.append(f"Episode: {getattr(episode, 'title', 'Untitled')}")
        prompt_parts.append(f"Scene: {scene.scene_name}")
        prompt_parts.append(f"Setting: {scene.location_id}")
        prompt_parts.append(f"Description: {scene.description}")
        
        camera = scene.camera
        prompt_parts.append(
            f"Camera: {camera.shot_type}, {camera.lens} lens, {camera.depth_of_field} focus. "
            f"Movement: {camera.movement}. Framing: {camera.framing}. "
            f"Lighting: {camera.lighting}. Time: {camera.time_of_day}."
        )
        
        for action in scene.actions:
            prompt_parts.append(
                f"Action - {action.character_id}: Starts at {action.starting_position}. "
                f"{action.movement}. Emotion: {action.emotional_state}. "
                f"Ends at {action.ending_position}."
            )
            
        if style:
            prompt_parts.append(f"Style: {style}")
            
        return "\n".join(prompt_parts)

    def compile_google_flow_prompt(self, scene: SceneNode, episode: Any, story: Any, style: Any = None) -> str:
        # Resolve character descriptions
        char_descriptions = []
        for char_id in scene.character_ids:
            char_obj = None
            if hasattr(self.character_bible, "get_character"):
                char_obj = self.character_bible.get_character(char_id)
            if char_obj:
                desc = f"{char_obj.name}: {char_obj.physical_description or char_obj.face_description}"
                if char_obj.wardrobe:
                    desc += f", wearing {char_obj.wardrobe}"
                char_descriptions.append(desc)
            else:
                char_descriptions.append(f"Character {char_id}")
        char_desc_str = ". ".join(char_descriptions)

        # Resolve location description
        loc_desc = scene.location_id
        if hasattr(self.world_bible, "get_location"):
            loc_obj = self.world_bible.get_location(scene.location_id)
            if loc_obj:
                loc_desc = f"{loc_obj.name} ({loc_obj.description or loc_obj.architecture})"

        # Resolve style description
        style_desc = ""
        if style:
            if hasattr(style, "name"):
                style_desc = f"{style.name}, {getattr(style, 'lens', '')}, {getattr(style, 'lighting_style', '')}"
            else:
                style_desc = str(style)
        else:
            style_desc = "cinematic lighting, 35mm lens, photorealistic"

        camera_dir = scene.camera.shot_type if hasattr(scene.camera, "shot_type") else "MEDIUM_SHOT"
        action_desc = " ".join([f"{a.character_id} {a.movement} {a.interaction}".strip() for a in scene.actions])
        lighting = getattr(scene.camera, "lighting", "")

        negative_constraints = "text, watermarks, deformed features, low resolution, bad anatomy"

        prompt = (
            f"Vertical 9:16 format cinematic video. {camera_dir}. Setting: {loc_desc}. "
            f"{char_desc_str}. Action: {action_desc}. Lighting: {lighting}. Style: {style_desc}. "
            f"Do not include {negative_constraints}."
        )
        return prompt

    def get_prompt_version(self, prompt_text: str) -> str:
        return hashlib.sha256(prompt_text.encode('utf-8')).hexdigest()
