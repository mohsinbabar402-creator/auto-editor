"""
TMDb (The Movie Database) API Client for Channel 4 (Movie Recaps)
Provides official movie metadata, cast, synopses, and direct YouTube video IDs.
"""
import requests
from typing import Dict, Any, List, Optional
import config

TMDB_BASE_URL = "https://api.themoviedb.org/3"

def get_tmdb_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    key = api_key or getattr(config, "TMDB_API_KEY", "")
    if key.startswith("eyJ"): # v4 Read Access Token (Bearer)
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    return {}

def search_movie(query: str, year: Optional[int] = None, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Search movie by title and return the best match metadata."""
    key = api_key or getattr(config, "TMDB_API_KEY", "")
    headers = get_tmdb_headers(key)
    params = {"query": query}
    if not key.startswith("eyJ"):
        params["api_key"] = key
    if year:
        params["year"] = year

    resp = requests.get(f"{TMDB_BASE_URL}/search/movie", headers=headers, params=params, timeout=10)
    if resp.status_code == 200:
        results = resp.json().get("results", [])
        if results:
            return results[0]
    return None

def get_movie_videos(movie_id: int, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch all official trailers, teasers, clips, and featurettes for a movie."""
    key = api_key or getattr(config, "TMDB_API_KEY", "")
    headers = get_tmdb_headers(key)
    params = {}
    if not key.startswith("eyJ"):
        params["api_key"] = key

    resp = requests.get(f"{TMDB_BASE_URL}/movie/{movie_id}/videos", headers=headers, params=params, timeout=10)
    if resp.status_code == 200:
        return resp.json().get("results", [])
    return []

def get_movie_details(movie_id: int, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch full movie details including plot, tagline, runtime, genres."""
    key = api_key or getattr(config, "TMDB_API_KEY", "")
    headers = get_tmdb_headers(key)
    params = {}
    if not key.startswith("eyJ"):
        params["api_key"] = key

    resp = requests.get(f"{TMDB_BASE_URL}/movie/{movie_id}", headers=headers, params=params, timeout=10)
    if resp.status_code == 200:
        return resp.json()
    return None
