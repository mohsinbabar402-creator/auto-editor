import sys, os, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from generate_perfect_flow_videos import setup_and_generate_part

print("Creating fresh Part 6 project in Google Flow...")
setup_and_generate_part("part6_the_twilight_zone")
