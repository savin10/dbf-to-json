"use strict";

const $ = (sel) => document.querySelector(sel);

const state = {
  items: [],          // { id, stem, dbf, memo, status, info, error }
  orphanMemos: {},    // stem -> File (memo dropped before its DBF)
  selectedId: null,
  tab: "table",
};
let nextId = 1;

const els = {
  dropzone: $("#dropzone"),
  input: $("#fileInput"),
  list: $("#fileList"),
  convertAll: $("#convertAllBtn"),
  clear: $("#clearBtn"),
  stats: $("#stats"),
  body: $("#previewBody"),
  title: $("#previewTitle"),
  toast: $("#toast"),
  encoding: $("#encoding"),
  includeSchema: $("#includeSchema"),
  pretty: $("#pretty"),
  lowercase: $("#lowercase"),
  includeDeleted: $("#includeDeleted"),
};

/* ---------- helpers ---------- */

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const stemOf = (name) => name.replace(/\.[^.]+$/, "").toLowerCase();
const extOf = (name) => (name.match(/\.([^.]+)$/) || ["", ""])[1].toLowerCase();

function formatBytes(n) {
  const units = ["o", "Ko", "Mo", "Go"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
}

let toastTimer;
function toast(msg) {
  els.toast.textContent = msg;
  els.toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => els.toast.classList.remove("show"), 3500);
}

function buildForm(item, extra = {}) {
  const fd = new FormData();
  fd.append("dbf", item.dbf, item.dbf.name);
  if (item.memo) fd.append("memo", item.memo, item.memo.name);
  fd.append("encoding", els.encoding.value);
  fd.append("include_deleted", els.includeDeleted.checked);
  fd.append("lowercase", els.lowercase.checked);
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  return fd;
}

async function errorMessage(res) {
  try {
    const data = await res.json();
    return data.detail || res.statusText;
  } catch {
    return res.statusText || `Erreur ${res.status}`;
  }
}

/* ---------- file intake ---------- */

function addFiles(fileList) {
  let added = 0;
  for (const file of fileList) {
    const ext = extOf(file.name);
    const stem = stemOf(file.name);
    if (ext === "dbf") {
      const existing = state.items.find((it) => it.stem === stem);
      if (existing) {
        existing.dbf = file;
        existing.info = null;
        existing.status = "pending";
        inspect(existing);
        continue;
      }
      const item = {
        id: nextId++, stem, dbf: file,
        memo: state.orphanMemos[stem] || null,
        status: "pending", info: null, error: null,
      };
      delete state.orphanMemos[stem];
      state.items.push(item);
      if (!state.selectedId) state.selectedId = item.id;
      inspect(item);
      added++;
    } else if (ext === "dbt" || ext === "fpt") {
      const owner = state.items.find((it) => it.stem === stem);
      if (owner) {
        owner.memo = file;
        owner.info = null;
        inspect(owner);
      } else {
        state.orphanMemos[stem] = file;
        toast(`Fichier mémo ${file.name} en attente de son ${stem}.dbf`);
      }
    } else {
      toast(`Ignoré : ${file.name} (format non pris en charge)`);
    }
  }
  if (added) toast(`${added} fichier(s) ajouté(s)`);
  render();
}

/* ---------- API calls ---------- */

async function inspect(item) {
  item.jsonSize = null;
  item.status = "loading";
  item.error = null;
  render();
  try {
    const res = await fetch("/api/inspect", { method: "POST", body: buildForm(item, { preview_rows: 100 }) });
    if (!res.ok) throw new Error(await errorMessage(res));
    item.info = await res.json();
    item.status = "ready";
  } catch (err) {
    item.status = "error";
    item.error = err.message;
  }
  render();
}

