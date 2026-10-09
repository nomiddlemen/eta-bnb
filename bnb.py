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
  RATE          starting pace in calls/s across all workers (default 4)
  RATE_MAX      ceiling for the adaptive pace (default 8)

`python bnb.py probe` checks the live API (response formats, throughput,
rate-limit headers) without touching the population and writes state/probe/.
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
RATE = float(os.environ.get("RATE", "4"))          # starting calls/s, all workers together
RATE_MAX = float(os.environ.get("RATE_MAX", "8"))  # never exceed this
RATE_MIN = float(os.environ.get("RATE_MIN", "1"))  # never slow below this; 429 backoff still applies
SANS_DEPOT_PASSES = 3  # a company with no deposit after this many separate passes is final

BAND_LOW, BAND_HIGH = 300_000, 1_500_000
MAX_TRIES = 7
EMPTY_RECHECKS = (3, 12)      # seconds to wait before re-asking an empty /references
MAX_DEPOSITS_TRIED = 3        # fall back to older deposits if the latest is unusable
OLD_EXERCISE_YEARS = 2        # flag exercises ending more than this many years ago
OLD_DEPOSIT_YEARS = 3         # last exercise older than this: company stopped filing, and
                              # Authentic Data no longer serves the content (404)

LUES = os.path.join(STATE, "lues.jsonl")
TENTATIVES = os.path.join(STATE, "tentatives.jsonl")
TERMINE = os.path.join(STATE, "TERMINE")

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
    "1003": ["1003"],  # social balance: total FTE, filled when 9087 is not
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

class RateLimiter:
    """Global pacing shared by all workers. Cuts the rate by a quarter on each
    burst of 429s (floor RATE_MIN) and raises it by a quarter after 30 quiet
    seconds, never above `ceiling` calls/s."""

    def __init__(self, rate, ceiling):
        self.lock = threading.Lock()
        self.rate = rate
        self.ceiling = ceiling
        self.next_slot = 0.0
        self.last_429 = 0.0
        self.last_raise = time.monotonic()
        self.lowest = rate

    def acquire(self):
        with self.lock:
            now = time.monotonic()
            if now - self.last_429 > 30 and now - self.last_raise > 30 and self.rate < self.ceiling:
                self.rate = min(self.ceiling, self.rate * 1.25)
                self.last_raise = now
            slot = max(now, self.next_slot)
            self.next_slot = slot + 1 / self.rate
        if slot > now:
            time.sleep(slot - now)

    def throttled(self, pause):
        with self.lock:
            now = time.monotonic()
            if now - self.last_429 > 2:  # one halving per burst of 429s
                self.rate = max(RATE_MIN, self.rate * 0.75)
                self.lowest = min(self.lowest, self.rate)
            self.last_429 = now
            self.last_raise = now
            self.next_slot = max(self.next_slot, now + pause)


class Client:
    def __init__(self, key, rate=None, ceiling=None):
        self.key = key
        self.lock = threading.Lock()
        self.limiter = RateLimiter(rate or RATE, ceiling or RATE_MAX)
        self.stats = Counter()
        self.status_codes = Counter()
        self.limit_headers = {}

    def _note_headers(self, code, headers):
        for k, v in (headers or {}).items():
            kl = k.lower()
            if any(t in kl for t in ("ratelimit", "rate-limit", "quota", "retry-after", "x-ms-")):
                with self.lock:
                    self.limit_headers[k] = f"{v} (HTTP {code})"

    def get(self, url, accept):
        """Return (status, body bytes). 404 is returned, not raised."""
        if not url.startswith("http"):
            url = BASE + url
        for attempt in range(MAX_TRIES):
            self.limiter.acquire()
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
                    self.status_codes[resp.status] += 1
                    self._note_headers(resp.status, resp.headers)
                    return resp.status, resp.read()
            except urllib.error.HTTPError as e:
                code = e.code
                self.status_codes[code] += 1
                self._note_headers(code, e.headers)
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
                        self.stats["http_429"] += 1
                        self.limiter.throttled(retry_after or 5 * 2 ** attempt)
                else:
                    raise CallFailed(f"HTTP {code} on {url}: {body!r}")
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                self.stats["erreurs_reseau"] += 1
                self.status_codes["réseau"] += 1
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


