"""Ajaia Docs: a lightweight collaborative document editor.

One FastAPI process serves the JSON API under /api and the static frontend.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db as db_module
from .content import ImportError_, file_to_html, html_to_markdown, sanitize_html, title_from_filename
from .models import Document, DocumentShare, User, utcnow
from .seed import seed_users

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def init_db(engine) -> None:
    db_module.Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_users(session)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db(db_module.engine)
    yield


app = FastAPI(title="Ajaia Docs", lifespan=lifespan)


# ---------- Schemas ----------

class UserOut(BaseModel):
    id: int
    name: str
    email: str


class DocumentSummary(BaseModel):
    id: int
    title: str
    owner: UserOut
    updated_at: datetime
    access: Literal["owner", "editor", "viewer"]


class DocumentDetail(DocumentSummary):
    content: str


class DocumentList(BaseModel):
    owned: list[DocumentSummary]
    shared: list[DocumentSummary]


class DocumentCreate(BaseModel):
    title: str = Field(default="Untitled document", max_length=200)
    content: str = ""


class DocumentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    content: Optional[str] = Field(default=None, max_length=1_000_000)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Title cannot be empty")
        return v.strip() if v is not None else v


class ShareCreate(BaseModel):
    email: str = Field(max_length=200)
    role: Literal["editor", "viewer"] = "editor"


class ShareOut(BaseModel):
    user: UserOut
    role: str


# ---------- Auth and access helpers ----------

def current_user(
    x_user_id: Optional[int] = Header(default=None),
    db: Session = Depends(db_module.get_db),
) -> User:
    """Mocked auth: the frontend sends the selected demo user's id in X-User-Id."""
    if x_user_id is None:
        raise HTTPException(401, "Missing X-User-Id header. Pick a user first.")
    user = db.get(User, x_user_id)
    if user is None:
        raise HTTPException(401, "Unknown user")
    return user


def access_level(doc: Document, user: User) -> Optional[str]:
    if doc.owner_id == user.id:
        return "owner"
    for share in doc.shares:
        if share.user_id == user.id:
            return share.role
    return None


def load_doc(doc_id: int, user: User, db: Session, need: str = "view") -> tuple[Document, str]:
    doc = db.get(Document, doc_id)
    level = access_level(doc, user) if doc else None
    # Same 404 for "missing" and "no access" so ids cannot be probed.
    if doc is None or level is None:
        raise HTTPException(404, "Document not found")
    if need == "edit" and level == "viewer":
        raise HTTPException(403, "You have view-only access to this document")
    if need == "owner" and level != "owner":
        raise HTTPException(403, "Only the owner can do this")
    return doc, level


def to_user(u: User) -> UserOut:
    return UserOut(id=u.id, name=u.name, email=u.email)


def to_summary(doc: Document, level: str) -> DocumentSummary:
    updated = doc.updated_at
    if updated.tzinfo is None:  # SQLite drops timezone info. Values are stored in UTC.
        updated = updated.replace(tzinfo=timezone.utc)
    return DocumentSummary(
        id=doc.id, title=doc.title, owner=to_user(doc.owner),
        updated_at=updated, access=level,
    )


def to_detail(doc: Document, level: str) -> DocumentDetail:
    return DocumentDetail(**to_summary(doc, level).model_dump(), content=doc.content)


# ---------- Routes ----------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/users", response_model=list[UserOut])
def list_users(db: Session = Depends(db_module.get_db)):
    return [to_user(u) for u in db.scalars(select(User).order_by(User.id))]


@app.get("/api/documents", response_model=DocumentList)
def list_documents(user: User = Depends(current_user), db: Session = Depends(db_module.get_db)):
    owned = db.scalars(
        select(Document).where(Document.owner_id == user.id).order_by(Document.updated_at.desc())
    ).all()
    shares = db.scalars(select(DocumentShare).where(DocumentShare.user_id == user.id)).all()
    shared = sorted((s for s in shares), key=lambda s: s.document.updated_at, reverse=True)
    return DocumentList(
        owned=[to_summary(d, "owner") for d in owned],
        shared=[to_summary(s.document, s.role) for s in shared],
    )


