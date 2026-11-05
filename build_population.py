#!/usr/bin/env python3
"""Rebuild data/bce_industrie.csv.gz from the KBO/BCE open data full extract.

Usage: python build_population.py KboOpenData_XXXX_Full.zip [output.csv.gz]

Keeps: registered office in the ZONES postcode ranges (default 1000-1499 and 4000-7999), active status,
legal person (TypeOfEnterprise = 2), and at least one NACE-BEL code in
divisions 05-09, 10-33, 35, 36-39 or 49-53 (sections B, C, D, E, H).
NACE-BEL 2025 codes are used when present, otherwise the 2008 ones.
"""

import csv
import gzip
import io
import os
import sys
import zipfile
from collections import defaultdict

DIVISIONS = {f"{d:02d}" for d in [*range(5, 10), *range(10, 34), 35, *range(36, 40), *range(49, 54)]}
# Optional extra divisions (e.g. 43,46,47: makers declared as builders or traders), kept but flagged.
EXTRA = {d.strip().zfill(2) for d in os.environ.get("EXTRA_DIVISIONS", "").split(",") if d.strip()}
# Mission 4: a list of NACE classes (e.g. "01.63,96.01") replaces the sections B/C/D/E/H test.
CLASSES = {c.replace(".", "").strip() for c in os.environ.get("CLASSES", "").split(",") if c.strip()}
# The same classes in NACE-BEL 2008 numbering, for companies whose latest codes are still 2008 ones.
CLASSES_2008 = {c.replace(".", "").strip() for c in os.environ.get("CLASSES_2008", "").split(",") if c.strip()}
NACE_DUMP = os.environ.get("NACE_DUMP", "")  # optional: write every NACE class label (2025 and 2008) here
# Postcode ranges, default = first pass (Brussels + Wallonia).
ZONES = [tuple(map(int, z.split("-"))) for z in os.environ.get("ZONES", "1000-1499,4000-7999").split(",")]
# Preferred denomination language: KBO codes 1 = FR, 2 = NL, 3 = DE.
LANG_FIRST = os.environ.get("NAME_LANG", "fr")


def rows(zf, name):
    member = next(n for n in zf.namelist() if n.lower().endswith(name))
    with zf.open(member) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))


def in_zone(zipcode):
    try:
        z = int(zipcode)
    except (TypeError, ValueError):
        return False
    return any(lo <= z <= hi for lo, hi in ZONES)


def flemish(zipcode):
    z = int(zipcode)
    return 1500 <= z <= 3999 or 8000 <= z <= 9999


