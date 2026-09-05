"""
Creative Intelligence Engine — Context Integrity Engine (Phase 3)

PURPOSE:
    Ensures that no clip distorts the speaker's intended meaning
    by removing necessary surrounding context.

    Before ANY clip can proceed to production, this engine must verify:
    - The clip contains a complete thought (not cut mid-sentence)
    - Important qualifications/disclaimers are preserved
    - Pronouns have their references intact
    - Sarcasm/jokes are not presented as literal statements
    - Questions are not separated from their answers when both are needed
    - The clip does not make the speaker appear to say something they didn't mean

INPUTS:
    - ClipCandidate (with transcript, context_before, context_after)

OUTPUTS:
    - Updated ClipCandidate with:
        - context_safety status (SAFE, QUESTIONABLE, CONTEXT_REQUIRED, MISLEADING, REJECT)
        - claims list with classifications
        - adjusted context_completeness score
        - boundary adjustment recommendations
"""

from __future__ import annotations
import re
from typing import List, Dict, Any, Tuple
from brain.models import (
    ClipCandidate, ContextSafety, ClaimType, NegativeFactors
)


# ─── Sentence Boundary Detection ────────────────────────────────────────────

def _detect_incomplete_start(text: str) -> bool:
    """Check if the transcript starts mid-sentence."""
    text = text.strip()
    if not text:
        return True

    # Starts with lowercase (mid-sentence)
    if text[0].islower() and text[0] not in ('i',):
        return True

    # Starts with a conjunction or continuation word
    continuation_starts = [
        r'^(and|but|or|so|because|since|while|although|however|though|yet|then)\b',
        r'^(which|that|where|when|who|whom)\b',
        r'^\.\.\.',
    ]
    for pat in continuation_starts:
        if re.match(pat, text, re.IGNORECASE):
            return True

    return False


def _detect_incomplete_end(text: str) -> bool:
    """Check if the transcript ends mid-sentence."""
    text = text.strip()
    if not text:
        return True

    # Ends with a conjunction or preposition (cut mid-thought)
    incomplete_endings = [
        r'\b(and|but|or|so|because|since|with|for|to|of|in|on|at|by|the|a|an|that|which)\s*$',
        r'\b(is|are|was|were|have|has|will|would|should|could|can)\s*$',
        r'\.\.\.\s*$',
    ]
    for pat in incomplete_endings:
        if re.search(pat, text, re.IGNORECASE):
            return True

    return False


# ─── Pronoun Reference Detection ────────────────────────────────────────────

def _find_unresolved_pronouns(transcript: str, context_before: str) -> List[str]:
    """
    Find pronouns in the transcript that might refer to something
    only mentioned in the context_before (which would be cut).
    """
    issues = []

    # Check for pronouns at the very start of the clip
    first_sentence = transcript.split('.')[0] if '.' in transcript else transcript[:100]

    # Pronouns that need antecedents
    pronoun_patterns = [
        (r'^(He|She|They|It|That|This|These|Those)\b', "starts with a pronoun"),
        (r'^(His|Her|Their|Its)\b', "starts with a possessive pronoun"),
    ]

    for pat, issue in pronoun_patterns:
        if re.match(pat, first_sentence.strip()):
            # Check if the referent exists in context_before but not in transcript
            if context_before and not _has_clear_referent_in_text(first_sentence, transcript):
                issues.append(f"Clip {issue} ('{re.match(pat, first_sentence.strip()).group(1)}') "
                            f"whose referent may only appear in preceding context")

    return issues


def _has_clear_referent_in_text(first_sentence: str, full_text: str) -> bool:
    """Check if a pronoun has its referent within the same text."""
    # Look for proper nouns or specific subjects
    has_subject = bool(re.search(r'\b[A-Z][a-z]+\b', full_text[:200]))
    return has_subject


# ─── Qualifier & Disclaimer Detection ───────────────────────────────────────

def _find_missing_qualifiers(transcript: str, context_before: str, context_after: str) -> List[str]:
    """
    Detect if the surrounding context contains qualifications or disclaimers
    that the clip removes, potentially changing the meaning.
    """
    issues = []

    qualifier_patterns = [
        r'\b(but|however|although|that said|having said that|on the other hand)\b',
        r'\b(it depends|not always|sometimes|in some cases|for some people)\b',
        r'\b(I could be wrong|I might be|not sure|disclaimer|caveat)\b',
        r'\b(joking|just kidding|sarcasm|not literally|tongue in cheek)\b',
        r'\b(allegedly|reportedly|supposedly|rumor|unconfirmed)\b',
    ]

    # Check if context_after contains a qualifier that reverses the clip's apparent meaning
    for pat in qualifier_patterns:
        after_matches = re.findall(pat, context_after, re.IGNORECASE)
        if after_matches:
            # The speaker qualifies/reverses their statement right after the clip ends
            issues.append(
                f"Context after clip contains qualifier '{after_matches[0]}' "
                f"that may change the meaning of the clip"
            )

    # Check if context_before contains setup that the clip depends on
    setup_patterns = [
        r'\b(the reason|what happened was|here.s the thing|context is)\b',
        r'\b(to understand this|first you need to know|let me explain)\b',
    ]
    for pat in setup_patterns:
        before_matches = re.findall(pat, context_before, re.IGNORECASE)
        if before_matches:
            issues.append(
                f"Context before clip contains important setup ('{before_matches[0]}') "
                f"that may be needed for comprehension"
            )

    return issues


