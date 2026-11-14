import io
import os

# Use a fresh in-memory database for the test run. Must be set before importing the app.
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from fastapi.testclient import TestClient

from app.main import app

ALICE, BOB, CAROL = 1, 2, 3


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # "with" runs startup, which creates tables and seeds users
        yield c


def as_user(user_id):
    return {"X-User-Id": str(user_id)}


def test_document_roundtrip_preserves_formatting(client):
    html = "<h1>Plan</h1><p><strong>bold</strong> <em>it</em> <u>under</u></p><ol><li>one</li></ol>"
    r = client.post("/api/documents", json={"title": "Q4 plan"}, headers=as_user(ALICE))
    assert r.status_code == 201
    doc_id = r.json()["id"]

    r = client.patch(f"/api/documents/{doc_id}", json={"title": "Q4 plan v2", "content": html},
                     headers=as_user(ALICE))
    assert r.status_code == 200

    r = client.get(f"/api/documents/{doc_id}", headers=as_user(ALICE))
    body = r.json()
    assert body["title"] == "Q4 plan v2"
    for tag in ("<h1>", "<strong>", "<em>", "<u>", "<ol>"):
        assert tag in body["content"]


def test_script_tags_are_stripped(client):
    r = client.post("/api/documents",
                    json={"title": "x", "content": "<p>hi</p><script>alert(1)</script>"},
                    headers=as_user(ALICE))
    assert "<script>" not in r.json()["content"]
    assert "<p>hi</p>" in r.json()["content"]


def test_sharing_controls_access(client):
    doc_id = client.post("/api/documents", json={"title": "Private"}, headers=as_user(ALICE)).json()["id"]

    # Bob cannot see it before it is shared
    assert client.get(f"/api/documents/{doc_id}", headers=as_user(BOB)).status_code == 404

    # Only the owner can share
    r = client.post(f"/api/documents/{doc_id}/shares", json={"email": "carol@ajaia.test"},
                    headers=as_user(BOB))
    assert r.status_code == 404

    # Alice shares with Bob as viewer
    r = client.post(f"/api/documents/{doc_id}/shares",
                    json={"email": "bob@ajaia.test", "role": "viewer"}, headers=as_user(ALICE))
    assert r.status_code == 201

    # Bob sees it in his "shared" list, not "owned"
    lists = client.get("/api/documents", headers=as_user(BOB)).json()
    assert doc_id in [d["id"] for d in lists["shared"]]
    assert doc_id not in [d["id"] for d in lists["owned"]]

    # Viewer can read but not edit
    assert client.get(f"/api/documents/{doc_id}", headers=as_user(BOB)).json()["access"] == "viewer"
    r = client.patch(f"/api/documents/{doc_id}", json={"content": "<p>hack</p>"}, headers=as_user(BOB))
    assert r.status_code == 403

    # Upgrade to editor, then Bob can edit
    client.post(f"/api/documents/{doc_id}/shares",
                json={"email": "bob@ajaia.test", "role": "editor"}, headers=as_user(ALICE))
    r = client.patch(f"/api/documents/{doc_id}", json={"content": "<p>edited by bob</p>"},
                     headers=as_user(BOB))
    assert r.status_code == 200

    # Carol still has no access
    assert client.get(f"/api/documents/{doc_id}", headers=as_user(CAROL)).status_code == 404

    # Revoking removes access
    assert client.delete(f"/api/documents/{doc_id}/shares/{BOB}", headers=as_user(ALICE)).status_code == 204
    assert client.get(f"/api/documents/{doc_id}", headers=as_user(BOB)).status_code == 404


def test_import_markdown_creates_document(client):
    data = b"# Meeting notes\n\n- **Decision**: ship it\n- Owner: Alice\n"
    r = client.post("/api/documents/import",
                    files={"file": ("notes.md", io.BytesIO(data), "text/markdown")},
                    headers=as_user(ALICE))
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "notes"
    assert "<h1>Meeting notes</h1>" in body["content"]
    assert "<strong>Decision</strong>" in body["content"]


def test_import_rejects_unsupported_type(client):
    r = client.post("/api/documents/import",
                    files={"file": ("photo.png", io.BytesIO(b"\x89PNG"), "image/png")},
                    headers=as_user(ALICE))
    assert r.status_code == 400
    assert "Unsupported" in r.json()["detail"]


def test_requests_without_user_are_rejected(client):
    assert client.get("/api/documents").status_code == 401


def test_blank_title_is_rejected(client):
    doc_id = client.post("/api/documents", json={}, headers=as_user(ALICE)).json()["id"]
    r = client.patch(f"/api/documents/{doc_id}", json={"title": "   "}, headers=as_user(ALICE))
    assert r.status_code == 422


def test_export_markdown(client):
    doc_id = client.post("/api/documents",
                         json={"title": "Notes", "content": "<h2>Agenda</h2><ul><li><strong>one</strong></li></ul>"},
                         headers=as_user(ALICE)).json()["id"]
    r = client.get(f"/api/documents/{doc_id}/export.md", headers=as_user(ALICE))
    assert r.status_code == 200
    assert "## Agenda" in r.text
    assert "- **one**" in r.text
