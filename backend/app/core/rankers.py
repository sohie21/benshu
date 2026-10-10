"""Ранжирование значений слова по контексту.

Все методы имеют одинаковый интерфейс:
    rank(sentence, word, entry) -> RankResult

Методы:
    first_sense — baseline 1: порядок обычного словаря (первое значение = ответ).
    context     — baseline 2 / офлайн-режим: совпадение контекстных подсказок
                  (cues) с остальной частью предложения + слабый частотный приоритет.
    llm         — метод Benshu: LLM выбирает номер значения ТОЛЬКО из списка
                  словарных кандидатов (не может придумать перевод).
                  Если LLM не настроена или упала — откат на context.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from .dictionary import Entry, Sense
from . import llm as llm_client

LOW_CONFIDENCE = 0.55


@dataclass
class RankResult:
    method: str
    ranked: list[Sense]
    scores: list[float]
    confidence: float
    explanation: str
    evidence: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    fallback_reason: str | None = None

    @property
    def low_confidence(self) -> bool:
        return self.confidence < LOW_CONFIDENCE


def _context_without_target(sentence: str, word: str) -> str:
    return sentence.replace(word, "□", 1)


def _softmax(xs: list[float], temp: float = 1.0) -> list[float]:
    m = max(xs)
    ex = [math.exp((x - m) / temp) for x in xs]
    s = sum(ex)
    return [e / s for e in ex]


def rank_first_sense(sentence: str, word: str, entry: Entry) -> RankResult:
    n = len(entry.senses)
    conf = 1.0 if n == 1 else round(1 / n, 2)
    return RankResult(
        method="first_sense",
        ranked=list(entry.senses),
        scores=[float(n - i) for i in range(n)],
        confidence=conf,
        explanation="Показан порядок обычного словаря: первым идёт самое частое значение.",
    )


def rank_context(sentence: str, word: str, entry: Entry) -> RankResult:
    senses = entry.senses
    if len(senses) == 1:
        return RankResult("context", list(senses), [1.0], 1.0, "У слова одно значение.")
    if not any(s.cues for s in senses):
        return RankResult(
            "context", list(senses), [float(len(senses) - i) for i in range(len(senses))], 0.5,
            "Для этого слова нет контекстных подсказок (значения из CC-CEDICT, англ.) — показан порядок словаря. "
            "С подключённой LLM значение выбирается по контексту.",
        )
    ctx = _context_without_target(sentence, word)
    pos = max(0, sentence.find(word))
    n = len(senses)
    raw, hits = [], []
    for i, s in enumerate(senses):
        found, score = [], 0.0
        for c in s.cues:
            if not c or c not in ctx:
                continue
            # расстояние от подсказки до слова (в символах): ближние подсказки важнее
            idxs = [j for j in range(len(ctx)) if ctx.startswith(c, j)]
            dist = min(abs(j - pos) for j in idxs)
            score += (1 + 0.5 * (len(c) - 1)) / (1 + dist / 4)
            found.append((dist, c))
        found = [c for _, c in sorted(found)]
        score += 0.15 * (n - i) / n  # слабый приоритет частого значения
        raw.append(score)
        hits.append(found)
    order = sorted(range(n), key=lambda i: -raw[i])
    probs = _softmax(raw, temp=0.6)
    top = order[0]
    if hits[top]:
        cues = ", ".join(f"«{c}»" for c in hits[top][:3])
        expl = f"Рядом со словом есть {cues} — это типичный контекст для значения «{senses[top].gloss}»."
    else:
        expl = "Явных контекстных подсказок не найдено — показано самое частое значение. Проверьте по полному списку."
    return RankResult(
        method="context",
        ranked=[senses[i] for i in order],
        scores=[round(raw[i], 3) for i in order],
        confidence=min(round(probs[top], 2), 0.95) if hits[top] else min(round(probs[top], 2), 0.45),
        explanation=expl,
        evidence=hits[top],
    )


def rank_llm(sentence: str, word: str, entry: Entry) -> RankResult:
    senses = entry.senses
    if len(senses) == 1:
        return RankResult("llm", list(senses), [1.0], 1.0, "У слова одно значение.")
    if not llm_client.is_configured():
        res = rank_context(sentence, word, entry)
        res.fallback_reason = "LLM не настроена (нет LLM_API_KEY) — использован метод context"
        return res
    try:
        choice = llm_client.choose_sense(sentence, word, [s.gloss for s in senses])
    except Exception as exc:  # сеть, лимиты, неверный JSON
        res = rank_context(sentence, word, entry)
        res.fallback_reason = f"Ошибка LLM ({type(exc).__name__}) — использован метод context"
        return res
    order = [choice["best"]]
    if choice.get("second") is not None and choice["second"] != choice["best"]:
        order.append(choice["second"])
    order += [i for i in range(len(senses)) if i not in order]
    conf = float(choice.get("confidence", 0.7))
    return RankResult(
        method="llm",
        ranked=[senses[i] for i in order],
        scores=[round(conf if k == 0 else (1 - conf) / max(1, len(order) - 1), 3) for k in range(len(order))],
        confidence=round(conf, 2),
        explanation=choice.get("explanation") or "Значение выбрано моделью по контексту предложения.",
    )


RANKERS = {
    "first_sense": rank_first_sense,
    "context": rank_context,
    "llm": rank_llm,
}


def rank(sentence: str, word: str, entry: Entry, method: str = "llm") -> RankResult:
    fn = RANKERS.get(method, rank_llm)
    t0 = time.perf_counter()
    res = fn(sentence, word, entry)
    res.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    return res