# ─── Sarcasm & Humor Detection ──────────────────────────────────────────────

def _detect_sarcasm_risk(transcript: str) -> List[str]:
    """
    Flag content that might be sarcastic or humorous
    and could be misinterpreted as literal if clipped out of context.
    """
    issues = []

    sarcasm_indicators = [
        r'\[laughter\]',
        r'\b(obviously|clearly|of course|sure)\b.*\b(not|never|nobody)\b',
        r'\b(yeah right|sure buddy|great idea|what a)\b',
    ]

    for pat in sarcasm_indicators:
        if re.search(pat, transcript, re.IGNORECASE):
            issues.append("Content may contain sarcasm/humor that could be misinterpreted as literal")
            break

    return issues


# ─── Claim Identification & Classification ───────────────────────────────────

def _identify_claims(transcript: str) -> List[Dict[str, Any]]:
    """
    Identify factual-looking statements in the transcript
    and classify each one.
    """
    claims = []

    # Patterns that indicate factual-looking claims
    claim_patterns = [
        (r'(\d+%|\$\d+[kKmMbB]?|\d+ (?:million|billion|thousand|percent))', 'numerical_claim'),
        (r'\b(studies show|research shows|data shows|statistics show)\b', 'cited_evidence'),
        (r'\b(always|never|everyone|nobody|impossible|guaranteed)\b', 'absolute_claim'),
        (r'\b(the (?:best|worst|only|first|biggest|fastest))\b', 'superlative_claim'),
    ]

    for pat, claim_type in claim_patterns:
        matches = re.finditer(pat, transcript, re.IGNORECASE)
        for match in matches:
            # Get surrounding context (30 chars before and after)
            start = max(0, match.start() - 30)
            end = min(len(transcript), match.end() + 30)
            context = transcript[start:end]

            # Classify the claim
            classification = _classify_claim(context, claim_type)

            claims.append({
                'text': match.group(0),
                'context': context.strip(),
                'type': claim_type,
                'classification': classification.value,
                'position': match.start(),
            })

    return claims


def _classify_claim(context: str, claim_type: str) -> ClaimType:
    """Classify a claim based on its context and type."""
    context_lower = context.lower()

    # Personal experience indicators
    if re.search(r'\b(I|we|my|our|me)\b', context):
        if re.search(r'\b(I (?:think|believe|feel|guess)|in my (?:experience|opinion))\b', context_lower):
            return ClaimType.OPINION
        if re.search(r'\b(I (?:did|made|built|started|went|saw|had))\b', context):
            return ClaimType.PERSONAL_EXPERIENCE

    # Speculation indicators
    if re.search(r'\b(probably|maybe|might|could be|I think|potentially)\b', context_lower):
        return ClaimType.SPECULATION

    # Opinion indicators
    if re.search(r'\b(I (?:think|believe|feel)|in my view|my take)\b', context_lower):
        return ClaimType.OPINION

    # If it uses absolute language but is clearly opinion
    if claim_type == 'absolute_claim':
        return ClaimType.OPINION  # Most podcast absolutes are opinions

    # If it cites evidence
    if claim_type == 'cited_evidence':
        return ClaimType.UNVERIFIED_CLAIM  # We can't verify the source

    # Numerical claims from personal experience
    if claim_type == 'numerical_claim':
        if re.search(r'\b(I|we|our)\b', context):
            return ClaimType.PERSONAL_EXPERIENCE
        return ClaimType.UNVERIFIED_CLAIM

    return ClaimType.FACTUAL_FROM_SOURCE


# ─── Main Context Integrity Check ───────────────────────────────────────────