def _mandates(e):
    funcs, starts, ends = [], [], []
    for m in ci(e, "Mandates") or []:
        f = ci(m, "FunctionMandate") or ci(m, "OtherFunctionMandate")
        if f:
            funcs.append(str(f).replace("fct:", ""))
        d = ci(m, "MandateDates") or {}
        if ci(d, "StartDate"):
            starts.append(str(ci(d, "StartDate"))[:10])
        if ci(d, "EndDate"):
            ends.append(str(ci(d, "EndDate"))[:10])
    label = ""
    if funcs:
        label += f" [{', '.join(sorted(set(funcs)))}]"
    if starts:
        label += f" depuis {min(starts)}"
    if ends:
        label += f" jusqu'à {max(ends)}"
    return label


def format_admins(block):
    if isinstance(block, dict) and ("NaturalPersons" in block or "LegalPersons" in block):
        parts = []
        for e in block.get("NaturalPersons") or []:
            p = ci(e, "Person") or e
            parts.append(f"{_names(p)}{_mandates(e)}")
        for e in block.get("LegalPersons") or []:
            ent = ci(e, "Entity") or e
            label = _names(ent)
            if ci(ent, "Identifier"):
                label += f" ({ci(ent, 'Identifier')})"
            reps = [_names(r) for r in ci(e, "Representatives") or []]
            if reps:
                label += f" repr. {', '.join(filter(None, reps))}"
            parts.append(label + _mandates(e))
        return " | ".join(p for p in parts if p.strip())
    return _format_admins_generic(block)


