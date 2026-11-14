// Ajaia Docs frontend. Plain JavaScript, no build step.

const POLL_MS = 5000; // how often an open document checks the server for changes by others

const state = {
  userId: null,
  users: [],
  doc: null,          // currently open document (from the API), includes .version
  saveTimer: null,
  dirty: false,       // local edits not yet saved
  saving: false,      // a save request is in flight
  saveQueued: false,  // edits happened while a save was in flight
  conflict: false,    // someone else saved a newer version, autosave is paused
};

const $ = (id) => document.getElementById(id);

// ---------- Small helpers ----------

// Per-tab storage, so two tabs can be signed in as two different demo users.
function storageGet(key) {
  try { return sessionStorage.getItem(key); } catch { return null; }
}
function storageSet(key, value) {
  try { sessionStorage.setItem(key, value); } catch { /* ignore */ }
}

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = "toast" + (isError ? " error" : "");
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, 3500);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.userId) headers["X-User-Id"] = state.userId;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.json);
  }
  const res = await fetch(path, { ...options, headers });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    let msg = data.detail || `Request failed (${res.status})`;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join(", ");
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function formatTime(iso) {
  return new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function timeAgo(iso) {
  const sec = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 45) return "just now";
  if (sec < 3600) return `${Math.round(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)} h ago`;
  return formatTime(iso);
}

// ---------- Editor ----------

const quill = new Quill("#editor", {
  theme: "snow",
  modules: { toolbar: "#toolbar" },
  placeholder: "Start writing...",
});

quill.on("text-change", (_delta, _old, source) => {
  if (source !== "user" || !state.doc) return;
  state.dirty = true;
  if (state.conflict) return; // keep edits locally, but do not autosave until resolved
  setStatus("Unsaved changes");
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(saveContent, 800);
});

function setStatus(text) { $("save-status").textContent = text; }

function editorHtml() {
  // Store standard HTML (<ul>/<ol>) instead of Quill's internal markup so the
  // content is portable (export, other editors). Quill 2.0.3 turns every space
  // into &nbsp; here, so we convert those back.
  return quill.getSemanticHTML().replace(/&nbsp;/g, " ");
}

function setEditorHtml(html) {
  const hadFocus = quill.hasFocus();
  const range = quill.getSelection();
  quill.setContents(quill.clipboard.convert({ html: html || "" }), "silent");
  if (hadFocus && range) quill.setSelection(Math.min(range.index, quill.getLength() - 1), 0, "silent");
}

async function saveContent() {
  if (!state.doc || !state.dirty || state.conflict) return;
  if (state.saving) { state.saveQueued = true; return; } // one save at a time
  clearTimeout(state.saveTimer);
  const docId = state.doc.id;
  state.saving = true;
  state.dirty = false;
  setStatus("Saving...");
  try {
    const updated = await api(`/api/documents/${docId}`, {
      method: "PATCH",
      json: { content: editorHtml(), base_version: state.doc.version },
    });
    if (state.doc && state.doc.id === docId) {
      state.doc.version = updated.version;
      state.doc.updated_at = updated.updated_at;
      state.doc.updated_by = updated.updated_by;
      setStatus(state.dirty ? "Unsaved changes" : "Saved");
      renderMeta();
      loadActivity();
    }
    refreshLists();
  } catch (err) {
    state.dirty = true;
    if (err.status === 409) {
      showConflict(err.message);
    } else {
      setStatus("Save failed");
      toast(err.message, true);
    }
  } finally {
    state.saving = false;
    if (state.saveQueued) { state.saveQueued = false; saveContent(); }
  }
}

// Save before leaving the page if there are pending edits.
window.addEventListener("beforeunload", (e) => {
  if (state.dirty) { saveContent(); e.preventDefault(); }
});

// ---------- Conflict handling ----------

function showConflict(message) {
  state.conflict = true;
  clearTimeout(state.saveTimer);
  setStatus("Not saved");
  $("conflict-text").textContent = `${message} Your latest changes are not saved yet.`;
  $("conflict-banner").hidden = false;
}