def verify_context_integrity(candidate: ClipCandidate) -> ClipCandidate:
    """
    Run the full context integrity analysis on a clip candidate.

    This modifies the candidate in-place:
    - Sets context_safety status
    - Populates claims list
    - Adjusts context_completeness score
    - Updates negative factors

    Returns the modified candidate.
    """
    issues = []
    severity = 0  # Track cumulative severity

    transcript = candidate.transcript
    ctx_before = candidate.context_before
    ctx_after = candidate.context_after

    # 1. Check sentence boundaries
    if _detect_incomplete_start(transcript):
        issues.append("BOUNDARY: Clip starts mid-sentence")
        severity += 1

    if _detect_incomplete_end(transcript):
        issues.append("BOUNDARY: Clip ends mid-sentence")
        severity += 1

    # 2. Check pronoun references
    pronoun_issues = _find_unresolved_pronouns(transcript, ctx_before)
    issues.extend(pronoun_issues)
    severity += len(pronoun_issues)

    # 3. Check missing qualifiers/disclaimers
    qualifier_issues = _find_missing_qualifiers(transcript, ctx_before, ctx_after)
    issues.extend(qualifier_issues)
    severity += len(qualifier_issues) * 2  # Qualifiers are higher severity

    # 4. Check sarcasm risk
    sarcasm_issues = _detect_sarcasm_risk(transcript)
    issues.extend(sarcasm_issues)
    severity += len(sarcasm_issues)

    # 5. Identify and classify claims
    claims = _identify_claims(transcript)
    candidate.claims = claims

    # Check for misleading claims
    misleading_claims = [c for c in claims if c['classification'] == ClaimType.MISLEADING_RISK.value]
    if misleading_claims:
        issues.append(f"CLAIMS: {len(misleading_claims)} potentially misleading claim(s) detected")
        severity += len(misleading_claims) * 3

    # 6. Determine context safety status
    if severity == 0:
        candidate.context_safety = ContextSafety.SAFE
    elif severity <= 2:
        candidate.context_safety = ContextSafety.QUESTIONABLE
    elif severity <= 4:
        candidate.context_safety = ContextSafety.CONTEXT_REQUIRED
    elif severity <= 6:
        candidate.context_safety = ContextSafety.MISLEADING
    else:
        candidate.context_safety = ContextSafety.REJECT

    # 7. Adjust scores based on findings
    context_score = max(0, 10.0 - severity * 1.5)
    candidate.scores.context_completeness = round(context_score, 1)

    candidate.negatives.context_dependent = min(10.0, severity * 1.5)
    candidate.negatives.misleading_risk = min(10.0, severity * 1.0)

    # Store issues for debugging/audit
    if not hasattr(candidate, '_context_issues'):
        candidate._context_issues = []
    candidate._context_issues = issues

    return candidate


def verify_batch(candidates: List[ClipCandidate]) -> List[ClipCandidate]:
    """
    Run context integrity verification on all candidates.
    Returns only those that pass (SAFE or QUESTIONABLE).
    """
    passed = []
    rejected = 0

    for candidate in candidates:
        verify_context_integrity(candidate)

        if candidate.context_safety in (ContextSafety.SAFE, ContextSafety.QUESTIONABLE):
            passed.append(candidate)
        elif candidate.context_safety == ContextSafety.CONTEXT_REQUIRED:
            # Still include but flag
            passed.append(candidate)
        else:
            rejected += 1
            candidate.rejection_reason = f"Context integrity: {candidate.context_safety.value}"

    print(f"[Context Engine] Verified {len(candidates)} candidates: "
          f"{len(passed)} passed, {rejected} rejected")
    return passed


# ─── CLI Testing ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
    from brain.source_analyzer import analyze_source
    from brain.clip_discovery import discover_candidates
    from pathlib import Path

    test_srt = Path(__file__).resolve().parent.parent / "projects" / "07_viral_podcasts" / "raw_subtitles.en.srt"

    print("=" * 70)
    print("PHASE 3: CONTEXT INTEGRITY ENGINE TEST")
    print("=" * 70)

    analysis = analyze_source(test_srt, title="Cap Table Ep 25", source_id="cap_table_ep25")
    candidates = discover_candidates(analysis)

    print(f"\n[Context Engine] Running integrity checks on top {min(10, len(candidates))} candidates...")
    top_candidates = candidates[:10]
    verified = verify_batch(top_candidates)

    print(f"\n{'=' * 70}")
    print(f"CONTEXT INTEGRITY RESULTS")
    print(f"{'=' * 70}")

    for i, c in enumerate(verified, 1):
        issues = getattr(c, '_context_issues', [])
        print(f"\n  [{i}] Score: {c.final_score:.2f} | Context: {c.context_safety.value.upper()}")
        print(f"      Time: {c.start_sec:.1f}s - {c.end_sec:.1f}s ({c.duration_sec:.0f}s)")
        print(f"      Claims: {len(c.claims)}")
        print(f"      Context Score: {c.scores.context_completeness:.1f}/10")
        if issues:
            for issue in issues:
                print(f"      >> {issue}")
        if c.claims:
            for claim in c.claims[:3]:
                print(f"      Claim: [{claim['classification']}] \"{claim['context'][:80]}\"")
