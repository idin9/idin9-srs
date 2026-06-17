import re
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_BAD_WORDS = {
    "fuck", "shit", "damn", "ass", "bitch", "bastard", "dick", "pussy",
    "cunt", "cock", "whore", "slut", "nigger", "nigga", "faggot", "fag",
    "motherfucker", "bullshit", "jackass", "retard", "mong", "wanker",
    "piss", "crap", "douchebag", "twat", "scumbag", "asshole",
}


class ProfanityAnalyzer:
    def __init__(self, bad_words: Optional[set] = None):
        self._bad_words = bad_words or DEFAULT_BAD_WORDS

    def analyze(self, text: str) -> Dict:
        if not text or not text.strip():
            return {"bad_word_percentage": 0.0, "bad_word_count": 0, "total_word_count": 0, "matched_words": []}

        words = re.findall(r"[a-zA-Z]+", text.lower())
        total_words = len(words)

        if total_words == 0:
            return {"bad_word_percentage": 0.0, "bad_word_count": 0, "total_word_count": 0, "matched_words": []}

        matched = []
        bad_count = 0
        for word in words:
            if word in self._bad_words:
                bad_count += 1
                matched.append(word)

        percentage = round((bad_count / total_words) * 100, 1)

        return {
            "bad_word_percentage": percentage,
            "bad_word_count": bad_count,
            "total_word_count": total_words,
            "matched_words": list(set(matched)),
        }