function clearConflict() {
  state.conflict = false;
  $("conflict-banner").hidden = true;
}

$("conflict-reload").addEventListener("click", async () => {
  // Discard local edits and load the newest version from the server.
  state.dirty = false;
  clearConflict();
  await openDoc(state.doc.id);
  toast("Loaded the latest version");
});

$("conflict-overwrite").addEventListener("click", async () => {
  // Keep local edits and save them on top of the newest version (deliberate overwrite).
  try {
    const latest = await api(`/api/documents/${state.doc.id}`);
    state.doc.version = latest.version;
    clearConflict();
    state.dirty = true;
    await saveContent();
  } catch (err) { toast(err.message, true); }
});

// ---------- Polling for changes by other users ----------

async function pollOpenDoc() {
  const d = state.doc;
  if (!d || state.saving || document.hidden) return;
  let latest;
  try {
    latest = await api(`/api/documents/${d.id}`);
  } catch (err) {
    if (err.status === 404 && state.doc && state.doc.id === d.id) {
      // Access was removed or the document was deleted while it was open.
      state.doc = null;
      state.dirty = false;
      clearConflict();
      history.replaceState(null, "", location.pathname);
      renderDoc();
      refreshLists();
      toast("You no longer have access to this document", true);
    }
    return;
  }
  if (!state.doc || state.doc.id !== d.id) return; // user switched documents meanwhile

  if (latest.access !== state.doc.access) {
    // The owner changed this user's role. Re-render with the new permissions.
    state.doc = latest;
    state.dirty = false;
    renderDoc();
    toast(`Your access changed to: ${latest.access === "viewer" ? "view only" : "can edit"}`);
    return;
  }

  if (latest.version > state.doc.version && !state.conflict) {
    const who = latest.updated_by ? latest.updated_by.name : "Someone";
    if (state.dirty) {
      showConflict(`${who} saved a newer version while you were editing.`);
    } else {
      setEditorHtml(latest.content);
      Object.assign(state.doc, { version: latest.version, content: latest.content,
        updated_at: latest.updated_at, updated_by: latest.updated_by });
      renderMeta();
      toast(`Updated with ${who}'s changes`);
    }
  }
  if (latest.title !== state.doc.title && document.activeElement !== $("doc-title")) {
    state.doc.title = latest.title;
    $("doc-title").value = latest.title;
  }
  loadActivity();
}
setInterval(pollOpenDoc, POLL_MS);

// ---------- Activity log ----------

function describe(e) {
  const d = escapeHtml(e.detail);
  switch (e.action) {
    case "created": return "created the document";
    case "imported": return `imported the document ${d}`;
    case "renamed": return `renamed it ${d}`;
    case "edited": return "edited the content";
    case "shared": return `shared it ${d}`;
    case "role_changed": return `changed access for ${d}`;
    case "unshared": return `removed access for ${d}`;
    default: return `${escapeHtml(e.action)} ${d}`;
  }
}

async function loadActivity() {
  if (!state.doc) return;
  const docId = state.doc.id;
  try {
    const events = await api(`/api/documents/${docId}/activity`);
    if (!state.doc || state.doc.id !== docId) return;
    $("activity-list").innerHTML = events.length
      ? events.map((e) => `<li><strong>${escapeHtml(e.actor.name)}</strong> ${describe(e)}
          <span class="when" title="${formatTime(e.created_at)}">${timeAgo(e.created_at)}</span></li>`).join("")
      : `<li class="hint">No activity yet</li>`;
  } catch { /* the poller will retry */ }
}

// ---------- Document list ----------

function renderList(el, docs, shared) {
  el.innerHTML = "";
  if (docs.length === 0) {
    el.innerHTML = `<li class="none">${shared ? "Nothing shared with you yet" : "No documents yet"}</li>`;
    return;
  }
  for (const d of docs) {
    const li = document.createElement("li");
    li.dataset.id = d.id;
    if (state.doc && state.doc.id === d.id) li.classList.add("active");
    const sub = shared
      ? `from ${escapeHtml(d.owner.name)} · ${d.access === "viewer" ? "view only" : "can edit"}`
      : `edited ${formatTime(d.updated_at)}`;
    li.innerHTML = `${escapeHtml(d.title)}<span class="sub">${sub}</span>`;
    li.addEventListener("click", () => openDoc(d.id));
    el.appendChild(li);
  }
}

