#!/usr/bin/env python3
"""Rebuild data/bce_industrie.csv.gz from the KBO/BCE open data full extract.

Usage: python build_population.py KboOpenData_XXXX_Full.zip [output.csv.gz]

Keeps: registered office in postcodes 1000-1499 or 4000-7999, active status,
legal person (TypeOfEnterprise = 2), and at least one NACE-BEL code in
divisions 05-09, 10-33, 35, 36-39 or 49-53 (sections B, C, D, E, H).
NACE-BEL 2025 codes are used when present, otherwise the 2008 ones.
"""

import csv
import gzip
import io
import sys
import zipfile
from collections import defaultdict

DIVISIONS = {f"{d:02d}" for d in [*range(5, 10), *range(10, 34), 35, *range(36, 40), *range(49, 54)]}


def rows(zf, name):
    member = next(n for n in zf.namelist() if n.lower().endswith(name))
    with zf.open(member) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))


def in_zone(zipcode):
    try:
        z = int(zipcode)
    except (TypeError, ValueError):
        return False
    return 1000 <= z <= 1499 or 4000 <= z <= 7999


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
            addr[n] = (r["Zipcode"], r["MunicipalityFR"] or r["MunicipalityNL"])
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
        hits = [c for _, c in codes if c[:2] in DIVISIONS]
        if not hits:
            continue
        main_codes = [c for cl, c in codes if cl == "MAIN"]
        principal = next((c for c in main_codes if c[:2] in DIVISIONS), main_codes[0] if main_codes else hits[0])
        division = principal[:2] if principal[:2] in DIVISIONS else hits[0][:2]
        all_codes = sorted(set(c for _, c in codes))
        keep[n] = (principal, ",".join(all_codes), division)
    print(f"industrial: {len(keep)}", file=sys.stderr)

    names = {}
    rank = {"1": 0, "0": 1, "2": 2, "3": 3, "4": 4}  # prefer French
    for r in rows(zf, "denomination.csv"):
        n = r["EntityNumber"]
        if n in keep and r["TypeOfDenomination"] == "001":
            k = rank.get(r["Language"], 9)
            if n not in names or k < names[n][0]:
                names[n] = (k, r["Denomination"])

    with gzip.open(dst, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(["numero_bce", "nom", "code_postal", "commune", "nace_principal",
                    "tous_les_nace", "division", "forme", "creation"])
        for n in sorted(keep):
            principal, all_codes, division = keep[n]
            e = ent[n]
            w.writerow([n.replace(".", ""), names.get(n, (0, ""))[1], *addr[n],
                        principal, all_codes, division, e["JuridicalForm"], e["StartDate"]])
    print(f"wrote {len(keep)} rows to {dst}", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(*sys.argv[1:])
