#!/usr/bin/env python3
"""Draft mission 2 analysis from the collected Moniteur/KBO data.

For each target it derives, with sources:
  current directors (KBO public search, BNB filing as fallback), the main one,
  the first act naming each of them (and their family name), birth date when an
  act gives it (national register number or "né le"), new directors since 2018,
  last articles-of-association change, and control signals (legal-person
  directors, foreign entities, public investors, industrial groups).
Writes moniteur/brouillon.json and a readable moniteur/dossiers.md for review.
"""

import csv
import json
import os
import re
import unicodedata
from datetime import date

DATA = "moniteur/data"
TODAY = date(2026, 10, 10)
MONTHS = {m: i + 1 for i, m in enumerate(
    "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split())}
MONTHS.update({m: i + 1 for i, m in enumerate(
    "januari februari maart april mei juni juli augustus september oktober november december".split())})

PUBLIC_INVEST = ["OSTBELGIENINVEST", "BETEILIGUNGSGESELLSCHAFT OSTBELGIENS", "SRIW", "WALLONIE ENTREPRENDRE", "SOWALFIN", "SOGEPA", "NOSHAQ",
                 "MEUSINVEST", "SAMBRINVEST", "IMBC", "INVEST MONS BORINAGE", "SOCAMUT", "SOFINEX",
                 "FINANCE.BRUSSELS", "FINANCE&INVEST", "SRIB", "SFPI", "FPIM", "INVESTSUD", "NAMUR INVEST",
                 "INVEST DEVELOPPEMENT", "LUXEMBOURG DEVELOPPEMENT", "IDELUX", "SOFIPOLE", "W.ALTER",
                 "WALLONIE DEVELOPPEMENT", "CAPITAL B", "SPI", "IGRETEC", "TIBI", "HYGEA", "IPALLE"]
INDUSTRIAL = ["VEOLIA", "SUEZ", "RENEWI", "HOLCIM", "HEIDELBERG", "CRH", "SAINT-GOBAIN", "ENGIE"]
FUND_WORDS = ["CAPITAL PARTNERS", " PARTNERS", " FUND", "PRIVATE EQUITY", "INVESTMENT", " VENTURES",
              "GIMV", "SOFINA", "AHEAD", "BELFIUS", "BNP PARIBAS FORTIS PRIVATE EQUITY", "KBC PRIVATE EQUITY"]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9 ]+", " ", s.upper())


def load(path, default=None):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else default


def acts(bce, company=""):
    d = os.path.join(DATA, bce, "ocr")
    out = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            body = open(os.path.join(d, f), encoding="utf-8").read()
            head = body.split("\n", 2)
            out.append({"date": f[:10], "ref": f[11:-4], "type": head[0][2:].split(" ", 2)[-1],
                        "url": head[1][2:] if len(head) > 1 else "", "text": body,
                        "norm": norm(body).replace(norm(company).strip(), " ") if norm(company).strip() else norm(body)})
    return out


JUNK = re.compile(r"Montrez les titulaires.*?Masquez les titulaires de fonctions\s*\.?\s*(?:\w+(?: \w+)*?\s)?|\(\d+\)")


def clean_kbo_name(q):
    q = re.sub(r"^.*Masquez les titulaires de fonctions\s*\.\s*(Administrateur délégué|Administrateur|Gérant|Président|"
               r"Représentant permanent|Personne déléguée à la gestion journalière)?\s*", "", q)
    return re.sub(r"\s*\(\d+\)", "", q).strip()


def person_from_kbo(q):
    q = clean_kbo_name(q)
    if "," in q:
        last, first = [x.strip() for x in q.split(",", 1)]
        return {"nom": last, "prenom": first}
    return None


def first_pat(first):
    fn = [t for t in norm(first).split() if len(t) > 1]
    if not fn:
        return None
    f = fn[0]
    # tolerate one OCR slip at the end (Erna/Ema) but demand the whole word otherwise
    return r"\b" + re.escape(f[:max(3, len(f) - 1)]) + r"[A-Z]{0,2}\b"


def full_hits(text_norm, last, first):
    L = norm(last).split()
    fp = first_pat(first)
    if not L or not fp:
        return []
    pat = r"\b" + r"\s+".join(map(re.escape, L)) + r"\b"
    out = []
    for m in re.finditer(pat, text_norm):
        window = text_norm[max(0, m.start() - 30):m.end() + 30]
        if re.search(fp, window):
            out.append(m.start())
    return out


NUM = re.compile(r"\b0?(\d{3}) (\d{3}) (\d{3})\b")


def own_notice(act, pos, bce):
    """On pre-2003 pages several companies share a page: keep a hit only if the
    nearest company number around it is ours (or if there is none to compare)."""
    if act["date"] >= "2003" or not bce:
        return True
    n = act["norm"]
    near = [(abs(m.start() - pos), "".join(m.groups())) for m in NUM.finditer(n[max(0, pos - 400):pos + 400])]
    if not near:
        return True
    return min(near)[1] == bce[-9:]


def mentions(act, last, first, bce=""):
    n = act["norm"]
    L = norm(last).split()
    if not L:
        return False, False
    fam = re.search(r"\b" + r"\s+".join(map(re.escape, L)) + r"\b", n) is not None
    hits = [h for h in full_hits(n, last, first) if own_notice(act, h, bce)] if fam else []
    return fam, bool(hits)


def birth(acts_list, last, first):
    """Birth date from a national register number or 'né le' next to the name."""
    for a in acts_list:
        t = norm(a["text"].split("\n", 2)[-1])
        for h in full_hits(t, last, first):
            win = t[h:h + 160]
            rn = re.search(r"\b(\d{2})\s?([01]\d)\s?([0-3]\d)\s?\d{3}\s?\d{2}\b", win)
            if rn:
                yy, mm, dd = map(int, rn.groups())
                if 1 <= mm <= 12 and 1 <= dd <= 31:
                    year = 1900 + yy if yy > 26 else 2000 + yy
                    if year < 2008:
                        return year, f"n° registre national {rn.group(0)} ({a['date']} {a['ref']})"
            ne = re.search(r"\b(?:NE|NEE|GEBOREN)\s+(?:(?:A|TE)\s+[A-Z' -]{2,30}?\s+)?(?:LE|OP)\s+"
                           r"(\d{1,2})\s*(?:ER)?\s+([A-Z]+)\s+(\d{4})", win)
            if ne and ne.group(2).lower() in {norm(k).lower() for k in MONTHS} and 1920 < int(ne.group(3)) < 2008:
                return int(ne.group(3)), f"« {ne.group(0)} » ({a['date']} {a['ref']})"
    return None, ""


def kbo_since(s):
    m = re.match(r"(\d{1,2}) (\w+) (\d{4})", s or "")
    return int(m.group(3)) if m else None


def analyse(row):
    bce = row["bce"]
    kbo = load(os.path.join(DATA, bce, "kbo.json"), {})
    lst = load(os.path.join(DATA, bce, "list.json"), {"items": []})
    A = acts(bce, row["nom"])
    srcs = []
    funcs = []
    for f in kbo.get("fonctions", []):
        f = dict(f)
        if f.get("role", "").startswith(("Il y a", "Montrez", "Masquez")):
            # collapsed list on the KBO page: the real role and name are at the end of 'qui'
            if f.get("qui", "").isdigit():
                f["role"] = "Administrateur"
                funcs.append(f)
                continue
            rest = re.sub(r"^.*Masquez les titulaires de fonctions\s*\.\s*", "", f.get("qui", ""))
            m = re.match(r"((?:Administrateur|Gérant|Président|Représentant permanent|Personne déléguée|Délégué|"
                         r"Membre|Liquidateur|Commissaire|Associé)[^,\d]*?)\s+(\d{10}|\S[^,]*,.*)$", rest)
            if not m:
                continue
            f["role"], f["qui"] = m.group(1), m.group(2)
        funcs.append(f)
    kbo_url = f"https://kbopub.economie.fgov.be/kbopub/zoeknummerform.html?nummer={bce}&actionLu=Rechercher"

    # current people: natural persons directly, or permanent representatives of legal persons
    people, corporate = {}, {}
    for f in funcs:
        q = f.get("qui", "")
        if q.isdigit():
            corporate.setdefault(q.zfill(10), {"roles": set(), "depuis": f.get("depuis")})["roles"].add(f["role"])
            continue
        p = person_from_kbo(q)
        if not p:
            continue
        key = (norm(p["nom"]), norm(p["prenom"]).split()[0] if p["prenom"] else "")
        e = people.setdefault(key, {**p, "roles": set(), "depuis_kbo": [], "pour": set()})
        e["roles"].add(f["role"])
        e["depuis_kbo"].append(f.get("depuis"))
        if f.get("pour"):
            e["pour"].add(f["pour"].zfill(10))
    if not people and row["administrateurs_bnb"]:
        for part in row["administrateurs_bnb"].split("|"):
            part = part.strip()
            m = re.match(r"([^(\[]+?)\s*(?:\((\S+)\))?\s*(?:repr\.\s*([^\[]+))?\s*(?:\[([^\]]+)\])?\s*(?:depuis|jusqu|$)", part)
            if not m:
                continue
            name, num, rep, role = m.groups()
            if num:
                corporate.setdefault(re.sub(r"\D", "", num).zfill(10), {"roles": {role or "?"}, "depuis": None})
            target = (rep or ("" if num else name)).strip()
            if target:
                toks = target.split()
                last = " ".join(t for t in toks if t.isupper() and len(t) > 1) or toks[0]
                first = " ".join(t for t in toks if t not in last.split())
                e = people.setdefault((norm(last), norm(first)[:3]), {"nom": last, "prenom": first, "roles": set(),
                                                                       "depuis_kbo": [], "pour": set()})
                e["roles"].add(role or "?")
        srcs.append("dirigeants : dépôt BNB (fiche BCE sans fonctions)")

    # first act naming each person, family first appearance, birth year
    oldest_pdf = min((a["date"] for a in A), default=None)
    older_without_pdf = any(not i["pdf"] and i["date"] and (oldest_pdf is None or i["date"] < oldest_pdf)
                            and not i["type"].upper().startswith(("ME.", "COMPTES"))
                            for i in lst["items"])
    for e in people.values():
        e["premier_acte"], e["famille_acte"] = None, None
        for a in A:
            fam, full = mentions(a, e["nom"], e["prenom"], bce)
            if fam and not e["famille_acte"]:
                e["famille_acte"] = a
            if full and not e["premier_acte"]:
                e["premier_acte"] = a
        e["renouvellement"] = False
        if e["premier_acte"]:
            n = e["premier_acte"]["norm"]
            if re.search(r"HERBENOEM|HERKOZEN|RENOUVEL|REELU|REELECTION|RENOMM|HERVERKOZEN|WIEDERERNANNT|"
                         r"WIEDERGEWAHLT|VERLENG|PROLONG", n):
                e["renouvellement"] = True
        e["kbo_min"] = min([y for y in map(kbo_since, e["depuis_kbo"]) if y] or [None]) if e["depuis_kbo"] else None
        linked = [x for c in e["pour"] | set(corporate) for x in acts(c)]
        e["naissance"], e["naissance_src"] = birth(A + linked, e["nom"], e["prenom"])

    def rank(e):
        r = " ".join(e["roles"]).lower()
        return (0 if ("délégué" in r or "gérant" in r or "gestion journalière" in r or "m14" in r or "m10" in r)
                else 1 if "président" in r else 2,
                int(e["premier_acte"]["date"][:4]) if e["premier_acte"] else 9999)

    main = sorted(people.values(), key=rank)[0] if people else None

    first_year = None
    if main:
        cands = [y for y in [int(main["premier_acte"]["date"][:4]) if main["premier_acte"] else None,
                             main["kbo_min"]] if y]
        first_year = min(cands) if cands else None
        if main["premier_acte"]:
            srcs.append(f"première mention de {main['prenom']} {main['nom']} : {main['premier_acte']['date']} "
                        f"{main['premier_acte']['ref']} {main['premier_acte']['url']}"
                        + (" (page multi-sociétés d'avant 2003, à confirmer)" if main['premier_acte']['date'] < "2003" else ""))
        if main["kbo_min"]:
            srcs.append(f"BCE : fonction depuis {main['kbo_min']} ({kbo_url})")
        if main["naissance"]:
            srcs.append(f"naissance {main['naissance']} : {main['naissance_src']}")
    bound = bool(main and main["premier_acte"] and (
        (main["premier_acte"]["date"] == oldest_pdf and older_without_pdf) or main["renouvellement"])
        and (not main["kbo_min"] or main["kbo_min"] >= int(main["premier_acte"]["date"][:4])))

    # relève: someone first appearing 2018+ sharing the main surname, or born after TODAY-45
    newcomers = [e for e in people.values() if e is not main and (
        (e["premier_acte"] and e["premier_acte"]["date"] >= "2018") or
        (not e["premier_acte"] and (e["kbo_min"] or 0) >= 2018))]
    releve, releve_why = "non", []
    incumbents = {norm(e["nom"]) for e in people.values() if e not in newcomers}
    for e in newcomers:
        same = norm(e["nom"]) in incumbents
        young = e["naissance"] and TODAY.year - e["naissance"] < 45
        if same or young:
            releve = "oui"
            releve_why.append(f"{e['prenom']} {e['nom']} ({'même nom' if same else f'né en {e['naissance']}'}, "
                              f"{e['premier_acte']['date'] if e['premier_acte'] else 'BCE ' + str(e['kbo_min'])})")
        elif releve == "non":
            releve = "incertain"
            releve_why.append(f"{e['prenom']} {e['nom']} nommé {e['premier_acte']['date'] if e['premier_acte'] else e['kbo_min']} (âge inconnu)")

    statuts = [i for i in lst["items"] if re.search(r"STATUT|SATZUNG|CONSTITUTION|OPRICHTING|GRÜNDUNG", i["type"].upper())]
    last_statuts = max(statuts, key=lambda i: i["date"]) if statuts else None
    if last_statuts:
        srcs.append(f"statuts : {last_statuts['date']} {last_statuts['ref']} {last_statuts['pdf'] or '(liste Moniteur)'}")

    # control signals
    signals, ctrl, mere = [], "inconnu", ""
    bnb_names = {re.sub(r"\D", "", num).zfill(10): name.strip() for name, num in
                 re.findall(r"([^|()]+?)\s*\((\d{4}\.?\d{3}\.?\d{3})\)", row["administrateurs_bnb"])}
    for c, info in corporate.items():
        ck = load(os.path.join(DATA, c, "kbo.json"), {})
        nm = ck.get("denomination", "") or c
        sub = [person_from_kbo(f.get("qui", "")) for f in ck.get("fonctions", [])]
        sub = [p for p in sub if p]
        fam = main and any(norm(p["nom"]) == norm(main["nom"]) for p in sub)
        signals.append(f"administrateur personne morale {nm} ({c}, {ck.get('forme', '?')}) — "
                       f"dirigée par {', '.join(p['prenom'] + ' ' + p['nom'] for p in sub) or '?'}"
                       + (" [même famille]" if fam else ""))
        srcs.append(f"BCE {c} : https://kbopub.economie.fgov.be/kbopub/zoeknummerform.html?nummer={c}&actionLu=Rechercher")
        N = norm(nm + " " + bnb_names.get(c, ""))
        if any(norm(x) in N for x in PUBLIC_INVEST):
            ctrl = "invest public"
        elif any(norm(x) in N for x in INDUSTRIAL):
            ctrl = "groupe industriel" if ctrl == "inconnu" else ctrl
        elif any(norm(x) in N for x in FUND_WORDS):
            ctrl = "fonds" if ctrl == "inconnu" else ctrl
        elif fam and ctrl == "inconnu":
            ctrl = "holding patrimonial"
    for c in corporate:
        ck = load(os.path.join(DATA, c, "kbo.json"), {})
        if "étrangère" in ck.get("forme", "").lower():
            signals.append(f"administrateur inscrit comme entité étrangère : {ck.get('denomination', c)} ({c})")
            mere = mere or f"{ck.get('denomination', c)} (entité étrangère, pays à préciser)"
    foreign = re.findall(r"\b(DE|LU|NL|FR)\d{6,}\b", row["administrateurs_bnb"])
    if foreign:
        signals.append(f"administrateur étranger ({', '.join(foreign)})")
        if ctrl == "inconnu":
            ctrl = "groupe industriel"
            mere = f"? ({', '.join(foreign)})"
    if row["forme"] == "706" or "INTERCOMMUNAL" in norm(row["nom"]):
        ctrl = "invest public"
        signals.append("intercommunale / coopérative publique")
    if ctrl == "inconnu" and main and people and all(norm(e["nom"]) == norm(main["nom"]) for e in people.values()):
        ctrl = "famille" if len(people) > 1 else "personne physique"
        signals.append("tous les dirigeants portent le même nom (indice, pas preuve de détention)")

    for f in funcs:
        if "provisoire" in f.get("role", "").lower() or "tribunal" in f.get("role", "").lower():
            signals.append(f"ALERTE : {f['role']} — {clean_kbo_name(f.get('qui', ''))} depuis {f.get('depuis')} "
                           f"(gestion sous contrôle judiciaire, litige probable)")
    anc = TODAY.year - first_year if first_year else None
    age = TODAY.year - main["naissance"] if main and main["naissance"] else None
    if any(x.startswith("ALERTE") for x in signals):
        verdict = "A VERIFIER (administrateur provisoire désigné par le tribunal)"
    elif ctrl in ("fonds", "invest public") or (ctrl == "groupe industriel" and foreign):
        verdict = "ECARTER"
    elif releve == "oui":
        verdict = "SURVEILLER"
    elif anc and 10 <= anc <= 25 and releve == "non" and age and 58 <= age <= 70:
        verdict = "GARDER"
    else:
        missing = []
        if not first_year:
            missing.append("date de nomination")
        if not age:
            missing.append("âge du dirigeant")
        if ctrl == "inconnu":
            missing.append("actionnariat")
        if releve == "incertain":
            missing.append("âge des nouveaux administrateurs")
        if anc and not 10 <= anc <= 25:
            missing.append(f"ancienneté {anc} ans hors 10-25")
        verdict = "A VERIFIER" + (f" ({', '.join(missing)})" if missing else "")

    return {
        "bce": bce, "nom": row["nom"],
        "premiere_nomination": (f"≤{first_year}" if bound else str(first_year)) if first_year else "",
        "anciennete_ans": f"{'≥' if bound else ''}{anc}" if anc is not None else "",
        "dirigeant_principal": f"{main['prenom']} {main['nom']}".strip() + (f" (né {main['naissance']})" if main and main["naissance"] else "") if main else "",
        "releve": releve + (f" : {'; '.join(releve_why)}" if releve_why else ""),
        "derniere_modification_statuts": last_statuts["date"] if last_statuts else "",
        "actionnaires": "",
        "type_controle": ctrl,
        "societe_mere": mere,
        "verdict": verdict,
        "sources": " | ".join(srcs),
        "_signaux": signals,
        "_personnes": [{"nom": f"{e['prenom']} {e['nom']}", "roles": sorted(e["roles"]),
                        "premier_acte": e["premier_acte"]["date"] if e["premier_acte"] else None,
                        "famille_acte": e["famille_acte"]["date"] if e["famille_acte"] else None,
                        "bce_depuis": e["kbo_min"], "naissance": e["naissance"]} for e in people.values()],
        "_nb_actes": len(A), "_plus_ancien_pdf": oldest_pdf, "_actes_plus_anciens_sans_pdf": older_without_pdf,
    }


def main():
    rows = list(csv.DictReader(open("moniteur/cibles_moniteur.csv", encoding="utf-8"), delimiter=";"))
    ctrl = [{"bce": "0447639261", "nom": "WERKHUIZEN HAEMERS", "forme": "014", "administrateurs_bnb": ""},
            {"bce": "0408287450", "nom": "DUPONT-DRION", "forme": "610", "administrateurs_bnb": ""}]
    res = [analyse(r) for r in ctrl + rows]
    json.dump(res, open("moniteur/brouillon.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open("moniteur/dossiers.md", "w", encoding="utf-8") as f:
        for r in res:
            f.write(f"## {r['bce']} {r['nom']} — {r['verdict']}\n")
            f.write(f"- principal : {r['dirigeant_principal']} ; 1re nomination {r['premiere_nomination']} "
                    f"({r['anciennete_ans']} ans) ; relève : {r['releve']} ; statuts {r['derniere_modification_statuts']}\n")
            f.write(f"- contrôle : {r['type_controle']} {r['societe_mere']} ; actes OCR {r['_nb_actes']} "
                    f"(plus ancien {r['_plus_ancien_pdf']}, plus anciens sans PDF : {r['_actes_plus_anciens_sans_pdf']})\n")
            for p in r["_personnes"]:
                f.write(f"  - {p['nom']} {p['roles']} acte {p['premier_acte']} famille {p['famille_acte']} "
                        f"BCE {p['bce_depuis']} né {p['naissance']}\n")
            for s in r["_signaux"]:
                f.write(f"  - ⚑ {s}\n")
            f.write("\n")
    from collections import Counter
    print(Counter(r["verdict"].split(" (")[0] for r in res))


if __name__ == "__main__":
    main()