async function refreshLists() {
  try {
    const data = await api("/api/documents");
    renderList($("owned-list"), data.owned, false);
    renderList($("shared-list"), data.shared, true);
  } catch (err) {
    toast(err.message, true);
  }
}

// ---------- Open / render a document ----------

function renderMeta() {
  const d = state.doc;
  const ownerText = d.access === "owner" ? "You own this document" : `Owned by ${d.owner.name}`;
  const by = d.updated_by ? ` by ${d.updated_by.name}` : "";
  $("doc-meta").textContent = `${ownerText} · Last edited${by} ${formatTime(d.updated_at)}`;
}

function renderDoc() {
  const d = state.doc;
  $("empty-state").hidden = !!d;
  $("doc-view").hidden = !d;
  if (!d) return;

  const canEdit = d.access !== "viewer";
  const isOwner = d.access === "owner";

  $("doc-title").value = d.title;
  $("doc-title").disabled = !canEdit;
  setEditorHtml(d.content);
  quill.enable(canEdit);
  $("toolbar").style.display = canEdit ? "" : "none";

  const badge = $("access-badge");
  badge.className = `badge ${d.access}`;
  badge.textContent = { owner: "Owner", editor: "Can edit", viewer: "View only" }[d.access];

  $("share-btn").hidden = !isOwner;
  $("delete-btn").hidden = !isOwner;
  setStatus(canEdit ? "Saved" : "");
  renderMeta();
  loadActivity();

  document.querySelectorAll(".doc-list li").forEach((li) => {
    li.classList.toggle("active", Number(li.dataset.id) === d.id);
  });
}

async function openDoc(id) {
  await saveContent(); // flush pending edits on the current doc first
  clearConflict();
  state.dirty = false;
  try {
    state.doc = await api(`/api/documents/${id}`);
    location.hash = `doc/${id}`;
  } catch (err) {
    state.doc = null;
    history.replaceState(null, "", location.pathname);
    toast(err.message, true);
  }
  renderDoc();
}

// ---------- Create / rename / delete ----------

$("new-doc").addEventListener("click", async () => {
  try {
    const doc = await api("/api/documents", { method: "POST", json: { title: "Untitled document" } });
    await refreshLists();
    await openDoc(doc.id);
    $("doc-title").select();
  } catch (err) { toast(err.message, true); }
});

async function saveTitle() {
  const input = $("doc-title");
  if (!state.doc || input.disabled) return;
  const title = input.value.trim();
  if (title === state.doc.title) return;
  if (!title) {
    input.value = state.doc.title;
    toast("Title cannot be empty", true);
    return;
  }
  try {
    const updated = await api(`/api/documents/${state.doc.id}`, { method: "PATCH", json: { title } });
    state.doc.title = updated.title;
    state.doc.updated_at = updated.updated_at;
    renderMeta();
    refreshLists();
    loadActivity();
  } catch (err) {
    input.value = state.doc.title;
    toast(err.message, true);
  }
}
$("doc-title").addEventListener("blur", saveTitle);
$("doc-title").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); e.target.blur(); }
});

$("delete-btn").addEventListener("click", async () => {
  if (!state.doc) return;
  if (!confirm(`Delete "${state.doc.title}"? This cannot be undone.`)) return;
  try {
    await api(`/api/documents/${state.doc.id}`, { method: "DELETE" });
    state.doc = null;
    state.dirty = false;
    history.replaceState(null, "", location.pathname);
    renderDoc();
    refreshLists();
    toast("Document deleted");
  } catch (err) { toast(err.message, true); }
});

// ---------- Export ----------

