# Whop Short-Form AI Editing System (Stage 1)

Stage 1 implementation of the deterministic short-form video editing engine.

## Core Philosophy
- **Brain Thinks:** Gemini / Antigravity proposes structured editing decisions.
- **Database Remembers:** PostgreSQL persists projects, videos, knowledge candidates, evidence, and audit logs.
- **Tools Execute:** Whisper for word-level timestamps, FFmpeg for deterministic punch-in rendering, and QC for output verification.

## Pipeline Flow
1. Validate input video
2. Register video in PostgreSQL
3. Run Whisper speech-to-text with word-level timestamps
4. Normalize and validate transcript tokens
5. Obtain AI punch-in proposal (word_index, scale, duration_ms)
6. Validate proposal against schema constraints
7. Calculate crop & scale parameters safely
8. Render punch-in with FFmpeg (subprocess argument lists, zero shell injection)
9. Quality control (existence, readability, duration, audio preservation)
10. Persist knowledge candidate and evidence in PostgreSQL
11. Write immutable audit log record
