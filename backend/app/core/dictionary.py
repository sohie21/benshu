"""Словарь Benshu: русский мини-словарь + (опционально) CC-CEDICT как резерв.

Русский словарь — основной: значения упорядочены как в обычном словаре,
у многозначных слов есть контекстные подсказки (cues).
CC-CEDICT (если скачан скриптом scripts/download_cedict.py) подключается
только для слов, которых нет в русском словаре; его значения на английском.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from pypinyin import Style, pinyin

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RU_DICT_PATH = DATA_DIR / "dictionary_ru.json"
CEDICT_PATH = DATA_DIR / "cedict_ts.u8"


@dataclass
class Sense:
    id: str
    gloss: str
    pos: str = ""
    pinyin: str | None = None
    cues: list[str] = field(default_factory=list)
    lang: str = "ru"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "gloss": self.gloss,
            "pos": self.pos,
            "pinyin": self.pinyin,
            "lang": self.lang,
        }


@dataclass
class Entry:
    word: str
    pinyin: str
    senses: list[Sense]
    source: str = "ru"

    @property
    def is_polysemous(self) -> bool:
        return len(self.senses) > 1


def to_pinyin(word: str) -> str:
    return " ".join(s[0] for s in pinyin(word, style=Style.TONE))


class Dictionary:
    def __init__(self) -> None:
        self.entries: dict[str, Entry] = {}
        self._load_ru()
        self.cedict_loaded = self._load_cedict()

    def _load_ru(self) -> None:
        raw = json.loads(RU_DICT_PATH.read_text(encoding="utf-8"))
        for word, data in raw.items():
            if word.startswith("_"):
                continue
            senses = [
                Sense(
                    id=s["id"],
                    gloss=s["gloss"],
                    pos=s.get("pos", ""),
                    pinyin=s.get("pinyin"),
                    cues=s.get("cues", []),
                )
                for s in data["senses"]
            ]
            self.entries[word] = Entry(word=word, pinyin=data["pinyin"], senses=senses)

    def _load_cedict(self) -> bool:
        if not CEDICT_PATH.exists():
            return False
        line_re = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]+)\]\s+/(.+)/\s*$")
        for line in CEDICT_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                continue
            m = line_re.match(line)
            if not m:
                continue
            _trad, simp, _pin, glosses = m.groups()
            if simp in self.entries and self.entries[simp].source == "ru":
                continue  # русский словарь приоритетнее
            parts = [g for g in glosses.split("/") if g and not g.startswith("CL:")]
            entry = self.entries.get(simp)
            if entry is None:
                entry = Entry(word=simp, pinyin=to_pinyin(simp), senses=[], source="cedict")
                self.entries[simp] = entry
            for g in parts[:6]:
                entry.senses.append(
                    Sense(id=f"{simp}#en{len(entry.senses) + 1}", gloss=g, lang="en")
                )
        return True

    def get(self, word: str) -> Entry | None:
        return self.entries.get(word)

    def __contains__(self, word: str) -> bool:
        return word in self.entries

    @property
    def words(self) -> list[str]:
        return list(self.entries.keys())


@lru_cache(maxsize=1)
def get_dictionary() -> Dictionary:
    return Dictionary()
