"""Command-line interface.

    python -m claimbench case new "Title" [--description ...]
    python -m claimbench case list
    python -m claimbench source url <case> https://... [--kind news] [--grade B2]
    python -m claimbench source image <case> photo.jpg [--grade E5]
    python -m claimbench claim <case> "Claim text" [--event-date 2026-03-12]
    python -m claimbench link <claim> <source> supports|refutes|attributes|mentions [--quote ...] [--value ...]
    python -m claimbench report <case> [--markdown]
    python -m claimbench demo
    python -m claimbench serve
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .demo import seed
from .service import add_image_source, add_url_source, report, to_markdown
from .store import STANCES, Store


def _grade(g: str) -> tuple[str, int]:
    return g[0].upper(), int(g[1])


def _print(r: dict) -> None:
    print(f"\n  {r['case']['title']}\n")
    for c in r["claims"]:
        print(f"  [{c['status'].upper():<10}] {c['text']}\n               {c['explanation']}")
    if r["contradictions"]:
        print("\n  Contradictions:")
        for x in r["contradictions"]:
            print(f"   ! claim {x['claim_id']} ({x['type']}): {x['detail']}")
    print()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="claimbench", description="Open-Source Claim Verification Workbench")
    p.add_argument("--db")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("case")
    cs = c.add_subparsers(dest="action", required=True)
    cn = cs.add_parser("new")
    cn.add_argument("title")
    cn.add_argument("--description", default="")
    cs.add_parser("list")
    s = sub.add_parser("source")
    ss = s.add_subparsers(dest="action", required=True)
    su = ss.add_parser("url")
    su.add_argument("case", type=int)
    su.add_argument("url")
    su.add_argument("--kind", default="news")
    su.add_argument("--grade", default="F6")
    su.add_argument("--no-archive", action="store_true")
    si = ss.add_parser("image")
    si.add_argument("case", type=int)
    si.add_argument("path")
    si.add_argument("--grade", default="F6")
    si.add_argument("--url", default="")
    cl = sub.add_parser("claim")
    cl.add_argument("case", type=int)
    cl.add_argument("text")
    cl.add_argument("--event-date", default="")
    lk = sub.add_parser("link")
    lk.add_argument("claim", type=int)
    lk.add_argument("source", type=int)
    lk.add_argument("stance", choices=STANCES)
    lk.add_argument("--quote", default="")
    lk.add_argument("--value", default="")
    r = sub.add_parser("report")
    r.add_argument("case", type=int)
    r.add_argument("--markdown", action="store_true")
    sub.add_parser("demo")
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    a = p.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("claimbench.app:app", host=a.host, port=a.port, reload=a.reload)
        return 0
    st = Store(a.db)
    if a.cmd == "case":
        if a.action == "new":
            print(f"case {st.add_case(a.title, a.description)} created")
        else:
            for row in st.cases():
                print(f"  {row['id']:>3}  {row['title']:<50} {row['claims']} claims · {row['sources']} sources")
    elif a.cmd == "source":
        rel, cred = _grade(a.grade)
        if a.action == "url":
            out = add_url_source(st, a.case, a.url, a.kind, rel, cred, archive=not a.no_archive)
            print(f"source {out['id']}: {out['page']['title']} ({out['page']['publisher'] or 'unknown publisher'})")
            for e in out["errors"]:
                print(f"  ! {e}")
        else:
            out = add_image_source(st, a.case, Path(a.path).read_bytes(), Path(a.path).name, a.url, rel, cred)
            m = out["image"]
            print(f"source {out['id']}: {m['width']}x{m['height']} taken {m['taken'] or 'unknown'} camera {m['camera'] or '—'} software {m['software'] or '—'}")
    elif a.cmd == "claim":
        print(f"claim {st.add_claim(a.case, a.text, a.event_date)} added")
    elif a.cmd == "link":
        st.set_statement(a.claim, a.source, a.stance, a.quote, a.value)
        print("linked")
    elif a.cmd == "report":
        rep = report(st, a.case)
        sys.stdout.write(to_markdown(rep)) if a.markdown else _print(rep)
    elif a.cmd == "demo":
        _print(report(st, seed(st)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
