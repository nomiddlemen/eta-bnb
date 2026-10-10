#!/usr/bin/env python3
"""Turn moniteur/brouillon.json into the mission 2 deliverables: moniteur.csv and rapport.md."""

import csv
import json
from collections import Counter

LIST = "https://www.ejustice.just.fgov.be/cgi_tsv/list.pl?language=fr&btw={}&liste=Liste"
COLS = ["bce", "nom", "premiere_nomination", "anciennete_ans", "dirigeant_principal", "releve",
        "derniere_modification_statuts", "actionnaires", "type_controle", "societe_mere", "verdict", "sources"]


def main():
    draft = json.load(open("moniteur/brouillon.json", encoding="utf-8"))
    controls = {"0447639261", "0408287450"}
    rows = []
    for r in draft:
        if r["bce"] in controls:
            continue
        corp = [s for s in r["_signaux"] if s.startswith(("administrateur personne morale", "administrateur étranger",
                                                          "administrateur inscrit", "intercommunale", "ALERTE"))]
        evidence = "; ".join(corp)
        actionnaires = ("aucune détention publiée au Moniteur" + (f" — indices par les mandats : {evidence}" if evidence else ""))
        ctrl = r["type_controle"]
        if ctrl in ("famille", "personne physique", "holding patrimonial"):
            ctrl += " (présumé, d'après les mandats)"
        rows.append({**{k: r.get(k, "") for k in COLS}, "actionnaires": actionnaires, "type_controle": ctrl,
                     "sources": f"liste des actes : {LIST.format(r['bce'])} | " + r["sources"]})
    with open("moniteur/moniteur.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS, delimiter=";", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    v = Counter(r["verdict"].split(" (")[0] for r in rows)
    why = Counter(x.strip() for r in rows if r["verdict"].startswith("A VERIFIER")
                  for x in r["verdict"][len("A VERIFIER ("):-1].split(",") if r["verdict"] != "A VERIFIER")
    print(v)
    print(why.most_common())
    json.dump({"verdicts": v, "a_verifier_motifs": why.most_common(), "n": len(rows),
               "avec_age": sum(1 for r in rows if "(né" in r["dirigeant_principal"]),
               "borne": sum(1 for r in rows if r["premiere_nomination"].startswith("≤"))},
              open("moniteur/stats.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
