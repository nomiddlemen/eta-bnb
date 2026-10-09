#!/usr/bin/env python3
"""Download the latest KboOpenData_*_Full.zip.

Either ZIP_URL points at the file directly, or KBO_USER / KBO_PASSWORD are the
credentials of a (free) account on kbopub.economie.fgov.be/kbo-open-data.
The login form is parsed rather than hard-coded, and each step prints what it
saw (never the credentials) so a change on the site is easy to diagnose.
"""

import http.cookiejar
import os
import re
import sys
import urllib.parse
import urllib.request

SITE = "https://kbopub.economie.fgov.be/kbo-open-data/"


def main(dst):
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", "Mozilla/5.0 eta-bnb")]
    url = os.environ.get("ZIP_URL")
    if not url:
        user, pwd = os.environ.get("KBO_USER"), os.environ.get("KBO_PASSWORD")
        if not user or not pwd:
            sys.exit("Set ZIP_URL, or the KBO_USER and KBO_PASSWORD repository secrets.")
        resp = opener.open(SITE + "login?lang=fr")
        page = resp.read().decode("utf-8", "replace")
        form = re.search(r"<form[^>]*action=\"([^\"]+)\"[^>]*>(.*?)</form>", page, re.S | re.I)
        if not form:
            sys.exit(f"No login form found at {resp.url}:\n{page[:2000]}")
        action = urllib.parse.urljoin(resp.url, form.group(1))
        fields = dict(re.findall(r"<input[^>]*name=\"([^\"]+)\"[^>]*value=\"([^\"]*)\"", form.group(2), re.I))
        names = re.findall(r"<input[^>]*name=\"([^\"]+)\"", form.group(2), re.I)
        u = next((n for n in names if re.search(r"user|login|mail", n, re.I)), None)
        p = next((n for n in names if re.search(r"pass", n, re.I)), None)
        print(f"login form: action={action} fields={names}")
        if not u or not p:
            sys.exit("Could not identify username/password fields.")
        fields.update({u: user, p: pwd})
        resp = opener.open(action, urllib.parse.urlencode(fields).encode())
        print(f"after login: {resp.url}")
        links, page = [], ""
        for start in (SITE + "affiliation/xml/?files", SITE + "affiliation/xml/", resp.url):
            page = opener.open(start).read().decode("utf-8", "replace")
            links = [urllib.parse.urljoin(start, h) for h in re.findall(r"href=\"([^\"]*Full\.zip[^\"]*)\"", page)]
            if links:
                break
        if not links:
            sys.exit(f"No *_Full.zip link found after login. Last page:\n{page[:2000]}")
        url = sorted(links)[-1]
    print(f"downloading {url}")
    with opener.open(url) as r, open(dst, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    print(f"saved {os.path.getsize(dst) / 1e6:.0f} MB to {dst}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "kbo.zip")