@app.post("/api/documents", response_model=DocumentDetail, status_code=201)
def create_document(
    body: DocumentCreate,
    user: User = Depends(current_user),
    db: Session = Depends(db_module.get_db),
):
    doc = Document(
        title=body.title.strip() or "Untitled document",
        content=sanitize_html(body.content),
        owner_id=user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return to_detail(doc, "owner")


@app.post("/api/documents/import", response_model=DocumentDetail, status_code=201)
async def import_document(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(db_module.get_db),
):
    data = await file.read()
    try:
        content = file_to_html(file.filename or "", data)
    except ImportError_ as exc:
        raise HTTPException(400, str(exc))
    doc = Document(title=title_from_filename(file.filename or ""), content=content, owner_id=user.id)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return to_detail(doc, "owner")


@app.get("/api/documents/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: int, user: User = Depends(current_user), db: Session = Depends(db_module.get_db)):
    doc, level = load_doc(doc_id, user, db)
    return to_detail(doc, level)


@app.patch("/api/documents/{doc_id}", response_model=DocumentDetail)
def update_document(
    doc_id: int,
    body: DocumentUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(db_module.get_db),
):
    doc, level = load_doc(doc_id, user, db, need="edit")
    if body.title is not None:
        doc.title = body.title
    if body.content is not None:
        doc.content = sanitize_html(body.content)
    doc.updated_at = utcnow()
    db.commit()
    return to_detail(doc, level)


@app.get("/api/documents/{doc_id}/export.md")
def export_markdown(doc_id: int, user: User = Depends(current_user), db: Session = Depends(db_module.get_db)):
    doc, _ = load_doc(doc_id, user, db)
    body = f"# {doc.title}\n\n" + html_to_markdown(doc.content)
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in doc.title).strip() or "document"
    return Response(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.md"'},
    )


@app.delete("/api/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int, user: User = Depends(current_user), db: Session = Depends(db_module.get_db)):
    doc, _ = load_doc(doc_id, user, db, need="owner")
    db.delete(doc)
    db.commit()


@app.get("/api/documents/{doc_id}/shares", response_model=list[ShareOut])
def list_shares(doc_id: int, user: User = Depends(current_user), db: Session = Depends(db_module.get_db)):
    doc, _ = load_doc(doc_id, user, db)
    return [ShareOut(user=to_user(s.user), role=s.role) for s in doc.shares]


@app.post("/api/documents/{doc_id}/shares", response_model=ShareOut, status_code=201)
def add_share(
    doc_id: int,
    body: ShareCreate,
    user: User = Depends(current_user),
    db: Session = Depends(db_module.get_db),
):
    doc, _ = load_doc(doc_id, user, db, need="owner")
    target = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if target is None:
        raise HTTPException(404, f"No user with email {body.email}")
    if target.id == doc.owner_id:
        raise HTTPException(400, "The owner already has access")
    share = next((s for s in doc.shares if s.user_id == target.id), None)
    if share:
        share.role = body.role  # re-sharing updates the role
    else:
        share = DocumentShare(document_id=doc.id, user_id=target.id, role=body.role)
        db.add(share)
    db.commit()
    return ShareOut(user=to_user(target), role=share.role)


@app.delete("/api/documents/{doc_id}/shares/{user_id}", status_code=204)
def remove_share(
    doc_id: int,
    user_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(db_module.get_db),
):
    doc, _ = load_doc(doc_id, user, db, need="owner")
    share = next((s for s in doc.shares if s.user_id == user_id), None)
    if share is None:
        raise HTTPException(404, "Share not found")
    db.delete(share)
    db.commit()


# ---------- Frontend ----------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
