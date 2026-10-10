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

## Важно про метрики оценки

Демо-датасет `data/wsd_eval_demo.csv` (42 примера) проверяет только то, что пайплайн работает. Подсказки метода `context` и эти предложения составлены вместе, поэтому результат `context` (Recall@1 = 1,00) **завышен из-за утечки** и не подходит как аргумент на защите. Baseline `first_sense` на нём даёт Recall@1 = 0,36, Recall@2 = 0,81.

Для гипотезы H3:

1. Соберите 150–300 предложений из реальных текстов уровня HSK 1–4 (учебники, адаптированные новости), не глядя на подсказки.
2. Разметьте правильное значение (`gold_sense_id`) вдвоём и посчитайте согласие разметчиков (Cohen's kappa).
3. Разделите датасет: dev — для правки подсказок и промпта, test — только для финального замера.
4. Сравните `first_sense`, `context` и `llm` на test; приведите 95% ДИ (скрипт считает бутстрепом) и разбор ошибок.

## Деплой на сервер в Yandex Cloud

### 1. Подготовка ВМ

- Ubuntu 22.04/24.04, 2 vCPU, 2 ГБ RAM и 20 ГБ диска достаточно (CC-CEDICT занимает примерно 260 МБ RAM на процесс; если памяти мало, поставьте `--workers 1` в `backend/Dockerfile`).
- **Сделайте публичный IP статическим** (VPC → IP-адреса), иначе он может смениться после перезапуска.
- В группе безопасности откройте входящие 22 (лучше только со своего IP), 80, 443.

```bash
sudo apt update && sudo apt install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
```

### 2. Домен

У регистратора создайте A-запись `benshu.<ваш-домен>` → статический IP ВМ. Проверка: `dig +short benshu.<ваш-домен>`.

### 3. Запуск

```bash
git clone <ваш-репозиторий> benshu && cd benshu
cp .env.example .env && nano .env       # DOMAIN, ключи LLM
docker compose up -d --build
curl http://localhost/api/health
```

Сайт уже открывается по `http://<домен>`.

### 4. HTTPS (Let's Encrypt)

```bash
mkdir -p deploy/certbot/www deploy/certbot/conf
docker run --rm \
  -v "$PWD/deploy/certbot/conf:/etc/letsencrypt" \
  -v "$PWD/deploy/certbot/www:/var/www/certbot" \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d "$(grep ^DOMAIN .env | cut -d= -f2)" --email <ваша-почта> --agree-tos --no-eff-email
```

Затем в `deploy/nginx.conf` раскомментируйте редирект на https и блок `server { listen 443 ... }`, а строку `include` в блоке 80 закомментируйте. Перезапуск: `docker compose restart web`.

Продление сертификата — в `crontab -e`:

```
0 4 * * 1 cd ~/benshu && docker run --rm -v "$PWD/deploy/certbot/conf:/etc/letsencrypt" -v "$PWD/deploy/certbot/www:/var/www/certbot" certbot/certbot renew -q && docker compose restart web
```

### 5. YandexGPT

В `.env` (по [документации Yandex AI Studio](https://aistudio.yandex.ru/en/docs/ai-studio/operations/generation/completions-basic)):

```
LLM_BASE_URL=https://ai.api.cloud.yandex.net/v1
LLM_API_KEY=<API-ключ сервисного аккаунта с ролью ai.languageModels.user>
LLM_AUTH_PREFIX="Api-Key "
LLM_PROJECT=<folder_id>
LLM_MODEL=gpt://<folder_id>/yandexgpt/latest
```

`docker compose up -d` → на вкладке «Метрики» должно появиться «LLM». Тексты уходят провайдеру внутри России, это аргумент для блока о нормативных требованиях.

### 6. Бэкап журнала и карточек

```bash
mkdir -p ~/backups
# crontab: ежедневно в 03:00
0 3 * * * docker run --rm -v benshu_benshu-data:/data -v ~/backups:/b alpine sh -c 'cp /data/benshu.db /b/benshu-$(date +\%F).db'
```

Имя тома смотрите в `docker volume ls`. Копии можно выгружать в Object Storage.

### 7. Перед настоящим A/B-тестом

- В `.env` поставьте `BENSHU_DEMO_SWITCH=0`: переключатель режима в шапке перестанет менять группу на сервере, и пользователи останутся в случайно назначенной группе 50/50.
- Заранее рассчитайте размер выборки (в файле расчётов: 728 пользователей на группу для MDE +7 п. п.). На бете 10–20 человек это пилот юзабилити, а не A/B-тест.

## Метрики из базы (SQL)

```bash
docker compose exec api python -c "import sqlite3;c=sqlite3.connect('/data/benshu.db');print(c.execute('select grp,event,count(*) from events group by 1,2').fetchall())"
```

```sql
-- воронка по группам
SELECT grp, event, COUNT(*) FROM events GROUP BY grp, event;
-- точность по отзывам «Да / Нет» (группа B)
SELECT AVG(json_extract(payload,'$.correct')) FROM events WHERE event='feedback';
-- time-to-card, мс
SELECT grp, AVG(json_extract(payload,'$.ms_since_select')) FROM events WHERE event='card_saved' GROUP BY grp;
-- удержание повторений
SELECT AVG(json_extract(payload,'$.remembered')) FROM events WHERE event='card_reviewed';
```

## События журнала

`text_opened`, `word_selected`, `meaning_shown` (метод, уверенность, задержка), `card_saved` (время от клика до сохранения), `feedback` (верно/неверно и выбранное значение), `show_all_senses`, `card_reviewed`, `review_started`, `page_view`.

## Данные и право

- Тексты пользователя **не сохраняются**: сервер только разбивает их на слова. В журнал попадают слово, предложение для ранжирования (если LLM подключена — оно уходит провайдеру), метод и время.
- Пользователь анонимен: случайный ID в браузере, без e-mail и имени. При добавлении регистрации потребуются согласие на обработку персональных данных и политика конфиденциальности (152-ФЗ); хранение базы на ВМ в Yandex Cloud (РФ) упрощает требование о локализации.
- CC-CEDICT распространяется по лицензии CC BY-SA 4.0 — атрибуция есть в футере сайта. БКРС не используется, пока не проверена его лицензия.
- Значения выбирает алгоритм, который может ошибаться: уверенность и кнопка «Все значения» показываются всегда.

## Что не входит в MVP

Регистрация, оплата, OCR, мобильное приложение, дообучение модели, интервальное повторение сложнее Лейтнера (SM-2/FSRS — следующий шаг).
