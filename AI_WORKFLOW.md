# AI Workflow Note

## Tools used

- **Claude (Anthropic), in an agentic coding session.** Used for planning the scope, writing the backend, frontend and tests, running the test suite, driving a headless browser to check the UI, and drafting the documentation.
- **Playwright with headless Chrome**, run by the AI session, to click through the app and take screenshots.

## How I worked with it

I treated the AI as a fast pair programmer and kept the product decisions with me. The flow was:

1. **Scope first.** I pasted the full assignment and asked for a plan before any code. We agreed on the stack (FastAPI, plain JavaScript, Quill, SQLite locally and Postgres on Neon in production, Render for hosting) and a time budget for each phase.
2. **Backend and tests together.** The API, data model and pytest suite were written in one pass, and the tests were run immediately. All tests passed before any frontend work started.
3. **Frontend, then a browser check.** After the UI was written, a Playwright script created a document, typed formatted text, reloaded the page, shared the document, switched users and imported a file. Screenshots were reviewed after each run.
4. **Differentiation pass.** With the core working, I asked the AI how to make the result less like a generic answer to this prompt. It proposed an activity log and conflict protection. I chose both because they connect to my compliance background and go deeper into sharing, which is where the product risk is. I rejected an AI writing feature because it would need a paid API key, which the brief rules out, and it is the most obvious idea.
5. **Docs last,** based on what was actually built and tested.

## Where AI materially sped things up

- Boilerplate for FastAPI routes, Pydantic schemas and SQLAlchemy models took minutes instead of an hour.
- The test suite covers the full sharing and permission matrix (owner, editor, viewer, no access, revoke). Writing that by hand is slow and easy to get wrong.
- The end to end browser check found two UI bugs that I would otherwise have found only while recording the demo.

## What I changed or rejected

| AI output or first approach | What happened | Final decision |
|---|---|---|
| Load Quill from a CDN | The sandboxed test browser had restricted network access, and a CDN is one more thing that can fail at review time. | Bundled Quill 2.0.3 in `static/vendor`. |
| Save the editor's raw `innerHTML` | Quill stores bullet lists as `<ol><li data-list="bullet">`, which breaks Markdown export and is not portable. | Save `getSemanticHTML()` output (standard `<ul>`/`<ol>`). |
| `getSemanticHTML()` as is | Testing showed Quill 2.0.3 turns every space into `&nbsp;`. | Convert `&nbsp;` back to spaces before saving, and documented the side effect. |
| Share and Delete buttons hidden with the `hidden` attribute | The screenshot as a viewer still showed both buttons, because the button CSS overrode `hidden`. | Added a global `[hidden] { display: none !important; }` rule. Access is also enforced on the server, so this was a UI bug, not a security hole. |
| SQLite in production | Render's free plan wipes the disk on restart, so documents would disappear. | Postgres on Neon (free) in production, SQLite locally. Same code, chosen by `DATABASE_URL`. |
| Autosave sends a save every time the timer fires | With conflict checks, two overlapping saves from the same tab would conflict with each other. | Only one save is in flight at a time. Edits made during a save are queued and sent right after. |
| Log every autosave as an "edited" event | Autosave runs about once a second while typing, so the log would fill with noise. | Merge consecutive edits by the same person within 10 minutes into one entry. |
| Rename bumps the version like a content edit | A rename by one person would block another person's typing with a false conflict. | Only content saves change the version. |
| Return 403 when a user has no access | Leaks that a document id exists. | Return 404 for both "missing" and "no access". 403 only for "you can see it but cannot do this". |

## How I verified correctness, UX and reliability

- **Automated tests (10, pytest):** formatting survives save and reload, script tags are stripped, the full share, role change and revoke flow, Markdown and invalid file import, missing user header, blank title validation, Markdown export, a stale save rejected with 409 without losing the other person's text, and the exact order of activity log entries.
- **Scripted browser runs:** create, format, autosave, reload, share as viewer, switch to the shared user, confirm read-only editor, import a file. A second script used two browser pages as Alice and Bob to check live refresh, the conflict banner, "Keep mine and overwrite", and a role change taking effect without a reload. The only console error was the expected 409 response.
- **Manual check of the deployed app:** walked through the same flow on the live Render URL with the Neon database before submitting. This check caught a real problem. My first upload to GitHub was an older build, and the Neon table list had no `activity_events` table. Because the schema is created with `create_all` and there are no migrations, the old tables also lacked the new `version` column. I dropped the empty tables, uploaded the correct build, and confirmed all four tables and the three seeded users after redeploying. This is the migration tradeoff listed in the architecture note, showing up in practice.
- **Code review of AI output:** I read every access check in `load_doc` and the sanitizer allowlist myself, since those are the parts where a subtle mistake matters most.
