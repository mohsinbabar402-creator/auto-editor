"""
Creative Intelligence Engine -- Hook Intelligence Engine (Phase 5)

PURPOSE:
    For each selected clip candidate, generate multiple hook variants
    using different psychological mechanisms, score them, verify
    truthfulness, and select the strongest appropriate hook.

    The hook system is NOT a single hardcoded formula.
    It is a library of mechanisms that the brain selects from
    based on the actual content of each clip.

INPUTS:
    - ClipCandidate (with transcript, topic, content_type, scores)

OUTPUTS:
    - HookSelection containing:
        - Multiple HookCandidate variants
        - The selected best hook
        - Selection reasoning

HOOK MECHANISMS SUPPORTED:
    1. Curiosity Gap       - "This 19yo discovered something most founders never will..."
    2. Open Loop           - "He lost everything. Then he found this one strategy."
    3. Contrarian          - "Everyone says you need VC funding. He proved them all wrong."
    4. Conflict-First      - "They called him a fake. Here's what happened next."
    5. Outcome-First       - "He went from broke to $10K/month. Here's exactly how."
    6. Strong Claim        - "This is the ONLY strategy that actually works in 2024."
    7. Question            - "What if everything you know about marketing is wrong?"
    8. Challenge           - "Most people can't do this. Can you?"
    9. Unexpected Reveal   - "Nobody expected what he said next."
    10. Emotional Tension  - "The moment he almost gave up changed everything."
    11. Status Conflict    - "A 19 year old is outperforming Fortune 500 marketing teams."
    12. Intriguing Quote   - Direct powerful quote from the speaker.
    13. Story Opening      - "At 3AM, with $47 in his account, he had an idea..."
    14. Payoff Preview     - "By the end of this, you'll know exactly how to..."

TRUTHFULNESS RULE:
    A hook MUST NOT promise something the clip does not deliver.
    A hook MUST NOT fabricate claims.
    A hook MUST NOT remove qualifiers to create false certainty.
"""

from __future__ import annotations
import re
from typing import List, Optional
from brain.models import (
    ClipCandidate, HookCandidate, HookSelection, HookMechanism, ContentType
)


# -- Hook Mechanism Library ---------------------------------------------------

# Maps content types to their best-fit hook mechanisms (ordered by priority)
CONTENT_HOOK_AFFINITY = {
    ContentType.STRONG_OPINION: [
        HookMechanism.CONTRARIAN,
        HookMechanism.STRONG_CLAIM,
        HookMechanism.CONFLICT_FIRST,
        HookMechanism.QUESTION,
    ],
    ContentType.STORY: [
        HookMechanism.STORY_OPENING,
        HookMechanism.OPEN_LOOP,
        HookMechanism.EMOTIONAL_TENSION,
        HookMechanism.CURIOSITY_GAP,
    ],
    ContentType.ADVICE: [
        HookMechanism.PAYOFF_PREVIEW,
        HookMechanism.STRONG_CLAIM,
        HookMechanism.CURIOSITY_GAP,
        HookMechanism.QUESTION,
    ],
    ContentType.REVELATION: [
        HookMechanism.UNEXPECTED_REVELATION,
        HookMechanism.CURIOSITY_GAP,
        HookMechanism.OUTCOME_FIRST,
        HookMechanism.OPEN_LOOP,
    ],
    ContentType.DEBATE: [
        HookMechanism.CONFLICT_FIRST,
        HookMechanism.CONTRARIAN,
        HookMechanism.QUESTION,
        HookMechanism.STATUS_CONFLICT,
    ],
    ContentType.HUMOR: [
        HookMechanism.INTRIGUING_QUOTE,
        HookMechanism.CURIOSITY_GAP,
        HookMechanism.OPEN_LOOP,
    ],
    ContentType.EMOTIONAL: [
        HookMechanism.EMOTIONAL_TENSION,
        HookMechanism.STORY_OPENING,
        HookMechanism.OPEN_LOOP,
        HookMechanism.CURIOSITY_GAP,
    ],
    ContentType.TECHNICAL: [
        HookMechanism.CURIOSITY_GAP,
        HookMechanism.PAYOFF_PREVIEW,
        HookMechanism.STATUS_CONFLICT,
        HookMechanism.STRONG_CLAIM,
    ],
    ContentType.CONFLICT: [
        HookMechanism.CONFLICT_FIRST,
        HookMechanism.CONTRARIAN,
        HookMechanism.STATUS_CONFLICT,
        HookMechanism.INTRIGUING_QUOTE,
    ],
    ContentType.PERSONAL_EXPERIENCE: [
        HookMechanism.STORY_OPENING,
        HookMechanism.OUTCOME_FIRST,
        HookMechanism.EMOTIONAL_TENSION,
        HookMechanism.CURIOSITY_GAP,
    ],
}


