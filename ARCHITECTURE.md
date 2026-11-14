# Architecture Note

## Overview

```
Browser (index.html + app.js + Quill editor)
        |  JSON over HTTP, X-User-Id header
        |  polls the open document every 5 s
        v
FastAPI app (one process)
  - /api/*      documents, import, sharing, activity, export
  - /           serves the static frontend
        |
        v
SQLAlchemy  ->  SQLite (local) or Postgres on Neon (production)
                tables: users, documents, document_shares, activity_events
```

One FastAPI process serves both the API and the frontend. There is no separate frontend build. This keeps deployment to a single free Render service and keeps local setup to three commands.

## Product angle

A shared document is only useful if people trust it. Two questions come up quickly once more than one person works on a doc: "who changed this, and who can see it?" and "did my edit just wipe out someone else's?" Most of the extra time went into answering those two questions well, instead of adding more formatting options or a second upload type.

This comes from my background in compliance work (NIST 800-53), where access changes must be auditable and data must not be lost silently. The activity log maps directly to the audit and accountability controls in that framework.

## What I prioritized and why

**1. Access control on the server, not just the UI.** Every document route goes through one helper, `load_doc`, which checks whether the user is the owner, an editor, or a viewer. The UI hides buttons for convenience, but the API enforces the rules. A user without access gets a 404 instead of a 403, so document ids cannot be probed. Only the owner can share, change roles, unshare or delete.

**2. Role-based sharing (editor and viewer).** The minimum was "grant access". Two roles needed only one `role` column and make the owned vs shared distinction much clearer. Re-sharing with the same email updates the role.

**3. Activity log.** Every create, import, rename, edit, share, role change and unshare writes a row to `activity_events` in the same transaction as the change itself, so the log cannot drift from the data. Autosave runs about once a second while typing, so consecutive edits by the same person within 10 minutes are merged into one entry. Otherwise the log would be unreadable. Anyone who can open the document can read its log, and nobody else.

**4. Conflict protection (optimistic concurrency).** Each document has a `version` number that goes up by one on every content save. The client sends the version it last loaded as `base_version`. If it does not match, the server returns 409 with the name of the person who saved last, and the client pauses autosave and shows two choices: load their version, or keep mine and overwrite on purpose. Renaming does not change the version, so a rename never blocks someone's typing. I chose this over real-time merging (CRDT or OT) because it is small, easy to test, and fully prevents silent data loss, which is the actual risk.

**5. Live refresh by polling.** The open document checks the server every 5 seconds. If the user has no unsaved edits, other people's changes are applied automatically. If they do, the conflict banner appears before they even try to save. Role changes and revoked access also take effect without a reload. Polling is simpler than WebSockets and works on Render's free plan without extra setup. The cost is up to 5 seconds of delay.

**6. Content format: sanitized standard HTML.** The frontend sends standard HTML (`<h1>`, `<strong>`, `<ul>`, `<ol>`) rather than Quill's internal markup. The server cleans it with `nh3` using an allowlist of the tags the editor can produce. The same format comes out of the `.docx` importer and goes into the Markdown exporter, and a crafted API request cannot store a `<script>` tag.

**7. File import as "new document".** Turning a file into a new editable document is the most useful upload behavior for a docs product. `.docx` is converted with `mammoth`, `.md` with `markdown`, and `.txt` line by line. Type and size (2 MB) are validated in the browser and on the server, and the UI states the supported types.

**8. Mocked auth.** A user picker and an `X-User-Id` header keep the focus on sharing logic instead of login screens. Each browser tab keeps its own user, so two tabs can act as two people for the conflict demo. All access logic depends on one `current_user` function, so real auth would change one place.

## Tradeoffs and deliberate cuts

| Decision | Why | Cost |
|---|---|---|
| Detect conflicts instead of merging them | Prevents silent data loss with little code | Two people cannot type in the same doc at the same time without one of them resolving a conflict |
| Polling every 5 s instead of WebSockets | Works on any host, nothing extra to run | Up to 5 s delay, and some extra requests |
| Mocked auth via header | Saves time for sharing logic | Anyone can act as any demo user. Not for production. |
| Plain JS frontend, no React | No build step, one deploy, easy to review | Harder to scale to a large UI |
| `create_all` instead of migrations | Fine for a fixed schema in a timebox | Schema changes later would need Alembic |
| Neon Postgres for production | Render free disks are wiped on restart | One more free account to set up |
| Quill bundled in `static/vendor` | No dependency on a CDN at review time | Slightly larger repo |

Not built: character-level co-editing, comments, version history, attachments, image upload, search, pagination.

## Known issue found during build

Quill 2.0.3's `getSemanticHTML()` converts every space into `&nbsp;`. The frontend converts them back before saving. The side effect is that runs of multiple spaces collapse into one, which is acceptable for this scope.

## What I would build next (2 to 4 more hours)

1. **Version history with restore.** The version counter and activity log are already in place. Storing a snapshot per merged "edited" entry would make each one restorable.
2. **Better conflict resolution.** Show a side by side diff of the two versions instead of choosing one whole version.
3. **Real auth.** Email magic link or Google OAuth, replacing the header.
4. **Presence.** Show who else has the document open, using the existing polling loop.
5. **Frontend tests in CI.** I ran the sharing and conflict flows with a two-browser Playwright script during development, but did not add it to the repository.
