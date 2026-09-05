import os
import sys
from pathlib import Path
import imageio_ffmpeg

# Base Project Directories
BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
MUSIC_DIR = ASSETS_DIR / "audio" / "music"
SFX_DIR = ASSETS_DIR / "audio" / "sfx"
FONTS_DIR = ASSETS_DIR / "fonts"

# Default Projects Directory
PROJECTS_DIR = BASE_DIR / "projects"

# Dedicated Browser Profile Directory for Google Flow automation
BROWSER_PROFILE_DIR = BASE_DIR / "browser" / "google_flow_profile"

# FFmpeg Executable Discovery
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

# Video Specifications for 9:16 Vertical Video
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30
VIDEO_BITRATE = "8M"
AUDIO_BITRATE = "192k"

# Audio Mixing Settings
VOICE_VOLUME_DB = 0.0          # Master speech normalized
MUSIC_VOLUME_DB = -18.0        # Background music during speech
MUSIC_DUCKING_ATTENUATION = -8.0 # Additional attenuation when voice is talking
SFX_VOLUME_DB = -6.0           # SFX level

# Google AI Studio / Gemini API Key (loaded from environment)
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

# ElevenLabs Settings (loaded from environment)
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
# Default high-quality narrative voice (Adam - deep cinematic documentary tone)
DEFAULT_VOICE_ID = "pNInz6obpgDQGcFmaJgB" # Adam
DEFAULT_MODEL_ID = "eleven_turbo_v2_5"

# The Movie Database (TMDb) API Key
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")

# Caption Styling
CAPTION_FONT_PATH = r"C:\Windows\Fonts\impact.ttf"
CAPTION_FONT_SIZE = 72
CAPTION_TEXT_COLOR = "&H00FFFFFF"     # White in ASS format (BBGGRR)
CAPTION_HIGHLIGHT_COLOR = "&H0000FFFF"# Vivid Yellow in ASS format (&HAABBGGRR)
CAPTION_OUTLINE_COLOR = "&H00000000"  # Black outline
CAPTION_OUTLINE_WIDTH = 5
CAPTION_MARGIN_V = 450                # Vertical offset from bottom (safe zone)

# STRICT PRODUCTION & CREDIT RULES (Zero-Waste Policy)
# 1. Exactly 1 generation batch per video. Never re-roll or generate extra clips.
# 2. Max scenes per video is strictly capped.
# 3. If a clip is rendered, download it. Never generate another prompt.
STRICT_SINGLE_PASS = True
DEFAULT_NUM_SCENES = 5
MAX_GENERATION_ATTEMPTS = 1

# Google Drive Cloud Storage (All renders save to cloud, local copies auto-deleted)
CLOUD_STORAGE_ENABLED = True
CLOUD_BASE_DIR = Path("G:/My Drive/YouTube Shorts")
CLOUD_CHANNEL_DIRS = {
    "01_scifi": CLOUD_BASE_DIR / "01_scifi",
    "02_viral_memes": CLOUD_BASE_DIR / "02_viral_memes",
    "03_kids_stories": CLOUD_BASE_DIR / "03_kids_stories",
    "04_movie_recaps": CLOUD_BASE_DIR / "04_movie_recaps",
    "05_vyro_campaigns": CLOUD_BASE_DIR / "05_vyro_campaigns",
    "06_ai_influencer": CLOUD_BASE_DIR / "06_ai_influencer",
    "07_viral_podcasts": CLOUD_BASE_DIR / "07_viral_podcasts",
}


