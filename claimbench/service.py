"""Source intake (URL, image, manual) and case assessment, shared by API and CLI."""

from __future__ import annotations

from . import collect
from .analysis import assess
from .evidence import utcnow
from .http import FetchError
from .store import Store


class LiveProvider:
    def page(self, url):
        return collect.fetch_page(url)

    def captures(self, url):
        return collect.wayback_captures(url)

    def archived_text(self, url, ts):
        return collect.wayback_text(url, ts)


def add_url_source(store: Store, case_id: int, url: str, kind: str = "news", reliability: str = "F", credibility: int = 6,
                   provider=None, archive: bool = True) -> dict:
    provider = provider or LiveProvider()
    page, ev = provider.page(url)
    arch, errors = {}, []
    if archive:
        try:
            caps, cev = provider.captures(url)
            arch = collect.summarise_captures(caps)
            arch["evidence"] = cev.to_dict()
            if arch["versions"] > 1:
                first_ts = min(caps, key=lambda c: c["timestamp"])["timestamp"]
                old, _ = provider.archived_text(url, first_ts)
                arch["diff"] = collect.text_diff(old, page["text"])
                arch["similarity_first_vs_live"] = collect.similarity(old, page["text"])
        except FetchError as exc:
            errors.append(f"Wayback: {exc}")
    sid = store.add_source(case_id, kind, url=url, title=page["title"], publisher=page["publisher"], author=page["author"],
                           published=page["published"], modified=page["modified"], retrieved_at=ev.retrieved_at, sha256=ev.sha256,
                           reliability=reliability, credibility=credibility, text=page["text"], archive=arch)
    return {"id": sid, "page": {k: page[k] for k in ("title", "publisher", "published", "author")}, "errors": errors}


def add_image_source(store: Store, case_id: int, raw: bytes, name: str, url: str = "", reliability: str = "F", credibility: int = 6,
                     caption: str = "", published: str = "") -> dict:
    meta = collect.image_metadata(raw, name)
    sid = store.add_source(case_id, "image", url=url, title=name, publisher="", published=published, sha256=meta["sha256"],
                           reliability=reliability, credibility=credibility, text=caption, image=meta, retrieved_at=utcnow())
    return {"id": sid, "image": meta}


def report(store: Store, case_id: int) -> dict:
    case = store.case(case_id)
    if not case:
        raise KeyError(case_id)
    return assess(case, store.sources(case_id), store.claims(case_id), store.statements(case_id))


STATUS_ICON = {"verified": "✅", "refuted": "❌", "contested": "⚖️", "allegation": "🗣️", "unverified": "❔"}


def to_markdown(r: dict) -> str:
    src = {s["id"]: s for s in r["sources"]}
    out = [f"# Claim verification: {r['case']['title']}", "", r["case"].get("description") or "", "",
           f"_Generated {utcnow()} UTC · {r['summary']['sources']} sources in {r['summary']['independent_groups']} independent groups · "
           f"{r['summary']['contradictions']} contradiction(s) flagged_", "", "## Claims", ""]
    for c in r["claims"]:
        out += [f"### {STATUS_ICON[c['status']]} {c['text']}", "", f"**{c['status'].upper()}**: {c['explanation']}", ""]
        for st in c["statements"]:
            s = src[st["source_id"]]
            q = f" “{st['quote']}”" if st["quote"] else ""
            v = f" (value: {st['value']})" if st["value"] else ""
            out.append(f"- **{st['stance']}** · #{s['id']} {s['publisher'] or s['title']} [{s['reliability']}{s['credibility']}]{q}{v}")
        cc = [x for x in r["contradictions"] if x["claim_id"] == c["id"]]
        if cc:
            out += ["", "Contradictions:"] + [f"- ⚠️ ({x['type']}) {x['detail']}" for x in cc]
        out.append("")
    out += ["## Evidence timeline", ""] + [f"- **{t['date'][:16].replace('T', ' ')}** · {t['kind']} · {t['title']}" for t in r["timeline"] if t["kind"] != "retrieved"]
    out += ["", "## Sources", "", "| # | Kind | Source | Published | Grade | Independence | SHA-256 |", "|---:|---|---|---|---|---|---|"]
    for s in r["sources"]:
        name = f"[{s['publisher'] or s['title'] or s['url']}]({s['url']})" if s["url"] else (s["publisher"] or s["title"])
        ind = f"group {s['independence']['group']}" + (f" ({'; '.join(s['independence']['reasons'][:2])})" if s["independence"]["reasons"] else "")
        out.append(f"| {s['id']} | {s['kind']} | {name} | {(s['published'] or '')[:10]} | {s['reliability']}{s['credibility']} | {ind} | `{(s['sha256'] or '')[:16]}…` |")
    out += ["", "> Verified means corroborated by independent credible sources, not certain. Revisit when new evidence appears.", ""]
    return "\n".join(out)