async function convert(item) {
  item.status = "converting";
  render();
  try {
    const res = await fetch("/api/convert", {
      method: "POST",
      body: buildForm(item, {
        include_schema: els.includeSchema.checked,
        pretty: els.pretty.checked,
      }),
    });
    if (!res.ok) throw new Error(await errorMessage(res));
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${item.dbf.name.replace(/\.[^.]+$/, "")}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    item.status = "done";
    item.jsonSize = blob.size;
  } catch (err) {
    item.status = "error";
    item.error = err.message;
    toast(`Échec : ${item.dbf.name} — ${err.message}`);
  }
  render();
}

/* ---------- rendering ---------- */

const STATUS_LABEL = {
  pending: ["En attente", ""],
  loading: ["Analyse…", "busy"],
  ready: ["Prêt", ""],
  converting: ["Conversion…", "busy"],
  done: ["Converti", "ok"],
  error: ["Erreur", "err"],
};

function renderList() {
  els.convertAll.disabled = !state.items.some((it) => it.status !== "error" && it.status !== "converting");
  els.clear.disabled = state.items.length === 0;

  if (!state.items.length) {
    els.list.innerHTML = `<li class="empty">Aucun fichier pour l'instant.</li>`;
    return;
  }
  els.list.innerHTML = state.items.map((it) => {
    const [label, cls] = STATUS_LABEL[it.status];
    const busy = it.status === "loading" || it.status === "converting";
    const meta = [
      `<span class="badge ${cls}">${label}</span>`,
      `<span>${formatBytes(it.dbf.size)}</span>`,
      it.info ? `<span>${it.info.record_count.toLocaleString("fr-FR")} enreg.</span>` : "",
      it.info ? `<span>${it.info.fields.length} champs</span>` : "",
      it.memo ? `<span>+ ${escapeHtml(it.memo.name)}</span>` : "",
      it.jsonSize ? `<span>JSON ${formatBytes(it.jsonSize)}</span>` : "",
    ].join("");
    return `
      <li class="file ${it.id === state.selectedId ? "selected" : ""}" data-id="${it.id}">
        <span class="file-name">${escapeHtml(it.dbf.name)}</span>
        <span class="file-actions">
          <button class="btn small primary" data-action="convert" ${busy || it.status === "error" ? "disabled" : ""}>JSON ⤓</button>
          <button class="remove" data-action="remove" title="Retirer">✕</button>
        </span>
        <div class="file-meta">${meta}</div>
      </li>`;
  }).join("");
}

function renderValueCell(value) {
  if (value === null || value === undefined) return `<td class="null">null</td>`;
  if (typeof value === "number") return `<td class="num">${value}</td>`;
  if (typeof value === "boolean") return `<td>${value ? "✓ true" : "✗ false"}</td>`;
  if (typeof value === "object") {
    const text = value.$binary !== undefined ? `[binaire ${value.$binary.length} b64]` : JSON.stringify(value);
    return `<td class="null">${escapeHtml(text)}</td>`;
  }
  const s = String(value);
  return `<td title="${escapeHtml(s)}">${escapeHtml(s.length > 80 ? s.slice(0, 80) + "…" : s)}</td>`;
}