def main(src, dst="data/bce_industrie.csv.gz"):
    zf = zipfile.ZipFile(src)

    ent = {}
    for r in rows(zf, "enterprise.csv"):
        if r["Status"] == "AC" and r["TypeOfEnterprise"] == "2":
            ent[r["EnterpriseNumber"]] = r
    print(f"active legal persons: {len(ent)}", file=sys.stderr)

    addr = {}
    for r in rows(zf, "address.csv"):
        n = r["EntityNumber"]
        if n in ent and r["TypeOfAddress"] == "REGO" and in_zone(r["Zipcode"]):
            nl_first = LANG_FIRST == "nl" or (LANG_FIRST == "auto" and flemish(r["Zipcode"]))
            addr[n] = (r["Zipcode"], (r["MunicipalityNL"] or r["MunicipalityFR"]) if nl_first
                       else (r["MunicipalityFR"] or r["MunicipalityNL"]))
    print(f"in zone: {len(addr)}", file=sys.stderr)

    acts = defaultdict(lambda: defaultdict(list))  # entity -> version -> [(classif, code)]
    for r in rows(zf, "activity.csv"):
        n = r["EntityNumber"]
        if n in addr:
            acts[n][r["NaceVersion"]].append((r["Classification"], r["NaceCode"]))

    keep = {}
    for n, versions in acts.items():
        ver = max(versions)  # most recent NACE version available for this entity
        codes = versions[ver]
        if CLASSES:
            wanted = CLASSES_2008 if ver == "2008" else CLASSES
            hits = [c for _, c in codes if c.replace(".", "")[:4] in wanted]
            extra = []
        else:
            hits = [c for _, c in codes if c[:2] in DIVISIONS]
            extra = [c for _, c in codes if c[:2] in EXTRA]
        if not hits and not extra:
            continue
        pool = hits or extra
        main_codes = [c for cl, c in codes if cl == "MAIN"]
        if CLASSES:
            principal = next((c for c in main_codes if c in hits), hits[0])
            classes = ",".join(sorted({c.replace(".", "")[:4] + ("/2008" if ver == "2008" else "") for c in hits}))
            keep[n] = (principal, ",".join(sorted(set(c for _, c in codes))), principal[:2], classes)
            continue
        principal = next((c for c in main_codes if c[:2] in DIVISIONS),
                         next((c for c in main_codes if c[:2] in EXTRA), main_codes[0] if main_codes else pool[0]))
        division = principal[:2] if principal[:2] in DIVISIONS | EXTRA else pool[0][:2]
        all_codes = sorted(set(c for _, c in codes))
        keep[n] = (principal, ",".join(all_codes), division, "non" if hits else "oui")
    print(f"industrial: {len(keep)}", file=sys.stderr)

    names = {}
    rank_nl = {"2": 0, "0": 1, "1": 2, "3": 3, "4": 4}
    rank_fr = {"1": 0, "0": 1, "2": 2, "3": 3, "4": 4}
    for r in rows(zf, "denomination.csv"):
        n = r["EntityNumber"]
        if n in keep and r["TypeOfDenomination"] == "001":
            nl = LANG_FIRST == "nl" or (LANG_FIRST == "auto" and flemish(addr[n][0]))
            k = (rank_nl if nl else rank_fr).get(r["Language"], 9)
            if n not in names or k < names[n][0]:
                names[n] = (k, r["Denomination"])

    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with gzip.open(dst, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(["numero_bce", "nom", "code_postal", "commune", "nace_principal",
                    "tous_les_nace", "division", "forme", "creation",
                    "classes" if CLASSES else "hors_sections_industrielles"])
        for n in sorted(keep):
            principal, all_codes, division, hors = keep[n]
            e = ent[n]
            w.writerow([n.replace(".", ""), names.get(n, (0, ""))[1], *addr[n],
                        principal, all_codes, division, e["JuridicalForm"], e["StartDate"], hors])
    print(f"wrote {len(keep)} rows to {dst}", file=sys.stderr)
    if CLASSES:
        write_class_labels(zf, keep, dst)


def write_class_labels(zf, keep, dst):
    """Official FR labels of each target class (NACE-BEL 2025 and 2008) and how many companies matched."""
    labels = defaultdict(dict)
    every = []
    for r in rows(zf, "code.csv"):
        cat, code = r["Category"], r["Code"].replace(".", "")
        if cat in ("Nace2025", "Nace2008") and r["Language"] == "FR":
            labels[code][cat] = r["Description"]
            if len(code) == 4:
                every.append((cat, f"{code[:2]}.{code[2:]}", r["Description"]))
    if NACE_DUMP:
        with open(NACE_DUMP, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";", lineterminator="\n")
            w.writerow(["version", "classe", "libelle"])
            w.writerows(sorted(every))
    count = defaultdict(int)
    for v in keep.values():
        for c in v[3].split(","):
            count[c] += 1
    out = dst.replace(".csv.gz", "_classes.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(["classe", "version", "libelle_officiel", "societes"])
        for ver, cat, wanted, suffix in (("2025", "Nace2025", CLASSES, ""), ("2008", "Nace2008", CLASSES_2008, "/2008")):
            for c in sorted(wanted):
                w.writerow([f"{c[:2]}.{c[2:]}", ver, labels[c].get(cat, "ABSENT"), count[c + suffix]])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(*sys.argv[1:])