$("export-btn").addEventListener("click", async () => {
  if (!state.doc) return;
  await saveContent();
  try {
    const res = await fetch(`/api/documents/${state.doc.id}/export.md`, { headers: { "X-User-Id": state.userId } });
    if (!res.ok) throw new Error("Export failed");
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${state.doc.title || "document"}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (err) { toast(err.message, true); }
});

// ---------- Import ----------

$("import-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = ""; // allow re-selecting the same file
  if (!file) return;
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (![".txt", ".md", ".docx"].includes(ext)) {
    toast("Only .txt, .md and .docx files are supported", true);
    return;
  }
  if (file.size > 2 * 1024 * 1024) {
    toast("File is larger than the 2 MB limit", true);
    return;
  }
  const form = new FormData();
  form.append("file", file);
  try {
    toast(`Importing ${file.name}...`);
    const doc = await api("/api/documents/import", { method: "POST", body: form });
    await refreshLists();
    await openDoc(doc.id);
    toast(`Imported "${doc.title}"`);
  } catch (err) { toast(err.message, true); }
});

// ---------- Sharing ----------

async function renderShares() {
  const list = $("share-list");
  list.innerHTML = "";
  const owner = document.createElement("li");
  owner.innerHTML = `<span>${escapeHtml(state.doc.owner.name)} (${escapeHtml(state.doc.owner.email)})</span><span>Owner</span>`;
  list.appendChild(owner);
  try {
    const shares = await api(`/api/documents/${state.doc.id}/shares`);
    for (const s of shares) {
      const li = document.createElement("li");
      li.innerHTML = `<span>${escapeHtml(s.user.name)} (${escapeHtml(s.user.email)})</span>
        <span>${s.role === "viewer" ? "Can view" : "Can edit"}
        <button type="button" class="remove" data-user="${s.user.id}">Remove</button></span>`;
      list.appendChild(li);
    }
  } catch (err) {
    $("share-error").textContent = err.message;
  }
}

$("share-btn").addEventListener("click", () => {
  $("share-error").textContent = "";
  $("share-email").value = "";
  renderShares();
  $("share-dialog").showModal();
});

$("share-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("share-error").textContent = "";
  const email = $("share-email").value.trim();
  const role = $("share-role").value;
  try {
    const s = await api(`/api/documents/${state.doc.id}/shares`, { method: "POST", json: { email, role } });
    $("share-email").value = "";
    toast(`${s.user.name} can now ${s.role === "viewer" ? "view" : "edit"}`);
    renderShares();
    loadActivity();
  } catch (err) {
    $("share-error").textContent = err.message;
  }
});

$("share-list").addEventListener("click", async (e) => {
  const btn = e.target.closest(".remove");
  if (!btn) return;
  try {
    await api(`/api/documents/${state.doc.id}/shares/${btn.dataset.user}`, { method: "DELETE" });
    renderShares();
    loadActivity();
  } catch (err) {
    $("share-error").textContent = err.message;
  }
});

$("share-close").addEventListener("click", () => $("share-dialog").close());

// ---------- User switching (mocked auth) ----------

$("user-select").addEventListener("change", async (e) => {
  await saveContent();
  state.userId = e.target.value;
  storageSet("ajaia-user", state.userId);
  state.doc = null;
  state.dirty = false;
  clearConflict();
  history.replaceState(null, "", location.pathname);
  renderDoc();
  refreshLists();
  const u = state.users.find((x) => String(x.id) === state.userId);
  if (u) toast(`Switched to ${u.name}`);
});

// ---------- Start ----------

async function init() {
  try {
    state.users = await api("/api/users");
  } catch (err) {
    toast("Could not reach the server. It may be waking up, try refreshing in a moment.", true);
    return;
  }
  const select = $("user-select");
  select.innerHTML = state.users
    .map((u) => `<option value="${u.id}">${escapeHtml(u.name)} (${escapeHtml(u.email)})</option>`)
    .join("");
  const saved = storageGet("ajaia-user");
  state.userId = state.users.some((u) => String(u.id) === saved) ? saved : String(state.users[0].id);
  select.value = state.userId;

  await refreshLists();
  const match = location.hash.match(/^#doc\/(\d+)$/);
  if (match) await openDoc(Number(match[1]));
  else renderDoc();
}

init();
