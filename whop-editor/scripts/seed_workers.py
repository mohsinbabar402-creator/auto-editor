import sys
from pathlib import Path

# Add whop-editor to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.repository import DatabaseRepository

repo = DatabaseRepository()

workers_spec = [
    ("worker_antigravity_01", "antigravity", ["EDITING", "RENDERING", "AUDIO_EXTRACTION"], {"email": "mohsinoctal777@gmail.com", "profile": 1, "priority": 1}),
    ("worker_antigravity_02", "antigravity", ["EDITING", "RENDERING", "AUDIO_EXTRACTION"], {"email": "aoctal522@gmail.com", "profile": 2, "priority": 1}),
    ("worker_antigravity_03", "antigravity", ["EDITING", "RENDERING", "AUDIO_EXTRACTION"], {"email": "mohsinmughal1771@gmail.com", "profile": 3, "priority": 1}),
    ("worker_antigravity_04", "antigravity", ["EDITING", "RENDERING", "AUDIO_EXTRACTION"], {"email": "blazingsoul451@gmail.com", "profile": 4, "priority": 1}),
    ("worker_antigravity_05", "antigravity", ["EDITING", "RENDERING", "AUDIO_EXTRACTION"], {"email": "zestify1771@gmail.com", "profile": 7, "priority": 1}),
]

for wid, prov, caps, meta in workers_spec:
    reg = repo.register_worker(wid, prov, caps, status="available", metadata=meta)
    print(f"Registered: {reg['id']} ({reg['provider']}) - {meta['email']}")

print(f"Total workers registered in PostgreSQL: {len(repo.list_workers())}")
