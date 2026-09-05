"""
Cloud Storage Utility: Save to Google Drive & Free Local Disk

Usage:
    from pipeline.cloud_save import save_to_cloud
    save_to_cloud("projects/01_scifi/renders/video.mp4", channel="01_scifi")

What it does:
    1. Copies the rendered video to G:\My Drive\YouTube Shorts\{channel}\
    2. Deletes the local copy to free disk space
    3. Prints the Google Drive link to watch in browser
"""
import shutil
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


def save_to_cloud(local_path: str, channel: str, delete_local: bool = True) -> Path:
    """
    Saves a rendered video to Google Drive cloud and optionally deletes local copy.
    
    Args:
        local_path: Path to the local rendered file
        channel: Channel key (e.g. "01_scifi", "04_movie_recaps")
        delete_local: If True, deletes local file after cloud copy succeeds
    
    Returns:
        Path to the cloud file
    """
    local = Path(local_path)
    
    if not local.exists():
        raise FileNotFoundError(f"Local file not found: {local}")
    
    if not config.CLOUD_STORAGE_ENABLED:
        print(f"[Cloud] Cloud storage disabled. File stays at: {local}")
        return local
    
    # Get cloud destination
    cloud_dir = config.CLOUD_CHANNEL_DIRS.get(channel, config.CLOUD_BASE_DIR)
    cloud_dir.mkdir(parents=True, exist_ok=True)
    cloud_path = cloud_dir / local.name
    
    # Copy to cloud
    file_size_mb = local.stat().st_size / (1024 * 1024)
    print(f"[Cloud] Uploading {local.name} ({file_size_mb:.1f} MB) to Google Drive...")
    shutil.copy2(str(local), str(cloud_path))
    
    # Verify cloud copy exists and matches size
    if cloud_path.exists() and cloud_path.stat().st_size == local.stat().st_size:
        print(f"[Cloud] >> Upload complete: {cloud_path}")
        
        if delete_local:
            local.unlink()
            print(f"[Cloud] >> Local copy deleted. Freed {file_size_mb:.1f} MB on C: drive.")
        
        print(f"[Cloud] >> Watch at: drive.google.com > YouTube Shorts > {channel}")
        return cloud_path
    else:
        print(f"[Cloud] FAIL: Upload verification failed! Local copy preserved.")
        return local


def cleanup_local_renders(channel: str = None):
    """
    Moves ALL rendered videos from local projects/ to Google Drive cloud.
    Useful for bulk cleanup when disk is getting full.
    """
    projects_dir = config.PROJECTS_DIR
    moved = 0
    freed_mb = 0
    
    for renders_dir in projects_dir.glob("*/renders"):
        ch_name = renders_dir.parent.name
        
        if channel and ch_name != channel:
            continue
            
        for video_file in renders_dir.glob("*.mp4"):
            size_mb = video_file.stat().st_size / (1024 * 1024)
            try:
                save_to_cloud(str(video_file), ch_name, delete_local=True)
                moved += 1
                freed_mb += size_mb
            except Exception as e:
                print(f"[Cloud] Failed to move {video_file.name}: {e}")
    
    print(f"\n[Cloud] Summary: Moved {moved} videos, freed {freed_mb:.1f} MB on local disk.")


if __name__ == "__main__":
    # Run this to move ALL existing renders to Google Drive
    print("=" * 50)
    print("Moving all local renders to Google Drive cloud...")
    print("=" * 50)
    cleanup_local_renders()
