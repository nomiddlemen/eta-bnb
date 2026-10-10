#!/usr/bin/env python3
"""Fetch raw Moniteur belge pages for a few company numbers, to learn the site's format.

Saves every response under moniteur/probe/ so the parser can be written against real HTML.
"""

import os
import re
import sys
import urllib.parse
import urllib.request

OUT = "moniteur/probe"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) eta-bnb research"}


def get(url, name):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            body = r.read()
            status, final = r.status, r.url
    except Exception as e:
        body, status, final = str(e).encode(), "ERR", url
    with open(os.path.join(OUT, name), "wb") as f:
        f.write(body)
    print(f"{status} {len(body):>8} {name} <- {url} (final {final})")
    return body


def main(numbers):
    os.makedirs(OUT, exist_ok=True)
    for bce in numbers:
        candidates = {
            "list_fr": f"https://www.ejustice.just.fgov.be/cgi_tsv/list.pl?language=fr&btw={bce}&liste=Liste",
            "list_fr_page": f"https://www.ejustice.just.fgov.be/cgi_tsv/list.pl?language=fr&btw={bce}&page=1&la_search=f&caller=list&view_numac=&btw_search=&fromtab=&sum_type=&pdate=&pdda=&pddm=&pddj=&pdfa=&pdfm=&pdfj=&naam=&postkode=&localite=&numpu=&hrc=&akte=&jaar=",
            "kbo": f"https://kbopub.economie.fgov.be/kbopub/zoeknummerform.html?nummer={bce}&actionLu=Rechercher&lang=fr",
        }
        for key, url in candidates.items():
            body = get(url, f"{bce}_{key}.html")
            if key.startswith("list"):
                pdfs = sorted(set(re.findall(rb'href="?([^" >]*\.pdf)', body)))
                print(f"   {len(pdfs)} pdf links, first: {pdfs[:3]}")
                for i, p in enumerate(pdfs[:3]):
                    url_pdf = urllib.parse.urljoin(url, p.decode())
                    get(url_pdf, f"{bce}_{key}_pdf{i}.pdf")


if __name__ == "__main__":
    main(sys.argv[1:] or ["0447639261", "0408287450"])
