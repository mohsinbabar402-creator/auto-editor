import json
from pathlib import Path

local_state_path = Path(r"C:\Users\ice\AppData\Local\Google\Chrome\User Data\Local State")

if not local_state_path.exists():
    print("Local State not found!")
    exit(1)

with open(local_state_path, "r", encoding="utf-8") as f:
    d = json.load(f)

cache = d.get("profile", {}).get("info_cache", {})
print(f"Total profiles found in master Chrome database: {len(cache)}\n")

mapped = []
for folder, info in sorted(cache.items()):
    email = info.get("user_name")
    name = info.get("name")
    if email and "@" in email:
        mapped.append({
            "folder": folder,
            "email": email,
            "name": name
        })

print("=" * 65)
print(f"{'#':<3} | {'Chrome Folder':<15} | {'Google Email':<32} | {'Profile Name'}")
print("=" * 65)
for i, item in enumerate(mapped, 1):
    print(f"{i:<3} | {item['folder']:<15} | {item['email']:<32} | {item['name']}")
print("=" * 65)
