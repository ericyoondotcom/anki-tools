#!/usr/bin/env python3
"""
Pull the ＊-marked vocab rows out of a class handout PDF.

    extract_starred.py --dump  FILE...                  inspect the layout
    extract_starred.py --count FILE...                  count ＊ markers
    extract_starred.py [--jp 125 --kana 250 --en 375] FILE...
    extract_starred.py --selftest

Always --dump first: the column x positions differ between handout batches.
"""

import argparse
import json
import sys
import unicodedata

HEADER_JP = {"日本語", "⽇本語"}
ROW_HEIGHT = 6
TABLE_TOP = 80
MARKER_MAX_X = 120


def group_rows(words):
    grouped = {}
    for word in words:
        grouped.setdefault(round(word["top"] / ROW_HEIGHT), []).append(word)
    for key in sorted(grouped):
        if key * ROW_HEIGHT < TABLE_TOP:
            continue
        yield key * ROW_HEIGHT, sorted(grouped[key], key=lambda w: w["x0"])


def build_entries(pages, jp_x, kana_x, en_x, src=""):
    """pages: iterable of word-dict lists, one per page. Returns starred entries."""
    entries = []
    for words in pages:
        for _, ws in group_rows(words):
            def col(lo, hi):
                return [w for w in ws if lo <= w["x0"] < hi]

            jp, kana, en = col(jp_x, kana_x), col(kana_x, en_x), col(en_x, 1e9)
            if jp and jp[0]["text"] in HEADER_JP:
                continue
            if jp:
                starred = any(
                    w["text"].startswith("＊") and w["x0"] < jp_x for w in ws
                )
                entries.append({"starred": starred, "jp": "", "kana": "", "en": []})
            if not entries:
                continue
            cur = entries[-1]
            cur["jp"] += "".join(w["text"] for w in jp)
            cur["kana"] += "".join(w["text"] for w in kana)
            cur["en"] += [w["text"] for w in en]

    out = []
    for e in entries:
        if not e["starred"]:
            continue
        out.append({
            "jp": clean(e["jp"]),
            "kana": clean(e["kana"]),
            "en": unicodedata.normalize("NFKC", " ".join(e["en"])),
            "src": src,
        })
    return out


def clean(text):
    """The inline *** slang marker can fall inside the Japanese column."""
    return unicodedata.normalize("NFKC", text).replace("＊", "").replace("*", "").strip()


def pdf_pages(path):
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            yield page.extract_words()


def dump(paths):
    for path in paths:
        print(f"##### {path}")
        for page_no, words in enumerate(pdf_pages(path), 1):
            print(f"===== page {page_no}")
            for top, ws in group_rows(words):
                cells = " | ".join(f"{w['text']}@{int(w['x0'])}" for w in ws)
                print(f"[{top}] {cells}")


def count_markers(paths):
    total = 0
    for path in paths:
        n = sum(
            1
            for words in pdf_pages(path)
            for w in words
            if w["text"].startswith("＊") and w["x0"] < MARKER_MAX_X
        )
        print(f"{n:4d}  {path}")
        total += n
    print(f"{total:4d}  TOTAL")
    return total


SELFTEST_PAGE = [
    # page number: high x, above the table — must not reach the English column
    {"text": "2", "x0": 533, "top": 36},
    {"text": "⽇本語", "x0": 138, "top": 126},
    {"text": "読み⽅", "x0": 256, "top": 126},
    # unstarred entry
    {"text": "年齢層", "x0": 138, "top": 150},
    {"text": "ねんれいそう", "x0": 256, "top": 150},
    {"text": "age", "x0": 383, "top": 150},
    {"text": "group", "x0": 405, "top": 150},
    # starred, Kangxi radical ⽣ (U+2F63), reading and gloss wrap to later rows
    {"text": "＊", "x0": 77, "top": 210},
    {"text": "⽣きがい", "x0": 138, "top": 210},
    {"text": "purpose", "x0": 383, "top": 210},
    {"text": "in", "x0": 427, "top": 210},
    {"text": "life;", "x0": 440, "top": 210},
    {"text": "いきがい", "x0": 256, "top": 216},
    {"text": "worth", "x0": 383, "top": 228},
    {"text": "living", "x0": 415, "top": 228},
    # trailing *** slang marker sits inline, NOT in the marker column
    {"text": "おっさん", "x0": 138, "top": 246},
    {"text": "***", "x0": 190, "top": 246},
    {"text": "middle-aged", "x0": 383, "top": 246},
    # starred, also carries the slang marker
    {"text": "＊", "x0": 77, "top": 264},
    {"text": "⼈柄", "x0": 138, "top": 264},
    {"text": "***", "x0": 200, "top": 264},
    {"text": "ひとがら", "x0": 256, "top": 264},
    {"text": "character", "x0": 383, "top": 264},
]


def selftest():
    got = build_entries([SELFTEST_PAGE], 125, 250, 375)
    expect = [
        {"jp": "生きがい", "kana": "いきがい",
         "en": "purpose in life; worth living", "src": ""},
        {"jp": "人柄", "kana": "ひとがら", "en": "character", "src": ""},
    ]
    checks = [
        ("two starred entries found", len(got) == 2),
        ("unstarred row skipped", all(e["jp"] != "年齢層" for e in got)),
        ("inline *** not treated as a marker", all(e["jp"] != "おっさん" for e in got)),
        ("inline *** stripped from the word", all("*" not in e["jp"] for e in got)),
        ("Kangxi radicals normalised", got and got[0]["jp"] == "生きがい"),
        ("wrapped reading stitched", got and got[0]["kana"] == "いきがい"),
        ("wrapped gloss stitched",
         got and got[0]["en"] == "purpose in life; worth living"),
        ("page number not glued onto a gloss",
         all("2" not in e["en"] for e in got)),
        ("header row dropped", all(e["jp"] not in HEADER_JP for e in got)),
    ]
    ok = True
    for label, passed in checks:
        print(f"{'pass' if passed else 'FAIL'}  {label}")
        ok &= bool(passed)
    if got != expect:
        print(f"\ngot:    {got}\nexpect: {expect}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--jp", type=float, default=125)
    ap.add_argument("--kana", type=float, default=250)
    ap.add_argument("--en", type=float, default=375)
    ap.add_argument("--json", metavar="FILE")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if selftest() else 1)
    if not args.paths:
        ap.error("need at least one PDF path")
    if args.dump:
        dump(args.paths)
        return
    if args.count:
        count_markers(args.paths)
        return

    found = []
    for path in args.paths:
        found += build_entries(pdf_pages(path), args.jp, args.kana, args.en,
                               src=path.split("/")[-1])
    for e in found:
        print(f"{e['jp']:<16} | {e['kana']:<22} | {e['en']}")
    print(f"\n{len(found)} starred entries parsed", file=sys.stderr)
    expected = count_markers(args.paths)
    if expected != len(found):
        print(f"MISMATCH: {expected} ＊ markers but {len(found)} entries parsed. "
              f"Re-run with --dump and check the column boundaries.", file=sys.stderr)
        sys.exit(1)
    if args.json:
        json.dump(found, open(args.json, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
