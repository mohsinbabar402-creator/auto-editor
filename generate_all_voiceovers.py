import os, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
from pipeline.stage3_voiceover import build_full_script, generate_voiceover_elevenlabs

series = [
    {
        "id": "part1_the_first_second",
        "title": "Part 1: The First Second (The Cataclysm)",
        "scenes": [
            {
                "scene_number": 1,
                "name": "The Instant Freeze",
                "narration": "If Earth stopped spinning right now, you wouldn't just fall over. You would be launched east at a thousand miles per hour.",
                "visual_prompt": "Cinematic vertical 9:16 video of planet Earth spinning gracefully in dark space, sudden dramatic halt with atmospheric shockwaves, photorealistic 8k National Geographic."
            },
            {
                "scene_number": 2,
                "name": "Supersonic City Destruction",
                "narration": "Because the atmosphere keeps moving at rotational speed, supersonic winds over 1,000 miles an hour would instantly wipe entire cities off the map.",
                "visual_prompt": "Cinematic vertical 9:16 video of modern glass skyscrapers being shredded by supersonic wind streaks and shockwaves, steel bridges fracturing, hyper-realistic."
            },
            {
                "scene_number": 3,
                "name": "Supersonic Shockwave Horizon",
                "narration": "Cars, buildings, and trillions of tons of soil would turn into supersonic shrapnel, scouring the continent down to bedrock.",
                "visual_prompt": "Cinematic vertical 9:16 high-altitude view of a massive circular atmospheric shockwave tearing across land and forests, cloud rings expanding."
            },
            {
                "scene_number": 4,
                "name": "Orbital Blackout",
                "narration": "Thousands of satellites in orbit would record global communications going dark in less than thirty seconds.",
                "visual_prompt": "Cinematic vertical 9:16 view from orbit showing cities blacking out simultaneously across the dark side of Earth, dramatic."
            },
            {
                "scene_number": 5,
                "name": "Daylight Turned to Ash",
                "narration": "Massive plumes of pulverized dust and debris would instantly blot out the sun, turning daylight into midnight.",
                "visual_prompt": "Cinematic vertical 9:16 ground-level view of a pitch-black wall of dust and smoke rolling over the horizon, blocking the blazing sun."
            },
            {
                "scene_number": 6,
                "name": "The Ocean Warning (Cliffhanger)",
                "narration": "The initial blast destroyed civilization in seconds, but the real nightmare is just waking up in the oceans. Check Part 2 right now.",
                "visual_prompt": "Cinematic vertical 9:16 dramatic coastal view showing the ocean violently retreating miles into the distance, exposing dark seabed under ominous skies."
            }
        ]
    },
    {
        "id": "part2_the_great_ocean_surge",
        "title": "Part 2: The Great Ocean Surge",
        "scenes": [
            {
                "scene_number": 1,
                "name": "The Ocean Migration (Hook)",
                "narration": "If you survived the initial blast, you have exactly twelve minutes before a five-mile-high wall of water reaches you.",
                "visual_prompt": "Cinematic vertical 9:16 planetary orbital view showing Earth's oceans violently sloshing away from the equator towards both poles, massive water displacement."
            },
            {
                "scene_number": 2,
                "name": "The Towering Mega-Tsunami",
                "narration": "Without centrifugal force holding water at the equator, gravity pulls trillions of gallons of water toward the poles in colossal mega-tsunamis.",
                "visual_prompt": "Cinematic vertical 9:16 low-angle view of a monstrous 3-mile-high pitch-black ocean wave towering above clouds, cresting with violent spray."
            },
            {
                "scene_number": 3,
                "name": "Continents Submerged",
                "narration": "Entire coastlines and low-lying countries disappear beneath turbulent black water in less than an hour.",
                "visual_prompt": "Cinematic vertical 9:16 drone shot of ocean waves violently crashing into coastal mountain ridges, water churning and swallowing entire valleys."
            },
            {
                "scene_number": 4,
                "name": "Underwater Megacities",
                "narration": "Iconic cities like London, New York, and Tokyo are permanently submerged under miles of freezing ocean.",
                "visual_prompt": "Cinematic vertical 9:16 eerie underwater view of submerged modern skyscraper canyons, sunlight filtering through murky deep water with floating debris."
            },
            {
                "scene_number": 5,
                "name": "The Two Polar Oceans",
                "narration": "Earth's geography is completely redrawn into two massive polar oceans separated by a giant dry equatorial continent.",
                "visual_prompt": "Cinematic vertical 9:16 globe map in space showing two blue polar oceans at the north and south, with a massive dry brown supercontinent across the middle."
            },
            {
                "scene_number": 6,
                "name": "The Atmospheric Threat (Cliffhanger)",
                "narration": "The flood drowned half the world, but the atmosphere is about to cook whatever is left. Go to Part 3 to see the Mach-1 firestorms.",
                "visual_prompt": "Cinematic vertical 9:16 sky view showing boiling turbulent storm clouds igniting with red electrical sparks as extreme atmospheric friction begins."
            }
        ]
    },
    {
        "id": "part3_atmospheric_superstorms",
        "title": "Part 3: Atmospheric Superstorms",
        "scenes": [
            {
                "scene_number": 1,
                "name": "Mach-1 Firewinds (Hook)",
                "narration": "Think hiding underground will save you? The air above you is moving at Mach 1 and burning at eight hundred degrees.",
                "visual_prompt": "Cinematic vertical 9:16 high-altitude view of supersonic hurricane cloud bands wrapping tightly around the globe, red friction glows."
            },
            {
                "scene_number": 2,
                "name": "Mountain Friction Storms",
                "narration": "Extreme friction between the stationary ground and racing atmosphere ignites global firestorms that incinerate whole continents.",
                "visual_prompt": "Cinematic vertical 9:16 dramatic landscape view of mountain peaks glowing red from supersonic friction, firestorms raging through dry canyons."
            },
            {
                "scene_number": 3,
                "name": "Continental Lightning Bolts",
                "narration": "Massive static friction creates non-stop lightning storms spanning thousands of miles with violent violet electrical discharge.",
                "visual_prompt": "Cinematic vertical 9:16 view of continuous massive violet lightning web branching across dark storm clouds from horizon to horizon."
            },
            {
                "scene_number": 4,
                "name": "The Red Iron Dust Sky",
                "narration": "Atmospheric pressure crushes surface structures while red iron dust envelopes the planet in eternal haze.",
                "visual_prompt": "Cinematic vertical 9:16 view of an eerie orange-red sky with heavy atmospheric pressure layers pressing down on desolate barren ground."
            },
            {
                "scene_number": 5,
                "name": "The Scoured Wasteland",
                "narration": "When the supersonic winds finally slow down, Earth's lush surface is stripped down to polished, lifeless bedrock.",
                "visual_prompt": "Cinematic vertical 9:16 ground view of smooth, mirror-polished bedrock canyon stretching infinitely under smoky skies, zero vegetation."
            },
            {
                "scene_number": 6,
                "name": "Core Failure Warning (Cliffhanger)",
                "narration": "The winds finally settled, but inside the planet, Earth's engine just died. Tap Part 4 to see our magnetic shield collapse.",
                "visual_prompt": "Cinematic vertical 9:16 deep cross-section cutaway illustration of Earth showing the glowing liquid iron outer core slowing and fading to dark crimson."
            }
        ]
    },
    {
        "id": "part4_the_vanishing_shield",
        "title": "Part 4: The Vanishing Shield",
        "scenes": [
            {
                "scene_number": 1,
                "name": "Invisible Cosmic Death (Hook)",
                "narration": "The wind finally stopped, but invisible death just pierced straight through the sky.",
                "visual_prompt": "Cinematic vertical 9:16 space view of Earth with glowing blue magnetic field lines breaking, snapping, and fading away into darkness."
            },
            {
                "scene_number": 2,
                "name": "Deadly Low-Altitude Auroras",
                "narration": "Without planetary rotation, the core stops generating our magnetic shield, dropping deadly glowing auroras right onto the surface.",
                "visual_prompt": "Cinematic vertical 9:16 ground view of vibrant green and violet aurora curtains touching the ground in abandoned ruins, eerie glowing atmosphere."
            },
            {
                "scene_number": 3,
                "name": "Solar Radiation Bombardment",
                "narration": "Solar flares and intense cosmic rays bombard the atmosphere, destroying genetic material in every living cell.",
                "visual_prompt": "Cinematic vertical 9:16 shot from space of a massive blinding golden solar flare slamming into Earth's unprotected upper atmosphere."
            },
            {
                "scene_number": 4,
                "name": "Ozone Layer Stripped",
                "narration": "The ozone layer is completely stripped away, allowing raw ultraviolet radiation to sterilize the Earth's surface.",
                "visual_prompt": "Cinematic vertical 9:16 high stratosphere view of shimmering ozone gas evaporating away into the vacuum of space, harsh white sunlight piercing."
            },
            {
                "scene_number": 5,
                "name": "Boiling Inland Seas",
                "narration": "Direct cosmic heating and reduced atmospheric pressure cause surface lakes and rivers to rapidly boil away.",
                "visual_prompt": "Cinematic vertical 9:16 shot of a shallow lake bubbling and boiling vigorously, thick steam rising into a hazy ultraviolet sky."
            },
            {
                "scene_number": 6,
                "name": "The Six-Month Day (Cliffhanger)",
                "narration": "The shield is gone, but the next six months will divide the planet into two extreme hells. Watch Part 5 to see Fire and Ice.",
                "visual_prompt": "Cinematic vertical 9:16 space view of the sun locked directly over one hemisphere of Earth, casting an intense permanent beam of light."
            }
        ]
    },
    {
        "id": "part5_fire_and_ice",
        "title": "Part 5: Fire & Ice (The Divided Worlds)",
        "scenes": [
            {
                "scene_number": 1,
                "name": "The Two Hells (Hook)",
                "narration": "Welcome to the new Earth: six months of 250-degree scorching sun, or six months of minus 150-degree absolute frost. Which one do you choose?",
                "visual_prompt": "Cinematic vertical 9:16 orbital split view of Earth: left half blazing orange scorched desert, right half deep frozen blue ice and glaciers."
            },
            {
                "scene_number": 2,
                "name": "The Scorched Sun Hemisphere",
                "narration": "On the sun-facing side, relentless daylight heats the ground to over two hundred degrees, turning former farmland into cracked glass deserts.",
                "visual_prompt": "Cinematic vertical 9:16 ground view of cracked red desert baking under a massive glaring white sun, heat distortion waves rippling."
            },
            {
                "scene_number": 3,
                "name": "The Frozen Night Hemisphere",
                "narration": "On the dark side, temperatures plummet to minus one hundred and fifty degrees, encasing skyscrapers in fifty-foot glaciers.",
                "visual_prompt": "Cinematic vertical 9:16 night view of massive frozen skyscraper peaks buried in deep blue glacial ice under brilliant starry cosmos."
            },
            {
                "scene_number": 4,
                "name": "Underground Thermal Bunkers",
                "narration": "Surface survival is impossible. The remaining survivors are forced into deep geothermal bunkers beneath the crust.",
                "visual_prompt": "Cinematic vertical 9:16 interior view of high-tech subterranean bunker hallway, amber emergency lighting, humans in thermal environmental suits."
            },
            {
                "scene_number": 5,
                "name": "Extreme Border Super-Convection",
                "narration": "Between the boiling heat and freezing cold, violent thermal currents collide into permanent boundary blizzards.",
                "visual_prompt": "Cinematic vertical 9:16 aerial shot of massive wall of clouds where scorching hot air crashes into freezing blizzard fronts, swirling violently."
            },
            {
                "scene_number": 6,
                "name": "The Golden Strip (Cliffhanger)",
                "narration": "Living on either side is certain death, except for one razor-thin line of salvation. Watch Part 6 to see the Twilight Zone.",
                "visual_prompt": "Cinematic vertical 9:16 wide view of a narrow glowing golden horizon line dividing the blazing day from the icy dark night."
            }
        ]
    },
    {
        "id": "part6_the_twilight_zone",
        "title": "Part 6: The Twilight Zone (Humanity's Final Stand)",
        "scenes": [
            {
                "scene_number": 1,
                "name": "The 20-Mile Strip (Hook)",
                "narration": "There is only a twenty-mile-wide strip where human beings could survive on Earth. Welcome to the Twilight Zone.",
                "visual_prompt": "Cinematic vertical 9:16 scenic vista of a lush green temperate valley basking in eternal golden-hour twilight between ice mountains and red desert."
            },
            {
                "scene_number": 2,
                "name": "Mobile Nomadic Cities",
                "narration": "Because Earth still orbits the sun once a year, this habitable twilight band moves slowly across the planet, forcing humanity into gigantic mobile cities.",
                "visual_prompt": "Cinematic vertical 9:16 view of colossal tracked nomadic crawler cities slowly moving across terrain at sunset, industrial lights glowing."
            },
            {
                "scene_number": 3,
                "name": "Geothermal Energy Harvesters",
                "narration": "Tapping into volcanic heat along the moving boundary provides endless clean power to sustain the final human colonies.",
                "visual_prompt": "Cinematic vertical 9:16 futuristic geothermal energy harvesting towers venting white steam into a twilight sky, high-tech glowing pipes."
            },
            {
                "scene_number": 4,
                "name": "The Eternal Sunset Sky",
                "narration": "Generations will grow up under a sky that never turns to night and never turns to day, frozen in permanent twilight.",
                "visual_prompt": "Cinematic vertical 9:16 sky view where golden orange sunset clouds seamlessly transition into dark velvet sky filled with brilliant stars."
            },
            {
                "scene_number": 5,
                "name": "The Lone Survivor on the Cliff",
                "narration": "A lone observer looks across the boundary between fire and ice, witnessing a transformed world reborn in silence.",
                "visual_prompt": "Cinematic vertical 9:16 a lone human silhouette standing on a high rocky cliff looking at the golden horizon divide, National Geographic 8k."
            },
            {
                "scene_number": 6,
                "name": "The Final Verdict (Series Finale)",
                "narration": "If humanity adapts to the moving border, we survive. If we stop, we freeze or burn. Would you make the journey? Comment your thoughts below.",
                "visual_prompt": "Cinematic vertical 9:16 slow cinematic pull-back from Earth into deep space, revealing the dual-toned world orbiting the glowing sun, 8k masterpiece."
            }
        ]
    }
]

for s in series:
    p_id = s["id"]
    p_dir = config.PROJECTS_DIR / p_id
    p_dir.mkdir(parents=True, exist_ok=True)
    
    # Save storyboard.json
    sb = {
        "title": s["title"],
        "target_duration_sec": 50,
        "scenes": s["scenes"]
    }
    with open(p_dir / "storyboard.json", "w", encoding="utf-8") as f:
        json.dump(sb, f, indent=2)
    print(f"Saved storyboard: {p_id}")

    # Generate Voiceover with ElevenLabs
    audio_path = p_dir / "narration.mp3"
    words_path = p_dir / "words.json"
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        print(f"Generating ElevenLabs Voiceover for {p_id}...")
        script = build_full_script(sb)
        generate_voiceover_elevenlabs(script, audio_path, words_path)
        print(f"   Voiceover saved: {audio_path.stat().st_size} bytes")
    else:
        print(f"   Voiceover already exists for {p_id}")

print("\nALL 6 STORYBOARDS & VOICEOVERS COMPLETED SUCCESSFULLY!")
