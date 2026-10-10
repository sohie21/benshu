/* Benshu MVP — фронтенд без фреймворков. */
(() => {
  "use strict";
  const API = (window.BENSHU_API_BASE || "").replace(/\/$/, "");
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  // ---------- анонимный пользователь ----------
  const store = (() => {
    try { localStorage.setItem("__t", "1"); localStorage.removeItem("__t"); return localStorage; }
    catch { const m = {}; return { getItem: k => m[k] ?? null, setItem: (k, v) => { m[k] = String(v); } }; }
  })();
  const newId = () => (crypto.randomUUID ? crypto.randomUUID() : "u" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
  let uid = store.getItem("benshu_uid");
  if (!uid) { uid = newId(); store.setItem("benshu_uid", uid); }

  const state = {
    group: null, texts: [], current: null, sentences: [], selected: null,
    saved: new Set(), cards: [], showPinyin: store.getItem("benshu_pinyin") === "1",
    review: { queue: [], i: 0, revealed: false, done: 0 },
  };

  // ---------- утилиты ----------
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const markWord = (sentence, word) => {
    const s = esc(sentence), w = esc(word); const i = s.indexOf(w);
    return i < 0 ? s : s.slice(0, i) + "<mark>" + w + "</mark>" + s.slice(i + w.length);
  };
  const hash = s => { let h = 0; for (const c of s) h = (h * 31 + c.codePointAt(0)) | 0; return "t" + (h >>> 0).toString(36); };
  let toastTimer;
  const toast = msg => { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2200); };

  async function api(path, { method = "GET", body } = {}) {
    const res = await fetch(API + path, {
      method, headers: { "Content-Type": "application/json", "X-User-Id": uid },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) { let d = ""; try { d = (await res.json()).detail; } catch {} throw new Error(d || res.statusText); }
    return res.json();
  }
  const track = (event, payload = {}) => api("/api/events", { method: "POST", body: { event, payload: { ...payload, group: state.group } } }).catch(() => {});

  // ---------- навигация ----------
  function show(view) {
    $$(".tab").forEach(b => b.classList.toggle("is-active", b.dataset.view === view));
    $$(".view").forEach(v => v.classList.toggle("is-active", v.id === "view-" + view));
    if (view === "cards") renderCards();
    if (view === "review") startReview();
    if (view === "stats") renderStats();
    track("page_view", { view });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  $$(".tab").forEach(b => b.addEventListener("click", () => show(b.dataset.view)));

  // ---------- режим (A/B-группа) ----------
  function paintMode() { $$(".mode-btn").forEach(b => b.classList.toggle("is-active", b.dataset.group === state.group)); }
  $$(".mode-btn").forEach(b => b.addEventListener("click", async () => {
    if (b.dataset.group === state.group) return;
    const r = await api("/api/session", { method: "POST", body: { preferred_group: b.dataset.group, force: true } });
    state.group = r.group; paintMode();
    toast(state.group === "benshu" ? "Режим Benshu: значение по контексту" : "Режим «Словарь»: полный список значений");
    if (state.selected) selectToken(state.selected.s, state.selected.t, true);
  }));

  // ---------- тексты ----------
  function renderChips() {
    $("#textChips").innerHTML = state.texts.map(t =>
      `<button class="chip${state.current && state.current.id === t.id ? " is-active" : ""}" data-id="${esc(t.id)}" role="tab">${esc(t.title)}</button>`).join("");
    $$("#textChips .chip").forEach(c => c.addEventListener("click", () => openText(state.texts.find(t => t.id === c.dataset.id))));
  }

  async function openText(t) {
    state.current = t; state.selected = null; renderChips();
    $("#textTitle").textContent = t.title; $("#textLevel").textContent = t.level || ""; $("#textLevel").hidden = !t.level;
    $("#text").innerHTML = `<div class="skel" style="height:2.2em;margin-bottom:.6em"></div><div class="skel" style="height:2.2em;width:70%"></div>`;
    resetPanel();
    try {
      const r = await api("/api/segment", { method: "POST", body: { text: t.text } });
      state.sentences = r.sentences; renderText();
      track("text_opened", { text_id: t.id.startsWith("own:") ? undefined : t.id, hash: t.id.startsWith("own:") ? t.id : undefined, chars: t.text.length });
    } catch (e) { $("#text").innerHTML = `<p class="muted">Не удалось разобрать текст: ${esc(e.message)}</p>`; }
  }

  function renderText() {
    const box = $("#text"); box.classList.toggle("with-pinyin", state.showPinyin);
    box.innerHTML = state.sentences.map(s => `<span class="sent" data-s="${s.index}">` + s.tokens.map((k, i) => {
      if (!k.clickable) return `<span class="tok">${esc(k.t)}</span>`;
      const saved = [...state.saved].some(key => key.startsWith(k.t + "|"));
      const cls = ["tok", "click", k.polysemous ? "poly" : "", saved ? "saved" : ""].join(" ");
      const inner = state.showPinyin ? `<ruby>${esc(k.t)}<rt>${esc(k.pinyin)}</rt></ruby>` : esc(k.t);
      return `<span class="${cls}" role="button" tabindex="0" data-s="${s.index}" data-t="${i}" aria-label="${esc(k.t)} ${esc(k.pinyin)}">${inner}</span>`;
    }).join("") + `</span>`).join("");
  }
  $("#text").addEventListener("click", e => { const el = e.target.closest(".tok.click"); if (el) selectToken(+el.dataset.s, +el.dataset.t); });
  $("#text").addEventListener("keydown", e => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches(".tok.click")) { e.preventDefault(); selectToken(+e.target.dataset.s, +e.target.dataset.t); }
  });
  $("#pinyinToggle").checked = state.showPinyin;
  $("#pinyinToggle").addEventListener("change", e => { state.showPinyin = e.target.checked; store.setItem("benshu_pinyin", e.target.checked ? "1" : "0"); renderText(); highlightSelected(); });

  $("#ownTextBtn").addEventListener("click", () => { const f = $("#ownTextForm"); f.hidden = !f.hidden; if (!f.hidden) $("#ownText").focus(); });
  $("#ownTextForm").addEventListener("submit", e => {
    e.preventDefault(); const text = $("#ownText").value.trim();
    if (!/[\u3400-\u9fff]/.test(text)) { toast("В тексте нет китайских иероглифов"); return; }
    const t = { id: "own:" + hash(text), title: "Свой текст", level: "", text };
    state.texts = state.texts.filter(x => !x.id.startsWith("own:")).concat(t);
    $("#ownTextForm").hidden = true; openText(t);
  });

  // ---------- выбор слова ----------
  function highlightSelected() {
    $$(".tok.is-selected").forEach(x => x.classList.remove("is-selected"));
    if (!state.selected) return;
    const el = $(`.tok[data-s="${state.selected.s}"][data-t="${state.selected.t}"]`); if (el) el.classList.add("is-selected");
  }
  function resetPanel() {
    $("#panel").classList.remove("is-open");
    $("#panelBody").innerHTML = `<div class="empty"><div class="empty-glyph" aria-hidden="true">字</div><p class="empty-title">Выберите слово в тексте</p><p class="empty-text">Здесь появится значение, подходящее к этому предложению, и кнопка «В карточки».</p></div>`;
  }
  $("#panelClose").addEventListener("click", () => $("#panel").classList.remove("is-open"));

  async function selectToken(s, t, silent = false) {
    const sent = state.sentences[s]; const tok = sent.tokens[t];
    state.selected = { s, t, word: tok.t, sentence: sent.text, t0: silent && state.selected ? state.selected.t0 : performance.now() };
    highlightSelected(); $("#panel").classList.add("is-open");
    $("#panelBody").innerHTML = `<div class="w-head"><div class="w-han">${esc(tok.t)}</div><div class="w-pin">${esc(tok.pinyin)}</div></div>
      <div class="skel" style="height:14px;width:80%;margin:14px 0 22px"></div><div class="skel" style="height:30px;width:60%;margin-bottom:12px"></div>
      <div class="skel" style="height:60px;margin-bottom:16px"></div><div class="skel" style="height:42px"></div>`;
    if (!silent) track("word_selected", { word: tok.t, polysemous: tok.polysemous, in_dict: tok.in_dict });
    try {
      const r = await api("/api/rank", { method: "POST", body: { sentence: sent.text, word: tok.t, method: state.group === "control" ? "first_sense" : undefined } });
      if (!state.selected || state.selected.s !== s || state.selected.t !== t) return;
      state.selected.result = r; renderPanel(r);
    } catch (e) { $("#panelBody").innerHTML = `<p class="muted">Ошибка: ${esc(e.message)}</p>`; }
  }

  const isSaved = (word, senseId) => state.saved.has(word + "|" + senseId);
  const senseBtn = (r, x, i) => `<li><button class="sense${isSaved(r.word, x.id) ? " is-saved" : ""}" data-sense="${esc(x.id)}">
      <span class="n">${i + 1}</span><span>${esc(x.gloss)}${x.lang === "en" ? ' <span class="p">(англ.)</span>' : ""}</span><span class="p">${esc(x.pinyin || "")}</span></button></li>`;

  function renderPanel(r) {
    const sel = state.selected; const body = $("#panelBody");
    const head = `<div class="w-head"><div class="w-han">${esc(r.word)}</div><div class="w-pin">${esc(r.pinyin || state.sentences[sel.s].tokens[sel.t].pinyin)}</div></div>
      <div class="w-sentence">${markWord(sel.sentence, r.word)}</div>`;
    if (!r.found) {
      body.innerHTML = head + `<p class="w-kicker">Нет в словаре MVP</p><p class="muted" style="font-size:var(--t-sm)">Этого слова пока нет в мини-словаре. Подключите CC-CEDICT (scripts/download_cedict.py), чтобы покрыть остальную лексику.</p>`;
      return;
    }
    if (state.group === "control") {
      body.innerHTML = head + `<p class="w-kicker">Значения из словаря</p>
        <p class="muted" style="font-size:var(--t-sm);margin:0 0 6px">Выберите подходящее значение — оно сохранится в карточки.</p>
        <ul class="sense-list">${r.dictionary_order.map((x, i) => senseBtn(r, x, i)).join("")}</ul>
        <div class="w-meta"><span>Режим «Словарь» (группа A)</span><span>${r.dictionary_order.length} знач.</span></div>`;
      $$(".sense", body).forEach(b => b.addEventListener("click", () => save(r, r.dictionary_order.find(x => x.id === b.dataset.sense), "dictionary_pick")));
      return;
    }
    const top = r.top[0], alt = r.top[1];
    const conf = Math.round(r.confidence * 100);
    const multi = r.senses.length > 1;
    body.innerHTML = head + `
      <p class="w-kicker">${multi ? "Значение в этом предложении" : "Значение"}</p>
      <p class="w-gloss">${esc(top.gloss)}</p>
      <div class="w-pos">${esc(top.pos || "")}${top.pinyin && top.pinyin !== r.pinyin ? " · " + esc(top.pinyin) : ""}${top.lang === "en" ? " · англ. (CC-CEDICT)" : ""}</div>
      ${alt ? `<div class="w-alt">Возможно также: <b>${esc(alt.gloss)}</b></div>` : ""}
      ${multi ? `<div class="w-why">${esc(r.explanation)}</div>
      <div class="conf${r.low_confidence ? " low" : ""}"><span>Уверенность</span><div class="conf-bar"><span style="width:${conf}%"></span></div><span>${conf}%</span></div>` : ""}
      ${r.low_confidence && multi ? `<p class="note">Уверенность низкая — проверьте значение по полному списку ниже.</p>` : ""}
      <div class="w-actions">
        <button class="btn btn-primary" id="saveTop">${isSaved(r.word, top.id) ? "Уже в карточках" : "В карточки"}</button>
      </div>
      ${multi ? `<div class="w-feedback"><span>Значение подходит?</span><span class="btns">
        <button class="btn btn-sm btn-ok" id="fbYes">Да</button><button class="btn btn-sm btn-bad" id="fbNo">Нет</button></span></div>
      <details class="details" id="allSenses"><summary>Все значения (${r.senses.length})</summary>
        <ul class="sense-list">${r.dictionary_order.map((x, i) => senseBtn(r, x, i)).join("")}</ul></details>` : ""}
      <div class="w-meta"><span>Метод: ${esc(methodName(r.method))}${r.fallback_reason ? " (LLM не подключена)" : ""}</span><span>${r.latency_ms} мс</span></div>`;
    $("#saveTop").addEventListener("click", () => save(r, top, "top"));
    if (multi) {
      $("#fbYes").addEventListener("click", () => { track("feedback", { word: r.word, correct: true, sense_id: top.id, method: r.method, confidence: r.confidence }); toast("Спасибо, учтено"); $(".w-feedback").innerHTML = "<span>Спасибо — отметка сохранена.</span>"; });
      $("#fbNo").addEventListener("click", () => { $("#allSenses").open = true; toast("Выберите верное значение в списке"); state.selected.wrong = true; });
      $("#allSenses").addEventListener("toggle", e => { if (e.target.open) track("show_all_senses", { word: r.word }); });
      $$("#allSenses .sense").forEach(b => b.addEventListener("click", () => {
        const x = r.dictionary_order.find(s => s.id === b.dataset.sense);
        track("feedback", { word: r.word, correct: x.id === top.id, sense_id: top.id, chosen_sense_id: x.id, method: r.method, confidence: r.confidence });
        save(r, x, "manual_pick");
      }));
    }
  }
  const methodName = m => ({ llm: "LLM по контексту", context: "контекстные подсказки", first_sense: "первое значение словаря" }[m] || m);

  async function save(r, sense, how) {
    const sel = state.selected; if (!sense) return;
    try {
      const out = await api("/api/cards", { method: "POST", body: {
        word: r.word, pinyin: sense.pinyin || r.pinyin, sense_id: sense.id, gloss: sense.gloss, sentence: sel.sentence,
        explanation: state.group === "benshu" ? r.explanation : null, method: state.group === "control" ? "dictionary_pick" : (how === "top" ? r.method : "manual_pick"),
        ms_since_select: Math.round(performance.now() - sel.t0),
      } });
      state.saved.add(r.word + "|" + sense.id);
      toast(out.created ? "Карточка сохранена" : "Эта карточка уже есть");
      await refreshCounts(); renderText(); highlightSelected(); renderPanel(r);
    } catch (e) { toast("Не удалось сохранить: " + e.message); }
  }

  // ---------- карточки ----------
  async function refreshCounts() {
    try {
      const [cards, due] = await Promise.all([api("/api/cards"), api("/api/review")]);
      state.cards = cards; state.saved = new Set(cards.map(c => c.word + "|" + c.sense_id));
      $("#cardsCount").textContent = cards.length; $("#cardsCount").dataset.zero = cards.length ? "0" : "1";
      $("#dueCount").textContent = due.length; $("#dueCount").dataset.zero = due.length ? "0" : "1";
    } catch {}
  }
  const boxes = n => `<span class="boxes" title="Коробка ${n} из 5">${[1, 2, 3, 4, 5].map(i => `<i class="${i <= n ? "on" : ""}"></i>`).join("")}</span>`;
  const emptyBlock = (text, btn) => `<div class="empty-block"><div class="empty-glyph" aria-hidden="true">卡</div><p>${text}</p>${btn ? `<button class="btn btn-primary" data-go="read">${btn}</button>` : ""}</div>`;
  const wireGo = el => $$("[data-go]", el).forEach(b => b.addEventListener("click", () => show(b.dataset.go)));

  async function renderCards() {
    await refreshCounts(); const g = $("#cardsGrid");
    if (!state.cards.length) { g.style.display = "block"; g.innerHTML = emptyBlock("Карточек пока нет. Нажмите на слово в тексте и сохраните значение.", "Перейти к чтению"); wireGo(g); return; }
    g.style.display = "";
    g.innerHTML = state.cards.map(c => `<article class="card">
      <div class="card-top"><div><div class="card-han">${esc(c.word)}</div><div class="card-pin">${esc(c.pinyin || "")}</div></div>
      <button class="btn-quiet btn" data-del="${c.id}" aria-label="Удалить карточку ${esc(c.word)}">Удалить</button></div>
      <div class="card-gloss">${esc(c.gloss)}</div>
      ${c.sentence ? `<div class="card-sent">${markWord(c.sentence, c.word)}</div>` : ""}
      <div class="card-foot">${boxes(c.box)}<span>${c.reviews} повтор.</span></div></article>`).join("");
    $$("[data-del]", g).forEach(b => b.addEventListener("click", async () => { await api("/api/cards/" + b.dataset.del, { method: "DELETE" }); toast("Карточка удалена"); renderCards(); }));
  }

  // ---------- повторение ----------
  async function startReview() {
    const q = await api("/api/review"); state.review = { queue: q, i: 0, revealed: false, done: 0 };
    if (q.length) track("review_started", { due: q.length });
    renderReview();
  }
  function renderReview() {
    const box = $("#reviewBox"), R = state.review;
    if (!R.queue.length || R.i >= R.queue.length) {
      box.innerHTML = R.done ? emptyBlock(`Готово: повторено карточек — ${R.done}. Следующие появятся по расписанию Лейтнера.`, "Читать дальше")
        : emptyBlock("Сейчас нечего повторять. Сохраните несколько слов из текста — новые карточки сразу попадают в повторение.", "Перейти к чтению");
      wireGo(box); refreshCounts(); return;
    }
    const c = R.queue[R.i];
    box.innerHTML = `<div class="flash">
      <div class="flash-progress">${R.i + 1} из ${R.queue.length} · коробка ${c.box}</div>
      <div class="flash-han">${esc(c.word)}</div>
      ${c.sentence ? `<div class="flash-sent">${markWord(c.sentence, c.word)}</div>` : ""}
      ${R.revealed ? `<div class="flash-answer"><div class="pin">${esc(c.pinyin || "")}</div><div class="gloss">${esc(c.gloss)}</div></div>
        <div class="flash-btns"><button class="btn btn-ghost" data-r="0">Не помню</button><button class="btn btn-primary" data-r="1">Помню</button></div>`
        : `<button class="btn btn-primary" id="reveal" style="min-width:220px">Показать ответ</button>`}
    </div>`;
    if (!R.revealed) $("#reveal").addEventListener("click", () => { R.revealed = true; renderReview(); });
    $$("[data-r]", box).forEach(b => b.addEventListener("click", async () => {
      await api(`/api/review/${c.id}`, { method: "POST", body: { remembered: b.dataset.r === "1" } });
      R.i += 1; R.done += 1; R.revealed = false; renderReview();
    }));
  }
  document.addEventListener("keydown", e => {
    if (!$("#view-review").classList.contains("is-active") || e.target.matches("input,textarea")) return;
    if (e.key === " " && $("#reveal")) { e.preventDefault(); $("#reveal").click(); }
    if (e.key === "1") $('[data-r="0"]')?.click();
    if (e.key === "2") $('[data-r="1"]')?.click();
  });

  // ---------- метрики ----------
  const pct = v => (v == null ? "—" : Math.round(v * 1000) / 10 + "%");
  const num = v => (v == null ? "—" : v);
  async function renderStats() {
    const box = $("#statsBox"); box.innerHTML = `<div class="skel" style="height:90px;margin-bottom:16px"></div><div class="skel" style="height:220px"></div>`;
    const [s, h] = await Promise.all([api("/api/stats"), api("/api/health")]);
    const A = s.groups.control || {}, B = s.groups.benshu || {};
    const rows = [
      ["Пользователей", num(A.users), num(B.users)],
      ["Выбрано слов", num(A.word_selected), num(B.word_selected)],
      ["Сохранено карточек", num(A.card_saved), num(B.card_saved)],
      ["Доля сохранений (карточки / клики)", pct(A.save_rate), pct(B.save_rate)],
      ["Медиана time-to-card, с", num(A.median_time_to_card_s), num(B.median_time_to_card_s)],
      ["Точность по отзывам «Да/Нет»", "—", pct(B.feedback_accuracy)],
      ["D7 activation (≥3 текстов и ≥5 карточек за 7 дней)", pct(A.d7_activation), pct(B.d7_activation)],
    ];
    box.innerHTML = `<div class="kpis">
        <div class="kpi"><div class="v">${s.total_users}</div><div class="l">пользователей всего</div></div>
        <div class="kpi"><div class="v">${s.total_events}</div><div class="l">событий в журнале</div></div>
        <div class="kpi"><div class="v">${h.words}</div><div class="l">слов в словаре${h.cedict ? " (с CC-CEDICT)" : ""}</div></div>
        <div class="kpi"><div class="v">${h.llm_configured ? "LLM" : "офлайн"}</div><div class="l">${h.llm_configured ? "метод Benshu: LLM" : "LLM не подключена — работает метод context"}</div></div>
      </div>
      <div class="table-wrap"><table class="stats"><thead><tr><th>Метрика</th><th>A · Словарь</th><th>B · Benshu</th></tr></thead>
      <tbody>${rows.map(r => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td></tr>`).join("")}</tbody></table></div>
      <p class="stats-note">Офлайн-качество ранжирования (Recall@1, Recall@2, MRR) считается скриптом <code>evaluate.py</code> на размеченном датасете — той же функцией, что работает на сайте. Для вывода о гипотезе H2 нужна заранее рассчитанная выборка на группу; до этого цифры — только проверка того, что логирование работает.</p>`;
  }

  // ---------- старт ----------
  async function init() {
    try {
      const sess = await api("/api/session", { method: "POST", body: {} });
      state.group = sess.group; paintMode();
      state.texts = await api("/api/texts"); renderChips();
      await refreshCounts();
      if (state.texts.length) openText(state.texts[0]);
    } catch (e) {
      $("#text").innerHTML = `<p class="muted">Не удалось подключиться к API (${esc(e.message)}). Проверьте, что бэкенд запущен.</p>`;
    }
  }
  init();
})();
