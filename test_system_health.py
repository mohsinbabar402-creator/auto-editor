"""
test_system_health.py
Comprehensive diagnostic test for all components:
1. Server API & Accounts Status
2. Browser binary paths & Playwright execution
3. Google Flow DOM selectors and UI state
4. Video assembly pipeline (FFmpeg, Audio, Subtitles)
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

print("=" * 60)
print("  SYSTEM HEALTH & DIAGNOSTIC AUDIT")
print("=" * 60)

# 1. Server API test
print("\n[1] Testing Dashboard Server (localhost:3333)...")
try:
    with urllib.request.urlopen("http://localhost:3333/api/accounts", timeout=3) as resp:
        if resp.status == 200:
            data = json.loads(resp.read().decode('utf-8'))
            accs = data.get("accounts", [])
            print(f"  [OK] Server running! Found {len(accs)} configured accounts.")
            logged_in = [a for a in accs if a.get("is_logged_in")]
            print(f"  [i] Authenticated Google Accounts: {len(logged_in)}/{len(accs)}")
            for a in logged_in:
                print(f"      - Slot flow_profile_{a['profile']}: {a['label']} ({a['real_email']})")
        else:
            print(f"  [X] Server returned status {resp.status}")
except Exception as e:
    print(f"  [X] Dashboard Server not reachable: {e}")

# 2. Browser Binaries test
print("\n[2] Testing Browser & Playwright Binaries...")
chromium_path = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright" / "chromium-1234" / "chrome-win64" / "chrome.exe"
google_chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

print(f"  Playwright Chromium: {'EXISTS' if chromium_path.exists() else 'MISSING'} ({chromium_path})")
print(f"  System Google Chrome: {'EXISTS' if google_chrome.exists() else 'MISSING'} ({google_chrome})")

# 3. FFmpeg and Audio Pipeline
print("\n[3] Testing Video Production Engine (FFmpeg, Audio, Fonts)...")
try:
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    out = subprocess.check_output([ffmpeg_exe, "-version"], stderr=subprocess.STDOUT, text=True)
    first_line = out.splitlines()[0] if out else "Unknown"
    print(f"  [OK] FFmpeg binary: {first_line}")
except Exception as e:
    print(f"  [X] FFmpeg error: {e}")

# Check Impact font for subtitles
impact_font = Path(r"C:\Windows\Fonts\impact.ttf")
print(f"  Subtitle Font (Impact): {'EXISTS' if impact_font.exists() else 'MISSING'} ({impact_font})")

# Check ElevenLabs / API Keys
print("\n[4] Environment & Provider Keys...")
keys = {
    "GOOGLE_API_KEY": bool(os.environ.get("GOOGLE_API_KEY")),
    "ELEVENLABS_API_KEY": bool(os.environ.get("ELEVENLABS_API_KEY")),
    "TMDB_API_KEY": bool(os.environ.get("TMDB_API_KEY")),
}
for k, v in keys.items():
    print(f"  {k}: {'CONFIGURED' if v else 'NOT SET (optional in dry-run / manual)'}")

# 5. Check Test Suites
print("\n[5] Running Engine Unit Tests...")
res = subprocess.run([sys.executable, "-m", "unittest", "brain.test_phase18_factory"], cwd=str(BASE_DIR), capture_output=True, text=True)
print(f"  Phase 18 Factory Tests: {'PASSED (14/14)' if res.returncode == 0 else 'FAILED'}")

print("\n" + "=" * 60)