function highlightJson(json) {
  return escapeHtml(json).replace(
    /(&quot;(?:\\.|(?!&quot;).)*&quot;)(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
    (m, str, colon, lit, num) => {
      if (str) return colon ? `<span class="j-key">${str}</span>${colon}` : `<span class="j-str">${str}</span>`;
      if (lit) return `<span class="j-lit">${lit}</span>`;
      return `<span class="j-num">${num}</span>`;
    }
  );
}

function renderPreview() {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === state.tab));
  const item = state.items.find((it) => it.id === state.selectedId);

  if (!item) {
    els.title.textContent = "Aperçu";
    els.stats.innerHTML = "";
    els.body.innerHTML = `<p class="placeholder">Sélectionnez un fichier pour afficher un aperçu.</p>`;
    return;
  }
  els.title.textContent = item.dbf.name;

  if (item.status === "error") {
    els.stats.innerHTML = "";
    els.body.innerHTML = `<p class="placeholder" style="color:var(--err)">${escapeHtml(item.error)}</p>`;
    return;
  }
  if (!item.info) {
    els.stats.innerHTML = "";
    els.body.innerHTML = `<p class="placeholder">Analyse en cours…</p>`;
    return;
  }

  const info = item.info;
  els.stats.innerHTML = [
    [info.record_count.toLocaleString("fr-FR"), "enregistrements"],
    [info.fields.length, "champs"],
    [escapeHtml(info.encoding), "encodage"],
    [`<span title="${escapeHtml(info.dbversion)}">${info.version_code}</span>`, "version"],
    [info.last_update || "—", "dernière mise à jour"],
  ].map(([v, l]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");

  if (state.tab === "schema") {
    els.body.innerHTML = `
      <table>
        <thead><tr><th>#</th><th>Nom</th><th>Type</th><th>Longueur</th><th>Décimales</th></tr></thead>
        <tbody>${info.fields.map((f, i) => `
          <tr><td>${i + 1}</td><td>${escapeHtml(f.name)}</td>
          <td><span class="type-code">${escapeHtml(f.type)}</span> ${escapeHtml(f.type_name)}</td>
          <td class="num">${f.length}</td><td class="num">${f.decimals}</td></tr>`).join("")}
        </tbody>
      </table>`;
    return;
  }

  if (state.tab === "json") {
    const { preview, ...meta } = info;
    const sample = els.includeSchema.checked ? { ...meta, records: preview } : preview;
    const text = JSON.stringify(sample, null, 2);
    const note = preview.length < info.record_count
      ? `<p class="placeholder">Aperçu limité aux ${preview.length} premiers enregistrements — utilisez « JSON ⤓ » pour le fichier complet.</p>`
      : "";
    els.body.innerHTML = `${note}<pre class="json">${highlightJson(text)}</pre>`;
    return;
  }

  if (!info.preview.length) {
    els.body.innerHTML = `<p class="placeholder">La table ne contient aucun enregistrement.</p>`;
    return;
  }
  const cols = Object.keys(info.preview[0]);
  els.body.innerHTML = `
    <table>
      <thead><tr><th>#</th>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
      <tbody>${info.preview.map((row, i) => `
        <tr class="${row._deleted ? "deleted" : ""}"><td class="null">${i + 1}</td>${cols.map((c) => renderValueCell(row[c])).join("")}</tr>`).join("")}
      </tbody>
    </table>`;
}

function render() {
  renderList();
  renderPreview();
}

/* ---------- events ---------- */

els.input.addEventListener("change", (e) => {
  addFiles(e.target.files);
  e.target.value = "";
});

["dragenter", "dragover"].forEach((type) =>
  els.dropzone.addEventListener(type, (e) => { e.preventDefault(); els.dropzone.classList.add("drag"); }));
["dragleave", "drop"].forEach((type) =>
  els.dropzone.addEventListener(type, (e) => { e.preventDefault(); els.dropzone.classList.remove("drag"); }));
els.dropzone.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

els.list.addEventListener("click", (e) => {
  const li = e.target.closest(".file");
  if (!li) return;
  const item = state.items.find((it) => it.id === Number(li.dataset.id));
  const action = e.target.closest("[data-action]")?.dataset.action;
  if (action === "convert") return convert(item);
  if (action === "remove") {
    state.items = state.items.filter((it) => it !== item);
    if (state.selectedId === item.id) state.selectedId = state.items[0]?.id ?? null;
    return render();
  }
  state.selectedId = item.id;
  render();
});

els.convertAll.addEventListener("click", async () => {
  for (const item of state.items) {
    if (item.status !== "error") await convert(item);
  }
});

els.clear.addEventListener("click", () => {
  state.items = [];
  state.orphanMemos = {};
  state.selectedId = null;
  render();
});

document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => { state.tab = tab.dataset.tab; renderPreview(); }));

// Options that change how records are read -> re-analyse every file
[els.encoding, els.lowercase, els.includeDeleted].forEach((el) =>
  el.addEventListener("change", () => state.items.forEach((it) => inspect(it))));
els.includeSchema.addEventListener("change", renderPreview);

render();