# -- Text Extraction Helpers --------------------------------------------------

def _extract_key_entity(transcript: str) -> str:
    """Extract the main person/company/product mentioned."""
    # Look for proper nouns (capitalized words not at sentence start)
    proper_nouns = re.findall(r'(?<!\. )(?<!\n)\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', transcript)
    # Filter out common words that get capitalized
    stopwords = {'The', 'This', 'That', 'And', 'But', 'So', 'Yeah', 'Yes', 'No',
                 'Like', 'Just', 'Well', 'Actually', 'Really', 'Hey', 'Oh', 'Okay',
                 'Now', 'Here', 'There', 'What', 'How', 'Why', 'When', 'Where', 'Who'}
    filtered = [n for n in proper_nouns if n not in stopwords and len(n) > 2]
    return filtered[0] if filtered else "this founder"


def _extract_core_topic(transcript: str) -> str:
    """Extract what the clip is fundamentally about in 3-5 words."""
    # Look for key phrases
    topic_patterns = [
        r'\b(building|creating|launching|growing|scaling)\s+(\w+(?:\s+\w+){0,2})',
        r'\b(AI|automation|agents?|marketing|content|clipping)\b',
        r'\b(money|revenue|\$\d+|income|profit)\b',
        r'\b(hiring|team|culture|startup|founder)\b',
        r'\b(gaming|esports|community|events?)\b',
    ]
    for pat in topic_patterns:
        match = re.search(pat, transcript, re.IGNORECASE)
        if match:
            return match.group(0).lower()
    return "business"


def _extract_money_amount(transcript: str) -> Optional[str]:
    """Extract monetary amounts from transcript."""
    patterns = [
        r'\$[\d,]+(?:\.\d+)?[kKmMbB]?',
        r'\b\d+(?:,\d+)?\s*(?:thousand|million|billion|k|K|M|B)\s*(?:dollars?)?\b',
    ]
    for pat in patterns:
        match = re.search(pat, transcript)
        if match:
            return match.group(0)
    return None


def _extract_strong_quote(transcript: str, max_words: int = 15) -> Optional[str]:
    """Find the most impactful short quote from the transcript."""
    # Split into sentences
    sentences = re.split(r'[.!?]+', transcript)
    best_quote = None
    best_score = 0

    for sent in sentences:
        sent = sent.strip()
        words = sent.split()
        if len(words) < 4 or len(words) > max_words:
            continue

        # Score by signal density
        score = 0
        intensity_words = ['never', 'always', 'everyone', 'nobody', 'impossible',
                          'changed', 'realized', 'discovered', 'truth', 'secret',
                          'crazy', 'insane', 'incredible', 'massive', 'huge']
        for w in intensity_words:
            if w in sent.lower():
                score += 2

        # Bonus for first-person declarations
        if re.match(r'^I\b', sent):
            score += 1

        if score > best_score:
            best_score = score
            best_quote = sent

    return best_quote


def _estimate_spoken_duration(text: str, wpm: float = 160.0) -> float:
    """Estimate how long it takes to speak the hook text at the target WPM."""
    word_count = len(text.split())
    return round(word_count / wpm * 60, 1)


# -- Hook Generators (one per mechanism) --------------------------------------

def _gen_curiosity_gap(candidate: ClipCandidate) -> HookCandidate:
    entity = _extract_key_entity(candidate.transcript)
    topic = _extract_core_topic(candidate.transcript)
    money = _extract_money_amount(candidate.transcript)

    if money:
        text = f"{entity} just revealed how {topic} generates {money} and most people have no idea this exists."
    else:
        text = f"{entity} just exposed something about {topic} that changes everything most people assume."

    header = f"WHAT {entity.upper()} DISCOVERED"

    return HookCandidate(
        mechanism=HookMechanism.CURIOSITY_GAP,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning=f"Curiosity gap: creates information asymmetry around {topic}",
    )


