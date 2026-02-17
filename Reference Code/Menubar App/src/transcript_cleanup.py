"""
Transcript cleanup utilities: dictionary-based corrections and mechanical cleanup.
Lightweight module (no audio deps) for use by task_handlers and asr_helper.
"""

import re

# Pre-compiled regex patterns for mechanical_cleanup
_RE_FILLER_WORDS = re.compile(
    r"\b(um|uh|er|ah|hmm|hm|mhm|uh-huh|like,?)\b", re.IGNORECASE
)
_RE_MULTI_SPACE = re.compile(r" {2,}")
_RE_BROKEN_NEWLINE = re.compile(r"(?<=[a-z,])\n(?=[a-z])")
_RE_STUTTER = re.compile(r"\b(\w+)(\s+\1)+\b", re.IGNORECASE)
_RE_REPEATED_PHRASE = re.compile(r"\b((\w+\s+){1,3})\1+")
_RE_SPACE_BEFORE_PUNCT = re.compile(r" +([.,!?;:])")

# Dictionary of common ASR mis-transcriptions (wrong -> correct).
# Applied before LLM cleanup for faster, deterministic fixes.
# Add personal names, Singapore places/food, technical terms, etc.
TRANSCRIPTION_DICTIONARY = {
    # Personal names
    "Mervyn": "Mervin",
    "Fe": "Fae",
    "Fey": "Fae",
    "Fei": "Fae",
    # Singapore places (common mis-transcriptions)
    "Sarengun": "Serangoon",
    # Hogwarts / Harry Potter
    "Hogwoods": "Hogwarts",
    "Slitterins": "Slytherins",
    "Slitterin": "Slytherin",
    "Raven Claw": "Ravenclaw",
    "Huffle Puffs": "Hufflepuffs",
    "Huff or puffs": "Hufflepuffs",
    "Hoffelpaf": "Hufflepuff",
    "House Litterin": "House Slytherin",
    "slitter in": "slytherin",
    # Anime (Naruto)
    "You-chaha": "Uchiha",
    "Yuchaha": "Uchiha",
    "Uchaha": "Uchiha",
    # German / technical terms (Zettelkasten variants)
    "Zettelcasten": "Zettelkasten",
    "Zettelcastan": "Zettelkasten",
    "Zettelkastin": "Zettelkasten",
    "Zettelcastin": "Zettelkasten",
    "The Talcastan": "Zettelkasten",
    "Zetel Kastan": "Zettelkasten",
    "Zettell castin": "Zettelkasten",
    "Zetel kasten": "Zettelkasten",
    "Zetelkasten": "Zettelkasten",
    "Zatel Kasten": "Zettelkasten",
    "The Thail Custin.": "Zettelkasten",
    "That's Hal Kasten.": "Zettelkasten",
    "Zattelle": "Zettel",
    # Tech / forum
}

TRANSCRIPTION_LIKELIHOOD_DICTIONARY = {
    "pose": "post",
    "poses": "posts",
    "asians": "agents",
}


def apply_transcription_dictionary(text: str, custom_dict: dict | None = None) -> str:
    """
    Replace commonly mis-transcribed words using a dictionary.
    Uses word-boundary matching so 'Mervyn' in "Mervyn's" becomes "Mervin's".

    Args:
        text: Raw transcript text
        custom_dict: Optional override; defaults to TRANSCRIPTION_DICTIONARY

    Returns:
        Text with dictionary replacements applied
    """
    if not text:
        return ""
    d = custom_dict if custom_dict is not None else TRANSCRIPTION_DICTIONARY
    if not d:
        return text
    result = text
    for wrong, right in d.items():
        if wrong == right:
            continue
        # Word-boundary replacement (case-sensitive to preserve casing context)
        pattern = re.compile(r"\b" + re.escape(wrong) + r"\b")
        result = pattern.sub(right, result)
    return result


def mechanical_cleanup(text: str) -> str:
    """
    Mechanical text cleanup using regex (fillers, stutters, whitespace).
    Matches asr_helper.mechanical_cleanup logic for use without audio deps.
    """
    if not text:
        return ""
    text = _RE_FILLER_WORDS.sub("", text)
    text = _RE_MULTI_SPACE.sub(" ", text)
    text = _RE_BROKEN_NEWLINE.sub(" ", text)
    text = _RE_STUTTER.sub(r"\1", text)
    text = _RE_REPEATED_PHRASE.sub(r"\1", text)
    text = _RE_MULTI_SPACE.sub(" ", text)
    text = _RE_SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return text.strip()


def pre_llm_transcript_cleanup(text: str) -> str:
    """
    Run dictionary replacements + mechanical cleanup before LLM.
    Order: apply_transcription_dictionary -> mechanical_cleanup.
    """
    return mechanical_cleanup(apply_transcription_dictionary(text))


# Sentence-boundary pattern for context-window chunking (same idea as task_handlers).
_RE_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def _chunk_at_sentence_boundaries(text: str, max_chunk_chars: int) -> list[str]:
    """
    Split text into chunks at sentence boundaries, each chunk <= max_chunk_chars.
    Used so LanguageTool sees bounded context; avoids huge inputs.
    """
    if not text or not text.strip():
        return []
    if len(text) <= max_chunk_chars:
        return [text.strip()] if text.strip() else []

    chunks = []
    start = 0
    # Hard cap for a single chunk when no sentence boundary found
    max_fallback = int(max_chunk_chars * 1.5)

    while start < len(text):
        remaining = len(text) - start
        if remaining <= max_chunk_chars:
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        search_start = start + int(max_chunk_chars * 0.7)
        search_end = min(start + max_fallback, len(text))
        search_region = text[search_start:search_end]
        matches = list(_RE_SENTENCE_END.finditer(search_region))

        if matches:
            split_pos = search_start + matches[0].end()
        else:
            fallback_region = text[start : start + max_fallback]
            last_space = fallback_region.rfind(" ")
            if last_space > max_chunk_chars * 0.5:
                split_pos = start + last_space
            else:
                split_pos = start + max_fallback

        chunk = text[start:split_pos].strip()
        if chunk:
            chunks.append(chunk)
        start = split_pos

    return chunks


def _apply_languagetool(text: str) -> str:
    """
    Apply LanguageTool grammar/spelling corrections to text.
    Returns text unchanged if language_tool_python is not installed or on error.
    """
    try:
        import language_tool_python
    except ImportError:
        return text

    if not text or not text.strip():
        return text

    try:
        tool = language_tool_python.LanguageTool("en-US")
        matches = tool.check(text)
        corrected = language_tool_python.utils.correct(text, matches)
        return corrected.strip() if corrected else text
    except Exception:
        return text


def code_based_cleanup(text: str, max_chunk_chars: int = 4000) -> str:
    """
    Code-based transcript cleanup: dictionary + mechanical + LanguageTool (if available).
    Uses context-window heuristics: long text is split at sentence boundaries into
    chunks of at most max_chunk_chars, each chunk corrected by LanguageTool, then rejoined.
    Does not call any LLM; use when code-based-text-cleaning setting is enabled.
    """
    if not text:
        return ""
    pre_cleaned = pre_llm_transcript_cleanup(text)
    if not pre_cleaned.strip():
        return pre_cleaned

    chunks = _chunk_at_sentence_boundaries(pre_cleaned, max_chunk_chars)
    if not chunks:
        return pre_cleaned

    try:
        import language_tool_python
    except ImportError:
        return pre_cleaned

    corrected_chunks = []
    for chunk in chunks:
        corrected = _apply_languagetool(chunk)
        corrected_chunks.append(corrected if corrected else chunk)
    return " ".join(corrected_chunks)
