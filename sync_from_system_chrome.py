import json
from pathlib import Path

local_state_path = Path(r"C:\Users\ice\AppData\Local\Google\Chrome\User Data\Local State")
mc_path = Path(r"c:\Users\ice\Desktop\youtube shorts project\mission_control.json")

with open(local_state_path, "r", encoding="utf-8") as f:
    d = json.load(f)

cache = d.get("profile", {}).get("info_cache", {})

with open(mc_path, "r", encoding="utf-8") as f:
    mc = json.load(f)

power_emails = {
    "mohsinoctal777@gmail.com": 1050,
    "aoctal522@gmail.com": 1050,
    "mohsinmughal1771@gmail.com": 1050,
    "blazingsoul451@gmail.com": 1050,
    "zestify1771@gmail.com": 1050
}

flow = mc.setdefault("google_flow_accounts", {})
flow["power_accounts"] = []
flow["daily_accounts"] = []

seen_emails = set()
slot_num = 1

for folder, info in sorted(cache.items()):
    email = info.get("user_name", "").strip()
    name = info.get("name", folder).strip()
    if not email or "@" not in email or email in seen_emails:
        continue
    seen_emails.add(email)

    is_power = email in power_emails
    entry = {
        "priority": 1 if is_power else 2,
        "profile": slot_num,
        "chrome_directory": folder,
        "label": name,
        "email": email,
        "tier": "pro" if is_power else "free",
        "status": "ready"
    }
    if is_power:
        entry["credits"] = power_emails[email]
        flow["power_accounts"].append(entry)
    else:
        entry["credits_daily"] = 50
        flow["daily_accounts"].append(entry)
    slot_num += 1

flow["total_banked_credits"] = sum(a.get("credits", 0) for a in flow["power_accounts"])
flow["total_daily_credits"] = sum(a.get("credits_daily", 50) for a in flow["daily_accounts"])

with open(mc_path, "w", encoding="utf-8") as f:
    json.dump(mc, f, indent=2)

print("SUCCESS: mission_control.json fully synced from Chrome database!")
print(f"Power accounts ({len(flow['power_accounts'])}):")
for a in flow["power_accounts"]:
    print(f"  Slot {a['profile']}: {a['email']} (Chrome folder: {a['chrome_directory']})")

print(f"Daily accounts ({len(flow['daily_accounts'])}):")
for a in flow["daily_accounts"]:
    print(f"  Slot {a['profile']}: {a['email']} (Chrome folder: {a['chrome_directory']})")
