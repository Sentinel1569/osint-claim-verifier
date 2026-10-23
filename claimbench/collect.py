"""Collectors: web pages, Wayback Machine captures and image metadata.

Parsing is separated from fetching so every function can be tested on
recorded inputs.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime

from bs4 import BeautifulSoup
from PIL import ExifTags, Image

from .evidence import Evidence, sha256_bytes
from .http import fetch

CDX_URL = "https://web.archive.org/cdx/search/cdx"
WAYBACK_RAW = "https://web.archive.org/web/{ts}id_/{url}"


# --------------------------------------------------------------------------- pages

def _first(*vals):
    return next((v.strip() for v in vals if v and str(v).strip()), "")


def _jsonld_dates(soup) -> tuple[str, str]:
    pub = mod = ""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []:
            if isinstance(item, dict):
                pub = pub or item.get("datePublished", "")
                mod = mod or item.get("dateModified", "")
    return pub, mod


def parse_page(html: str, url: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")

    def meta(*names):
        for n in names:
            t = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n}) or soup.find("meta", attrs={"itemprop": n})
            if t and t.get("content"):
                return t["content"]
        return ""
    ld_pub, ld_mod = _jsonld_dates(soup)
    time_tag = soup.find("time", attrs={"datetime": True})
    for t in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form"]):
        t.decompose()
    container = soup.find("article") or soup.find("main") or soup.body or soup
    paras = [" ".join(p.get_text(" ").split()) for p in container.find_all(["p", "li", "h1", "h2", "blockquote"])]
    text = "\n".join(p for p in paras if len(p) > 1) or " ".join(container.get_text(" ").split())
    return {
        "title": _first(meta("og:title", "twitter:title"), soup.title.string if soup.title else ""),
        "publisher": _first(meta("og:site_name", "application-name", "publisher")),
        "author": _first(meta("author", "article:author", "parsely-author")),
        "published": _first(meta("article:published_time", "datePublished", "pubdate", "date", "DC.date.issued"), ld_pub,
                            time_tag["datetime"] if time_tag else "")[:25],
        "modified": _first(meta("article:modified_time", "dateModified", "og:updated_time"), ld_mod)[:25],
        "canonical": _first((soup.find("link", rel="canonical") or {}).get("href") if soup.find("link", rel="canonical") else "", url),
        "images": [img.get("src") for img in container.find_all("img") if img.get("src")][:10],
        "text": text[:20000],
    }


def fetch_page(url: str) -> tuple[dict, Evidence]:
    body, ev = fetch(url, source=re.sub(r"^https?://(www\.)?", "", url).split("/")[0], reliability="F", credibility=6, ttl=3600,
                     headers={"Accept": "text/html,application/xhtml+xml"})
    page = parse_page(body.decode("utf-8", "replace"), url)
    ev.note = "Page retrieved; reliability is set by the analyst per source."
    return page, ev


# --------------------------------------------------------------------------- Wayback

def parse_cdx(rows: list[list[str]]) -> list[dict]:
    if not rows:
        return []
    header, data = rows[0], rows[1:]
    out = []
    for r in data:
        d = dict(zip(header, r))
        ts = d.get("timestamp", "")
        out.append({"timestamp": ts, "date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}" if len(ts) >= 14 else ts,
                    "status": d.get("statuscode", ""), "digest": d.get("digest", ""), "mimetype": d.get("mimetype", ""),
                    "url": WAYBACK_RAW.format(ts=ts, url=d.get("original", "")).replace("id_/", "/")})
    return out


def wayback_captures(url: str, limit: int = 200) -> tuple[list[dict], Evidence]:
    body, ev = fetch(CDX_URL, params={"url": url, "output": "json", "fl": "timestamp,original,statuscode,digest,mimetype",
                                      "limit": limit, "filter": "statuscode:200"},
                     source="Internet Archive Wayback Machine (CDX)", reliability="A", credibility=2, ttl=6 * 3600)
    return parse_cdx(json.loads(body or b"[]")), ev


def wayback_text(url: str, ts: str) -> tuple[str, Evidence]:
    body, ev = fetch(WAYBACK_RAW.format(ts=ts, url=url), source="Internet Archive Wayback Machine", reliability="A", credibility=2, ttl=-1)
    return parse_page(body.decode("utf-8", "replace"), url)["text"], ev


def summarise_captures(caps: list[dict]) -> dict:
    """First/last capture and how often the archived content changed (distinct digests in time order)."""
    if not caps:
        return {"count": 0, "first": "", "last": "", "versions": 0, "changes": []}
    caps = sorted(caps, key=lambda c: c["timestamp"])
    changes, prev = [], None
    for c in caps:
        if prev is not None and c["digest"] != prev["digest"]:
            changes.append({"from": prev["date"], "to": c["date"], "url": c["url"]})
        prev = c
    return {"count": len(caps), "first": caps[0]["date"], "last": caps[-1]["date"], "versions": len({c["digest"] for c in caps}),
            "changes": changes, "first_url": caps[0]["url"]}


# --------------------------------------------------------------------------- text comparison

def shingles(text: str, k: int = 5) -> set[str]:
    w = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))} if w else set()


def similarity(a: str, b: str) -> float:
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return round(len(sa & sb) / len(sa | sb), 3)


def containment(a: str, b: str) -> float:
    """Share of the shorter text's 5-word shingles found in the longer one (robust to added paragraphs)."""
    sa, sb = shingles(a), shingles(b)
    if not sa or not sb:
        return 0.0
    return round(len(sa & sb) / min(len(sa), len(sb)), 3)