def _gen_open_loop(candidate: ClipCandidate) -> HookCandidate:
    entity = _extract_key_entity(candidate.transcript)
    topic = _extract_core_topic(candidate.transcript)

    text = f"{entity} tried {topic} and failed hard. But then one thing changed that nobody expected."
    header = f"NOBODY EXPECTED THIS"

    return HookCandidate(
        mechanism=HookMechanism.OPEN_LOOP,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning=f"Open loop: creates narrative tension around {entity}'s journey",
    )


def _gen_contrarian(candidate: ClipCandidate) -> HookCandidate:
    topic = _extract_core_topic(candidate.transcript)

    text = f"Everyone says {topic} is the way to grow. This founder proved them completely wrong."
    header = f"THE {topic.upper()} MYTH"

    return HookCandidate(
        mechanism=HookMechanism.CONTRARIAN,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning=f"Contrarian: challenges conventional wisdom about {topic}",
    )


def _gen_conflict_first(candidate: ClipCandidate) -> HookCandidate:
    entity = _extract_key_entity(candidate.transcript)
    quote = _extract_strong_quote(candidate.transcript)

    if quote and len(quote.split()) <= 12:
        text = f"'{quote}' {entity} just said this and the internet is divided."
    else:
        text = f"{entity} just made a statement that has everyone talking."

    header = f"CONTROVERSIAL TAKE"

    return HookCandidate(
        mechanism=HookMechanism.CONFLICT_FIRST,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning="Conflict-first: leads with the most divisive statement",
    )


def _gen_outcome_first(candidate: ClipCandidate) -> HookCandidate:
    entity = _extract_key_entity(candidate.transcript)
    money = _extract_money_amount(candidate.transcript)
    topic = _extract_core_topic(candidate.transcript)

    if money:
        text = f"{entity} went from nothing to {money} using {topic}. Here is exactly what they did."
    else:
        text = f"{entity} built something incredible with {topic}. Here is the exact blueprint."

    header = f"THE EXACT BLUEPRINT"

    return HookCandidate(
        mechanism=HookMechanism.OUTCOME_FIRST,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning=f"Outcome-first: leads with the result to create instant credibility",
    )


def _gen_strong_claim(candidate: ClipCandidate) -> HookCandidate:
    topic = _extract_core_topic(candidate.transcript)

    text = f"This is the single most effective approach to {topic} that nobody is talking about."
    header = f"THE #{topic.upper().split()[0] if topic.split() else 'SECRET'} APPROACH"

    return HookCandidate(
        mechanism=HookMechanism.STRONG_CLAIM,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning=f"Strong claim: positions the content as uniquely valuable insight",
    )


def _gen_question(candidate: ClipCandidate) -> HookCandidate:
    topic = _extract_core_topic(candidate.transcript)

    text = f"What if everything you think you know about {topic} is completely wrong?"
    header = f"THINK AGAIN"

    return HookCandidate(
        mechanism=HookMechanism.QUESTION,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning=f"Question: invites self-reflection and challenges assumptions about {topic}",
    )


def _gen_unexpected_revelation(candidate: ClipCandidate) -> HookCandidate:
    entity = _extract_key_entity(candidate.transcript)
    topic = _extract_core_topic(candidate.transcript)

    text = f"{entity} just revealed something about {topic} that nobody saw coming."
    header = f"NOBODY SAW THIS COMING"

    return HookCandidate(
        mechanism=HookMechanism.UNEXPECTED_REVELATION,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning="Unexpected revelation: promises new information the audience hasn't encountered",
    )


def _gen_emotional_tension(candidate: ClipCandidate) -> HookCandidate:
    entity = _extract_key_entity(candidate.transcript)

    text = f"The moment {entity} almost gave up on everything. What happened next changed the game."
    header = f"THE TURNING POINT"

    return HookCandidate(
        mechanism=HookMechanism.EMOTIONAL_TENSION,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning="Emotional tension: creates empathy and anticipation through vulnerability",
    )


