"""Note and task attachments: upload, isolation, retrieval and cleanup.

The bytes live in their own table. These tests pin down the parts that would
otherwise fail quietly: a note list must carry the metadata, another user must
never read the blob, and deleting the record must take its files with it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app import models
from app.database import get_db
from app.main import app as fastapi_app
from app.security import get_current_user


@pytest.fixture()
def client(db, user):
    def _db():
        try:
            yield db
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = _db
    fastapi_app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(fastapi_app, raise_server_exceptions=False)
    finally:
        fastapi_app.dependency_overrides.clear()


def _upload(client, owner_kind, owner_id, name="photo.png", payload=b"\x89PNG\r\n", mime="image/png"):
    return client.post(
        "/api/attachments",
        files={"file": (name, payload, mime)},
        data={"owner_kind": owner_kind, "owner_id": owner_id},
    )


def test_upload_attaches_metadata_to_the_record(client):
    note = client.post("/api/notes", json={"id": "note-attach-1", "title": "Trip"}).json()

    uploaded = _upload(client, "note", note["id"])
    assert uploaded.status_code == 200, uploaded.text
    meta = uploaded.json()
    assert meta["name"] == "photo.png"
    assert meta["mime"] == "image/png"
    assert meta["size"] == 6

    listed = client.get("/api/notes").json()[0]
    assert [a["id"] for a in listed["attachments"]] == [meta["id"]]
    # The list payload carries metadata only, never the bytes.
    assert "data" not in listed["attachments"][0]


def test_attachment_can_exist_before_its_note_is_saved(client):
    uploaded = _upload(client, "note", "note-draft-42")
    assert uploaded.status_code == 200, uploaded.text

    client.post("/api/notes", json={"id": "note-draft-42", "title": "Draft that grew files"})
    listed = client.get("/api/notes").json()[0]
    assert len(listed["attachments"]) == 1


def test_image_is_served_inline_and_other_files_are_downloads(client):
    image = _upload(client, "note", "note-inline-1").json()
    res = client.get(f"/api/attachments/{image['id']}")
    assert res.status_code == 200
    assert res.content == b"\x89PNG\r\n"
    assert res.headers["content-type"] == "image/png"
    assert res.headers["content-disposition"].startswith("inline;")

    document = _upload(client, "note", "note-inline-1", "notes.txt", b"hello", "text/plain").json()
    res = client.get(f"/api/attachments/{document['id']}")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/octet-stream"
    assert res.headers["content-disposition"].startswith("attachment;")
    assert res.content == b"hello"


def test_another_user_cannot_read_or_delete_the_blob(client, db, user):
    other = models.User(name="Other", email="other@local.dev", password_hash="x")
    db.add(other)
    db.commit()
    attachment = _upload(client, "note", "note-private-1").json()

    fastapi_app.dependency_overrides[get_current_user] = lambda: other
    try:
        assert client.get(f"/api/attachments/{attachment['id']}").status_code == 404
        assert client.delete(f"/api/attachments/{attachment['id']}").json() == {"ok": True}
    finally:
        fastapi_app.dependency_overrides[get_current_user] = lambda: user

    # The other user's delete was a no-op; the owner still has the file.
    assert client.get(f"/api/attachments/{attachment['id']}").status_code == 200


def test_deleting_a_note_deletes_its_attachments(client, db):
    note = client.post("/api/notes", json={"id": "note-delete-1", "title": "Throwaway"}).json()
    attachment = _upload(client, "note", note["id"]).json()

    assert client.delete(f"/api/notes/{note['id']}").json() == {"ok": True}
    assert db.query(models.Attachment).filter_by(id=attachment["id"]).first() is None
    assert client.get(f"/api/attachments/{attachment['id']}").status_code == 404


def test_deleting_a_task_deletes_its_attachments(client, db):
    task = client.post("/api/tasks", json={"id": "task-delete-1", "text": "Renew insurance"}).json()
    attachment = _upload(client, "task", task["id"]).json()

    client.delete(f"/api/tasks/{task['id']}")
    assert db.query(models.Attachment).filter_by(id=attachment["id"]).first() is None


def test_task_payload_carries_its_attachments(client):
    task = client.post("/api/tasks", json={"id": "task-attach-1", "text": "File the papers"}).json()
    meta = _upload(client, "task", task["id"], "papers.pdf", b"%PDF", "application/pdf").json()

    listed = client.get("/api/tasks").json()[0]
    assert [a["id"] for a in listed["attachments"]] == [meta["id"]]


def test_upload_rejects_an_unknown_owner_kind(client):
    res = _upload(client, "journal", "entry-1")
    assert res.status_code == 400
    assert "owner_kind" in res.json()["detail"]


def test_upload_rejects_an_empty_file(client):
    res = _upload(client, "note", "note-empty-1", "empty.txt", b"", "text/plain")
    assert res.status_code == 400


def test_upload_rejects_a_file_over_the_limit(client, monkeypatch):
    monkeypatch.setattr(main_module, "MAX_ATTACHMENT_BYTES", 4)
    res = _upload(client, "note", "note-big-1", "big.bin", b"12345", "application/octet-stream")
    assert res.status_code == 413


def test_attaching_touches_the_record_so_other_devices_refresh(client):
    note = client.post("/api/notes", json={"id": "note-sync-1", "title": "Live"}).json()
    before = client.get("/api/sync/version").json()["version"]

    _upload(client, "note", note["id"])

    assert client.get("/api/sync/version").json()["version"] != before


def test_a_record_has_an_attachment_count_limit(client, monkeypatch):
    monkeypatch.setattr(main_module, "MAX_ATTACHMENTS_PER_RECORD", 1)
    note = client.post("/api/notes", json={"id": "note-cap-1", "title": "Capped"}).json()

    assert _upload(client, "note", note["id"]).status_code == 200
    second = _upload(client, "note", note["id"])
    assert second.status_code == 422


def test_a_record_has_a_total_size_limit(client, monkeypatch):
    monkeypatch.setattr(main_module, "MAX_ATTACHMENTS_TOTAL_BYTES", 6)
    note = client.post("/api/notes", json={"id": "note-total-1", "title": "Total"}).json()

    assert _upload(client, "note", note["id"], "a.txt", b"abc", "text/plain").status_code == 200
    second = _upload(client, "note", note["id"], "b.txt", b"abcd", "text/plain")
    assert second.status_code == 413


def test_removing_one_attachment_leaves_the_others(client):
    note = client.post("/api/notes", json={"id": "note-many-1", "title": "Many"}).json()
    first = _upload(client, "note", note["id"], "one.png").json()
    second = _upload(client, "note", note["id"], "two.png").json()

    client.delete(f"/api/attachments/{first['id']}")
    listed = client.get("/api/notes").json()[0]
    assert [a["id"] for a in listed["attachments"]] == [second["id"]]
