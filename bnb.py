#!/usr/bin/env python3
"""Extract Belgian annual accounts (NBB Central Balance Sheet Office) for a
population of companies and keep those whose EBITDA falls in a target band.

Stdlib only. Resumable: every processed company is appended to
state/lues.jsonl and every unsuccessful attempt to state/tentatives.jsonl as
soon as it is known, so the process can be killed at any time. CSV outputs and
the summary are regenerated from those logs at the end of each pass
(or on demand with `python bnb.py resume`).

Environment:
  NBB_KEY       subscription key (product "Authentic Data")
  TIME_BUDGET   minutes of work before stopping cleanly (default 290)
  WORKERS       parallel calls, capped at 6 (default 6)
  POPULATION    population file (default data/bce_industrie.csv.gz)
  STATE_DIR     output directory (default state)
  NBB_BASE      API base URL (default https://ws.cbso.nbb.be)
  LIMIT         process at most this many companies in this pass (testing)
"""

import csv
import gzip
import io
import json
import os
import random
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime, timezone

BASE = os.environ.get("NBB_BASE", "https://ws.cbso.nbb.be").rstrip("/")
KEY = os.environ.get("NBB_KEY", "")
TIME_BUDGET = float(os.environ.get("TIME_BUDGET", "290")) * 60
WORKERS = max(1, min(6, int(os.environ.get("WORKERS", "6"))))
POPULATION = os.environ.get("POPULATION", "data/bce_industrie.csv.gz")
STATE = os.environ.get("STATE_DIR", "state")
LIMIT = int(os.environ.get("LIMIT", "0"))

BAND_LOW, BAND_HIGH = 300_000, 1_500_000
MAX_TRIES = 7
EMPTY_RECHECKS = (3, 12)      # seconds to wait before re-asking an empty /references
MAX_DEPOSITS_TRIED = 3        # fall back to older deposits if the latest is unusable
OLD_EXERCISE_YEARS = 2        # flag exercises ending more than this many years ago

LUES = os.path.join(STATE, "lues.jsonl")
TENTATIVES = os.path.join(STATE, "tentatives.jsonl")

# Rubric aliases: the XBRL taxonomy writes some ranges in short form ("170/4").
RUBRICS = {
    "9901": ["9901"],
    "630": ["630"],
    "9900": ["9900"],
    "20/58": ["20/58"],
    "10/15": ["10/15"],
    "22/27": ["22/27"],
    "22": ["22"],
    "23": ["23"],
    "170/4": ["170/4", "170/174"],
    "43": ["43"],
    "54/58": ["54/58"],
    "50/53": ["50/53"],
    "62": ["62"],
    "9087": ["9087"],
}

TOUT_COLS = ["bce", "nom", "division", "commune", "exercice", "ebitda", "bilan"]
RETENUES_COLS = [
    "bce", "nom", "division", "commune", "nace", "exercice", "schema", "ebitda",
    "ebitda_n1", "marge_brute", "amortissements", "bilan", "immo_corp", "terrains",
    "machines", "fonds_propres", "dettes_fin", "tresorerie", "remunerations", "etp",
    "administrateurs", "actionnaires",
]


class Fatal(Exception):
    """Authentication or quota problem: no point continuing this pass."""


class CallFailed(Exception):
    """A call did not succeed after retries; the company must be retried later."""


# --------------------------------------------------------------------------- HTTP

class Client:
    def __init__(self, key):
        self.key = key
        self.lock = threading.Lock()
        self.pause_until = 0.0
        self.stats = Counter()

    def _wait_global_pause(self):
        while True:
            with self.lock:
                delay = self.pause_until - time.monotonic()
            if delay <= 0:
                return
            time.sleep(min(delay, 5))

    def _pause_all(self, seconds):
        with self.lock:
            self.pause_until = max(self.pause_until, time.monotonic() + seconds)

    def get(self, url, accept):
        """Return (status, body bytes). 404 is returned, not raised."""
        if not url.startswith("http"):
            url = BASE + url
        for attempt in range(MAX_TRIES):
            self._wait_global_pause()
            req = urllib.request.Request(url, headers={
                "NBB-CBSO-Subscription-Key": self.key,
                "X-Request-Id": str(uuid.uuid4()),
                "Accept": accept,
                "User-Agent": "eta-bnb/1.0",
            })
            self.stats["appels"] += 1
            retry_after = None
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as e:
                code = e.code
                body = e.read()[:500]
                if code == 404:
                    return 404, b""
                if code in (401, 403):
                    raise Fatal(f"HTTP {code} on {url}: {body!r}")
                if code == 415:
                    raise CallFailed(f"415 Unsupported Media Type for Accept={accept} on {url}")
                if code == 429 or code >= 500:
                    self.stats["bridages"] += 1
                    retry_after = _retry_after(e.headers.get("Retry-After"))
                    if code == 429:
                        self._pause_all(retry_after or 5 * 2 ** attempt)
                else:
                    raise CallFailed(f"HTTP {code} on {url}: {body!r}")
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                self.stats["erreurs_reseau"] += 1
                last = e
            delay = retry_after or min(300, 2 * 2 ** attempt) * (0.75 + random.random() / 2)
            time.sleep(delay)
        raise CallFailed(f"gave up after {MAX_TRIES} tries on {url}")


