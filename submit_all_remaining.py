import sys, time
from submit_part_to_flow import submit_part_to_flow

remaining_parts = [
    "part3_atmospheric_superstorms",
    "part4_the_vanishing_shield",
    "part5_fire_and_ice",
    "part6_the_twilight_zone"
]

for p in remaining_parts:
    print(f"\n>>> SUBMITTING {p} TO GOOGLE FLOW <<<")
    try:
        submit_part_to_flow(p)
        print(f">>> {p} QUEUED SUCCESSFULLY! <<<")
    except Exception as e:
        print(f">>> ERROR SUBMITTING {p}: {e} <<<")
    time.sleep(5)

print("\nALL REMAINING PARTS (3, 4, 5, 6) SUBMITTED TO GOOGLE FLOW!")
