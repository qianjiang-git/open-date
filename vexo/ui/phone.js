// Phone stub: polls the server once a second. All privacy rules are enforced server-side;
// this page only shows what the API returns for the token's own user.
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // Token: taken from ?token= once, then kept in sessionStorage and removed from the URL.
  let token = null;
  try {
    const q = new URLSearchParams(location.search).get("token");
    if (q) { sessionStorage.setItem("vexo-token", q); history.replaceState(null, "", location.pathname); }
    token = sessionStorage.getItem("vexo-token");
  } catch (_) {
    token = new URLSearchParams(location.search).get("token");
  }
  if (!token) {
    document.querySelector("main").innerHTML = "<div class='card'>Open the phone link printed by <code>demo/seed.py</code>.</div>";
    return;
  }

  const api = async (method, path, body) => {
    const r = await fetch(path, {
      method, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : r.statusText);
    return data;
  };
  const toast = (msg) => { const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.h); toast.h = setTimeout(() => (t.hidden = true), 3500); };

  let me = null, cursor = 0, items = [], lastMatchJson = "";
  const GOALS = { "long-term": "Long-term", casual: "Casual", "friendship-first": "Friendship first" };
  const tags = (list) => `<div class="tags">${(list || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>`;

  function renderMe() {
    $("name").textContent = me.display_name;
    $("band").textContent = me.band_number ? `Band ${me.band_number} · ${me.demo_mode} demo` : "No band enrolled";
    const h = me.hub;
    const hub = $("hub");
    if (!h || !h.online) { hub.textContent = "hub offline"; hub.className = "pill bad"; }
    else if (h.band_state === "needs_double_tap") { hub.textContent = "double-tap your band"; hub.className = "pill warn"; }
    else { hub.textContent = `band ${h.band_state}`; hub.className = "pill good"; }
    $("open").checked = me.dating_status === "open";
    $("status-note").textContent = me.dating_status === "open"
      ? "Discoverable to compatible people nearby. Your band blinks blue while searching."
      : "Paused: nobody can match with you.";
    const p = me.profile;
    $("profile").innerHTML = p ? `
      <div>${esc(p.summary)}</div>
      <div class="muted" style="margin-top:8px">Interests</div>${tags(p.interests)}
      <div class="muted" style="margin-top:8px">Values</div>${tags(p.values)}
      <div class="muted" style="margin-top:8px">Looking for: ${esc(GOALS[p.goal] || "not set")}</div>
      ${p.complete ? "" : "<div class='label'>Profile incomplete: you will not be matched yet.</div>"}` : "No profile yet.";
  }

  function renderMatch(m) {
    const box = $("match");
    if (!m) { box.innerHTML = "No match right now. Stay open and walk around."; return; }
    const secs = m.seconds_left != null ? `<span class="muted small">${m.seconds_left}s left</span>` : "";
    if (m.state === "SCORING") { box.innerHTML = `<b>Someone nearby…</b><div class="muted small">Checking compatibility.</div>`; return; }
    if (m.state === "SUGGESTED") {
      box.innerHTML = `<div class="row"><b>${esc(m.headline)}</b>${secs}</div>
        <div class="muted small">${esc(m.detail)}</div>
        ${m.you_accepted ? "<div class='label'>You accepted. Waiting for them.</div>" : `
        <div class="actions"><button class="primary" data-act="accept">Accept</button><button data-act="decline">Not now</button></div>`}`;
      return;
    }
    const c = m.counterpart;
    const colour = m.color ? `<div class="swatch ${m.state === "LIT" ? "lit" : ""}" style="background:${esc(m.color)}">${esc(m.color_name)}</div>` : "<div class='label'>Waiting for a free colour.</div>";
    const stateLine = {
      ACCEPTED: "It's mutual. Walk toward each other; both bands light up when you're close.",
      LIGHTING: "Preparing bands…",
      LIT: `Look for ${esc(m.color_name)} on a wrist. Tap your band when you meet.`,
      MET: "You met!",
    }[m.state] || "";
    const labels = [];
    if (m.evidence && m.evidence !== "real_beacon") labels.push(`Proximity source: ${esc(m.evidence)}`);
    if (m.proximity_note) labels.push(esc(m.proximity_note));
    if (m.met_note) labels.push(esc(m.met_note));
    if (m.scorer && m.scorer.includes("fallback")) labels.push(`Scored by ${esc(m.scorer)}`);
    box.innerHTML = `<div class="row"><b>${esc(c.display_name)}</b>${secs}</div>
      <div class="small">${esc(stateLine)}</div>${colour}
      <div class="small">${esc(c.summary)}</div>
      ${m.shared && m.shared.length ? `<div class="muted small" style="margin-top:8px">In common</div>${tags(m.shared)}` : ""}
      ${m.icebreaker ? `<div class="small" style="margin-top:8px">💬 ${esc(m.icebreaker)}</div>` : ""}
      ${labels.map((l) => `<div class="label">${l}</div>`).join("")}
      <div class="actions">
        ${m.state === "LIT" && !m.you_tapped ? `<button data-act="confirm">Band tap not working? Confirm here</button>` : ""}
        ${m.state !== "MET" ? `<button data-act="cancel">Cancel</button><button class="danger" data-act="block">Block</button>` : ""}
      </div>`;
  }

  function renderInbox() {
    const ul = $("inbox");
    if (!items.length) { ul.innerHTML = "<li class='muted'>Nothing yet.</li>"; return; }
    ul.innerHTML = items.slice().reverse().slice(0, 8).map((n) =>
      `<li class="${n.read ? "" : "unread"}" data-id="${esc(n.id)}"><b>${esc(n.title)}</b><div class="small muted">${esc(n.body)}</div></li>`).join("");
  }

  async function loadProposals() {
    const { items: props } = await api("GET", "/api/me/profile-proposals");
    $("proposals").innerHTML = props.map((p) => `
      <div class="card"><b>Suggested profile update</b> <span class="muted small">(${esc(p.provider)})</span>
        <div class="small" style="margin-top:6px">${esc(p.changes.summary)}</div>
        ${tags(p.changes.interests)}${tags(p.changes.values)}
        <div class="small muted">Looking for: ${esc(GOALS[p.changes.goal] || "not set")}</div>
        <div class="actions"><button class="primary" data-prop="${esc(p.id)}" data-dec="accept">Approve</button>
        <button data-prop="${esc(p.id)}" data-dec="reject">Reject</button></div></div>`).join("");
  }

  let currentMatch = null;
  async function poll() {
    try {
      const { match } = await api("GET", "/api/me/match");
      currentMatch = match;
      const j = JSON.stringify(match);
      if (j !== lastMatchJson) { lastMatchJson = j; renderMatch(match); }
      const inbox = await api("GET", `/api/me/notifications?after=${cursor}`);
      const seen = new Set(items.map((n) => n.id));
      for (const n of inbox.items) if (!seen.has(n.id)) { items.push(n); toast(`${n.title}: ${n.body}`); }
      cursor = inbox.cursor;
      if (inbox.items.length) renderInbox();
    } catch (e) { /* transient; next poll refreshes authoritative state */ }
  }
  async function refreshMe() {
    try { me = await api("GET", "/api/me"); renderMe(); } catch (e) { toast(e.message); }
  }

  $("open").addEventListener("change", async (ev) => {
    try {
      await api("PUT", "/api/me/dating-status", { status: ev.target.checked ? "open" : "paused", expected_version: me.status_version });
    } catch (e) { toast(e.message); }
    refreshMe();
  });
  $("match").addEventListener("click", async (ev) => {
    const act = ev.target.dataset.act;
    if (!act || !currentMatch) return;
    const id = currentMatch.id;
    try {
      if (act === "accept" || act === "decline") await api("POST", `/api/matches/${id}/respond`, { accept: act === "accept" });
      if (act === "cancel") await api("POST", `/api/matches/${id}/cancel`);
      if (act === "block") await api("POST", `/api/matches/${id}/block`);
      if (act === "confirm") await api("POST", `/api/matches/${id}/confirm-met`);
    } catch (e) { toast(e.message); }
    lastMatchJson = ""; poll();
  });
  $("inbox").addEventListener("click", async (ev) => {
    const li = ev.target.closest("li[data-id]");
    if (!li) return;
    await api("POST", `/api/notifications/${li.dataset.id}/read`).catch(() => {});
    const n = items.find((x) => x.id === li.dataset.id); if (n) n.read = true; renderInbox();
  });
  $("send-note").addEventListener("click", async () => {
    const text = $("note").value.trim();
    if (text.length < 3) return;
    $("send-note").disabled = true;
    try { await api("POST", "/api/me/voice-notes", { transcript: text, source: "typed" }); $("note").value = ""; await loadProposals(); }
    catch (e) { toast(e.message); }
    $("send-note").disabled = false;
  });
  $("proposals").addEventListener("click", async (ev) => {
    const id = ev.target.dataset.prop; if (!id) return;
    try { await api("POST", `/api/me/profile-proposals/${id}/${ev.target.dataset.dec}`); toast(ev.target.dataset.dec === "accept" ? "Profile updated" : "Suggestion rejected"); }
    catch (e) { toast(e.message); }
    loadProposals(); refreshMe();
  });

  refreshMe().then(loadProposals);
  poll();
  setInterval(poll, 1000);
  setInterval(refreshMe, 3000);
})();