def _retry_after(value):
    try:
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------- parsing

def ci(d, *names):
    """Case-insensitive dict lookup returning the first matching key's value."""
    if not isinstance(d, dict):
        return None
    lower = {k.lower(): v for k, v in d.items()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def as_list(payload):
    """/references returns a bare list, but some clients/proxies wrap it in {value: [...]}."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("value", "Value", "references", "References", "items"):
            if isinstance(payload.get(k), list):
                return payload[k]
    return []


def ref_sort_key(ref):
    ex = ci(ref, "ExerciseDates") or {}
    end = str(ci(ex, "endDate", "EndDate") or "")
    dep = str(ci(ref, "DepositDate") or "")
    return (end, dep)


def iter_rubrics(node):
    """Yield (code, period, value) from anything shaped like a rubric list."""
    if isinstance(node, list):
        for item in node:
            yield from iter_rubrics(item)
    elif isinstance(node, dict):
        code = ci(node, "Code")
        period = ci(node, "Period")
        if code is not None and period is not None and "Value" in {k.title() for k in node}:
            yield str(code), str(period), ci(node, "Value")
            return
        for v in node.values():
            if isinstance(v, (list, dict)):
                yield from iter_rubrics(v)


def to_num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def rubric_table(doc):
    table = {}
    for code, period, value in iter_rubrics(ci(doc, "Rubrics") or doc):
        n = to_num(value)
        if n is not None:
            table[(code, period.upper())] = n
    return table


def pick(table, name, period="N"):
    for alias in RUBRICS[name]:
        if (alias, period) in table:
            return table[(alias, period)]
    return None


def add(*vals):
    present = [v for v in vals if v is not None]
    return sum(present) if present else None


def _names(node, depth=0):
    """Best-effort display name for a person or entity block."""
    if not isinstance(node, dict) or depth > 3:
        return ""
    first = ci(node, "FirstName", "Firstname")
    last = ci(node, "LastName", "Lastname", "FamilyName")
    if first or last:
        return " ".join(str(x) for x in (last, first) if x)
    name = ci(node, "Name", "Denomination", "EntityName", "LegalName")
    if isinstance(name, str) and name.strip():
        return name.strip()
    for v in node.values():
        if isinstance(v, dict):
            n = _names(v, depth + 1)
            if n:
                return n
    return ""


def _find(node, pred, depth=0):
    if depth > 4:
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if pred(k, v):
                yield k, v
            yield from _find(v, pred, depth + 1)
    elif isinstance(node, list):
        for v in node:
            yield from _find(v, pred, depth + 1)


def _entries(block):
    """Flatten an Administrators/Shareholders block into person/entity dicts."""
    if isinstance(block, list):
        out = []
        for item in block:
            if isinstance(item, dict) and _names(item) and not any(
                isinstance(v, list) and v and isinstance(v[0], dict) and _names(v[0])
                for v in item.values()
            ):
                out.append(item)
            else:
                out.extend(_entries(item))
        return out
    if isinstance(block, dict):
        out = []
        for v in block.values():
            if isinstance(v, (list, dict)):
                out.extend(_entries(v))
        if not out and _names(block):
            out.append(block)
        return out
    return []


def format_admins(block):
    parts = []
    for e in _entries(block):
        name = _names(e)
        starts = sorted({str(v)[:10] for k, v in _find(e, lambda k, v: k.lower() == "startdate" and v)})
        funcs = sorted({str(v) for k, v in _find(
            e, lambda k, v: "function" in k.lower() and isinstance(v, (str, int)) and v != "")})
        label = name
        if funcs:
            label += f" [{', '.join(funcs)}]"
        if starts:
            label += f" depuis {starts[0]}"
        legal = ci(e, "Entity", "LegalPerson", "Company")
        rep = ci(e, "Representatives", "Representative", "PermanentRepresentative")
        if legal and rep:
            label += f" repr. {', '.join(_names(r) for r in (rep if isinstance(rep, list) else [rep]))}"
        parts.append(label)
    return " | ".join(dict.fromkeys(p for p in parts if p))


def format_shareholders(block):
    parts = []
    for e in _entries(block):
        name = _names(e)
        pct = [v for k, v in _find(e, lambda k, v: any(t in k.lower() for t in ("percent", "pourcent"))
                                   and to_num(v) is not None)]
        nb = [v for k, v in _find(e, lambda k, v: any(t in k.lower() for t in ("number", "nombre", "shares"))
                                  and to_num(v) is not None)]
        label = name
        if pct:
            label += f" ({to_num(pct[0]):g} %)"
        elif nb:
            label += f" ({to_num(nb[0]):g} titres)"
        parts.append(label)
    return " | ".join(dict.fromkeys(p for p in parts if p))


def months_between(start, end):
    try:
        s = date.fromisoformat(str(start)[:10])
        e = date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    return round((e - s).days / 30.44)


def extract(company, ref, doc):
    """Build the output record from one deposit. Returns None if no usable rubrics."""
    t = rubric_table(doc)
    if not t:
        return None
    ex = ci(ref, "ExerciseDates") or ci(doc, "ExerciseDates") or {}
    start = ci(ex, "startDate", "StartDate")
    end = ci(ex, "endDate", "EndDate")
    schema = ci(ref, "ModelType") or ci(doc, "ModelType") or ""
    r9901, r630 = pick(t, "9901"), pick(t, "630")
    r9901p, r630p = pick(t, "9901", "NM1"), pick(t, "630", "NM1")
    ebitda = r9901 + (r630 or 0) if r9901 is not None else None
    ebitda_n1 = r9901p + (r630p or 0) if r9901p is not None else None

    alerts = []
    if r9901 is None:
        alerts.append("9901 absent")
    if r630 is None:
        alerts.append("630 absent")
    if end and int(str(end)[:4]) < date.today().year - OLD_EXERCISE_YEARS:
        alerts.append(f"exercice ancien ({str(end)[:10]})")
    m = months_between(start, end)
    if m is not None and m != 12:
        alerts.append(f"exercice de {m} mois")
    cur = ci(ref, "Currency") or ci(doc, "Currency")
    if cur and str(cur).upper() != "EUR":
        alerts.append(f"devise {cur}")
    bilan = pick(t, "20/58")
    etp = pick(t, "9087")
    if ebitda is not None and bilan and ebitda > bilan:
        alerts.append("EBITDA > total du bilan")
    if ebitda is not None and ebitda >= BAND_LOW and not etp:
        alerts.append("EBITDA dans la bande sans personnel déclaré")
    if ebitda is not None and abs(ebitda) > 1e9:
        alerts.append("EBITDA aberrant (> 1 Md)")
    if ebitda is not None and ebitda_n1 not in (None, 0) and abs(ebitda) > 0 and (
            ebitda / ebitda_n1 > 5 or ebitda / ebitda_n1 < -5):
        alerts.append("variation N/N-1 extrême")

    return {
        "bce": company["bce"],
        "nom": company["nom"],
        "division": company["division"],
        "commune": company["commune"],
        "nace": company["nace"],
        "forme": company["forme"],
        "reference": ci(ref, "ReferenceNumber") or "",
        "depot": str(ci(ref, "DepositDate") or "")[:10],
        "exercice": str(end or "")[:10],
        "schema": schema,
        "ebitda": ebitda,
        "ebitda_n1": ebitda_n1,
        "marge_brute": pick(t, "9900"),
        "amortissements": r630,
        "bilan": bilan,
        "immo_corp": pick(t, "22/27"),
        "terrains": pick(t, "22"),
        "machines": pick(t, "23"),
        "fonds_propres": pick(t, "10/15"),
        "dettes_fin": add(pick(t, "170/4"), pick(t, "43")),
        "tresorerie": add(pick(t, "54/58"), pick(t, "50/53")),
        "remunerations": pick(t, "62"),
        "etp": etp,
        "administrateurs": format_admins(ci(doc, "Administrators")),
        "actionnaires": format_shareholders(ci(doc, "Shareholders")),
        "alertes": "; ".join(alerts),
    }


# ----------------------------------------------------------------------- worker

def process(client, company):
    """Return (status, payload, bridages). status in ok / sans_depot / erreur."""
    bce = company["bce"]
    path = f"/authentic/legalEntity/{bce}/references"
    suspicious = 0
    refs = []
    for i in range(len(EMPTY_RECHECKS) + 1):
        status, body = client.get(path, "application/json")
        if status == 404:
            return "sans_depot", "404 sur /references", suspicious
        try:
            refs = as_list(json.loads(body or b"[]"))
        except ValueError as e:
            raise CallFailed(f"/references non JSON: {e}")
        if refs:
            if i > 0:
                suspicious += 1  # empty answer turned non-empty: silent throttling
            break
        if i < len(EMPTY_RECHECKS):
            time.sleep(EMPTY_RECHECKS[i])
    if not refs:
        return "sans_depot", "aucun dépôt", suspicious

    refs.sort(key=ref_sort_key, reverse=True)
    tried = []
    for ref in refs[:MAX_DEPOSITS_TRIED]:
        url = ci(ref, "AccountingDataURL")
        refno = ci(ref, "ReferenceNumber")
        if not url and refno:
            url = f"/authentic/deposit/{refno}/accountingData"
        if not url:
            continue
        status, body = client.get(url, "application/x.jsonxbrl")
        if status == 404:
            tried.append(f"{refno}:404")
            continue
        try:
            doc = json.loads(body)
        except ValueError:
            tried.append(f"{refno}:non-json")
            continue
        rec = extract(company, ref, doc)
        if rec:
            if tried:
                rec["alertes"] = "; ".join(filter(None, [
                    rec["alertes"], f"dépôt plus récent inexploitable ({', '.join(tried)})"]))
            return "ok", rec, suspicious
        tried.append(f"{refno}:sans rubriques")
    return "sans_depot", f"{len(refs)} dépôt(s) inexploitable(s): {', '.join(tried)}", suspicious


# ------------------------------------------------------------------------ state

def load_population():
    opener = gzip.open if POPULATION.endswith(".gz") else open
    with opener(POPULATION, "rt", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    out = {}
    for r in rows:
        bce = "".join(ch for ch in r.get("numero_bce", "") if ch.isdigit()).zfill(10)
        if len(bce) != 10:
            continue
        out[bce] = {
            "bce": bce,
            "nom": r.get("nom", ""),
            "division": r.get("division", ""),
            "commune": r.get("commune", ""),
            "code_postal": r.get("code_postal", ""),
            "nace": r.get("nace_principal", ""),
            "forme": r.get("forme", ""),
            "creation": r.get("creation", ""),
        }
    return out


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass  # truncated last line after a kill
    return out


def load_state():
    lues = {r["bce"]: r for r in read_jsonl(LUES)}
    last_attempt = {}
    for t in read_jsonl(TENTATIVES):
        last_attempt[t["bce"]] = t
    for bce in lues:
        last_attempt.pop(bce, None)
    return lues, last_attempt


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    return str(v)


def to_csv(rows, cols):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([fmt(r.get(c)) for c in cols])
    return buf.getvalue()


def in_band(r):
    return r.get("ebitda") is not None and BAND_LOW <= r["ebitda"] <= BAND_HIGH


def write_outputs(population, lues, last_attempt):
    rows = sorted(lues.values(), key=lambda r: r["bce"])
    retenues = sorted((r for r in rows if in_band(r)), key=lambda r: -r["ebitda"])
    write_atomic(os.path.join(STATE, "tout.csv"), to_csv(rows, TOUT_COLS))
    write_atomic(os.path.join(STATE, "retenues.csv"), to_csv(retenues, RETENUES_COLS))
    sans = sorted(b for b, t in last_attempt.items() if t["status"] == "sans_depot")
    write_atomic(os.path.join(STATE, "sans_depot.txt"), "".join(b + "\n" for b in sans))
    anomalies = [r for r in rows if r.get("alertes")]
    write_atomic(os.path.join(STATE, "anomalies.csv"), to_csv(
        anomalies, ["bce", "nom", "exercice", "schema", "ebitda", "bilan", "etp", "alertes"]))
    write_atomic(os.path.join(STATE, "resume.md"), summary(population, lues, last_attempt))
    return retenues, sans


def summary(population, lues, last_attempt):
    rows = list(lues.values())
    retenues = sorted((r for r in rows if in_band(r)), key=lambda r: -r["ebitda"])
    sans = {b for b, t in last_attempt.items() if t["status"] == "sans_depot"}
    errs = {b for b, t in last_attempt.items() if t["status"] == "erreur"}
    untouched = len(population) - len(lues) - len(last_attempt)
    n = len(population) or 1
    L = []
    L.append(f"# Résumé — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n")
    L.append(f"- Population : {len(population)}")
    L.append(f"- Lues (dépôt exploitable) : {len(lues)} ({100 * len(lues) / n:.1f} %)")
    L.append(f"- Sans dépôt exploitable : {len(sans)} ({100 * len(sans) / n:.1f} %)")
    L.append(f"- En erreur (à retenter) : {len(errs)}")
    L.append(f"- Jamais interrogées : {untouched}")
    L.append(f"- Retenues ({BAND_LOW:,} € ≤ EBITDA ≤ {BAND_HIGH:,} €) : {len(retenues)}".replace(",", " "))
    L.append(f"  - dont dans la bande stricte 400 k€–1,2 M€ : "
             f"{sum(1 for r in retenues if 400_000 <= r['ebitda'] <= 1_200_000)}\n")

    L.append("## Retenues par division NACE\n")
    L.append("| Division | Retenues | Lues | Population |")
    L.append("| --- | ---: | ---: | ---: |")
    pop_div = Counter(c["division"] for c in population.values())
    lues_div = Counter(r["division"] for r in rows)
    ret_div = Counter(r["division"] for r in retenues)
    for d, k in sorted(ret_div.items(), key=lambda x: (-x[1], x[0])):
        L.append(f"| {d} | {k} | {lues_div[d]} | {pop_div[d]} |")

    L.append("\n## Dix plus gros EBITDA parmi les retenues\n")
    L.append("| BCE | Nom | Div. | Commune | Exercice | EBITDA | ETP |")
    L.append("| --- | --- | --- | --- | --- | ---: | ---: |")
    for r in retenues[:10]:
        L.append(f"| {r['bce']} | {r['nom']} | {r['division']} | {r['commune']} | "
                 f"{r['exercice']} | {r['ebitda']:,.0f} | {fmt(r.get('etp'))} |".replace(",", " "))

    L.append("\n## Couverture : sans dépôt par forme juridique\n")
    L.append("| Forme | Population | Lues | Sans dépôt | Taux sans dépôt |")
    L.append("| --- | ---: | ---: | ---: | ---: |")
    pop_f = Counter(c["forme"] for c in population.values())
    lues_f = Counter(population[b]["forme"] for b in lues if b in population)
    sans_f = Counter(population[b]["forme"] for b in sans if b in population)
    for f_, k in pop_f.most_common(20):
        tried = lues_f[f_] + sans_f[f_]
        rate = f"{100 * sans_f[f_] / tried:.0f} %" if tried else "—"
        L.append(f"| {f_ or '?'} | {k} | {lues_f[f_]} | {sans_f[f_]} | {rate} |")

    L.append("\n## Couverture : sans dépôt par année de création\n")
    L.append("| Création | Lues | Sans dépôt | Taux |")
    L.append("| --- | ---: | ---: | ---: |")
    def bucket(c):
        y = "".join(ch for ch in c.get("creation", "") if ch.isdigit())
        y = y[-4:] if len(y) >= 4 and not y.startswith(("19", "20")) else y[:4]
        if not y:
            return "?"
        y = int(y)
        return ("< 2000" if y < 2000 else "2000-2014" if y < 2015 else
                "2015-2021" if y < 2022 else str(y))
    lb, sb = Counter(bucket(population[b]) for b in lues if b in population), \
        Counter(bucket(population[b]) for b in sans if b in population)
    for k in sorted(set(lb) | set(sb)):
        t = lb[k] + sb[k]
        L.append(f"| {k} | {lb[k]} | {sb[k]} | {100 * sb[k] / t:.0f} % |")

    reasons = Counter(last_attempt[b].get("detail", "")[:60] for b in sans)
    if reasons:
        L.append("\n## Motifs « sans dépôt »\n")
        for k, v in reasons.most_common(8):
            L.append(f"- {v} × {k}")

    L.append("\n## Qualité des données (sur les sociétés lues)\n")
    al = Counter()
    for r in rows:
        for a in filter(None, (x.strip() for x in r.get("alertes", "").split(";"))):
            al[a.split(" (")[0] if a.startswith(("exercice ancien", "dépôt plus")) else
               ("exercice ≠ 12 mois" if a.startswith("exercice de") else a)] += 1
    for k, v in al.most_common():
        L.append(f"- {k} : {v}")
    years = Counter(r["exercice"][:4] for r in rows if r.get("exercice"))
    L.append("\nExercice le plus récent disponible, par année de clôture : " +
             ", ".join(f"{y}: {k}" for y, k in sorted(years.items())))
    schemas = Counter(r.get("schema") or "?" for r in rows)
    L.append("\nSchémas : " + ", ".join(f"{s}: {k}" for s, k in schemas.most_common()))
    L.append("\nDétail ligne à ligne : `state/anomalies.csv`.")
    return "\n".join(L) + "\n"


# -------------------------------------------------------------------------- run

def run():
    if not KEY:
        sys.exit("NBB_KEY is not set")
    os.makedirs(STATE, exist_ok=True)
    population = load_population()
    lues, last_attempt = load_state()

    # Never-tried first, then previous errors, then previous "no deposit".
    rank = {"erreur": 1, "sans_depot": 2}
    queue = sorted((b for b in population if b not in lues),
                   key=lambda b: (rank.get(last_attempt.get(b, {}).get("status"), 0), b))
    if LIMIT:
        queue = queue[:LIMIT]
    print(f"population={len(population)} déjà lues={len(lues)} à traiter={len(queue)}", flush=True)

    client = Client(KEY)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    t0 = time.monotonic()
    counts = Counter()
    fatal = None
    f_lues = open(LUES, "a", encoding="utf-8")
    f_tent = open(TENTATIVES, "a", encoding="utf-8")

    def record(status, company, payload, suspicious):
        counts["bridages_silencieux"] += suspicious
        counts[status] += 1
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if status == "ok":
            payload["lu_le"] = now
            lues[company["bce"]] = payload
            last_attempt.pop(company["bce"], None)
            f_lues.write(json.dumps(payload, ensure_ascii=False) + "\n")
            f_lues.flush()
        else:
            t = {"bce": company["bce"], "status": status, "detail": str(payload)[:300], "ts": now}
            last_attempt[company["bce"]] = t
            f_tent.write(json.dumps(t, ensure_ascii=False) + "\n")
            f_tent.flush()

    def task(company):
        try:
            return process(client, company)
        except CallFailed as e:
            return "erreur", str(e), 0

    it = iter(queue)
    inflight = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        while True:
            while (len(inflight) < WORKERS * 2 and not stop.is_set() and fatal is None
                   and time.monotonic() - t0 < TIME_BUDGET):
                bce = next(it, None)
                if bce is None:
                    break
                inflight[pool.submit(task, population[bce])] = population[bce]
            if not inflight:
                break
            done, _ = wait(inflight, timeout=10, return_when=FIRST_COMPLETED)
            for fut in done:
                company = inflight.pop(fut)
                try:
                    status, payload, suspicious = fut.result()
                except Fatal as e:
                    fatal = str(e)
                    print(f"FATAL: {e}", flush=True)
                    continue
                record(status, company, payload, suspicious)
            n = sum(counts[s] for s in ("ok", "sans_depot", "erreur"))
            if done and n % 200 < len(done):
                el = (time.monotonic() - t0) / 60
                print(f"[{el:6.1f} min] traitées={n} ok={counts['ok']} sans_depot={counts['sans_depot']} "
                      f"erreurs={counts['erreur']} appels={client.stats['appels']} "
                      f"429/5xx={client.stats['bridages']}", flush=True)
    f_lues.close()
    f_tent.close()

    retenues, sans = write_outputs(population, lues, last_attempt)
    line = (f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} "
            f"durée={(time.monotonic() - t0) / 60:.0f}min "
            f"lues={counts['ok']} retenues_total={len(retenues)} sans_depot={counts['sans_depot']} "
            f"erreurs={counts['erreur']} bridages={client.stats['bridages'] + counts['bridages_silencieux']} "
            f"(429/5xx={client.stats['bridages']} vides_corrigés={counts['bridages_silencieux']}) "
            f"appels={client.stats['appels']} | cumul lues={len(lues)} sans_depot={len(sans)} "
            f"restant={len(population) - len(lues)}"
            + (f" | ARRÊT: {fatal[:200]}" if fatal else ""))
    with open(os.path.join(STATE, "journal.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)
    if fatal:
        sys.exit(2)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "resume":
        population = load_population()
        lues, last_attempt = load_state()
        write_outputs(population, lues, last_attempt)
        print(open(os.path.join(STATE, "resume.md"), encoding="utf-8").read())
    else:
        run()


if __name__ == "__main__":
    main()
