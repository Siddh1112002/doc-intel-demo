# summarize.py
import re

_sentence_split_re = re.compile(r'(?<=[\.\?\!])\s+')

def extractive_summary(text: str, sentences_count: int = 3) -> str:
    if not text:
        return ""
    # naive split by punctuation
    sents = [s.strip() for s in _sentence_split_re.split(text) if s.strip()]
    if not sents:
        return text[:500]
    # choose the longest sentences (simple heuristic)
    ranked = sorted(sents, key=lambda s: len(s), reverse=True)
    chosen = ranked[:min(sentences_count, len(ranked))]
    # preserve original order:
    chosen_set = set(chosen)
    ordered = [s for s in sents if s in chosen_set]
    return " ".join(ordered[:sentences_count])