def text_diff(old: str, new: str, limit: int = 12) -> list[dict]:
    """Sentence-level additions/removals between two versions of a page."""
    import difflib

    def sents(t):
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", t) if len(s.strip()) > 3]
    out = []
    for line in difflib.ndiff(sents(old), sents(new)):
        if line[:2] in ("- ", "+ "):
            out.append({"op": "removed" if line[0] == "-" else "added", "text": line[2:][:300]})
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- images

def _ratio(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            return v[0] / v[1]
        except (TypeError, ZeroDivisionError, IndexError):
            return 0.0


def _gps(gps: dict) -> tuple[float, float] | None:
    try:
        def dec(vals, ref):
            d, m, s = (_ratio(x) for x in vals)
            v = d + m / 60 + s / 3600
            return -v if ref in ("S", "W") else v
        return round(dec(gps[2], gps[1]), 6), round(dec(gps[4], gps[3]), 6)
    except (KeyError, TypeError, ValueError):
        return None


def dhash(img: Image.Image, size: int = 8) -> str:
    g = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = list(g.getdata())
    bits = "".join("1" if px[r * (size + 1) + c] > px[r * (size + 1) + c + 1] else "0" for r in range(size) for c in range(size))
    return f"{int(bits, 2):016x}"


def image_metadata(raw: bytes, name: str = "image") -> dict:
    img = Image.open(io.BytesIO(raw))
    exif = img.getexif()
    tags = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
    try:
        sub = exif.get_ifd(0x8769)  # Exif sub-IFD (DateTimeOriginal lives here)
        tags.update({ExifTags.TAGS.get(k, str(k)): v for k, v in sub.items()})
    except (KeyError, AttributeError):
        pass
    gps = None
    try:
        gps_ifd = exif.get_ifd(0x8825)
        gps = _gps(dict(gps_ifd)) if gps_ifd else None
    except (KeyError, AttributeError):
        pass
    taken = str(tags.get("DateTimeOriginal") or tags.get("DateTime") or "")
    try:
        taken_iso = datetime.strptime(taken, "%Y:%m:%d %H:%M:%S").isoformat() if taken else ""
    except ValueError:
        taken_iso = ""
    software = str(tags.get("Software") or "")
    return {
        "name": name, "sha256": sha256_bytes(raw), "dhash": dhash(img), "format": img.format, "width": img.width, "height": img.height,
        "taken": taken_iso, "camera": " ".join(str(tags.get(k, "")).strip() for k in ("Make", "Model")).strip(),
        "software": software, "gps": gps, "has_exif": bool(tags),
        "edited_hint": bool(re.search(r"photoshop|gimp|lightroom|snapseed|picsart|canva|affinity", software, re.I)),
        "exif": {k: str(v)[:80] for k, v in tags.items() if k in ("Make", "Model", "Software", "DateTime", "DateTimeOriginal", "Artist",
                                                                  "ImageDescription", "LensModel")},
    }


def hamming_hex(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(re.findall(r"[a-z0-9]+", text.lower())).encode()).hexdigest()
