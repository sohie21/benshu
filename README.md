# Benshu MVP

Сервис для чтения китайских текстов: пользователь нажимает на слово и видит значение, подходящее именно к этому предложению. Значение можно сохранить в карточку и повторять по системе Лейтнера. Все действия пишутся в журнал событий, чтобы считать метрики гипотез.

| Гипотеза | Что проверяет MVP | Где смотреть |
|---|---|---|
| H3 (техническая) | Ранжирование значений по контексту лучше, чем «первое значение словаря» | `python evaluate.py` → Recall@1, Recall@2, MRR, p95 latency |
| H2 (продуктовая) | Benshu (группа B) быстрее и чаще доводит до карточки, чем обычный список значений (группа A) | вкладка «Метрики», `/api/stats`, SQL ниже |
| H1 (бизнес) | MVP по ссылке для CustDev-интервью и бета-теста | ваш домен |

## Что внутри

```
backend/
  app/main.py            API (FastAPI): /api/segment, /api/rank, /api/cards, /api/review, /api/events, /api/stats
  app/core/segment.py    разбиение текста: jieba + pypinyin
  app/core/dictionary.py русский мини-словарь (80 слов, 15 многозначных) + резерв CC-CEDICT (~121 тыс. слов, англ.)
  app/core/rankers.py    3 метода с одним интерфейсом: first_sense | context | llm
  app/core/llm.py        клиент OpenAI-совместимого API (YandexGPT и др.)
  app/core/storage.py    SQLite: пользователи и A/B-группа, карточки (Лейтнер), события, метрики
  data/                  словарь, демо-тексты, демо-датасет для оценки
  evaluate.py            офлайн-оценка той же функцией rank(), что работает на сайте
  tests/                 автотесты (pytest)
frontend/                index.html + styles.css + app.js, без сборки
deploy/                  nginx (HTTPS, лимит запросов), шаблон для certbot
docker-compose.yml       api + nginx
```

### Методы ранжирования

- **first_sense** — baseline: порядок обычного словаря (первое значение считается ответом).
- **context** — офлайн-метод: ищет в предложении контекстные подсказки для каждого значения (например, для 花 «тратить» — 钱, 块, 时间). Близкие к слову подсказки весят больше. Работает без интернета и ключей.
- **llm** — метод Benshu: модель получает предложение и пронумерованные словарные значения и возвращает JSON с номером. Придумать новый перевод она не может — только выбрать из словаря. Если ключ не задан, ответ неверный или истёк тайм-аут, сервис откатывается на `context`, и это видно в ответе API (`fallback_reason`).

Если уверенность ≥ 0,75, показывается одно значение, иначе два. Полный список всегда доступен по кнопке «Все значения».

## Локальный запуск

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/download_cedict.py          # необязательно: большой резервный словарь
FRONTEND_DIR=../frontend uvicorn app.main:app --reload --port 8000
# сайт: http://localhost:8000   документация API: http://localhost:8000/docs
```

Тесты и оценка:

```bash
python -m pytest -q
python evaluate.py --methods first_sense context        # без LLM
python evaluate.py                                      # + llm, если задан ключ в окружении
python evaluate.py --data data/my_test.csv              # ваш датасет
```
