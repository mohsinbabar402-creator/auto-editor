import requests, json
import config

url = 'https://api.elevenlabs.io/v1/voices'
headers = {'xi-api-key': config.ELEVENLABS_API_KEY}
r = requests.get(url, headers=headers)

if r.status_code == 200:
    voices = r.json().get('voices', [])
    print(f"Total ElevenLabs Voices: {len(voices)}")
    for v in voices[:20]:
        labels = v.get('labels', {})
        print(f"   [{v['voice_id']}] {v['name']} - {labels.get('accent','')} {labels.get('descriptive','')}")
else:
    print(f"Error {r.status_code}: {r.text}")
