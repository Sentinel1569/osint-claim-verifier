"""FastAPI application: JSON API + workbench UI."""

from __future__ import annotations

import base64
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .demo import DemoProvider, seed
from .evidence import RELIABILITY
from .http import FetchError
from .service import add_image_source, add_url_source, report, to_markdown
from .store import KINDS, Store

STATIC = Path(__file__).parent / "static"


def _grade(rel: str, cred: int):
    if rel not in RELIABILITY or not 1 <= int(cred) <= 6:
        raise HTTPException(422, "reliability must be A-F and credibility 1-6")


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="Claim Verification Workbench", version=__version__)
    st = Store(db_path)

    def case_or_404(cid):
        if not st.case(cid):
            raise HTTPException(404, "case not found")

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__, "kinds": KINDS}

    @app.get("/api/cases")
    def cases():
        return st.cases()

    @app.post("/api/cases")
    def new_case(title: str = Body(...), description: str = Body("")):
        if not title.strip():
            raise HTTPException(422, "title is required")
        return {"id": st.add_case(title.strip(), description.strip())}

    @app.delete("/api/cases/{cid}")
    def del_case(cid: int):
        st.delete_case(cid)
        return {"ok": True}

    @app.get("/api/cases/{cid}")
    def get_case(cid: int):
        case_or_404(cid)
        return report(st, cid)

    @app.get("/api/cases/{cid}/report.md", response_class=PlainTextResponse)
    def get_md(cid: int):
        case_or_404(cid)
        return to_markdown(report(st, cid))

    @app.post("/api/cases/{cid}/sources/url")
    def src_url(cid: int, url: str = Body(...), kind: str = Body("news"), reliability: str = Body("F"), credibility: int = Body(6),
                archive: bool = Body(True)):
        case_or_404(cid)
        _grade(reliability, credibility)
        if not url.startswith(("http://", "https://")):
            raise HTTPException(422, "URL must start with http:// or https://")
        provider = DemoProvider() if ".example/" in url else None
        try:
            return add_url_source(st, cid, url, kind, reliability, credibility, provider, archive)
        except FetchError as exc:
            raise HTTPException(502, f"could not retrieve the page: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/cases/{cid}/sources/image")
    def src_image(cid: int, name: str = Body(...), content_b64: str = Body(...), url: str = Body(""), reliability: str = Body("F"),
                  credibility: int = Body(6), caption: str = Body(""), published: str = Body("")):
        case_or_404(cid)
        _grade(reliability, credibility)
        try:
            return add_image_source(st, cid, base64.b64decode(content_b64), name, url, reliability, credibility, caption, published)
        except (OSError, ValueError) as exc:
            raise HTTPException(422, f"not a readable image: {exc}") from exc

    @app.post("/api/cases/{cid}/sources/manual")
    def src_manual(cid: int, kind: str = Body("other"), title: str = Body(...), publisher: str = Body(""), url: str = Body(""),
                   published: str = Body(""), text: str = Body(""), reliability: str = Body("F"), credibility: int = Body(6)):
        case_or_404(cid)
        _grade(reliability, credibility)
        from .evidence import sha256_bytes
        try:
            return {"id": st.add_source(cid, kind, title=title, publisher=publisher, url=url, published=published, text=text,
                                        reliability=reliability, credibility=credibility, sha256=sha256_bytes(text) if text else "")}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.patch("/api/sources/{sid}")
    def patch_source(sid: int, fields: dict = Body(..., embed=True)):
        if "reliability" in fields or "credibility" in fields:
            _grade(fields.get("reliability", "F"), fields.get("credibility", 6))
        st.update_source(sid, **fields)
        return {"ok": True}

    @app.delete("/api/sources/{sid}")
    def del_source(sid: int):
        st.delete_source(sid)
        return {"ok": True}

    @app.post("/api/cases/{cid}/claims")
    def new_claim(cid: int, text: str = Body(...), event_date: str = Body("")):
        case_or_404(cid)
        if not text.strip():
            raise HTTPException(422, "claim text is required")
        return {"id": st.add_claim(cid, text.strip(), event_date[:10])}

    @app.delete("/api/claims/{clid}")
    def del_claim(clid: int):
        st.delete_claim(clid)
        return {"ok": True}

    @app.post("/api/statements")
    def statement(claim_id: int = Body(...), source_id: int = Body(...), stance: str = Body(...), quote: str = Body(""), value: str = Body(""),
                  note: str = Body("")):
        try:
            st.set_statement(claim_id, source_id, stance, quote, value, note)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"ok": True}

    @app.post("/api/demo")
    def demo():
        return {"id": seed(st)}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app


app = create_app()
