"""Claim assessment: independence, status, contradictions and the evidence timeline.

Status vocabulary (deliberately conservative):

* **verified**: at least two *independent* credible sources support the
  claim, or a credible primary/official source does, and no credible source
  refutes it
* **refuted**: credible refutation and no credible support
* **contested**: credible sources on both sides
* **allegation**: asserted only by low-credibility or single non-primary
  sources, or only *attributed* ("X says…") without endorsement
* **unverified**: no source has been linked yet
"""

from __future__ import annotations

import re
from datetime import datetime

from .collect import containment, hamming_hex
from .evidence import admiralty_confidence, combine_confidence, confidence_label

CREDIBLE = 0.6
SYNDICATION = 0.6
PRIMARY_KINDS = {"official", "document"}


def source_conf(s: dict) -> float:
    return admiralty_confidence(s.get("reliability") or "F", int(s.get("credibility") or 6))


def independence_groups(sources: list[dict]) -> dict[int, dict]:
    """Union-find over sources that are not independent of one another."""
    parent = {s["id"]: s["id"] for s in sources}
    why: dict[int, list[str]] = {s["id"]: [] for s in sources}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b, reason):
        ra, rb = find(a["id"]), find(b["id"])
        if ra != rb:
            parent[rb] = ra
        why[a["id"]].append(f"{reason} as #{b['id']}")
        why[b["id"]].append(f"{reason} as #{a['id']}")

    for i, a in enumerate(sources):
        for b in sources[i + 1:]:
            if a.get("url") and a["url"] == b.get("url"):
                union(a, b, "same page")
            elif a.get("publisher") and a["publisher"].lower() == (b.get("publisher") or "").lower():
                union(a, b, "same publisher")
            elif len(a.get("text") or "") > 200 and len(b.get("text") or "") > 200 and containment(a["text"], b["text"]) >= SYNDICATION:
                union(a, b, "near-identical text (syndicated copy)")
            ia, ib = (a.get("image") or {}).get("dhash"), (b.get("image") or {}).get("dhash")
            if ia and ib and hamming_hex(ia, ib) <= 6:
                union(a, b, "same image")
    members: dict[int, list[int]] = {}
    for s in sources:
        members.setdefault(find(s["id"]), []).append(s["id"])
    return {s["id"]: {"id": find(s["id"]), "members": members[find(s["id"])], "reasons": sorted(set(why[s["id"]]))} for s in sources}


NUM_WORDS = {"no": 0, "none": 0, "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
             "nine": 9, "ten": 10, "dozens": 24, "dozen": 12, "hundreds": 200}


def _num(v: str) -> float | None:
    v = (v or "").strip().lower()
    m = re.search(r"-?\d+(?:[.,]\d+)?", v)
    if m:
        return float(m.group(0).replace(",", ""))
    for w, n in NUM_WORDS.items():
        if re.search(rf"\b{w}\b", v):
            return float(n)
    return None


def _date(v: str) -> str:
    m = re.search(r"\d{4}-\d{2}-\d{2}", v or "")
    return m.group(0) if m else ""


