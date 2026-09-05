"""
Generate Scene 6 video using Gemini API (Veo/Imagen Video) directly.
No browser needed.
"""
import sys, os, json, time, requests, subprocess
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

clips_dir = config.PROJECTS_DIR / "earth_stops_rotating" / "clips"
proj_dir = config.PROJECTS_DIR / "earth_stops_rotating"
scene6_path = clips_dir / "scene_06.mp4"

API_KEY = config.GOOGLE_API_KEY
BASE = "https://generativelanguage.googleapis.com/v1beta"

prompt = (
    "A lone human silhouette stands on a rocky cliff edge at golden hour. "
    "Behind them, the left half of the sky is deep frozen blue with stars, "
    "while the right half is blazing orange with heat waves. "
    "A narrow golden twilight strip divides the two halves. "
    "National Geographic cinematic documentary, photorealistic, vertical 9:16."
)

print("1. Requesting video generation from Gemini API (Veo)...", flush=True)

# Try Veo video generation endpoint
resp = requests.post(
    f"{BASE}/models/veo-2.0-generate-001:predictVideo",
    params={"key": API_KEY},
    json={
        "instances": [{"prompt": prompt}],
        "parameters": {
            "aspectRatio": "9:16",
            "duration": "8s",
            "personGeneration": "allow_all",
        },
    },
    timeout=30,
)

print(f"   Status: {resp.status_code}", flush=True)
if resp.status_code == 200:
    data = resp.json()
    print(f"   Response keys: {list(data.keys())}", flush=True)
    # Check if it's a long-running operation
    op_name = data.get("name", "")
    if op_name:
        print(f"   Operation: {op_name}", flush=True)
        # Poll for completion
        for i in range(30):
            time.sleep(10)
            poll = requests.get(
                f"{BASE}/operations/{op_name}",
                params={"key": API_KEY},
                timeout=30,
            )
            if poll.status_code == 200:
                pdata = poll.json()
                done = pdata.get("done", False)
                print(f"   Poll {i+1}: done={done}", flush=True)
                if done:
                    result = pdata.get("response", {})
                    videos = result.get("generatedSamples", [])
                    if videos:
                        video_data = videos[0].get("video", {})
                        video_uri = video_data.get("uri", "")
                        if video_uri:
                            print(f"   Downloading from: {video_uri[:80]}...", flush=True)
                            dl = requests.get(video_uri, stream=True, timeout=60)
                            with open(scene6_path, "wb") as f:
                                for chunk in dl.iter_content(chunk_size=8192):
                                    f.write(chunk)
                            print(f"   Saved scene_06.mp4: {scene6_path.stat().st_size // 1024} KB", flush=True)
                    break
            else:
                print(f"   Poll error: {poll.status_code}", flush=True)
else:
    print(f"   Response: {resp.text[:500]}", flush=True)
    
    # Try alternate endpoint
    print("\n   Trying generateVideos endpoint...", flush=True)
    resp2 = requests.post(
        f"{BASE}/models/veo-2.0-generate-001:generateVideos",
        params={"key": API_KEY},
        json={
            "prompt": {"text": prompt},
            "videoConfig": {
                "aspectRatio": "9:16",
                "durationSeconds": 8,
            },
        },
        timeout=30,
    )
    print(f"   Status: {resp2.status_code}", flush=True)
    print(f"   Response: {resp2.text[:500]}", flush=True)

    if resp2.status_code == 200:
        data2 = resp2.json()
        op_name = data2.get("name", "")
        if op_name:
            print(f"   Operation: {op_name}", flush=True)
            for i in range(30):
                time.sleep(10)
                poll = requests.get(
                    f"{BASE}/operations/{op_name}",
                    params={"key": API_KEY},
                    timeout=30,
                )
                if poll.status_code == 200:
                    pdata = poll.json()
                    done = pdata.get("done", False)
                    print(f"   Poll {i+1}: done={done}", flush=True)
                    if done:
                        result = pdata.get("response", {})
                        videos = result.get("generatedSamples", result.get("videos", []))
                        if videos:
                            import base64
                            vid = videos[0]
                            if "video" in vid and "uri" in vid["video"]:
                                dl = requests.get(vid["video"]["uri"], stream=True, timeout=60)
                                with open(scene6_path, "wb") as f:
                                    for chunk in dl.iter_content(chunk_size=8192):
                                        f.write(chunk)
                            elif "videoBytes" in vid:
                                with open(scene6_path, "wb") as f:
                                    f.write(base64.b64decode(vid["videoBytes"]))
                            print(f"   Saved scene_06.mp4: {scene6_path.stat().st_size // 1024} KB", flush=True)
                        break

# Verify we got something useful
if scene6_path.exists() and scene6_path.stat().st_size > 100000:
    # Run audit
    print("\n2. Running Gemini audit...", flush=True)
    from pipeline.gemini_video_reviewer import gemini_full_video_review
    audit = gemini_full_video_review(proj_dir)
    print(f"   Passed: {audit['passed']}", flush=True)
else:
    print("\nScene 6 not generated successfully.", flush=True)