def _gen_status_conflict(candidate: ClipCandidate) -> HookCandidate:
    entity = _extract_key_entity(candidate.transcript)
    topic = _extract_core_topic(candidate.transcript)

    text = f"A young founder is outperforming entire teams using {topic}. The industry is not ready for this."
    header = f"INDUSTRY DISRUPTOR"

    return HookCandidate(
        mechanism=HookMechanism.STATUS_CONFLICT,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning="Status conflict: creates David vs Goliath tension",
    )


def _gen_intriguing_quote(candidate: ClipCandidate) -> HookCandidate:
    quote = _extract_strong_quote(candidate.transcript)
    entity = _extract_key_entity(candidate.transcript)

    if quote:
        text = f"'{quote}' Listen to what {entity} says next."
        header = f"LISTEN CLOSELY"
    else:
        text = f"What {entity} said next left everyone speechless."
        header = f"WAIT FOR IT"

    return HookCandidate(
        mechanism=HookMechanism.INTRIGUING_QUOTE,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning="Intriguing quote: uses the speaker's own powerful words as the hook",
    )


def _gen_story_opening(candidate: ClipCandidate) -> HookCandidate:
    entity = _extract_key_entity(candidate.transcript)
    topic = _extract_core_topic(candidate.transcript)

    text = f"{entity} started with nothing but an idea about {topic}. This is what happened."
    header = f"FROM ZERO"

    return HookCandidate(
        mechanism=HookMechanism.STORY_OPENING,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning="Story opening: draws audience into a narrative arc",
    )


def _gen_payoff_preview(candidate: ClipCandidate) -> HookCandidate:
    topic = _extract_core_topic(candidate.transcript)

    text = f"By the end of this, you will know exactly how {topic} actually works behind the scenes."
    header = f"BEHIND THE SCENES"

    return HookCandidate(
        mechanism=HookMechanism.PAYOFF_PREVIEW,
        text=text,
        header_text=header,
        estimated_duration_sec=_estimate_spoken_duration(text),
        reasoning="Payoff preview: promises concrete knowledge gain to the viewer",
    )


# -- Generator Dispatch Table -------------------------------------------------

HOOK_GENERATORS = {
    HookMechanism.CURIOSITY_GAP: _gen_curiosity_gap,
    HookMechanism.OPEN_LOOP: _gen_open_loop,
    HookMechanism.CONTRARIAN: _gen_contrarian,
    HookMechanism.CONFLICT_FIRST: _gen_conflict_first,
    HookMechanism.OUTCOME_FIRST: _gen_outcome_first,
    HookMechanism.STRONG_CLAIM: _gen_strong_claim,
    HookMechanism.QUESTION: _gen_question,
    HookMechanism.UNEXPECTED_REVELATION: _gen_unexpected_revelation,
    HookMechanism.EMOTIONAL_TENSION: _gen_emotional_tension,
    HookMechanism.STATUS_CONFLICT: _gen_status_conflict,
    HookMechanism.INTRIGUING_QUOTE: _gen_intriguing_quote,
    HookMechanism.STORY_OPENING: _gen_story_opening,
    HookMechanism.PAYOFF_PREVIEW: _gen_payoff_preview,
}


# -- Truthfulness Verification ------------------------------------------------

