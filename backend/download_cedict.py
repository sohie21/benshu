"""Скачивает CC-CEDICT (CC BY-SA 4.0) в backend/data/cedict_ts.u8.

Используется как резервный словарь для слов, которых нет в русском мини-словаре
(значения на английском). Обязательна атрибуция на сайте — она уже есть в футере.
    python scripts/download_cedict.py
"""
import gzip
import io
import urllib.request
import zipfile
from pathlib import Path

URL = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip"
OUT = Path(__file__).resolve().parents[1] / "data" / "cedict_ts.u8"

def main() -> None:
    print("Скачиваю", URL)
    data = urllib.request.urlopen(URL, timeout=60).read()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = next(n for n in z.namelist() if n.endswith(".u8"))
            OUT.write_bytes(z.read(name))
    except zipfile.BadZipFile:
        OUT.write_bytes(gzip.decompress(data))
    print("Готово:", OUT, f"{OUT.stat().st_size / 1e6:.1f} МБ")

if __name__ == "__main__":
    main()
