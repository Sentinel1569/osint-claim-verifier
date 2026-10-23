"use strict";
let C = null, caseId = null, linkTarget = null, srcTab = "url";
const PAL = ["#2f6fde", "#d9822b", "#2f9e6e", "#c2477a", "#7b4bc4", "#3fa7d6", "#b7791f", "#5c7c99"];
const STANCE_ICON = { supports: "✔", refutes: "✖", attributes: "❝", mentions: "•" };
const KIND_COLOR = { event: "--accent", published: "--info", archived: "--muted", edited: "--warn", captured: "--hyp", retrieved: "--border" };

async function loadCases(select) {
  const cs = await api("/api/cases");
  $("#caseSel").innerHTML = cs.length ? cs.map((c) => `<option value="${c.id}">${esc(c.title)} (${c.claims} claims · ${c.sources} sources)</option>`).join("") : "<option value=''>No cases yet</option>";
  if (select) $("#caseSel").value = select;
  caseId = +$("#caseSel").value || null;
  await refresh();
}

async function refresh() {
  if (!caseId) { C = null; render(); return; }
  C = await api(`/api/cases/${caseId}`);
  render();
}

function render() {
  $("#mdLink").href = caseId ? `/api/cases/${caseId}/report.md` : "#";
  if (!C) { ["#stats", "#claims", "#matrix", "#contra", "#timeline", "#sources"].forEach((s) => $(s).innerHTML = ""); $("#claims").innerHTML = '<div class="empty">Create a case or load the demo.</div>'; return; }
  const b = C.summary.by_status;
  $("#stats").innerHTML = [["Claims", C.summary.claims, Object.entries(b).map(([k, v]) => `${v} ${k}`).join(" · ")],
    ["Sources", C.summary.sources, `${C.summary.independent_groups} independent groups`], ["Verified", b.verified || 0, ""], ["Red flags", C.summary.contradictions, ""]]
    .map(([l, v, sub]) => `<div class="card stat"><div class="v">${v}</div><div class="l">${l}${sub ? ` · ${esc(sub)}` : ""}</div></div>`).join("");
  const src = Object.fromEntries(C.sources.map((s) => [s.id, s]));
  const name = (s) => s.publisher || s.title || s.url || `#${s.id}`;
  $("#claims").innerHTML = C.claims.length ? C.claims.map((c) => `<div class="claim">
      <span class="status s-${c.status}">${c.status}</span> ${c.event_date ? `<span class="small muted mono">${esc(c.event_date)}</span>` : ""}
      <h3>${esc(c.text)}</h3><div class="small muted">${esc(c.explanation)}</div>
      <div class="row small" style="margin-top:8px"><span class="shrink">support</span>${bar(c.support)}<span class="shrink">refute</span>${bar(c.refute)}</div>
      ${c.contradictions ? `<div class="small" style="color:var(--warn);margin-top:6px">⚠ ${c.contradictions} red flag(s)</div>` : ""}
      <div style="margin-top:6px">${c.statements.map((st) => `<span class="badge st-${st.stance}" title="${esc(st.quote)}" style="margin:2px">${STANCE_ICON[st.stance]} #${st.source_id} ${esc(name(src[st.source_id]))}</span>`).join("")}</div>
      <div style="text-align:right"><button class="ghost sm" data-delclaim="${c.id}">Delete</button></div></div>`).join("") : '<div class="empty">Add a claim to evaluate.</div>';
  $$("[data-delclaim]").forEach((x) => x.onclick = async () => { if (confirm("Delete claim?")) { await api(`/api/claims/${x.dataset.delclaim}`, { method: "DELETE" }); refresh(); } });

  const groups = [...new Set(C.sources.map((s) => s.independence.group))];
  const gcol = (s) => PAL[groups.indexOf(s.independence.group) % PAL.length];
  $("#matrix").innerHTML = C.claims.length && C.sources.length ? `<table class="matrix"><thead><tr><th>Claim</th>${C.sources.map((s) => `<th class="src" title="${esc(s.title)}">#${s.id} ${esc(name(s)).slice(0, 26)}<div class="grpbar" style="background:${gcol(s)}"></div></th>`).join("")}</tr></thead><tbody>
    ${C.claims.map((c) => `<tr><td><span class="status s-${c.status}">${c.status.slice(0, 4)}</span> ${esc(c.text)}</td>${C.sources.map((s) => {
      const st = c.statements.find((x) => x.source_id === s.id);
      return `<td class="cell ${st ? "st-" + st.stance : ""}" data-c="${c.id}" data-s="${s.id}" title="${st ? esc(st.stance + (st.quote ? ": " + st.quote : "")) : "link…"}">${st ? STANCE_ICON[st.stance] : '<span class="muted">·</span>'}</td>`;
    }).join("")}</tr>`).join("")}</tbody></table>
    <div class="legend"><span class="st-supports">✔ supports</span><span class="st-refutes">✖ refutes</span><span class="st-attributes">❝ attributes</span><span class="st-mentions">• mentions</span></div>` : '<div class="empty">Add claims and sources.</div>';
  $$("#matrix .cell").forEach((td) => td.onclick = () => openLink(+td.dataset.c, +td.dataset.s));

  $("#contra").innerHTML = C.contradictions.length ? C.contradictions.map((x) => `<div class="flag"><span class="badge ${x.severity === "high" ? "b-bad" : x.severity === "medium" ? "b-warn" : "b-info"}">${esc(x.type)}</span>
      <span class="small muted">claim: ${esc((C.claims.find((c) => c.id === x.claim_id) || {}).text || "")}</span><div>${esc(x.detail)}</div></div>`).join("") : '<div class="empty">No contradictions detected.</div>';
  $("#timeline").innerHTML = `<div class="tl">${C.timeline.filter((t) => t.kind !== "retrieved").map((t) => `<div class="it" style="--k:var(${KIND_COLOR[t.kind]})"><div class="d">${esc(t.date.replace("T", " ").slice(0, 16))} · ${esc(t.kind)}</div><div>${esc(t.title)}</div></div>`).join("")}</div>`;
  $("#sources").innerHTML = C.sources.map((s) => {
    const a = s.archive || {}, im = s.image || {};
    return `<div class="src"><div class="row" style="justify-content:space-between">
      <div style="flex:1"><b>#${s.id} ${esc(s.title || name(s))}</b> <span class="badge b-muted">${esc(s.kind)}</span> ${confBadge(s.confidence)}
        <div class="small muted">${esc(s.publisher)}${s.author ? " · " + esc(s.author) : ""}${s.published ? " · published " + esc(s.published.slice(0, 16).replace("T", " ")) : ""}</div>
        ${s.url ? `<div class="small"><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.url)}</a></div>` : ""}</div>
      <div class="row" style="gap:4px;flex-wrap:nowrap"><select style="width:auto" data-g="rel" data-id="${s.id}">${"ABCDEF".split("").map((x) => `<option ${x === s.reliability ? "selected" : ""}>${x}</option>`).join("")}</select>
      <select style="width:auto" data-g="cred" data-id="${s.id}">${[1, 2, 3, 4, 5, 6].map((x) => `<option ${x === s.credibility ? "selected" : ""}>${x}</option>`).join("")}</select>
      <button class="ghost sm" data-delsrc="${s.id}">✕</button></div></div>
      <div class="small" style="margin-top:6px"><span class="grpbar" style="display:inline-block;width:24px;background:${gcol(s)}"></span> independence group ${s.independence.group}${s.independence.reasons.length ? ": " + esc(s.independence.reasons.join("; ")) : " (independent)"}</div>
      ${a.count ? `<div class="small" style="margin-top:6px"><b>Wayback:</b> ${a.count} capture(s), first ${esc(a.first.slice(0, 10))}, ${a.versions} distinct version(s)${a.first_url ? ` · <a href="${esc(a.first_url)}" target="_blank" rel="noopener noreferrer">earliest</a>` : ""}
        ${(a.diff || []).length ? `<div style="margin-top:4px">${a.diff.map((d) => `<div class="diff-${d.op}">${d.op === "added" ? "+" : "−"} ${esc(d.text)}</div>`).join("")}</div>` : ""}</div>` : ""}
      ${im.sha256 ? `<div class="small" style="margin-top:6px"><b>Image:</b> ${im.width}×${im.height} ${esc(im.format || "")} · taken <b>${esc(im.taken || "unknown")}</b> · camera ${esc(im.camera || "—")} · software ${esc(im.software || "—")}${im.gps ? ` · GPS ${im.gps.join(", ")}` : ""}
        <div class="mono muted">dHash ${esc(im.dhash)} · sha256 ${esc(im.sha256.slice(0, 24))}…</div>${im.has_exif ? "" : '<div class="muted">No EXIF (often stripped by social platforms; absence proves nothing).</div>'}</div>` : ""}
      ${s.text && !im.sha256 ? `<details style="margin-top:6px"><summary>Retrieved text</summary><pre style="white-space:pre-wrap">${esc(s.text.slice(0, 3000))}</pre></details>` : ""}
      <div class="small muted mono" style="margin-top:4px">retrieved ${esc((s.retrieved_at || "").slice(0, 19))} · sha256 ${esc((s.sha256 || "").slice(0, 24))}…</div></div>`;
  }).join("") || '<div class="empty">No sources yet.</div>';
  $$("[data-g]").forEach((x) => x.onchange = async () => {
    const id = x.dataset.id, rel = $(`[data-g=rel][data-id="${id}"]`).value, cred = +$(`[data-g=cred][data-id="${id}"]`).value;
    await api(`/api/sources/${id}`, { method: "PATCH", json: { fields: { reliability: rel, credibility: cred } } });
    refresh();
  });
  $$("[data-delsrc]").forEach((x) => x.onclick = async () => { if (confirm("Delete source and its links?")) { await api(`/api/sources/${x.dataset.delsrc}`, { method: "DELETE" }); refresh(); } });
}

function openLink(cid, sid) {
  const c = C.claims.find((x) => x.id === cid), s = C.sources.find((x) => x.id === sid);
  const st = c.statements.find((x) => x.source_id === sid) || {};
  linkTarget = { cid, sid };
  $("#linkCard").hidden = false;
  $("#linkWhat").innerHTML = `<b>Claim:</b> ${esc(c.text)}<br><b>Source:</b> #${s.id} ${esc(s.publisher || s.title)}`;
  $("#lStance").value = st.stance || "supports"; $("#lQuote").value = st.quote || ""; $("#lValue").value = st.value || "";
  $("#linkCard").scrollIntoView({ behavior: "smooth", block: "center" });
}

async function readB64(file) {
  return new Promise((res, rej) => { const fr = new FileReader(); fr.onload = () => res(String(fr.result).split(",")[1]); fr.onerror = rej; fr.readAsDataURL(file); });
}

document.addEventListener("DOMContentLoaded", async () => {
  $("#caseSel").onchange = (e) => { caseId = +e.target.value; refresh(); };
  $("#addCase").onclick = () => busy($("#addCase"), async () => { const r = await api("/api/cases", { json: { title: $("#newCase").value } }); $("#newCase").value = ""; await loadCases(r.id); });
  $("#demo").onclick = () => busy($("#demo"), async () => { const r = await api("/api/demo", { method: "POST" }); await loadCases(r.id); });
  $$("#srcTabs button").forEach((b) => b.onclick = () => {
    srcTab = b.dataset.t; $$("#srcTabs button").forEach((x) => x.classList.toggle("active", x === b));
    $$("#addSrcCard [data-p]").forEach((p) => p.hidden = p.dataset.p !== srcTab);
  });
  $("#addSrc").onclick = () => busy($("#addSrc"), async () => {
    if (!caseId) { toast("Create or select a case first"); return; }
    const grade = { kind: $("#sKind").value, reliability: $("#sRel").value, credibility: +$("#sCred").value };
    if (srcTab === "url") {
      const r = await api(`/api/cases/${caseId}/sources/url`, { json: { url: $("#sUrl").value, archive: $("#sArchive").checked, ...grade } });
      (r.errors || []).forEach((e) => toast(e)); $("#sUrl").value = "";
    } else if (srcTab === "image") {
      const f = $("#sImg").files[0]; if (!f) { toast("Choose an image"); return; }
      await api(`/api/cases/${caseId}/sources/image`, { json: { name: f.name, content_b64: await readB64(f), url: $("#sImgUrl").value, caption: $("#sImgCaption").value, published: $("#sImgDate").value, reliability: grade.reliability, credibility: grade.credibility } });
    } else {
      await api(`/api/cases/${caseId}/sources/manual`, { json: { title: $("#mTitle").value, publisher: $("#mPub").value, published: $("#mDate").value, text: $("#mText").value, ...grade } });
    }
    await refresh();
  });
  $("#addClaim").onclick = () => busy($("#addClaim"), async () => {
    if (!caseId) { toast("Create or select a case first"); return; }
    await api(`/api/cases/${caseId}/claims`, { json: { text: $("#cText").value, event_date: $("#cDate").value } });
    $("#cText").value = ""; await refresh();
  });
  $("#lSave").onclick = () => busy($("#lSave"), async () => {
    await api("/api/statements", { json: { claim_id: linkTarget.cid, source_id: linkTarget.sid, stance: $("#lStance").value, quote: $("#lQuote").value, value: $("#lValue").value } });
    $("#linkCard").hidden = true; await refresh();
  });
  $("#lCancel").onclick = () => { $("#linkCard").hidden = true; };
  await loadCases();
});
