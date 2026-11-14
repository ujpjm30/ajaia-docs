# Architecture Note

## Overview

```
Browser (index.html + app.js + Quill editor)
        |  JSON over HTTP, X-User-Id header
        v
FastAPI app (one process)
  - /api/*      documents, import, sharing, export
  - /           serves the static frontend
        |
        v
SQLAlchemy  ->  SQLite (local) or Postgres on Neon (production)
```

One FastAPI process serves both the API and the frontend. There is no separate frontend build. This keeps deployment to a single free Render service and keeps local setup to three commands.

## What I prioritized and why

The prompt asks for depth in a few areas over shallow coverage. I focused on making the core loop solid: create, format, save, reopen, share, and see the right permissions as a different user. Each of those works end to end and is covered by automated tests.

**1. Access control on the server, not just the UI.** Every document route goes through one helper, `load_doc`, which checks whether the user is the owner, an editor, or a viewer. The UI hides buttons for convenience, but the API enforces the rules. A user without access gets a 404 instead of a 403, so document ids cannot be probed. Only the owner can share, change roles, unshare or delete.

**2. Role-based sharing (editor and viewer).** The minimum was "grant access". I added two roles because it was a small change to the data model (one `role` column) and it makes the owned vs shared distinction much clearer in the demo. Re-sharing with the same email updates the role.

**3. Content format: sanitized standard HTML.** Quill is the editor. On save, the frontend sends standard HTML (`<h1>`, `<strong>`, `<ul>`, `<ol>`) rather than Quill's internal markup. The server cleans it with `nh3` using an allowlist of the tags the editor can produce. This means stored content is portable (the same format comes out of the `.docx` importer and goes into the Markdown exporter) and a crafted API request cannot store a `<script>` tag.

**4. File import as "new document".** Of the upload options, turning a file into a new editable document is the most useful for a docs product and the easiest to verify. `.docx` is converted with `mammoth`, `.md` with `markdown`, and `.txt` line by line. Type and size (2 MB) are validated in both the browser and the server, and the UI states the supported types.

**5. Mocked auth.** The prompt allows simulated users. A user picker and an `X-User-Id` header keep the focus on sharing logic instead of login screens. All access logic is written against a `current_user` dependency, so swapping in real auth (sessions or OAuth) would change one function.

## Tradeoffs and deliberate cuts

| Decision | Why | Cost |
|---|---|---|
| Mocked auth via header | Saves time for sharing logic | Anyone can act as any demo user. Not for production. |
| Plain JS frontend, no React | No build step, one deploy, easy to review | Harder to scale to a large UI |
| Autosave with last write wins | Simple and predictable | Two editors typing at the same time can overwrite each other. No real-time merge. |
| `create_all` instead of migrations | Fine for a fixed schema in a timebox | Schema changes later would need Alembic |
| Neon Postgres for production | Render free disks are wiped on restart | One more free account to set up |
| Quill bundled in `static/vendor` | No dependency on a CDN at review time | Slightly larger repo |

Not built: real-time co-editing, comments, version history, attachments on documents, image upload, search, pagination.

## Known issue found during build

Quill 2.0.3's `getSemanticHTML()` converts every space into `&nbsp;`. The frontend converts them back before saving. The side effect is that runs of multiple spaces collapse into one, which is acceptable for this scope.

## What I would build next (2 to 4 more hours)

1. **Conflict protection.** Send `updated_at` with each save and reject stale writes with 409, then show "This document changed, reload?" This fixes the main weakness of last write wins.
2. **Version history.** Store a snapshot row on each save (throttled), with a simple "restore this version" view.
3. **Real auth.** Email magic link or Google OAuth, replacing the header.
4. **Presence indicator.** Show who else has the document open, using a short polling endpoint.
5. **Frontend tests.** A Playwright test for the share and switch-user flow. I ran this flow with a Playwright script during development but did not add it to the repository.
