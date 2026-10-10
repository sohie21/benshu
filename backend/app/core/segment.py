"""Разбиение китайского текста на предложения и слова (jieba + pypinyin)."""
from __future__ import annotations

import json
import re
from functools import lru_cache

import jieba

from .dictionary import DATA_DIR, get_dictionary, to_pinyin

jieba.setLogLevel(60)

SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?[”」』\"]?")
HAN_RE = re.compile(r"[\u3400-\u9fff]")


@lru_cache(maxsize=1)
def _init_jieba() -> bool:
    d = get_dictionary()
    for word, entry in d.entries.items():
        if entry.source == "ru" and len(word) > 1:
            jieba.add_word(word, freq=2000)
    rules = json.loads((DATA_DIR / "segmentation_rules.json").read_text(encoding="utf-8"))
    for pair in rules.get("force_split", []):
        jieba.suggest_freq(tuple(pair), True)
    return True


def _split_unknown(token: str) -> list[str]:
    """Если склеенного слова нет в словаре — делим его жадно на словарные слова."""
    d = get_dictionary()
    if token in d or len(token) == 1 or not HAN_RE.search(token):
        return [token]
    out, i = [], 0
    while i < len(token):
        for j in range(len(token), i, -1):
            piece = token[i:j]
            if piece in d or j == i + 1:
                out.append(piece)
                i = j
                break
    return out


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    parts = [m.group(0).strip() for m in SENTENCE_RE.finditer(text)]
    return [p for p in parts if p]


def segment(text: str) -> list[dict]:
    _init_jieba()
    d = get_dictionary()
    result = []
    for s_idx, sentence in enumerate(split_sentences(text)):
        tokens = []
        for raw in jieba.cut(sentence):
            for tok in _split_unknown(raw):
                is_han = bool(HAN_RE.search(tok))
                entry = d.get(tok) if is_han else None
                tokens.append(
                    {
                        "t": tok,
                        "pinyin": (entry.pinyin if entry else to_pinyin(tok)) if is_han else "",
                        "clickable": is_han,
                        "in_dict": entry is not None,
                        "polysemous": bool(entry and entry.is_polysemous),
                    }
                )
        result.append({"index": s_idx, "text": sentence, "tokens": tokens})
    return result
