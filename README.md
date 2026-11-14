# Ajaia Docs

A lightweight collaborative document editor inspired by Google Docs. Users can create and format documents, import files, share documents with other users, and export to Markdown.

**Live app:** LIVE_URL_HERE
(Hosted on Render's free plan. The first request after a period of inactivity can take up to a minute while the server wakes up.)

## Features

| Area | What works |
|---|---|
| Editing | Create, rename, edit, delete. Bold, italic, underline, strikethrough, headings (H1 to H3), bulleted and numbered lists, quotes, links. Autosave about 1 second after you stop typing. |
| File import | Upload a `.txt`, `.md` or `.docx` file (up to 2 MB). It becomes a new editable document with headings, bold and lists preserved. |
| Sharing | Every document has one owner. The owner can share by email as "Can edit" or "Can view", change the role, or remove access. The sidebar separates "My documents" and "Shared with me". Viewers get a read-only editor. |
| Persistence | Documents, formatting and shares are stored in a database (SQLite locally, Postgres in production). Refreshing the page reopens the same document. |
| Export | Download any document you can access as Markdown. |

## Demo accounts

Login is mocked. Pick a user from the "Signed in as" menu at the top right.

| Name | Email |
|---|---|
| Alice Kim | alice@ajaia.test |
| Bob Lee | bob@ajaia.test |
| Carol Diaz | carol@ajaia.test |

**Try the sharing flow:** as Alice, create a document and click Share. Share it with `bob@ajaia.test` as "Can view". Switch to Bob. The document appears under "Shared with me" and opens read-only. Switch back to Alice, change Bob to "Can edit", and Bob can now edit it. Carol never sees it.

Sample files for the import feature are in `samples/`.

## Run locally

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000. A local SQLite file `data.db` is created on first start and the three demo users are seeded automatically. Delete `data.db` to reset.

To use Postgres instead, set `DATABASE_URL`:

```bash
export DATABASE_URL="postgresql://user:password@host/dbname?sslmode=require"
```

## Run tests

```bash
pytest -q
```

The tests run against an in-memory SQLite database. They cover formatting round trip, HTML sanitizing, the full sharing and permission flow, file import, invalid uploads, missing auth, input validation and Markdown export.

## Deploy (Render + Neon, both free)

1. Create a free Postgres database on Neon and copy its connection string.
2. On Render, create a new Web Service from this repository. `render.yaml` sets the build and start commands.
3. Set the environment variable `DATABASE_URL` to the Neon connection string.

Tables and demo users are created automatically on startup.

## Project layout

```
app/
  main.py      API routes, mocked auth, access checks
  models.py    User, Document, DocumentShare tables
  content.py   HTML sanitizing, file import, Markdown export
  db.py        Database engine (SQLite or Postgres)
  seed.py      Demo users
static/
  index.html   Single page UI
  app.js       Frontend logic (plain JavaScript, no build step)
  styles.css
  vendor/      Quill 2.0.3 editor (bundled, no CDN needed)
tests/
  test_api.py
samples/       Example .txt, .md and .docx files for import
```

## More documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): design decisions, tradeoffs, and what I would build next
- [AI_WORKFLOW.md](AI_WORKFLOW.md): how AI tools were used
- [SUBMISSION.md](SUBMISSION.md): list of everything included
