import sys, time
from generate_perfect_flow_videos import setup_and_generate_part

parts = [
    "part3_atmospheric_superstorms",
    "part4_the_vanishing_shield",
    "part5_fire_and_ice",
    "part6_the_twilight_zone"
]

for p in parts:
    print(f"\n==========================================")
    print(f"RUNNING VEO GENERATION FOR: {p}")
    print(f"==========================================")
    try:
        setup_and_generate_part(p)
    except Exception as e:
        print(f"Error on {p}: {e}")
    time.sleep(4)

print("\nALL REMAINING PARTS GENERATED VIA VEO IN GOOGLE FLOW!")
