# 🧠 PROJECT BRAIN & PRODUCTION RULES (LOCKED & ENFORCED)

This document serves as the permanent memory and quality contract for all YouTube Shorts and Movie Recap video production in this workspace. Every future script, pipeline, and render MUST strictly comply with these rules.

---

## 🛑 1. THE "SHOW WHAT YOU SAY" LAW (100% Literal Semantic Matching)
* **Zero Mismatched Footage:** The visual on screen MUST literally depict the exact sentence or concept being narrated at that exact second.
  * Example (*The Platform*):
    * *"Level 1 gets a feast"* $\rightarrow$ MUST show pristine, sparkling luxury gourmet food with whole roasts and wine glasses.
    * *"Level 2 eats scraps"* $\rightarrow$ MUST show inmates reaching into a mostly-full food table.
    * *"By Level 50, only bones remain"* $\rightarrow$ MUST show a ravaged, decimated table with empty plates and chewed bones.
    * *"Tied down with heavy ropes"* $\rightarrow$ MUST show the character tied down to the bed.
    * *"Holding a knife"* $\rightarrow$ MUST show the cellmate holding/sharpening the blade.
* **No Generic B-Roll Fillers:** If a specific scene is mentioned, find and cut that exact timestamp. Never substitute an unrelated shot.

---

## 📺 2. RESOLUTION & CLARITY STANDARDS (1080p Native)
* **Minimum Resolution:** All source footage must be native **1080p (1920x1080) minimum**.
* **Zero 360p Upscaling:** Never crop and upscale a 360p stream to 1080p (it causes pixelation and blur).
* **Sharpening Filter:** Apply subtle lanczos scaling + unsharp enhancement (`scale=flags=lanczos, unsharp=5:5:0.8`) to ensure crisp mobile playback.

---

## 🎨 3. THE "REFERENCE REEL" VISUAL LAYOUT (The Good Doctor Style)
* **Framing:** 1080×1920 vertical (9:16 canvas) with a centered **1:1 square or 4:5 active video window**.
* **Cinematic Margins:** Flanked by clean dark top/bottom cinematic bars to prevent excessive vertical cropping and preserve full facial expressions.
* **Top Header Hook:** High-contrast yellow/white category/dilemma bar (e.g. `THE VERTICAL PRISON (LEVEL 48)`).
* **Subtitle Standards:**
  * Clean, bold, italicized white text with a soft drop-shadow (`Arial` or `Montserrat`).
  * Placed across the lower third of the active video window.
  * **Strict Single Track:** All original hardcoded movie/trailer subtitles MUST be cropped out completely. Zero double subtitles.
* **Zero Logos/Watermarks:** Strictly crop out Netflix/Universal/Sony intro logos and end credit cards.

---

## 🎙️ 4. THE "HYBRID MIX" AUDIO FORMULA
* **Structure:**
  1. **Narrator Hook (0s–10s):** High-stakes moral dilemma or shocking premise.
  2. **Original Character Dialogue (10s–16s):** Raw, emotional original actor voices from the film.
  3. **Narrator Escalation (16s–30s):** The twist, the obstacle, the danger doubling.
  4. **Original Character Dialogue / Climax (30s–38s):** Peak dramatic tension.
  5. **Narrator Cliffhanger (38s–45s):** Abrupt cut at the breaking point $\rightarrow$ *"Go to Part 2 pinned in comments!"*
* **Sound Design:** Continuous low-end thriller drone with sidechain compression automatically ducking 18dB beneath voice.

---

## 🛡️ 5. STRICT FAIR USE & ANTI-COPYRIGHT ARMOR
1. **The 1.8s Cut Frequency Rule:** Micro-cuts every 1.2 to 2.0 seconds. No single raw clip plays for longer than 2.5s.
2. **Transformative Commentary:** Continuous narrative presence throughout.
3. **Color / Perceptual Hash Shift:** Contrast and saturation adjusted by +6% to defeat automated Content ID hashing.

---

## ⚡ 6. ZERO-WASTE PROCESS (Single-Pass Execution)
* **One-Shot Perfection:** Build and verify timestamps before rendering.
* **No Trial-and-Error Credit Burning:** Single batch generation, direct extraction, immediate verification.
