# Submission: Ajaia Docs

**Candidate:** Jimin Park (jimin.park.mlds@gmail.com)

## Links

- **Live app:** LIVE_URL_HERE
- **Source code (GitHub):** GITHUB_URL_HERE
- **Google Drive folder:** DRIVE_URL_HERE
- **Walkthrough video:** VIDEO_URL_HERE (also in `VIDEO_URL.txt`)

The app runs on Render's free plan. If the first load is slow, wait up to a minute for the server to wake up and refresh.

## Test accounts

No password needed. Choose a user from the "Signed in as" menu at the top right.

| Name | Email |
|---|---|
| Alice Kim | alice@ajaia.test |
| Bob Lee | bob@ajaia.test |
| Carol Diaz | carol@ajaia.test |

**Quick sharing test:** as Alice, create a document and share it with `bob@ajaia.test` as "Can view". Switch to Bob. It appears under "Shared with me" and is read-only. Switch back to Alice, change Bob to "Can edit", and Bob can edit. Carol cannot see it.

## What is included

| File or folder | Contents |
|---|---|
| `README.md` | Features, demo accounts, local setup, tests, deployment |
| `ARCHITECTURE.md` | Architecture note: priorities, tradeoffs, next steps |
| `AI_WORKFLOW.md` | AI workflow note: tools, speedups, rejected output, verification |
| `SUBMISSION.md` | This file |
| `VIDEO_URL.txt` | Walkthrough video link |
| `app/` | FastAPI backend |
| `static/` | Frontend (HTML, JavaScript, CSS, bundled Quill editor) |
| `tests/` | Automated tests (pytest, 8 tests) |
| `samples/` | Example `.txt`, `.md` and `.docx` files for the import feature |
| `screenshots/` | Screenshots of the main screens |
| `requirements.txt`, `requirements-dev.txt`, `render.yaml` | Dependencies and deployment config |

## Status

**Working end to end**
- Create, rename, edit, delete documents with rich text (bold, italic, underline, strikethrough, H1 to H3, bulleted and numbered lists, quotes, links)
- Autosave and reopen after refresh, with formatting preserved
- Import `.txt`, `.md`, `.docx` (up to 2 MB) as a new document
- Sharing by email with "Can edit" or "Can view" roles, role change and revoke
- "My documents" and "Shared with me" lists, read-only editor for viewers
- Export to Markdown (stretch item)
- Server-side access checks and HTML sanitizing, covered by tests

**Intentionally not built**
- Real login (auth is mocked with seeded users)
- Real-time co-editing. Saves are last write wins.
- Comments, version history, attachments, search

**Next 2 to 4 hours**
1. Reject stale saves (409) to prevent silent overwrites between two editors
2. Version history with restore
3. Real authentication
4. Presence indicator showing who else has the document open
5. Playwright test for the sharing flow in CI
