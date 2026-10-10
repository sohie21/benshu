"""Клиент LLM с OpenAI-совместимым API (chat/completions).

Подходит для любого провайдера с OpenAI-совместимым эндпоинтом
(YandexGPT в Yandex Cloud, GigaChat через совместимый прокси, DeepSeek и т. д. —
проверьте актуальный адрес и формат в документации провайдера).

Переменные окружения:
    LLM_BASE_URL  — например https://<провайдер>/v1
    LLM_API_KEY   — ключ
    LLM_MODEL     — имя модели
    LLM_AUTH_HEADER (необязательно) — заголовок авторизации, по умолчанию Authorization
    LLM_AUTH_PREFIX (необязательно) — префикс ключа, по умолчанию "Bearer "
    LLM_PROJECT (необязательно) — заголовок OpenAI-Project (для Yandex AI Studio — ID каталога)

Пример для YandexGPT (Yandex AI Studio):
    LLM_BASE_URL=https://ai.api.cloud.yandex.net/v1
    LLM_AUTH_PREFIX="Api-Key "
    LLM_PROJECT=<folder_id>
    LLM_MODEL=gpt://<folder_id>/yandexgpt/latest
"""
from __future__ import annotations

import json
import os
import re

import httpx

SYSTEM_PROMPT = (
    "Ты помогаешь изучающим китайский язык. Тебе дают предложение, выделенное слово "
    "и пронумерованный список словарных значений. Выбери значение, которое подходит "
    "к этому контексту. Нельзя придумывать новое значение — только номер из списка. "
    "Ответь строго JSON без пояснений вокруг: "
    '{"best": <номер>, "second": <номер или null>, "confidence": <0..1>, '
    '"explanation": "<1 короткое предложение по-русски: почему>"}'
)


def is_configured() -> bool:
    return bool(os.getenv("LLM_API_KEY") and os.getenv("LLM_BASE_URL") and os.getenv("LLM_MODEL"))


def _build_user_prompt(sentence: str, word: str, glosses: list[str]) -> str:
    options = "\n".join(f"{i}. {g}" for i, g in enumerate(glosses))
    return f"Предложение: {sentence}\nСлово: {word}\nЗначения:\n{options}"


def parse_choice(text: str, n: int) -> dict:
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("no JSON in LLM answer")
    data = json.loads(m.group(0))
    best = int(data["best"])
    if not 0 <= best < n:
        raise ValueError("best index out of range")
    second = data.get("second")
    second = int(second) if second is not None and 0 <= int(second) < n else None
    conf = max(0.0, min(1.0, float(data.get("confidence", 0.7))))
    return {"best": best, "second": second, "confidence": conf, "explanation": str(data.get("explanation", ""))[:300]}


def choose_sense(sentence: str, word: str, glosses: list[str]) -> dict:
    base = os.environ["LLM_BASE_URL"].rstrip("/")
    header = os.getenv("LLM_AUTH_HEADER", "Authorization")
    prefix = os.getenv("LLM_AUTH_PREFIX", "Bearer ")
    payload = {
        "model": os.environ["LLM_MODEL"],
        "temperature": 0,
        "max_tokens": 200,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(sentence, word, glosses)},
        ],
    }
    headers = {header: f"{prefix}{os.environ['LLM_API_KEY']}"}
    if os.getenv("LLM_PROJECT"):
        headers["OpenAI-Project"] = os.environ["LLM_PROJECT"]
    r = httpx.post(
        f"{base}/chat/completions",
        json=payload,
        headers=headers,
        timeout=float(os.getenv("LLM_TIMEOUT", "8")),
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    return parse_choice(content, len(glosses))