def _format_admins_generic(block):
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
    if etp is None:
        etp = pick(t, "1003")
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
    last_end = ref_sort_key(refs[0])[0][:10]
    if last_end and int(last_end[:4]) < date.today().year - OLD_DEPOSIT_YEARS:
        return "ancien", f"dernier exercice déposé clos le {last_end}", suspicious
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
    write_atomic(os.path.join(STATE, "depot_ancien.csv"), to_csv(
        [{**population.get(b, {"bce": b}), "dernier": t["detail"]} for b, t in sorted(last_attempt.items())
         if t["status"] == "ancien"], ["bce", "nom", "division", "forme", "creation", "dernier"]))
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
    anciens = {b for b, t in last_attempt.items() if t["status"] == "ancien"}
    untouched = len(population) - len(lues) - len(last_attempt)
    n = len(population) or 1
    L = []
    L.append(f"# Résumé — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n")
    L.append(f"- Population : {len(population)}")
    L.append(f"- Lues (dépôt exploitable) : {len(lues)} ({100 * len(lues) / n:.1f} %)")
    L.append(f"- Sans dépôt exploitable : {len(sans)} ({100 * len(sans) / n:.1f} %)")
    L.append(f"- Dernier dépôt antérieur à {date.today().year - OLD_DEPOSIT_YEARS} (ne déposent plus, "
             f"contenu non servi par Authentic Data) : {len(anciens)}")
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
    queue = pending(population, lues, last_attempt)
    queue.sort(key=lambda b: (rank.get(last_attempt.get(b, {}).get("status"), 0), b))
    if LIMIT:
        queue = queue[:LIMIT]
    print(f"population={len(population)} déjà lues={len(lues)} à traiter={len(queue)}", flush=True)
    if not queue:
        finish(population, lues, last_attempt)
        return
    pass_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")

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
            t = {"bce": company["bce"], "status": status, "detail": str(payload)[:300], "ts": now,
                 "passe": pass_id}
            last_attempt[company["bce"]] = t
            f_tent.write(json.dumps(t, ensure_ascii=False) + "\n")
            f_tent.flush()

    def task(company):
        try:
            return process(client, company)
        except CallFailed as e:
            return "erreur", str(e), 0

    total_queue = len(queue)
    last_progress = 0.0
    recent_errors = []

    def write_progress(final=False):
        el = (time.monotonic() - t0) / 60
        n = sum(counts[k] for k in ("ok", "sans_depot", "erreur", "ancien"))
        speed = n / el if el > 0 else 0
        eta = (total_queue - n) / speed if speed else 0
        write_atomic(os.path.join(STATE, "progres.md"), (
            f"# Progression — passe {pass_id}{' (terminée)' if final else ''}\n\n"
            f"- mis à jour : {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC, {el:.0f} min écoulées\n"
            f"- traitées : {n} / {total_queue} de cette passe ({speed:.0f}/min, reste ≈ {eta:.0f} min)\n"
            f"- lues : {counts['ok']}, sans dépôt : {counts['sans_depot']}, dépôt ancien : {counts['ancien']}, "
            f"erreurs : {counts['erreur']}\n"
            f"- cumul lues (toutes passes) : {len(lues)} / {len(population)}\n"
            f"- retenues jusqu'ici : {sum(1 for r in lues.values() if in_band(r))}\n"
            f"- appels : {client.stats['appels']} ({client.stats['appels'] / max(el, 0.01):.0f}/min), "
            f"HTTP 429 : {client.stats['http_429']}, 5xx/429 : {client.stats['bridages']}, "
            f"vides corrigés : {counts['bridages_silencieux']}, réseau : {client.stats['erreurs_reseau']}\n"
            f"- rythme : {client.limiter.rate:.2f}/s (plus bas {client.limiter.lowest:.2f}/s)\n"
            f"- codes HTTP : {dict(client.status_codes)}\n"
            f"- en-têtes de quota : {client.limit_headers or 'aucun'}\n"
            + ("\n## Dernières erreurs\n\n" + "\n".join(f"- {e}" for e in recent_errors[-10:]) + "\n"
               if recent_errors else "")))

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
                if status == "erreur":
                    recent_errors.append(f"{company['bce']}: {str(payload)[:160]}")
            if time.monotonic() - last_progress > 120:
                last_progress = time.monotonic()
                write_progress()
            n = sum(counts[s] for s in ("ok", "sans_depot", "erreur", "ancien"))
            if done and n % 200 < len(done):
                el = (time.monotonic() - t0) / 60
                print(f"[{el:6.1f} min] traitées={n} ok={counts['ok']} sans_depot={counts['sans_depot']} "
                      f"erreurs={counts['erreur']} appels={client.stats['appels']} "
                      f"429/5xx={client.stats['bridages']}", flush=True)
    f_lues.close()
    f_tent.close()
    write_progress(final=True)

    retenues, sans = write_outputs(population, lues, last_attempt)
    minutes = (time.monotonic() - t0) / 60
    lim = client.limiter
    rate_report = (
        f"# Débit et limites — passe {pass_id}\n\n"
        f"- appels : {client.stats['appels']} en {minutes:.0f} min "
        f"({client.stats['appels'] / max(minutes, 0.01):.0f} appels/min)\n"
        f"- rythme autorisé : départ {RATE}/s, fin {lim.rate:.2f}/s, plus bas {lim.lowest:.2f}/s, plafond {RATE_MAX}/s\n"
        f"- HTTP 429 : {client.stats['http_429']}, 5xx/429 total : {client.stats['bridages']}, "
        f"réponses vides corrigées en relance : {counts['bridages_silencieux']}, "
        f"erreurs réseau : {client.stats['erreurs_reseau']}\n"
        f"- codes HTTP : {dict(client.status_codes)}\n"
        f"- en-têtes de quota vus : {client.limit_headers or 'aucun'}\n")
    with open(os.path.join(STATE, "debit.md"), "a", encoding="utf-8") as f:
        f.write(rate_report + "\n")
    line = (f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} "
            f"durée={(time.monotonic() - t0) / 60:.0f}min "
            f"lues={counts['ok']} retenues_total={len(retenues)} sans_depot={counts['sans_depot']} "
            f"depot_ancien={counts['ancien']} "
            f"erreurs={counts['erreur']} bridages={client.stats['bridages'] + counts['bridages_silencieux']} "
            f"(429/5xx={client.stats['bridages']} vides_corrigés={counts['bridages_silencieux']}) "
            f"appels={client.stats['appels']} ({client.stats['appels'] / max(minutes, 0.01):.0f}/min, "
            f"429={client.stats['http_429']}, rythme fin={lim.rate:.2f}/s) "
            f"| cumul lues={len(lues)} sans_depot={len(sans)} "
            f"restant={len(population) - len(lues)}"
            + (f" | ARRÊT: {fatal[:200]}" if fatal else ""))
    with open(os.path.join(STATE, "journal.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)
    if fatal:
        sys.exit(2)
    if not LIMIT and not pending(population, lues, load_state()[1]):
        finish(population, lues, last_attempt)


def sans_depot_passes():
    passes = defaultdict(set)
    for t in read_jsonl(TENTATIVES):
        if t.get("status") == "sans_depot":
            passes[t["bce"]].add(t.get("passe") or t.get("ts", "")[:13])
    return passes


def pending(population, lues, last_attempt):
    """Companies still worth asking: never read, unless they already came back
    without deposit in SANS_DEPOT_PASSES separate passes."""
    passes = sans_depot_passes()
    return [b for b in population if b not in lues
            and last_attempt.get(b, {}).get("status") != "ancien" and not (
        last_attempt.get(b, {}).get("status") == "sans_depot" and len(passes[b]) >= SANS_DEPOT_PASSES)]


def finish(population, lues, last_attempt):
    retenues, sans = write_outputs(population, lues, last_attempt)
    msg = (f"{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} terminé: lues={len(lues)} "
           f"retenues={len(retenues)} sans_depot_definitifs={len(sans)}\n")
    if not os.path.exists(TERMINE):
        write_atomic(TERMINE, msg)
        with open(os.path.join(STATE, "journal.txt"), "a", encoding="utf-8") as f:
            f.write(msg)
    print(msg, end="", flush=True)


# ------------------------------------------------------------------------ probe

def valid_bce(rng):
    base = rng.randint(4_000_000, 8_999_999)  # enterprise numbers 0400.000.0xx to 0899.999.9xx
    return f"{base:08d}{97 - base % 97:02d}"


def raw_get(url, accept):
    """Single call, no retry: (status, seconds, body, headers)."""
    if not url.startswith("http"):
        url = BASE + url
    req = urllib.request.Request(url, headers={
        "NBB-CBSO-Subscription-Key": KEY, "X-Request-Id": str(uuid.uuid4()),
        "Accept": accept, "User-Agent": "eta-bnb/1.0"})
    t = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, time.monotonic() - t, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, time.monotonic() - t, e.read()[:2000], dict(e.headers)
    except Exception as e:
        return f"réseau:{type(e).__name__}", time.monotonic() - t, b"", {}


def probe():
    if not KEY:
        sys.exit("NBB_KEY is not set")
    out = os.path.join(STATE, "probe")
    os.makedirs(out, exist_ok=True)
    rng = random.Random(42)
    known = os.environ.get("SAMPLE_BCE", "0447639261").split(",")
    seconds = float(os.environ.get("PROBE_SECONDS", "40"))
    L = [f"# Sonde API BNB — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n", "## Formats\n"]

    # Formats on known companies plus random valid numbers until a few deposits are read.
    candidates = known + [valid_bce(rng) for _ in range(150)]
    read = 0
    tested_415 = False
    for bce in candidates:
        if read >= 5:
            break
        st, dt, body, hdr = raw_get(f"/authentic/legalEntity/{bce}/references", "application/json")
        if st != 200:
            if bce in known:
                L.append(f"- {bce} /references → HTTP {st} {body[:200]!r}")
            continue
        try:
            payload = json.loads(body)
        except ValueError:
            L.append(f"- {bce} /references → non JSON: {body[:200]!r}")
            continue
        refs = as_list(payload)
        if not refs:
            continue
        shape = "liste nue" if isinstance(payload, list) else f"objet clés={list(payload)[:6]}"
        with open(os.path.join(out, f"{bce}_references.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        refs.sort(key=ref_sort_key, reverse=True)
        ref = refs[0]
        url = ci(ref, "AccountingDataURL") or f"/authentic/deposit/{ci(ref, 'ReferenceNumber')}/accountingData"
        if not tested_415:
            st_json, *_ = raw_get(url, "application/json")
            L.append(f"- contrôle Accept: application/json sur accountingData → HTTP {st_json}")
            tested_415 = True
        st, dt, body, hdr = raw_get(url, "application/x.jsonxbrl")
        L.append(f"- {bce}: /references {shape}, {len(refs)} dépôts, clés={sorted(ref)[:14]}")
        if st != 200:
            L.append(f"  - accountingData → HTTP {st} {body[:200]!r}")
            continue
        doc = json.loads(body)
        with open(os.path.join(out, f"{bce}_accountingData.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        company = {"bce": bce, "nom": ci(ref, "EnterpriseName") or "", "division": "", "commune": "",
                   "nace": "", "forme": ci(ref, "LegalForm") or ""}
        rec = extract(company, ref, doc)
        t = rubric_table(doc)
        L.append(f"  - accountingData: clés={sorted(doc)[:14]}, {len(t)} rubriques, modèle={ci(ref, 'ModelType')}")
        if rec:
            L.append(f"  - extrait: exercice={rec['exercice']} ebitda={fmt(rec['ebitda'])} bilan={fmt(rec['bilan'])} "
                     f"etp={fmt(rec['etp'])} alertes={rec['alertes'] or '—'}")
            L.append(f"  - administrateurs: {rec['administrateurs'][:300] or 'VIDE'}")
            L.append(f"  - actionnaires: {rec['actionnaires'][:300] or 'VIDE'}")
        else:
            L.append("  - EXTRACTION VIDE: le format ne correspond pas au parseur")
        read += 1

    # Throughput ramp on /references, no client-side pacing.
    L.append("\n## Débit (appels /references sans pacing, numéros BCE valides aléatoires)\n")
    L.append("| Parallélisme | Appels | Appels/min | Latence moy. | Codes HTTP |")
    L.append("| ---: | ---: | ---: | ---: | --- |")
    headers_seen = {}
    for level in (1, 2, 4, 6):
        codes, lat = Counter(), []
        lock = threading.Lock()
        end = time.monotonic() + seconds

        def worker():
            r = random.Random()
            while time.monotonic() < end:
                st, dt, _, hdr = raw_get(f"/authentic/legalEntity/{valid_bce(r)}/references", "application/json")
                with lock:
                    codes[st] += 1
                    lat.append(dt)
                    for k, v in hdr.items():
                        if any(x in k.lower() for x in ("ratelimit", "rate-limit", "quota", "retry-after")):
                            headers_seen[k] = f"{v} (HTTP {st})"
                if st == 429:
                    time.sleep(2)

        threads = [threading.Thread(target=worker) for _ in range(level)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        n = sum(codes.values())
        L.append(f"| {level} | {n} | {n * 60 / seconds:.0f} | {1000 * sum(lat) / max(len(lat), 1):.0f} ms | {dict(codes)} |")
        if codes[429] > n / 4:
            L.append(f"| — | arrêt de la montée : trop de 429 à {level} | | | |")
            break
        time.sleep(5)
    L.append(f"\nEn-têtes de quota observés : {headers_seen or 'aucun'}")
    report = "\n".join(L) + "\n"
    write_atomic(os.path.join(out, "rapport.md"), report)
    print(report)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "resume":
        population = load_population()
        lues, last_attempt = load_state()
        write_outputs(population, lues, last_attempt)
        print(open(os.path.join(STATE, "resume.md"), encoding="utf-8").read())
    elif len(sys.argv) > 1 and sys.argv[1] == "probe":
        probe()
    else:
        run()


if __name__ == "__main__":
    main()