def _verify_truthfulness(hook: HookCandidate, candidate: ClipCandidate) -> float:
    """
    Score how truthfully the hook represents the actual clip content.

    Returns 0-10 where:
    - 10 = perfectly represents the content
    - 7+ = acceptable (passes)
    - <7 = misleading (fails)

    Checks:
    1. Does the hook mention money amounts that exist in the clip?
    2. Does the hook claim outcomes that the clip actually discusses?
    3. Does the hook attribute statements to the right entity?
    4. Does the hook promise a payoff the clip delivers?
    """
    score = 8.0  # Start with reasonable default
    transcript_lower = candidate.transcript.lower()
    hook_lower = hook.text.lower()

    # Check: If hook mentions money, does the clip mention money?
    hook_money = _extract_money_amount(hook.text)
    clip_money = _extract_money_amount(candidate.transcript)
    if hook_money and not clip_money:
        score -= 4.0  # Major: fabricated financial claim

    # Check: If hook says "revealed" or "discovered", does clip contain revelation?
    revelation_words = ['reveal', 'discover', 'expose', 'uncover', 'secret']
    hook_claims_revelation = any(w in hook_lower for w in revelation_words)
    clip_has_revelation = any(w in transcript_lower for w in
                             ['found out', 'realized', 'discovered', 'turns out',
                              'actually', 'the truth', 'nobody knows'])
    if hook_claims_revelation and not clip_has_revelation:
        score -= 2.0

    # Check: If hook says "failed" or "lost everything", does clip discuss failure?
    hook_claims_failure = any(w in hook_lower for w in ['failed', 'lost', 'gave up', 'almost'])
    clip_has_failure = any(w in transcript_lower for w in
                          ['failed', 'lost', 'gave up', 'struggle', 'hard time',
                           'difficult', 'broke', 'mistake'])
    if hook_claims_failure and not clip_has_failure:
        score -= 2.5

    # Check: If hook says "everyone/nobody", is it exaggerating?
    if re.search(r'\b(everyone|nobody|no one)\b', hook_lower):
        score -= 0.5  # Minor: absolute language is common but slightly misleading

    # Check: If hook is a direct quote, verify it actually appears
    if hook.mechanism == HookMechanism.INTRIGUING_QUOTE:
        quote_match = re.search(r"'([^']+)'", hook.text)
        if quote_match:
            quote = quote_match.group(1).lower()
            # Check if the quote (or close match) exists in transcript
            if quote not in transcript_lower:
                # Check word overlap
                quote_words = set(quote.split())
                transcript_words = set(transcript_lower.split())
                overlap = len(quote_words & transcript_words) / len(quote_words) if quote_words else 0
                if overlap < 0.6:
                    score -= 3.0  # Fabricated quote

    return max(0, min(10.0, round(score, 1)))


def _score_hook_strength(hook: HookCandidate, candidate: ClipCandidate) -> float:
    """
    Score how strong the hook is at stopping scrolling.

    Evaluates:
    - Specificity (specific > vague)
    - Tension/curiosity (questions > statements)
    - Brevity (shorter hooks score higher)
    - Pattern interrupt potential
    """
    score = 5.0  # Baseline

    text = hook.text

    # Specificity bonus: mentions specific numbers, names, or details
    if re.search(r'\$[\d,]+', text):
        score += 1.5
    if re.search(r'\b\d+\b', text):
        score += 0.5

    entity = _extract_key_entity(candidate.transcript)
    if entity.lower() != "this founder" and entity in text:
        score += 1.0

    # Brevity bonus: 8-18 words is the sweet spot
    word_count = len(text.split())
    if 8 <= word_count <= 18:
        score += 1.0
    elif word_count > 25:
        score -= 1.0

    # Tension/curiosity words
    tension_words = ['revealed', 'secret', 'nobody', 'wrong', 'changed',
                     'exactly', 'truth', 'proved', 'discovered', 'exposed']
    for w in tension_words:
        if w in text.lower():
            score += 0.5

    # Question hooks get a slight boost (engaging)
    if text.strip().endswith('?'):
        score += 0.5

    # Duration penalty: hooks over 6s feel too long
    if hook.estimated_duration_sec > 6.0:
        score -= 1.0

    return max(0, min(10.0, round(score, 1)))


# -- Main Hook Intelligence --------------------------------------------------

