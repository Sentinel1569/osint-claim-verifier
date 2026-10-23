import base64

import pytest
from fastapi.testclient import TestClient

from claimbench.analysis import _num, assess, independence_groups
from claimbench.app import create_app
from claimbench.collect import containment, image_metadata, parse_cdx, parse_page, summarise_captures, text_diff
from claimbench.demo import PAGES, U, seed, viral_photo
from claimbench.service import report, to_markdown
from claimbench.store import Store


@pytest.fixture
def st(tmp_path):
    return Store(str(tmp_path / "c.db"))


def test_parse_page_metadata_and_text():
    p = parse_page(PAGES[U["council"]], U["council"])
    assert p["publisher"] == "Harborview City Council" and p["published"].startswith("2026-03-12")
    assert "No injuries" in p["text"] and "Menu" not in p["text"]
    ld = parse_page('<html><head><script type="application/ld+json">{"datePublished":"2025-01-02T00:00:00Z"}</script></head><body><p>x</p></body></html>')
    assert ld["published"].startswith("2025-01-02")


def test_cdx_and_change_summary():
    caps = parse_cdx([["timestamp", "original", "statuscode", "digest", "mimetype"],
                      ["20260101000000", "u", "200", "A", "text/html"], ["20260102000000", "u", "200", "A", "text/html"],
                      ["20260103000000", "u", "200", "B", "text/html"]])
    s = summarise_captures(caps)
    assert s["count"] == 3 and s["versions"] == 2 and len(s["changes"]) == 1 and s["first"].startswith("2026-01-01")
    assert summarise_captures([])["count"] == 0
    d = text_diff("A happened. Three were hurt.", "A happened. Five were hurt.")
    assert {x["op"] for x in d} == {"added", "removed"}


def test_image_metadata():
    m = image_metadata(viral_photo(), "x.jpg")
    assert m["taken"] == "2023-08-01T17:42:10" and m["camera"] == "DemoCam DC-200" and m["edited_hint"]
    assert len(m["dhash"]) == 16


def test_numbers_and_containment():
    assert _num("dozens") == 24 and _num("5 people") == 5 and _num("none") == 0 and _num("unknown") is None
    a = "one two three four five six seven eight nine ten"
    assert containment(a, a + " eleven twelve thirteen") == 1.0


def test_independence_groups():
    srcs = [{"id": 1, "url": "u1", "publisher": "A", "text": "x" * 10}, {"id": 2, "url": "u2", "publisher": "a", "text": ""},
            {"id": 3, "url": "u1", "publisher": "", "text": ""}, {"id": 4, "url": "u4", "publisher": "B", "text": ""}]
    g = independence_groups(srcs)
    assert g[1]["id"] == g[2]["id"] == g[3]["id"] != g[4]["id"]


def test_demo_case_statuses_and_flags(st):
    r = report(st, seed(st))
    status = {c["text"]: c["status"] for c in r["claims"]}
    assert status["Harborview Bridge was closed to traffic on 12 March 2026"] == "verified"
    assert status["Harborview Bridge collapsed"] == "refuted"
    assert status["People were injured at Harborview Bridge on 12 March 2026"] == "contested"
    assert status["The viral photo shows Harborview Bridge on 12 March 2026"] == "refuted"
    types = {x["type"] for x in r["contradictions"]}
    assert {"stance", "value", "edited", "image_date", "image_software"} <= types
    # the syndicated copy is not independent of the original
    srcs = {s["publisher"]: s for s in r["sources"]}
    assert srcs["Regional News"]["independence"]["group"] == srcs["Daily Digest"]["independence"]["group"]
    # the edit flag only attaches to the claim the edit touched
    edited = [x for x in r["contradictions"] if x["type"] == "edited"]
    assert len(edited) == 1
    md = to_markdown(r)
    assert "VERIFIED" in md and "## Evidence timeline" in md


def test_status_rules(st):
    cid = st.add_case("t")
    a = st.add_source(cid, "news", title="a", publisher="A", reliability="B", credibility=2)
    b = st.add_source(cid, "social", title="b", publisher="B", reliability="E", credibility=5)
    o = st.add_source(cid, "official", title="o", publisher="O", reliability="A", credibility=2)
    c1, c2, c3, c4 = (st.add_claim(cid, t) for t in ("one", "two", "three", "four"))
    st.set_statement(c1, a, "supports")
    st.set_statement(c2, b, "supports")
    st.set_statement(c3, o, "supports")
    st.set_statement(c4, a, "attributes")
    r = assess(st.case(cid), st.sources(cid), st.claims(cid), st.statements(cid))
    s = {c["text"]: c["status"] for c in r["claims"]}
    assert s == {"one": "allegation", "two": "allegation", "three": "verified", "four": "allegation"}
    with pytest.raises(ValueError):
        st.set_statement(c1, a, "maybe")


def test_api(tmp_path):
    c = TestClient(create_app(str(tmp_path / "api.db")))
    cid = c.post("/api/demo").json()["id"]
    r = c.get(f"/api/cases/{cid}").json()
    assert r["summary"]["claims"] == 4
    assert c.get("/api/cases/999").status_code == 404
    new = c.post("/api/cases", json={"title": "x"}).json()["id"]
    assert c.post(f"/api/cases/{new}/sources/url", json={"url": "ftp://x"}).status_code == 422
    assert c.post(f"/api/cases/{new}/sources/url", json={"url": U["council"], "reliability": "Z"}).status_code == 422
    sid = c.post(f"/api/cases/{new}/sources/url", json={"url": U["council"], "kind": "official", "reliability": "A", "credibility": 2}).json()["id"]
    img = c.post(f"/api/cases/{new}/sources/image", json={"name": "p.jpg", "content_b64": base64.b64encode(viral_photo()).decode()}).json()
    assert img["image"]["taken"].startswith("2023")
    assert c.post(f"/api/cases/{new}/sources/image", json={"name": "p.jpg", "content_b64": base64.b64encode(b"nope").decode()}).status_code == 422
    cl = c.post(f"/api/cases/{new}/claims", json={"text": "Bridge closed", "event_date": "2026-03-12"}).json()["id"]
    assert c.post("/api/statements", json={"claim_id": cl, "source_id": sid, "stance": "supports"}).status_code == 200
    assert c.get(f"/api/cases/{new}").json()["claims"][0]["status"] == "verified"
    assert c.patch(f"/api/sources/{sid}", json={"fields": {"reliability": "E", "credibility": 5}}).status_code == 200
    assert c.get(f"/api/cases/{new}").json()["claims"][0]["status"] == "allegation"
    assert c.get(f"/api/cases/{new}/report.md").status_code == 200
    assert c.get("/").status_code == 200
