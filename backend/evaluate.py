"""Офлайн-оценка ранжировщиков (гипотеза H3).

Использует ТУ ЖЕ функцию rank(), что и сайт, поэтому метрики совпадают с продуктом.

    python evaluate.py                                # демо-датасет, все методы
    python evaluate.py --data data/my_test.csv        # свой размеченный датасет
    python evaluate.py --methods first_sense context  # без LLM

Формат CSV: id,sentence,word,gold_sense_id[,note]
Метрики: Recall@1 (= accuracy топ-1), Recall@2 (верное значение в топ-2), MRR, p95 latency.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path

from app.core.dictionary import get_dictionary
from app.core.rankers import rank


def bootstrap_ci(values: list[float], n: int = 2000, seed: int = 42) -> tuple[float, float]:
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choice(values) for _ in values) / len(values) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def evaluate(rows: list[dict], method: str) -> dict:
    d = get_dictionary()
    hits1, hits2, rr, lat, errors, fallbacks = [], [], [], [], [], 0
    for r in rows:
        entry = d.get(r["word"])
        if entry is None:
            errors.append({**r, "error": "нет в словаре"})
            continue
        res = rank(r["sentence"], r["word"], entry, method=method)
        ids = [s.id for s in res.ranked]
        pos = ids.index(r["gold_sense_id"]) + 1 if r["gold_sense_id"] in ids else math.inf
        hits1.append(1.0 if pos == 1 else 0.0)
        hits2.append(1.0 if pos <= 2 else 0.0)
        rr.append(0.0 if pos == math.inf else 1 / pos)
        lat.append(res.latency_ms)
        fallbacks += 1 if res.fallback_reason else 0
        if pos != 1:
            errors.append({"id": r["id"], "sentence": r["sentence"], "word": r["word"],
                           "gold": r["gold_sense_id"], "pred": ids[0]})
    n = len(hits1)
    lo, hi = bootstrap_ci(hits1)
    return {
        "method": method, "n": n,
        "recall@1": round(sum(hits1) / n, 3), "recall@1_ci95": [round(lo, 3), round(hi, 3)],
        "recall@2": round(sum(hits2) / n, 3), "mrr": round(sum(rr) / n, 3),
        "latency_p95_ms": round(sorted(lat)[max(0, int(0.95 * n) - 1)], 1),
        "fallbacks": fallbacks, "errors": errors,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/wsd_eval_demo.csv")
    ap.add_argument("--methods", nargs="+", default=["first_sense", "context", "llm"])
    ap.add_argument("--out", default="data/eval_results.json")
    args = ap.parse_args()

    rows = list(csv.DictReader(Path(args.data).open(encoding="utf-8")))
    # Считаем только многозначные слова — для однозначных задача тривиальна
    d = get_dictionary()
    rows = [r for r in rows if d.get(r["word"]) and d.get(r["word"]).is_polysemous]

    results = [evaluate(rows, m) for m in args.methods]
    print(f"\nДатасет: {args.data} | примеров (многозначные слова): {len(rows)}\n")
    print(f"{'метод':<13}{'Recall@1':>10}{'95% ДИ':>16}{'Recall@2':>10}{'MRR':>8}{'p95, мс':>10}{'откаты':>8}")
    for r in results:
        ci = f"[{r['recall@1_ci95'][0]:.2f}; {r['recall@1_ci95'][1]:.2f}]"
        print(f"{r['method']:<13}{r['recall@1']:>10.3f}{ci:>16}{r['recall@2']:>10.3f}{r['mrr']:>8.3f}"
              f"{r['latency_p95_ms']:>10.1f}{r['fallbacks']:>8}")
    for r in results:
        if r["errors"]:
            print(f"\nОшибки метода {r['method']} ({len(r['errors'])}):")
            for e in r["errors"][:12]:
                print(f"  #{e.get('id')} {e.get('sentence')}  [{e.get('word')}] gold={e.get('gold')} pred={e.get('pred', e.get('error'))}")
    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nПолные результаты: {args.out}")


if __name__ == "__main__":
    main()