def assess(case: dict, sources: list[dict], claims: list[dict], statements: list[dict]) -> dict:
    by_id = {s["id"]: s for s in sources}
    groups = independence_groups(sources)
    out_claims, contradictions, timeline = [], [], []

    for c in claims:
        sts = [st for st in statements if st["claim_id"] == c["id"] and st["source_id"] in by_id]

        def grp(stance, credible_only=True, sts=sts):
            gs: dict[int, float] = {}
            for st in sts:
                if st["stance"] != stance:
                    continue
                s = by_id[st["source_id"]]
                conf = source_conf(s)
                if credible_only and conf < CREDIBLE:
                    continue
                g = groups[s["id"]]["id"]
                gs[g] = max(gs.get(g, 0), conf)
            return gs
        sup, ref = grp("supports"), grp("refutes")
        sup_any, attrib = grp("supports", False), grp("attributes", False)
        primary = any(by_id[st["source_id"]]["kind"] in PRIMARY_KINDS and st["stance"] == "supports" and source_conf(by_id[st["source_id"]]) >= 0.75
                      for st in sts)
        if not sts:
            status, why = "unverified", "No sources linked yet."
        elif sup and ref:
            status, why = "contested", f"{len(sup)} independent credible source group(s) support it and {len(ref)} refute it."
        elif ref:
            status, why = "refuted", f"Refuted by {len(ref)} independent credible source group(s); no credible support."
        elif len(sup) >= 2:
            status, why = "verified", f"Supported by {len(sup)} independent credible source groups; no credible refutation."
        elif primary:
            status, why = "verified", "Supported by a credible primary/official source; no credible refutation."
        elif sup_any or attrib:
            n = len(sup_any)
            status, why = "allegation", ("Only reported second-hand (attributed, not endorsed)." if not sup_any else
                                         f"Asserted by {n} independent source group(s), none both credible and corroborated.")
        else:
            status, why = "unverified", "Linked sources only mention the claim."
        support_score = combine_confidence((str(g), v) for g, v in grp("supports", False).items())
        refute_score = combine_confidence((str(g), v) for g, v in grp("refutes", False).items())

        # ---- contradictions
        cc = []
        credible_sup = [st for st in sts if st["stance"] == "supports" and source_conf(by_id[st["source_id"]]) >= CREDIBLE]
        credible_ref = [st for st in sts if st["stance"] == "refutes" and source_conf(by_id[st["source_id"]]) >= CREDIBLE]
        for a in credible_sup:
            for b in credible_ref:
                cc.append({"type": "stance", "severity": "high", "sources": [a["source_id"], b["source_id"]],
                           "detail": f"#{a['source_id']} {by_id[a['source_id']]['publisher'] or by_id[a['source_id']]['title']} supports; "
                                     f"#{b['source_id']} {by_id[b['source_id']]['publisher'] or by_id[b['source_id']]['title']} refutes."})
        valued = [st for st in sts if st["value"]]
        conflict = False
        for i, a in enumerate(valued):
            for b in valued[i + 1:]:
                na, nb = _num(a["value"]), _num(b["value"])
                da, db = _date(a["value"]), _date(b["value"])
                conflict = conflict or (na is not None and nb is not None and abs(na - nb) > max(0.1 * max(abs(na), abs(nb)), 0.5)) \
                    or bool(da and db and da != db)
        if conflict:
            vals = "; ".join(f"“{st['value']}” (#{st['source_id']})" for st in sorted(valued, key=lambda x: _num(x["value"]) or 0))
            cc.append({"type": "value", "severity": "medium", "sources": [st["source_id"] for st in valued],
                       "detail": f"Sources report different values: {vals}."})
        for st in sts:
            s = by_id[st["source_id"]]
            arch = s.get("archive") or {}
            words = {w for w in re.findall(r"[a-z]{4,}", (st["quote"] + " " + st["value"]).lower())}
            touched = any(len(words & set(re.findall(r"[a-z]{4,}", d["text"].lower()))) >= 2 for d in arch.get("diff", []))
            if arch.get("changes") and (touched or not arch.get("diff")):
                cc.append({"type": "edited", "severity": "medium", "sources": [s["id"]],
                           "detail": f"#{s['id']} changed {len(arch['changes'])} time(s) after first capture"
                                     + (f"; {arch['diff'][0]['op']}: “{arch['diff'][0]['text'][:120]}”" if arch.get("diff") else "") + "."})
            img = s.get("image") or {}
            if img.get("taken") and c.get("event_date") and img["taken"][:10] < c["event_date"]:
                days = (datetime.fromisoformat(c["event_date"]) - datetime.fromisoformat(img["taken"][:10])).days
                if days > 1:
                    cc.append({"type": "image_date", "severity": "high", "sources": [s["id"]],
                               "detail": f"Image #{s['id']} EXIF capture date {img['taken'][:10]} is {days} days before the event ({c['event_date']}): "
                                         "possibly a recycled photo (EXIF can be wrong or altered)."})
            if img.get("edited_hint"):
                cc.append({"type": "image_software", "severity": "low", "sources": [s["id"]],
                           "detail": f"Image #{s['id']} metadata names editing software ({img['software']}). Editing is not proof of manipulation."})
            if s.get("published") and c.get("event_date") and s["published"][:10] < c["event_date"] and st["stance"] == "supports":
                cc.append({"type": "chronology", "severity": "high", "sources": [s["id"]],
                           "detail": f"#{s['id']} was published {s['published'][:10]}, before the event date {c['event_date']} it reports on."})
        for x in cc:
            x["claim_id"] = c["id"]
        contradictions += cc
        out_claims.append({**c, "status": status, "explanation": why, "support": support_score, "refute": refute_score,
                           "support_label": confidence_label(support_score), "statements": sts,
                           "independent_support": len(sup), "independent_refute": len(ref), "contradictions": len(cc)})

    by_date: dict[str, list[str]] = {}
    for c in claims:
        if c.get("event_date"):
            by_date.setdefault(c["event_date"], []).append(c["text"])
    for d, texts in by_date.items():
        title = f"Claimed event: {texts[0][:90]}" if len(texts) == 1 else f"Date of the claimed events ({len(texts)} claims)"
        timeline.append({"date": d, "kind": "event", "title": title})
    for s in sources:
        label = s["publisher"] or s["title"] or s["url"] or f"source #{s['id']}"
        if s.get("published"):
            timeline.append({"date": s["published"][:19], "kind": "published", "title": f"#{s['id']} published: {label}", "source_id": s["id"]})
        arch = s.get("archive") or {}
        if arch.get("first"):
            timeline.append({"date": arch["first"], "kind": "archived", "title": f"#{s['id']} first archived by the Wayback Machine", "source_id": s["id"]})
        for ch in arch.get("changes", []):
            timeline.append({"date": ch["to"], "kind": "edited", "title": f"#{s['id']} archived content changed", "source_id": s["id"], "url": ch.get("url")})
        img = s.get("image") or {}
        if img.get("taken"):
            timeline.append({"date": img["taken"], "kind": "captured", "title": f"#{s['id']} image captured (EXIF{', ' + img['camera'] if img.get('camera') else ''})",
                             "source_id": s["id"]})
        timeline.append({"date": (s.get("retrieved_at") or "")[:19], "kind": "retrieved", "title": f"#{s['id']} retrieved for this case", "source_id": s["id"]})

    counts: dict[str, int] = {}
    for c in out_claims:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    grp_view = {}
    for sid, g in groups.items():
        grp_view[sid] = {"group": g["id"], "size": len(g["members"]), "reasons": g["reasons"]}
    return {"case": case, "sources": [{**s, "confidence": source_conf(s), "independence": grp_view[s["id"]]} for s in sources],
            "claims": out_claims, "contradictions": contradictions, "timeline": sorted((t for t in timeline if t["date"]), key=lambda t: t["date"]),
            "summary": {"claims": len(claims), "sources": len(sources), "independent_groups": len({g["id"] for g in groups.values()}),
                        "contradictions": len(contradictions), "by_status": counts}}
