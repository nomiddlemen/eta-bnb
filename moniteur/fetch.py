#!/usr/bin/env python3
"""Collect Moniteur belge publications and KBO functions for the mission 2 targets.

For every company number in moniteur/cibles_moniteur.csv (plus the two control cases):
  data/<bce>/list.json   every publication: date, ref, act type, PDF url
  data/<bce>/kbo.json    KBO public search: name, legal form, start date, functions
  data/<bce>/ocr/<date>_<ref>.txt   OCR of every act except annual-account filings
Legal-person directors (KBO numbers found in functions or in administrateurs_bnb) get
their own list.json and kbo.json, without OCR, so control can be traced one level up.

Resumable: anything already on disk is skipped. Sequential HTTP with a pause, OCR in
parallel. Stops cleanly after TIME_BUDGET minutes.
"""

import csv
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DATA = "moniteur/data"
EJ = "https://www.ejustice.just.fgov.be"
KBO = "https://kbopub.economie.fgov.be/kbopub/zoeknummerform.html?nummer={}&actionLu=Rechercher&lang=fr"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) eta-bnb research (contact via GitHub)"}
PAUSE = float(os.environ.get("PAUSE", "0.7"))
BUDGET = float(os.environ.get("TIME_BUDGET", "300")) * 60
OCR_WORKERS = int(os.environ.get("OCR_WORKERS", "4"))
SHARD, NSHARDS = int(os.environ.get("SHARD", "0")), int(os.environ.get("NSHARDS", "1"))
GERMAN = ("sankt vith", "eupen", "büllingen", "amel", "bütgenbach", "burg-reuland", "kelmis", "lontzen", "raeren")
WATERMARK = re.compile(r"(Bijlagen bij het Belgisch Staatsblad|Annexes du Moniteur belge|Anlagen zum Belgischen Staatsblatt)[^\n]*")
CONTROL = ["0447639261", "0408287450"]
T0 = time.monotonic()


def out_of_time():
    return time.monotonic() - T0 > BUDGET


def fetch(url, binary=False, tries=4):
    for i in range(tries):
        time.sleep(PAUSE)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                body = r.read()
                return body if binary else body.decode(r.headers.get_content_charset() or "latin-1", "replace")
        except Exception as e:
            print(f"  retry {i + 1} {url}: {e}", flush=True)
            time.sleep(5 * 2 ** i)
    return None


def text_lines(fragment):
    fragment = re.sub(r"<script.*?</script>|<style.*?</style>", "", fragment, flags=re.S | re.I)
    txt = html.unescape(re.sub(r"<[^>]+>", "\n", fragment)).replace("\xa0", " ")
    return [re.sub(r"\s+", " ", l).strip() for l in txt.split("\n") if l.strip()]


# ------------------------------------------------------------------ Moniteur list

def parse_list(page):
    items = []
    for block in re.split(r'<div class="list-item">', page)[1:]:
        sub = re.search(r'list-item--subtitle">(.*?)</p>', block, re.S)
        title = re.search(r'list-item--title">(.*?)</a>\s*</div>', block, re.S)
        pdf = re.search(r'href="(/tsv_pdf/[^"]+\.pdf)"', block)
        lines = text_lines(title.group(1)) if title else []
        dref = next((l for l in lines if re.match(r"\d{4}-\d{2}-\d{2} / \S+", l)), "")
        m = re.match(r"(\d{4}-\d{2}-\d{2}) / (\S+)", dref)
        idx = lines.index(dref) if dref in lines else len(lines)
        items.append({
            "nom": " ".join(text_lines(sub.group(1))) if sub else "",
            "date": m.group(1) if m else "",
            "ref": m.group(2) if m else "",
            "type": lines[idx - 1] if idx >= 1 else "",
            "adresse": lines[0] if lines else "",
            "pdf": EJ + pdf.group(1) if pdf else "",
        })
    return items


def get_list(bce):
    num = bce.lstrip("0")
    first = fetch(f"{EJ}/cgi_tsv/list.pl?language=fr&btw={bce}&liste=Liste")
    if first is None:
        return None
    total = re.search(r"Liste \((\d+)\)", first)
    pages = [int(p) for p in re.findall(r"page=(\d+)&btw=", first)] or [1]
    items = parse_list(first)
    for p in range(2, max(pages) + 1):
        page = fetch(f"{EJ}/cgi_tsv/list.pl?language=fr&sum_date=&page={p}&btw={num}")
        if page:
            items += parse_list(page)
    return {"bce": bce, "total_annonce": int(total.group(1)) if total else None, "items": items}


# ------------------------------------------------------------------ KBO page

def get_kbo(bce):
    page = fetch(KBO.format(bce))
    if page is None:
        return None
    lines = text_lines(page)

    def after(label):
        for i, l in enumerate(lines):
            if l.rstrip(":") == label and i + 1 < len(lines):
                return lines[i + 1]
        return ""

    funcs = []
    if "Fonctions" in lines:
        i = lines.index("Fonctions") + 1
        cur = {}
        while i < len(lines) and not lines[i].startswith(("Capacités", "Qualités", "Autorisations")):
            l = lines[i]
            if l.startswith("Depuis le"):
                cur["depuis"] = l[len("Depuis le"):].strip()
                funcs.append(cur)
                cur = {}
            elif not cur.get("role"):
                cur["role"] = l
            elif re.fullmatch(r"\(?\d{4}\.\d{3}\.\d{3}\)?", l):
                key = "pour" if l.startswith("(") else "qui"
                cur[key] = l.strip("()").replace(".", "")
            else:
                cur["qui"] = (cur.get("qui", "") + " " + l).strip()
            i += 1
    return {
        "bce": bce,
        "denomination": after("Dénomination"),
        "forme": after("Forme légale"),
        "statut": after("Statut"),
        "situation": after("Situation juridique"),
        "debut": after("Date de début"),
        "fonctions": funcs,
        "texte": lines[:400],
    }


