import json
import logging
import os
import re
from typing import Any, Dict, Optional

from config import settings
from analysis.transcript import NormalizedTranscript

logger = logging.getLogger("whop_editor.ai.editor")


class AIEditorError(Exception):
    """Raised when AI edit proposal generation fails."""
    pass


class AIEditor:
    """
    Stateless reasoning layer: analyzes transcript and proposes structured edit decisions.
    
    Guarantees:
    - Never executes FFmpeg or file operations.
    - Never writes directly to the database.
    - Emits only structured dictionary matching {"word_index": int, "scale": float, "duration_ms": int}.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or settings.GOOGLE_API_KEY
        self.model_name = model_name or settings.GEMINI_MODEL_NAME

    def propose_punch_in(
        self,
        transcript: NormalizedTranscript,
        project_niche: str = "Whop short-form creator education"
    ) -> Dict[str, Any]:
        """
        Asks Gemini to identify the single most impactful word token for a punch-in zoom.
        Falls back to deterministic heuristic emphasis if API key is not configured.
        """
        if len(transcript) == 0:
            raise AIEditorError("Cannot propose an edit for an empty transcript.")

        # If no Gemini API key is configured, use deterministic linguistic heuristic
        if not self.api_key:
            logger.warning("No GOOGLE_API_KEY configured. Using deterministic fallback selection.")
            return self._heuristic_fallback_proposal(transcript)

        # Build clean, unambiguous prompt
        tokens_context = transcript.to_prompt_context()
        prompt = (
            f"You are a master short-form video editor for: {project_niche}.\n"
            f"Analyze the following numbered transcript tokens:\n"
            f"{tokens_context}\n\n"
            f"Select ONE single word token index that represents the peak narrative emphasis, "
            f"crucial keyword, revenue metric, or primary value hook to apply a punch-in zoom.\n\n"
            f"Respond with ONLY a raw JSON object matching this schema exactly:\n"
            f'{{\n  "word_index": <int>,\n  "scale": <float between 1.10 and 1.25>,\n  "duration_ms": <int between 400 and 1200>\n}}\n'
            f"Do not include markdown code blocks, backticks, or explanatory text."
        )

        try:
            raw_text = self._call_gemini(prompt)
            cleaned_json = self._extract_json(raw_text)
            data = json.loads(cleaned_json)
            logger.info(f"Gemini proposed punch-in: {data}")
            return data
        except Exception as e:
            logger.warning(f"Gemini call failed ({e}). Falling back to deterministic heuristic.")
            return self._heuristic_fallback_proposal(transcript)

    def _call_gemini(self, prompt: str) -> str:
        """Invokes Gemini model."""
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model_name)
            response = model.generate_content(
                prompt,
                generation_config={"temperature": 0.1, "max_output_tokens": 150}
            )
            return response.text
        except Exception as e:
            raise AIEditorError(f"Gemini API request failed: {e}") from e

    def _extract_json(self, text: str) -> str:
        """Strips markdown code blocks, whitespace, and non-JSON wrappers."""
        text = text.strip()
        # Strip ```json ... ```
        if "```" in text:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                return match.group(1).strip()
        # Search for first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text[start:end+1]
        return text

    def _heuristic_fallback_proposal(self, transcript: NormalizedTranscript) -> Dict[str, Any]:
        """
        Deterministic heuristic fallback for testing, offline mode, or API outages:
        Scans for high-value business/impact keywords, or selects the longest content word in the middle third.
        """
        keywords = {
            "revenue", "money", "scale", "secret", "growth", "community", "sales", "dollars",
            "profit", "results", "launch", "freedom", "subscribers", "customers", "whop", "blueprint"
        }
        
        chosen_idx = None
        for w in transcript.words:
            clean = re.sub(r"[^\w]", "", w.word.lower())
            if clean in keywords:
                chosen_idx = w.index
                break

        if chosen_idx is None:
            # Pick longest word in the middle third of the transcript
            start_bound = len(transcript) // 3
            end_bound = max(start_bound + 1, (2 * len(transcript)) // 3)
            candidates = transcript.words[start_bound:end_bound] or transcript.words
            chosen_idx = max(candidates, key=lambda token: len(token.word)).index

        return {
            "word_index": chosen_idx,
            "scale": 1.15,
            "duration_ms": 750
        }
