"""A fictional verification case with offline page, archive and image fixtures.

"Harborview" and every publisher below are invented; all domains use the
reserved ``.example`` TLD. The case contains a verified claim, a refuted
claim, a contested casualty figure that a news page later edited, and a
viral photo whose EXIF date predates the event.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from .evidence import Evidence, sha256_bytes
from .http import FetchError
from .service import add_image_source, add_url_source
from .store import Store

EVENT = "2026-03-12"
U = {
    "council": "https://www.harborview-council.example/news/bridge-closure",
    "news": "https://www.regional-news.example/2026/03/12/harborview-bridge-closed",
    "wire": "https://www.daily-digest.example/harborview-bridge-closed-railings",
    "social": "https://social.example/@citywatcher/status/9012",
    "factcheck": "https://factcheck.example/viral-harborview-collapse-photo",
}


def _page(title, site, published, body, author=""):
    paras = "".join(f"<p>{p}</p>" for p in body)
    return (f"<html><head><title>{title}</title><meta property='og:site_name' content='{site}'>"
            f"<meta property='article:published_time' content='{published}'><meta name='author' content='{author}'></head>"
            f"<body><header>Menu</header><article><h1>{title}</h1>{paras}</article><footer>© {site}</footer></body></html>")


NEWS_V1 = ["Harborview Bridge was closed to all traffic on Thursday 12 March after a section of pedestrian railing gave way during the morning rush.",
           "Three people were injured and taken to hospital with minor injuries, according to a witness at the scene.",
           "The city council said engineers would carry out a full structural inspection before the bridge reopens.",
           "Commuters were advised to use the northern ring road while the closure remains in place."]
NEWS_V2 = NEWS_V1[:1] + ["Five people were injured and taken to hospital, according to updated figures from the ambulance service."] + NEWS_V1[2:]

PAGES = {
    U["council"]: _page("Temporary closure of Harborview Bridge", "Harborview City Council", "2026-03-12T11:30:00+01:00",
                        ["Harborview Bridge is closed from 12 March 2026 while engineers carry out a structural inspection following damage to a "
                         "pedestrian railing.", "There has been no structural collapse of the bridge. No injuries were reported to the council.",
                         "We will publish an update when the inspection is complete."]),
    U["news"]: _page("Harborview Bridge closed after railing gives way", "Regional News", "2026-03-12T09:05:00+01:00", NEWS_V2, "J. Doe"),
    U["wire"]: _page("Harborview Bridge closed after railing gives way", "Daily Digest", "2026-03-12T10:40:00+01:00",
                     NEWS_V1 + ["This article was syndicated from a partner newsroom."]),
    U["social"]: _page("@citywatcher on Social", "Social", "2026-03-12T08:52:00+01:00",
                       ["BREAKING: Harborview Bridge has COLLAPSED!!! Dozens injured, share this photo before it gets deleted"]),
    U["factcheck"]: _page("No, Harborview Bridge did not collapse: the viral photo is from 2023", "FactCheck Example", "2026-03-13T15:00:00+01:00",
                          ["A photo shared widely on 12 March claims to show a collapsed Harborview Bridge.",
                           "The image is a 2023 photograph of a different bridge under demolition; metadata and reverse-image search both date it "
                           "to August 2023.", "The bridge was closed after a railing failed, but it did not collapse."]),
}
CAPTURES = {
    U["news"]: [["timestamp", "original", "statuscode", "digest", "mimetype"],
                ["20260312091500", U["news"], "200", "AAAA1111", "text/html"],
                ["20260312140200", U["news"], "200", "AAAA1111", "text/html"],
                ["20260313080000", U["news"], "200", "BBBB2222", "text/html"]],
    U["council"]: [["timestamp", "original", "statuscode", "digest", "mimetype"], ["20260312120000", U["council"], "200", "CCCC3333", "text/html"]],
}
ARCHIVED = {(U["news"], "20260312091500"): PAGES[U["news"]].replace("".join(f"<p>{p}</p>" for p in NEWS_V2), "".join(f"<p>{p}</p>" for p in NEWS_V1))}


def viral_photo() -> bytes:
    img = Image.new("RGB", (640, 400), (140, 160, 180))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 260, 640, 400), fill=(60, 80, 110))
    d.polygon([(80, 250), (300, 200), (330, 330), (60, 300)], fill=(90, 90, 90))
    d.polygon([(360, 330), (380, 210), (580, 240), (600, 300)], fill=(95, 95, 95))
    exif = Image.Exif()
    exif[0x010F] = "DemoCam"            # Make
    exif[0x0110] = "DC-200"             # Model
    exif[0x0131] = "Adobe Photoshop 25.0 (Windows)"
    exif[0x0132] = "2023:08:02 10:01:00"
    exif.get_ifd(0x8769)[0x9003] = "2023:08:01 17:42:10"   # DateTimeOriginal
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif, quality=85)
    return buf.getvalue()


class DemoProvider:
    def page(self, url):
        from .collect import parse_page
        html = PAGES.get(url)
        if html is None:
            raise FetchError(f"demo has no page for {url}")
        return parse_page(html, url), Evidence(source=url.split("/")[2] + " [demo]", url=url, sha256=sha256_bytes(html), method="demo")

    def captures(self, url):
        from .collect import parse_cdx
        rows = CAPTURES.get(url, [])
        return parse_cdx(rows), Evidence(source="Internet Archive Wayback Machine (CDX) [demo]", sha256=sha256_bytes(str(rows)), method="demo",
                                         reliability="A", credibility=2)

    def archived_text(self, url, ts):
        from .collect import parse_page
        html = ARCHIVED.get((url, ts), PAGES[url])
        return parse_page(html, url)["text"], Evidence(source="Wayback [demo]", method="demo")


def seed(store: Store) -> int:
    p = DemoProvider()
    cid = store.add_case("Harborview Bridge incident (demo)", "Fictional case: viral claims of a bridge collapse on 12 March 2026.")
    s = {k: add_url_source(store, cid, U[k], kind, rel, cred, p)["id"] for k, kind, rel, cred in (
        ("council", "official", "A", 2), ("news", "news", "B", 2), ("wire", "news", "C", 3), ("social", "social", "E", 5),
        ("factcheck", "factcheck", "B", 2))}
    s["photo"] = add_image_source(store, cid, viral_photo(), "viral-bridge.jpg", U["social"], "E", 5,
                                  "Photo attached to the @citywatcher post", "2026-03-12T08:52:00+01:00")["id"]
    c1 = store.add_claim(cid, "Harborview Bridge was closed to traffic on 12 March 2026", EVENT)
    c2 = store.add_claim(cid, "Harborview Bridge collapsed", EVENT)
    c3 = store.add_claim(cid, "People were injured at Harborview Bridge on 12 March 2026", EVENT)
    c4 = store.add_claim(cid, "The viral photo shows Harborview Bridge on 12 March 2026", EVENT)
    st = store.set_statement
    st(c1, s["council"], "supports", "Harborview Bridge is closed from 12 March 2026")
    st(c1, s["news"], "supports", "closed to all traffic on Thursday 12 March")
    st(c1, s["wire"], "supports", "closed to all traffic on Thursday 12 March")
    st(c1, s["factcheck"], "supports", "The bridge was closed after a railing failed")
    st(c2, s["social"], "supports", "Harborview Bridge has COLLAPSED!!!")
    st(c2, s["council"], "refutes", "There has been no structural collapse of the bridge.")
    st(c2, s["factcheck"], "refutes", "it did not collapse")
    st(c3, s["news"], "supports", "Five people were injured", value="5")
    st(c3, s["wire"], "supports", "Three people were injured", value="3")
    st(c3, s["social"], "supports", "Dozens injured", value="dozens")
    st(c3, s["council"], "refutes", "No injuries were reported to the council.", value="0")
    st(c4, s["social"], "supports", "share this photo")
    st(c4, s["photo"], "supports", "", note="The image itself, as posted")
    st(c4, s["factcheck"], "refutes", "The image is a 2023 photograph of a different bridge")
    return cid