def generate_hooks(
    candidate: ClipCandidate,
    max_variants: int = 4
) -> HookSelection:
    """
    Generate multiple hook variants for a clip candidate,
    score each on truthfulness and strength, and select the best.

    STRATEGY:
    1. Determine which hook mechanisms best fit the content type.
    2. Generate one variant per mechanism (up to max_variants).
    3. Score each on truthfulness and hook strength.
    4. Reject any hook with truthfulness < 7.0.
    5. Select the highest-scoring viable hook.
    """
    # Get mechanism priority for this content type
    priority_mechanisms = CONTENT_HOOK_AFFINITY.get(
        candidate.content_type,
        [HookMechanism.CURIOSITY_GAP, HookMechanism.OPEN_LOOP,
         HookMechanism.STRONG_CLAIM, HookMechanism.QUESTION]
    )

    # Generate variants
    variants = []
    for mechanism in priority_mechanisms[:max_variants]:
        generator = HOOK_GENERATORS.get(mechanism)
        if not generator:
            continue

        hook = generator(candidate)
        hook.truthfulness_score = _verify_truthfulness(hook, candidate)
        hook.hook_strength = _score_hook_strength(hook, candidate)
        variants.append(hook)

    # Sort by composite score: truthfulness * 0.4 + strength * 0.6
    variants.sort(
        key=lambda h: (h.truthfulness_score * 0.4 + h.hook_strength * 0.6),
        reverse=True
    )

    # Select the best viable hook
    selected = None
    selection_reasoning = ""

    for hook in variants:
        if hook.is_viable:
            selected = hook
            selection_reasoning = (
                f"Selected {hook.mechanism.value} hook "
                f"(truth={hook.truthfulness_score:.1f}, strength={hook.hook_strength:.1f}). "
                f"Reason: {hook.reasoning}"
            )
            break

    if not selected and variants:
        # Fall back to the most truthful hook even if strength is low
        truthful_hooks = [h for h in variants if h.is_truthful]
        if truthful_hooks:
            selected = truthful_hooks[0]
            selection_reasoning = (
                f"Fallback to {selected.mechanism.value} "
                f"(most truthful available, strength={selected.hook_strength:.1f})"
            )
        else:
            selection_reasoning = "No hook passed truthfulness threshold. Clip may need manual review."

    return HookSelection(
        candidate_id=candidate.candidate_id,
        variants=variants,
        selected=selected,
        selection_reasoning=selection_reasoning,
    )


def generate_hooks_batch(candidates: List[ClipCandidate]) -> List[HookSelection]:
    """Generate hooks for a batch of candidates."""
    selections = []
    for candidate in candidates:
        selection = generate_hooks(candidate)
        selections.append(selection)
        status = "OK" if selection.selected else "NO VIABLE HOOK"
        print(f"[Hook Engine] Candidate {candidate.candidate_id}: {status} "
              f"({len(selection.variants)} variants generated)")
    return selections


# -- CLI Testing ---------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
    from brain.source_analyzer import analyze_source
    from brain.clip_discovery import discover_candidates
    from brain.context_engine import verify_batch
    from pathlib import Path

    test_srt = Path(__file__).resolve().parent.parent / "projects" / "07_viral_podcasts" / "raw_subtitles.en.srt"

    print("=" * 70)
    print("PHASE 5: HOOK INTELLIGENCE ENGINE TEST")
    print("=" * 70)

    analysis = analyze_source(test_srt, title="Cap Table Ep 25", source_id="cap_table_ep25")
    candidates = discover_candidates(analysis)
    verified = verify_batch(candidates[:8])

    print(f"\n[Hook Engine] Generating hooks for top {len(verified)} verified candidates...\n")
    hook_selections = generate_hooks_batch(verified)

    print(f"\n{'=' * 70}")
    print("HOOK INTELLIGENCE RESULTS")
    print(f"{'=' * 70}")

    for i, (cand, sel) in enumerate(zip(verified, hook_selections), 1):
        print(f"\n  [{i}] Clip: {cand.start_sec:.0f}s-{cand.end_sec:.0f}s | "
              f"Score: {cand.final_score:.2f} | Type: {cand.content_type.value}")
        print(f"      Topic: {cand.topic}")

        print(f"\n      --- ALL VARIANTS ---")
        for j, v in enumerate(sel.variants, 1):
            viable = "PASS" if v.is_viable else "FAIL"
            print(f"      {j}. [{v.mechanism.value}] Truth={v.truthfulness_score:.1f} "
                  f"Strength={v.hook_strength:.1f} [{viable}]")
            print(f"         Text: \"{v.text}\"")
            print(f"         Header: \"{v.header_text}\"")

        if sel.selected:
            print(f"\n      >>> SELECTED: {sel.selected.mechanism.value}")
            print(f"      >>> \"{sel.selected.text}\"")
            print(f"      >>> Header: \"{sel.selected.header_text}\"")
            print(f"      >>> Duration: ~{sel.selected.estimated_duration_sec:.1f}s")
        else:
            print(f"\n      >>> NO VIABLE HOOK FOUND")

        print(f"      >>> Reasoning: {sel.selection_reasoning}")
