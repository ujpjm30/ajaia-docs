"""Ajaia Docs: a lightweight collaborative document editor.

One FastAPI process serves the JSON API under /api and the static frontend.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db as db_module
from .content import ImportError_, file_to_html, html_to_markdown, sanitize_html, title_from_filename
from .models import ActivityEvent, Document, DocumentShare, User, utcnow
from .seed import seed_users

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Autosave fires every second while someone types. Consecutive edits by the same
# person within this window are merged into one "edited" activity entry.
EDIT_MERGE_WINDOW = timedelta(minutes=10)


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
    version: int
    updated_by: Optional[UserOut]


class DocumentList(BaseModel):
    owned: list[DocumentSummary]
    shared: list[DocumentSummary]


class DocumentCreate(BaseModel):
    title: str = Field(default="Untitled document", max_length=200)
    content: str = ""


class DocumentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    content: Optional[str] = Field(default=None, max_length=1_000_000)
    # The content version the client last loaded. If someone else saved since,
    # the server rejects the save with 409 instead of silently overwriting.
    base_version: Optional[int] = None

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


class ActivityOut(BaseModel):
    actor: UserOut
    action: str
    detail: str
    created_at: datetime


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


def log_activity(db: Session, doc: Document, actor: User, action: str, detail: str = "") -> None:
    if action == "edited":
        last = db.scalar(
            select(ActivityEvent)
            .where(ActivityEvent.document_id == doc.id)
            .order_by(ActivityEvent.id.desc())
            .limit(1)
        )
        if (
            last is not None
            and last.action == "edited"
            and last.actor_id == actor.id
            and utcnow() - as_utc(last.created_at) < EDIT_MERGE_WINDOW
        ):
            last.created_at = utcnow()  # extend the existing entry instead of adding a new one
            return
    db.add(ActivityEvent(document_id=doc.id, actor_id=actor.id, action=action, detail=detail))


def as_utc(value: datetime) -> datetime:
    # SQLite drops timezone info. All values are stored in UTC.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def to_user(u: User) -> UserOut:
    return UserOut(id=u.id, name=u.name, email=u.email)


def to_summary(doc: Document, level: str) -> DocumentSummary:
    return DocumentSummary(
        id=doc.id, title=doc.title, owner=to_user(doc.owner),
        updated_at=as_utc(doc.updated_at), access=level,
    )


def to_detail(doc: Document, level: str) -> DocumentDetail:
    return DocumentDetail(
        **to_summary(doc, level).model_dump(),
        content=doc.content,
        version=doc.version,
        updated_by=to_user(doc.updated_by) if doc.updated_by else None,
    )


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
    shared = sorted(shares, key=lambda s: s.document.updated_at, reverse=True)
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
        updated_by_id=user.id,
    )
    db.add(doc)
    db.flush()  # assigns doc.id so the activity entry can reference it
    log_activity(db, doc, user, "created")
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
    doc = Document(
        title=title_from_filename(file.filename or ""), content=content,
        owner_id=user.id, updated_by_id=user.id,
    )
    db.add(doc)
    db.flush()
    log_activity(db, doc, user, "imported", f"from {file.filename}")
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

    if body.content is not None:
        # Optimistic concurrency: reject a save based on an outdated version.
        if body.base_version is not None and body.base_version != doc.version:
            editor = doc.updated_by.name if doc.updated_by else "Someone"
            return JSONResponse(
                status_code=409,
                content={
                    "detail": f"{editor} saved a newer version of this document.",
                    "current_version": doc.version,
                    "updated_by": editor,
                },
            )
        doc.content = sanitize_html(body.content)
        doc.version += 1
        doc.updated_by_id = user.id
        log_activity(db, doc, user, "edited")

    # Renaming does not change the content version, so it never causes a conflict.
    if body.title is not None and body.title != doc.title:
        log_activity(db, doc, user, "renamed", f'"{doc.title}" to "{body.title}"')
        doc.title = body.title

    doc.updated_at = utcnow()
    db.commit()
    db.refresh(doc)
    return to_detail(doc, level)


@app.get("/api/documents/{doc_id}/activity", response_model=list[ActivityOut])
def list_activity(doc_id: int, user: User = Depends(current_user), db: Session = Depends(db_module.get_db)):
    doc, _ = load_doc(doc_id, user, db)
    events = db.scalars(
        select(ActivityEvent)
        .where(ActivityEvent.document_id == doc.id)
        .order_by(ActivityEvent.id.desc())
        .limit(50)
    ).all()
    return [
        ActivityOut(actor=to_user(e.actor), action=e.action, detail=e.detail,
                    created_at=as_utc(e.created_at))
        for e in events
    ]


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
        if share.role != body.role:
            log_activity(db, doc, user, "role_changed", f"{target.name}: {share.role} to {body.role}")
            share.role = body.role
    else:
        share = DocumentShare(document_id=doc.id, user_id=target.id, role=body.role)
        db.add(share)
        log_activity(db, doc, user, "shared", f"with {target.name} as {body.role}")
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
    log_activity(db, doc, user, "unshared", share.user.name)
    db.delete(share)
    db.commit()


# ---------- Frontend ----------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