# ------------------------------------------------------------------ OCR

def real_text(txt):
    """Text layer minus the margin watermark that even scanned PDFs carry."""
    return re.sub(r"\s+", " ", WATERMARK.sub("", txt)).strip()


def ocr_pdf(pdf_bytes, langs="fra+nld"):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.pdf")
        with open(p, "wb") as f:
            f.write(pdf_bytes)
        txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout
        if len(real_text(txt)) > 400:
            return "[texte PDF]\n" + txt
        subprocess.run(["pdftoppm", "-r", "250", "-gray", "-png", p, os.path.join(d, "pg")], check=False)
        out = []
        for img in sorted(f for f in os.listdir(d) if f.startswith("pg")):
            r = subprocess.run(["tesseract", os.path.join(d, img), "-", "-l", langs, "--psm", "4"],
                               capture_output=True, text=True, env={**os.environ, "OMP_THREAD_LIMIT": "1"})
            out.append(r.stdout)
        return "[OCR]\n" + "\n\f\n".join(out)


def is_accounts(item):
    t = item["type"].upper()
    return t.startswith("ME.") or "JAARREKENING" in t or "COMPTES ANNUELS" in t or "JAHRESABSCHLUSS" in t


# ------------------------------------------------------------------ driver

def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def is_constitution(item):
    return re.search(r"CONSTITUTION|OPRICHTING|GRÜNDUNG|NOUVELLE PERSONNE MORALE|NIEUWE RECHTSPERSOON", item["type"].upper())


def collect(bce, with_ocr, pool, pending, langs="fra+nld", only_constitution=False):
    d = os.path.join(DATA, bce)
    lp, kp = os.path.join(d, "list.json"), os.path.join(d, "kbo.json")
    if not os.path.exists(lp):
        lst = get_list(bce)
        if lst is not None:
            save(lp, lst)
    if not os.path.exists(kp):
        k = get_kbo(bce)
        if k is not None:
            save(kp, k)
    if not (with_ocr or only_constitution) or not os.path.exists(lp):
        return
    lst = json.load(open(lp, encoding="utf-8"))
    for it in lst["items"]:
        if out_of_time():
            return
        if not it["pdf"] or is_accounts(it) or (only_constitution and not is_constitution(it)):
            continue
        tp = os.path.join(d, "ocr", f"{it['date']}_{it['ref']}.txt")
        if os.path.exists(tp):
            body = open(tp, encoding="utf-8").read()
            if not (body.split("\n", 3)[2:3] == ["[texte PDF]"] and len(real_text(body.split("\n", 3)[3])) <= 400):
                continue
            os.remove(tp)  # watermark-only text layer from an earlier run: redo with OCR
        pdf = fetch(it["pdf"], binary=True)
        if not pdf or not pdf.startswith(b"%PDF"):
            continue

        def job(pdf=pdf, tp=tp, it=it):
            txt = ocr_pdf(pdf, langs)
            os.makedirs(os.path.dirname(tp), exist_ok=True)
            with open(tp, "w", encoding="utf-8") as f:
                f.write(f"# {it['date']} {it['ref']} {it['type']}\n# {it['pdf']}\n{txt}")
        pending.append(pool.submit(job))


def main():
    rows = list(csv.DictReader(open("moniteur/cibles_moniteur.csv", encoding="utf-8"), delimiter=";"))
    targets = CONTROL + [r["bce"] for r in rows]
    langs = {r["bce"]: "fra+nld+deu" if r["commune"].lower() in GERMAN else "fra+nld" for r in rows}
    bnb_corporate = set()
    for r in csv.DictReader(open("moniteur/cibles_moniteur.csv", encoding="utf-8"), delimiter=";"):
        bnb_corporate |= {n.replace(".", "") for n in re.findall(r"\((\d{4}\.?\d{3}\.?\d{3})\)", r["administrateurs_bnb"])}
    only = sys.argv[1:]
    if only:
        targets = [t for t in targets if t in only] or only
    targets = targets[SHARD::NSHARDS]
    pending = []
    with ThreadPoolExecutor(OCR_WORKERS) as pool:
        for n, bce in enumerate(targets, 1):
            if out_of_time():
                break
            print(f"[{(time.monotonic() - T0) / 60:5.1f} min] {n}/{len(targets)} {bce}", flush=True)
            collect(bce, True, pool, pending, langs.get(bce, "fra+nld"))
        # one level up: legal-person directors
        corporate = set(bnb_corporate)
        for bce in targets:
            kp = os.path.join(DATA, bce, "kbo.json")
            if os.path.exists(kp):
                for f in json.load(open(kp, encoding="utf-8"))["fonctions"]:
                    q = f.get("qui", "")
                    if re.fullmatch(r"\d{10}", q.zfill(10)) and q.isdigit():
                        corporate.add(q.zfill(10))
        corporate -= set(targets)
        if SHARD:
            corporate = set()  # shard 0 handles the legal-person directors
        print(f"{len(corporate)} administrateurs personnes morales à remonter", flush=True)
        for bce in sorted(corporate):
            if out_of_time():
                break
            # constitution deeds of directors' own companies give the founders' birth dates
            collect(bce.zfill(10), False, pool, pending, only_constitution=True)
        for f in pending:
            f.result()
    n_ocr = sum(len(os.listdir(os.path.join(DATA, b, "ocr"))) for b in os.listdir(DATA)
                if os.path.isdir(os.path.join(DATA, b, "ocr")))
    print(f"terminé en {(time.monotonic() - T0) / 60:.0f} min ; {n_ocr} actes OCR", flush=True)


if __name__ == "__main__":
    main()
