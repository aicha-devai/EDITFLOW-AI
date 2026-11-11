import "./styles.css";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = {
  apiBase: localStorage.getItem("editflow-api-base") || "http://localhost:8000",
  accessToken: sessionStorage.getItem("editflow-access-token") || "",
  refreshToken: sessionStorage.getItem("editflow-refresh-token") || "",
  userEmail: sessionStorage.getItem("editflow-user-email") || "",
  mediaObjectUrl: "",
  projectId: "",
  jobId: "",
  graph: null,
  mediaUrl: "",
  playbackSeconds: 0,
  playbackWasPlaying: false,
  pendingSeekSeconds: null,
  currentEvidenceId: null,
  selectedId: null,
  selectedEdgeId: null,
  filter: "all",
  search: "",
  loading: false,
  error: "",
  zoom: 1,
};

const typeMeta = {
  character: { label: "Characters", icon: "♙", color: "#b99cff" },
  place: { label: "Places", icon: "⌖", color: "#61d9c5" },
  event: { label: "Events", icon: "✳", color: "#ffb86b" },
  shot: { label: "Shots", icon: "▧", color: "#78aaff" },
  narration: { label: "Voiceover", icon: "≋", color: "#f18fc2" },
  visual_observation: { label: "Visual evidence", icon: "◉", color: "#9acb8b" },
  story_beat: { label: "Story beats", icon: "◈", color: "#e9d77c" },
};
const relationLabels = {
  appears_in: "appears in", located_at: "located at", participates_in: "participates in",
  depicts: "depicts", mentions: "mentions", precedes: "precedes", supports: "supports",
  contradicts: "contradicts", causes: "causes", narrates: "narrates",
  observed_during: "observed during", sampled_during: "sampled during",
  evidenced_by: "evidenced by", present_during: "present during",
  temporally_associated_with: "temporally associated with",
};

function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function hasTimestamp(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}
function fmtTime(value) {
  if (value === null || value === undefined || !hasTimestamp(value)) return "Time unavailable";
  const seconds = Math.max(0, Number(value));
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(1).padStart(4, "0");
  return `${String(m).padStart(2, "0")}:${s}`;
}
function nodeTitle(node) {
  return node.label || node.name || node.title || node.id;
}
function nodeType(node) {
  return typeMeta[node.type] || { label: node.type || "Other", icon: "◇", color: "#9ca8bb" };
}
function evidenceFor(id) {
  return state.graph?.nodes?.find(n => n.id === id) || null;
}
function render() {
  const oldVideo = $("#story-video");
  if (oldVideo && Number.isFinite(oldVideo.currentTime)) {
    state.playbackSeconds = oldVideo.currentTime;
    state.playbackWasPlaying = !oldVideo.paused;
  }
  $("#app").innerHTML = `
    <div class="shell">
      <aside class="rail">
        <div class="brand-mark">E<span>.</span></div>
        <div class="rail-divider"></div>
        <button class="rail-button active" title="Story graph">⌘</button>
        <button class="rail-button" title="Timeline" disabled>▤</button>
        <button class="rail-button" title="Media" disabled>▧</button>
        <div class="rail-spacer"></div>
        <div class="avatar">AI</div>
      </aside>
      <main class="workspace">
        <header class="topbar">
          <div class="crumb"><span>EDITFLOW AI</span><b>/</b><strong>Story Graph Explorer</strong></div>
          <div class="top-actions">
            <span class="live-dot"></span><span class="top-status" id="account-status">${state.userEmail ? escapeHtml(state.userEmail) : "Not signed in"}</span>
            <button class="icon-button" id="account-btn" title="Account and API settings">⚙</button>
          </div>
        </header>
        <section class="intro">
          <div>
            <div class="eyebrow">STORY INTELLIGENCE / CONTINUITY</div>
            <h1>See how your story <em>connects.</em></h1>
            <p>Explore characters, places, events, shots and narration — linked by timestamped evidence.</p>
          </div>
          <div class="integrity-pill"><span>◈</span> Evidence-linked graph</div>
        </section>
        <section class="connect-panel" id="connect-panel">
          <div class="connect-copy"><span class="connect-icon">↗</span><div><strong>Connect a rendered story</strong><small>Load a graph from a completed Render Job.</small></div></div>
          <form id="load-form" class="load-form">
            <label>PROJECT ID<input id="project-input" autocomplete="off" placeholder="Project UUID" value="${escapeHtml(state.projectId)}" required></label>
            <label>RENDER JOB ID<input id="job-input" autocomplete="off" placeholder="Render Job UUID" value="${escapeHtml(state.jobId)}" required></label>
            <button class="primary-button" type="submit" ${state.loading ? "disabled" : ""}>${state.loading ? "Loading…" : "Load graph"} <span>→</span></button>
          </form>
          ${state.error ? `<div class="error-line">⚠ ${escapeHtml(state.error)}</div>` : ""}
        </section>
        ${state.graph ? renderExplorer() : renderWelcome()}
      </main>
    </div>
    <div id="settings-modal" class="modal-backdrop hidden">
      <section class="settings-modal">
        <div class="modal-head"><div><span class="eyebrow">CONNECTION</span><h2>API settings</h2></div><button id="close-settings" class="icon-button">×</button></div>
        <label>API BASE URL<input id="api-base-input" value="${escapeHtml(state.apiBase)}" placeholder="http://localhost:8000"></label>
        <button id="save-settings" class="primary-button full">Save connection</button>
        <div class="modal-head"><div><span class="eyebrow">ACCOUNT</span><h2>Sign in</h2></div></div>
        <label>EMAIL<input id="account-email" type="email" autocomplete="email" value="${escapeHtml(state.userEmail)}"></label>
        <label>PASSWORD<input id="account-password" type="password" autocomplete="current-password"></label>
        <button id="account-login" class="primary-button full">Sign in</button>
        <button id="account-register" class="secondary-button full">Create account</button>
        <div class="account-links"><button id="password-reset-request" class="text-button" type="button">Forgot password?</button><button id="verification-resend" class="text-button" type="button">Resend verification email</button></div>
        <div class="collaboration-panel">
          <div class="modal-head"><div><span class="eyebrow">COLLABORATION</span><h2>Invite to a project</h2></div></div>
          <label>PROJECT ID<input id="invite-project-id" value="${escapeHtml(state.projectId)}" placeholder="Project UUID"></label>
          <label>INVITEE EMAIL<input id="invite-email" type="email" autocomplete="email" placeholder="teammate@example.com"></label>
          <label>ACCESS ROLE<select id="invite-role"><option value="editor">Editor — can edit</option><option value="viewer">Viewer — read only</option></select></label>
          <button id="send-invitation" class="secondary-button full" type="button" ${state.accessToken ? "" : "disabled"}>Send invitation</button>
          <p class="muted">Only the project owner can invite. The invitation expires after 7 days.</p>
        </div>
        <button id="account-logout" class="icon-button full" ${state.accessToken ? "" : "disabled"}>Sign out</button>
        <p id="account-message" class="muted" role="status"></p>
        <p class="muted">New accounts must verify their email before signing in. Access and refresh tokens are kept in this browser tab session.</p>
      </section>
    </div>`;
  bindShell();
  if (state.graph) bindExplorer();
}
function renderWelcome() {
  return `
    <section class="welcome">
      <div class="welcome-art"><div class="orbit orbit-a"></div><div class="orbit orbit-b"></div><div class="orbit orbit-c"></div><div class="orbit-core">✳</div><i class="spark s1"></i><i class="spark s2"></i><i class="spark s3"></i></div>
      <div class="welcome-text"><span class="eyebrow">YOUR STORY, DECODED</span><h2>A connected view of every story element.</h2><p>Enter a Project ID and a successful Render Job ID above. The explorer will map the graph returned by the API and let you inspect every evidence link.</p><div class="welcome-tags"><span>Characters</span><span>Places</span><span>Events</span><span>Shots</span><span>Voiceover</span></div></div>
    </section>`;
}

function renderEvidenceTrack() {
  const items = (state.graph?.nodes || [])
    .filter(node => node.start_seconds !== null && node.start_seconds !== undefined && hasTimestamp(node.start_seconds))
    .sort((a,b) => Number(a.start_seconds) - Number(b.start_seconds))
    .slice(0, 160);
  if (!items.length) return `<div class="evidence-track-empty">No timestamped evidence is available for this render.</div>`;
  return `<div class="evidence-track-wrap"><div class="evidence-track-heading"><span>TIME-ALIGNED EVIDENCE</span><small>${items.length} markers · select to jump</small></div><div class="evidence-track" aria-label="Timestamped evidence markers">${items.map(node => {
    const meta = nodeType(node);
    const active = state.currentEvidenceId === node.id;
    return `<button class="evidence-marker ${active ? "is-playing" : ""}" data-evidence-node="${escapeHtml(node.id)}" data-jump-time="${Number(node.start_seconds)}" title="${escapeHtml(nodeTitle(node))} · ${fmtTime(node.start_seconds)}" aria-label="Jump to ${escapeHtml(nodeTitle(node))} at ${fmtTime(node.start_seconds)}"><i style="--entity:${meta.color}"></i><span>${escapeHtml(nodeTitle(node).slice(0,48))}</span><small>${fmtTime(node.start_seconds)}</small></button>`;
  }).join("")}</div></div>`;
}
function findCurrentEvidence(seconds) {
  const nodes = (state.graph?.nodes || []).filter(node => node.start_seconds !== null && node.start_seconds !== undefined && hasTimestamp(node.start_seconds));
  const covering = nodes.filter(node => {
    const start = Number(node.start_seconds);
    const end = hasTimestamp(node.end_seconds) ? Number(node.end_seconds) : start;
    return end > start ? seconds >= start && seconds < end : Math.abs(seconds - start) <= 0.45;
  }).sort((a,b) => Number(b.start_seconds) - Number(a.start_seconds));
  return covering[0] || null;
}
function updateActiveEvidence(seconds) {
  const active = findCurrentEvidence(seconds);
  state.currentEvidenceId = active?.id || null;
  $$(".evidence-marker").forEach(el => {
    el.classList.toggle("is-playing", Boolean(active && el.dataset.evidenceNode === active.id));
  });
  $$(".graph-node").forEach(el => el.classList.toggle("node-playing", Boolean(active && el.dataset.node === active.id)));
  const label = $("#active-evidence-label");
  if (label) label.textContent = active ? `Now: ${nodeTitle(active)} · ${fmtTime(active.start_seconds)}` : "No active evidence at this time";
}
function renderVideoPlayer() {
  if (!state.mediaUrl) return `
    <section class="video-panel video-unavailable">
      <div><span class="eyebrow">RENDER PLAYBACK</span><h2>Video preview unavailable</h2><p>The Render Job has no accessible output media. Confirm it completed successfully and that its storage object is present.</p></div>
    </section>`;
  return `
    <section class="video-panel">
      <div class="video-panel-head"><div><span class="eyebrow">RENDER PLAYBACK</span><h2>Evidence video</h2><p>Choose a timestamped evidence item to seek directly to its moment.</p></div><div class="player-time" id="player-time">${fmtTime(state.playbackSeconds)}</div></div>
      <video id="story-video" controls playsinline preload="metadata">
        <source src="${escapeHtml(state.mediaUrl)}" type="video/mp4">
        Your browser does not support HTML5 video.
      </video>
      ${renderEvidenceTrack()}
      <div class="player-foot"><span>Original rendered output</span><span id="active-evidence-label">No active evidence at this time</span></div>
    </section>`;
}
function seekToTimestamp(value, autoplay = true) {
  if (!hasTimestamp(value)) return;
  const seconds = Number(value);
  if (seconds < 0) return;
  state.pendingSeekSeconds = seconds;
  const video = $("#story-video");
  if (!video) return;
  const applySeek = () => {
    const max = Number.isFinite(video.duration) ? Math.max(0, video.duration - 0.05) : seconds;
    const target = Math.min(seconds, max);
    try { video.currentTime = target; } catch { return; }
    state.playbackSeconds = target;
    state.pendingSeekSeconds = null;
    updateActiveEvidence(target);
    const time = $("#player-time");
    if (time) time.textContent = fmtTime(target);
    if (autoplay) {
      const promise = video.play();
      if (promise?.catch) promise.catch(() => {});
    }
  };
  if (video.readyState >= 1 && Number.isFinite(video.duration)) applySeek();
  else video.addEventListener("loadedmetadata", applySeek, { once: true });
}
function bindVideoPlayer() {
  const video = $("#story-video");
  if (!video) return;
  const restore = () => {
    const hadPendingSeek = state.pendingSeekSeconds !== null;
    const target = hadPendingSeek ? state.pendingSeekSeconds : state.playbackSeconds;
    if (Number.isFinite(video.duration) && video.duration > 0) {
      video.currentTime = Math.min(target, Math.max(0, video.duration - 0.05));
      if (hadPendingSeek) state.pendingSeekSeconds = null;
      if (state.playbackWasPlaying) {
        const promise = video.play();
        if (promise?.catch) promise.catch(() => {});
      }
    }
  };
  if (video.readyState >= 1) restore();
  else video.addEventListener("loadedmetadata", restore, { once: true });
  updateActiveEvidence(video.currentTime || state.playbackSeconds);
  video.addEventListener("timeupdate", () => {
    state.playbackSeconds = video.currentTime;
    const time = $("#player-time");
    if (time) time.textContent = fmtTime(video.currentTime);
    updateActiveEvidence(video.currentTime);
  });
  video.addEventListener("play", () => { state.playbackWasPlaying = true; });
  video.addEventListener("pause", () => { state.playbackWasPlaying = false; });
  video.addEventListener("error", () => {
    const panel = $(".video-panel");
    if (panel) {
      const message = video.error?.code === 4 ? "The media URL or video format is not supported." : "Could not load the rendered video. Check API access and storage availability.";
      let notice = $(".video-error", panel);
      if (!notice) { notice = document.createElement("p"); notice.className = "video-error"; panel.append(notice); }
      notice.textContent = message;
    }
  });
}

function renderExplorer() {
  const graph = state.graph;
  const counts = Object.keys(typeMeta).map(type => ({ type, count: graph.nodes.filter(n => n.type === type).length })).filter(x => x.count);
  const status = graph.status || "unknown";
  const visibleNodes = filteredNodes();
  const selected = state.selectedId ? evidenceFor(state.selectedId) : null;
  return `
    <section class="stats-row">
      <div class="stat-card"><span>GRAPH NODES</span><strong>${graph.nodes.length}</strong><small>Story elements & evidence</small></div>
      <div class="stat-card"><span>RELATIONSHIPS</span><strong>${graph.edges.length}</strong><small>Connected evidence links</small></div>
      <div class="stat-card"><span>ENTITY EXTRACTION</span><strong class="stat-word">${escapeHtml((graph.entity_extraction_status || "unknown").replaceAll("_"," "))}</strong><small>Semantic extraction state</small></div>
      <div class="stat-card"><span>GRAPH STATUS</span><strong class="status-word ${status === "completed" ? "good" : "warn"}">${escapeHtml(status.replaceAll("_"," "))}</strong><small>${graph.integrity?.automatic_timeline_changes ?? 0} automatic timeline edits</small></div>
    </section>
    ${renderVideoPlayer()}
    <section class="explorer-layout">
      <div class="graph-column">
        <div class="graph-toolbar">
          <div><span class="eyebrow">CONTINUITY MAP</span><h2>Story network</h2></div>
          <div class="graph-actions"><div class="search-wrap">⌕ <input id="graph-search" placeholder="Find an element…" value="${escapeHtml(state.search)}"></div><button class="icon-button" id="zoom-out" title="Zoom out">−</button><button class="icon-button" id="zoom-in" title="Zoom in">+</button><button class="icon-button" id="fit-graph" title="Fit graph">⤢</button></div>
        </div>
        <div class="filter-row"><button class="filter-chip ${state.filter === "all" ? "selected" : ""}" data-filter="all">All <b>${graph.nodes.length}</b></button>${counts.map(x => `<button class="filter-chip ${state.filter === x.type ? "selected" : ""}" data-filter="${x.type}"><i style="--chip:${nodeType({type:x.type}).color}"></i>${nodeType({type:x.type}).label} <b>${x.count}</b></button>`).join("")}</div>
        <div class="graph-stage" id="graph-stage">
          ${visibleNodes.length ? renderGraphSvg(visibleNodes) : '<div class="empty-filter">No elements match this filter.</div>'}
          <div class="graph-legend"><span><i class="line-solid"></i> Timeline / evidence</span><span><i class="line-dashed"></i> Semantic relation</span></div>
          <div class="graph-hint">Select a node or connection to inspect its evidence</div>
        </div>
        <div class="graph-foot"><span>Showing <b>${visibleNodes.length}</b> of <b>${graph.nodes.length}</b> nodes</span><span>Graph is read-only · Original timeline remains unchanged</span></div>
      </div>
      <aside class="inspector">
        ${selected ? renderNodeInspector(selected) : state.selectedEdgeId ? renderEdgeInspector() : renderOverviewInspector()}
      </aside>
    </section>
    ${graph.limitations?.length ? `<section class="limitations"><strong>Analysis limitations</strong>${graph.limitations.map(x => `<p>${escapeHtml(x)}</p>`).join("")}</section>` : ""}
  `;
}
function filteredNodes() {
  const q = state.search.trim().toLowerCase();
  return state.graph.nodes.filter(n => (state.filter === "all" || n.type === state.filter) &&
    (!q || [nodeTitle(n), n.description, n.id].join(" ").toLowerCase().includes(q)));
}
function graphLayout(nodes) {
  const width = 1100, height = 650;
  const groups = ["character","place","event","story_beat","shot","visual_observation","narration"];
  const buckets = new Map(groups.map(g => [g, []]));
  nodes.forEach(n => (buckets.get(n.type) || buckets.get("story_beat")).push(n));
  const positions = new Map();
  const laneX = { character: 115, place: 285, event: 455, story_beat: 625, shot: 795, visual_observation: 945, narration: 1060 };
  groups.forEach(type => {
    const items = buckets.get(type);
    items.forEach((node, i) => {
      const gap = height / (items.length + 1);
      positions.set(node.id, { x: laneX[type], y: gap * (i + 1), node });
    });
  });
  return { width, height, positions };
}
function renderGraphSvg(nodes) {
  const { width, height, positions } = graphLayout(nodes);
  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  const edges = state.graph.edges.filter(e => positions.has(e.source) && positions.has(e.target));
  const paths = edges.map(edge => {
    const a = positions.get(edge.source), b = positions.get(edge.target);
    const mid = (a.x + b.x) / 2;
    const d = `M ${a.x} ${a.y} C ${mid} ${a.y}, ${mid} ${b.y}, ${b.x} ${b.y}`;
    const semantic = !["precedes","narrates","observed_during","sampled_during","temporally_associated_with"].includes(edge.type);
    const label = relationLabels[edge.type] || edge.type;
    return `<g class="edge-control" data-edge="${escapeHtml(edge.id)}" tabindex="0" role="button" aria-label="Inspect relationship: ${escapeHtml(label)}">
      <path class="edge-hit" d="${d}"></path>
      <path class="edge ${semantic ? "semantic" : "temporal"} ${state.selectedEdgeId === edge.id ? "edge-selected" : ""}" d="${d}" aria-hidden="true"><title>${escapeHtml(label)}</title></path>
    </g>`;
  }).join("");
  const circles = nodes.map(node => {
    const p = positions.get(node.id), meta = nodeType(node), selected = state.selectedId === node.id;
    const title = escapeHtml(nodeTitle(node).slice(0, 25));
    const label = title.length > 22 ? title.slice(0, 21) + "…" : title;
    return `<g class="graph-node ${selected ? "node-selected" : ""}" transform="translate(${p.x},${p.y})" data-node="${escapeHtml(node.id)}" tabindex="0" role="button" aria-label="${title}">
      <circle class="node-halo" r="26" fill="${meta.color}" opacity=".12"></circle><circle class="node-dot" r="17" fill="${meta.color}"></circle>
      <text class="node-icon" text-anchor="middle" y="5">${meta.icon}</text>
      <text class="node-label" text-anchor="middle" y="43">${label}</text>
      <text class="node-type" text-anchor="middle" y="57">${meta.label.toUpperCase()}</text>
    </g>`;
  }).join("");
  const laneLabels = ["CHARACTERS","PLACES","EVENTS","STORY BEATS","SHOTS","VISUAL EVIDENCE","VOICEOVER"];
  const laneXs = [115,285,455,625,795,945,1060];
  return `<svg class="graph-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Interactive story continuity graph">
    <defs><pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#ffffff" opacity=".08"/></pattern></defs>
    <rect width="${width}" height="${height}" fill="url(#dots)"></rect>
    ${laneXs.map((x,i)=>`<line class="lane-line" x1="${x}" y1="25" x2="${x}" y2="620"></line><text class="lane-label" x="${x}" y="18" text-anchor="middle">${laneLabels[i]}</text>`).join("")}
    <g class="edge-layer">${paths}</g><g class="node-layer">${circles}</g>
  </svg>`;
}
function renderOverviewInspector() {
  const edges = state.graph.edges.slice(0, 5);
  return `<div class="inspector-head"><span class="eyebrow">GRAPH INSPECTOR</span><span class="inspector-mark">✳</span></div><h3>Explore the connections</h3><p class="inspector-desc">Choose any node to see its details, timestamps and supporting evidence. Choose a line to inspect the relationship.</p>
    <div class="inspector-divider"></div><div class="mini-heading">RELATIONSHIP TYPES</div><div class="relation-list">${Object.entries(relationLabels).filter(([k]) => state.graph.edges.some(e=>e.type===k)).map(([k,v])=>`<div><span>${escapeHtml(v)}</span><b>${state.graph.edges.filter(e=>e.type===k).length}</b></div>`).join("")}</div>
    <div class="inspector-divider"></div><div class="mini-heading">RECENT CONNECTIONS</div>${edges.map(e=>`<button class="connection-row" data-inspect-edge="${escapeHtml(e.id)}"><span>${escapeHtml(nodeTitle(evidenceFor(e.source)) || e.source)}</span><i>→</i><span>${escapeHtml(nodeTitle(evidenceFor(e.target)) || e.target)}</span></button>`).join("") || '<p class="muted">No relationships available yet.</p>'}`;
}
function renderNodeInspector(node) {
  const meta = nodeType(node);
  const edges = state.graph.edges.filter(e => e.source === node.id || e.target === node.id);
  const refs = [...new Set([...(node.evidence_refs || []), ...edges.flatMap(e => e.evidence_refs || [])])];
  const evidenceNodes = refs.map(evidenceFor).filter(Boolean);
  const start = node.start_seconds, end = node.end_seconds;
  return `<div class="inspector-head"><span class="eyebrow">NODE DETAILS</span><button class="text-button" id="clear-selection">Clear ×</button></div>
    <div class="entity-title"><span class="entity-icon" style="--entity:${meta.color}">${meta.icon}</span><div><span class="entity-type">${meta.label.toUpperCase()}</span><h3>${escapeHtml(nodeTitle(node))}</h3></div></div>
    ${node.description ? `<p class="inspector-desc">${escapeHtml(node.description)}</p>` : ""}
    ${start !== undefined ? `<div class="time-range"><span>TIME RANGE</span><strong>${fmtTime(start)} ${end !== undefined ? "— "+fmtTime(end) : ""}</strong></div>` : ""}
    ${node.intent ? `<div class="intent-box"><span>STORY INTENT</span><p>${escapeHtml(node.intent)}</p></div>` : ""}
    ${node.perceptual_hash ? `<div class="hash-row"><span>PERCEPTUAL HASH</span><code>${escapeHtml(node.perceptual_hash)}</code></div>` : ""}
    <div class="inspector-divider"></div><div class="mini-heading">CONNECTED RELATIONSHIPS <b>${edges.length}</b></div>
    <div class="connection-list">${edges.map(e=>{const other=e.source===node.id?e.target:e.source;const target=evidenceFor(other);return `<button class="connection-item" data-inspect-edge="${escapeHtml(e.id)}"><span class="connection-type">${escapeHtml(relationLabels[e.type]||e.type)}</span><strong>${escapeHtml(nodeTitle(target)||other)}</strong><small>${escapeHtml(e.verification_status||"Evidence-linked")}</small></button>`;}).join("") || '<p class="muted">No connected relationships.</p>'}</div>
    <div class="inspector-divider"></div><div class="mini-heading">SUPPORTING EVIDENCE <b>${evidenceNodes.length}</b></div>
    <div class="evidence-list">${evidenceNodes.map(e=>renderEvidenceCard(e)).join("") || '<p class="muted">No linked evidence nodes.</p>'}</div>
    <div class="provenance"><span>PROVENANCE</span><small>${escapeHtml(node.evidence_status || "Graph node")}</small><code>${escapeHtml(node.id)}</code></div>`;
}
function renderEvidenceCard(node) {
  const meta = nodeType(node);
  return `<div class="evidence-card"><div class="evidence-card-top"><span class="evidence-kind" style="--entity:${meta.color}">${meta.icon} ${meta.label}</span><span class="evidence-time">${fmtTime(node.start_seconds)}${node.end_seconds !== undefined && node.end_seconds !== node.start_seconds ? " – "+fmtTime(node.end_seconds) : ""}</span></div><p>${escapeHtml(nodeTitle(node))}</p>${node.object_key ? `<small class="object-key">${escapeHtml(node.object_key)}</small>` : ""}<div class="evidence-actions"><button class="evidence-select" data-select-node="${escapeHtml(node.id)}">Inspect evidence</button>${hasTimestamp(node.start_seconds) ? `<button class="evidence-jump" data-jump-time="${Number(node.start_seconds)}">▶ Jump to ${fmtTime(node.start_seconds)}</button>` : ""}</div></div>`;
}
function renderEdgeInspector() {
  const edge = state.graph.edges.find(e=>e.id===state.selectedEdgeId);
  if (!edge) return renderOverviewInspector();
  const source=evidenceFor(edge.source), target=evidenceFor(edge.target);
  const refs=(edge.evidence_refs||[]).map(evidenceFor).filter(Boolean);
  return `<div class="inspector-head"><span class="eyebrow">RELATIONSHIP DETAILS</span><button class="text-button" id="clear-selection">Clear ×</button></div>
    <div class="relation-hero"><span>LINK</span><h3>${escapeHtml(relationLabels[edge.type]||edge.type)}</h3></div>
    <div class="relation-endpoints"><div><small>FROM</small><strong>${escapeHtml(nodeTitle(source)||edge.source)}</strong></div><i>→</i><div><small>TO</small><strong>${escapeHtml(nodeTitle(target)||edge.target)}</strong></div></div>
    <div class="verification-state"><span class="verify-icon">${edge.verification_status?.includes("verified") ? "✓" : "◈"}</span><div><small>VERIFICATION STATUS</small><strong>${escapeHtml((edge.verification_status||"requires review").replaceAll("_"," "))}</strong></div></div>
    ${edge.claim_quote ? `<blockquote class="claim-quote">“${escapeHtml(edge.claim_quote)}”<small>Narration claim · not independently verified</small></blockquote>` : ""}
    <div class="inspector-divider"></div><div class="mini-heading">EVIDENCE REFERENCES <b>${refs.length}</b></div><div class="evidence-list">${refs.map(e=>renderEvidenceCard(e)).join("") || '<p class="muted">No resolvable evidence references.</p>'}</div>
    <div class="provenance"><span>HUMAN REVIEW</span><small>${edge.requires_human_review ? "Required" : "Not required for timestamp relation"}</small><code>${escapeHtml(edge.id)}</code></div>`;
}
function refreshInspector() {
  const panel = $(".inspector");
  if (!panel) return;
  const selected = state.selectedId ? evidenceFor(state.selectedId) : null;
  panel.innerHTML = selected
    ? renderNodeInspector(selected)
    : state.selectedEdgeId ? renderEdgeInspector() : renderOverviewInspector();
  $$(".graph-node").forEach(el => {
    el.classList.toggle("node-selected", el.dataset.node === state.selectedId);
  });
  bindInspectorActions();
}
function inspectEdge(edgeId) {
  const edge = state.graph.edges.find(item => item.id === edgeId);
  if (!edge) return;
  state.selectedEdgeId = edgeId;
  state.selectedId = null;
  refreshInspector();
  const ref = (edge.evidence_refs || []).map(evidenceFor).filter(Boolean)
    .sort((a,b) => (hasTimestamp(a.start_seconds) ? Number(a.start_seconds) : Infinity) -
                   (hasTimestamp(b.start_seconds) ? Number(b.start_seconds) : Infinity))[0];
  if (ref && hasTimestamp(ref.start_seconds)) seekToTimestamp(ref.start_seconds);
}
function selectGraphNode(nodeId, seek = true) {
  const node = evidenceFor(nodeId);
  if (!node) return;
  state.selectedId = nodeId;
  state.selectedEdgeId = null;
  refreshInspector();
  if (seek && hasTimestamp(node.start_seconds)) seekToTimestamp(node.start_seconds);
}
function bindInspectorActions() {
  $$("[data-inspect-edge]").forEach(el => {
    el.addEventListener("click", () => inspectEdge(el.dataset.inspectEdge));
  });
  $$("[data-select-node]").forEach(el => {
    el.addEventListener("click", () => selectGraphNode(el.dataset.selectNode));
  });
  $("#clear-selection")?.addEventListener("click", () => {
    state.selectedId = null;
    state.selectedEdgeId = null;
    refreshInspector();
  });
}

function bindShell() {
  $("#load-form")?.addEventListener("submit", async e => {
    e.preventDefault();
    state.projectId=$("#project-input").value.trim();
    state.jobId=$("#job-input").value.trim();
    await loadGraph();
  });
  $("#account-btn")?.addEventListener("click",()=>$("#settings-modal").classList.remove("hidden"));
  $("#account-login")?.addEventListener("click", signIn);
  $("#account-register")?.addEventListener("click", registerAccount);
  $("#password-reset-request")?.addEventListener("click", requestPasswordReset);
  $("#verification-resend")?.addEventListener("click", resendVerificationEmail);
  $("#send-invitation")?.addEventListener("click", sendProjectInvitation);
  $("#account-logout")?.addEventListener("click", signOut);
  $("#close-settings")?.addEventListener("click",()=>$("#settings-modal").classList.add("hidden"));
  $("#settings-modal")?.addEventListener("click",e=>{if(e.target.id==="settings-modal") e.currentTarget.classList.add("hidden");});
  $("#save-settings")?.addEventListener("click",()=>{
    state.apiBase=$("#api-base-input").value.trim().replace(/\/$/,"");
    localStorage.setItem("editflow-api-base",state.apiBase);
    $("#settings-modal").classList.add("hidden");
  });
}
function saveSession(data, email) {
  state.accessToken=data.access_token;
  state.refreshToken=data.refresh_token;
  state.userEmail=email || data.user?.email || "";
  sessionStorage.setItem("editflow-access-token",state.accessToken);
  sessionStorage.setItem("editflow-refresh-token",state.refreshToken);
  sessionStorage.setItem("editflow-user-email",state.userEmail);
  const status=$("#account-status");
  if(status) status.textContent=state.userEmail;
  const logout=$("#account-logout");
  if(logout) logout.disabled=false;
}
function clearSession() {
  state.accessToken=""; state.refreshToken=""; state.userEmail="";
  sessionStorage.removeItem("editflow-access-token");
  sessionStorage.removeItem("editflow-refresh-token");
  sessionStorage.removeItem("editflow-user-email");
  const status=$("#account-status");
  if(status) status.textContent="Not signed in";
  const logout=$("#account-logout");
  if(logout) logout.disabled=true;
}
function accountMessage(message, error=false) {
  const el=$("#account-message");
  if(el){el.textContent=message;el.style.color=error?"#ff9eaa":"#aebbd5";}
}
async function signIn() {
  const email=$("#account-email").value.trim();
  const password=$("#account-password").value;
  try {
    const response=await fetch(state.apiBase+"/v1/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password})});
    const body=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(body.detail || "Sign in failed");
    saveSession(body,email);
    accountMessage("Signed in successfully.");
  } catch(error) { accountMessage(error.message || "Could not sign in.",true); }
}
async function registerAccount() {
  const email=$("#account-email").value.trim();
  const password=$("#account-password").value;
  try {
    const response=await fetch(state.apiBase+"/v1/auth/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,password})});
    const body=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(body.detail || "Registration failed");
    accountMessage("Verification email sent. Verify your email, then sign in here.");
  } catch(error) { accountMessage(error.message || "Could not create account.",true); }
}
async function requestPasswordReset() {
  const email=$("#account-email")?.value.trim();
  if(!email) return accountMessage("Enter your account email first.",true);
  try {
    const response=await fetch(state.apiBase+"/v1/auth/request-password-reset",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email})});
    const body=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(body.detail || "Could not request password reset.");
    accountMessage(body.message || "If the account exists and is verified, a reset email will be sent.");
  } catch(error) { accountMessage(error.message || "Could not request password reset.",true); }
}
async function resendVerificationEmail() {
  const email=$("#account-email")?.value.trim();
  if(!email) return accountMessage("Enter your account email first.",true);
  try {
    const response=await fetch(state.apiBase+"/v1/auth/resend-verification",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email})});
    const body=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(body.detail || "Could not resend verification email.");
    accountMessage(body.message || "If the account needs verification, a new email will be sent.");
  } catch(error) { accountMessage(error.message || "Could not resend verification email.",true); }
}
async function sendProjectInvitation() {
  const projectId=$("#invite-project-id")?.value.trim();
  const email=$("#invite-email")?.value.trim();
  const role=$("#invite-role")?.value || "viewer";
  if(!projectId || !email) return accountMessage("Enter both the project ID and invitee email.",true);
  const button=$("#send-invitation");
  if(button) button.disabled=true;
  try {
    const response=await authorizedFetch(state.apiBase.replace(/\/$/,"")+"/v1/projects/"+encodeURIComponent(projectId)+"/invitations",{
      method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email,role})
    });
    const body=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(body.detail || "Could not send invitation.");
    accountMessage("Invitation email sent. It expires in 7 days.");
  } catch(error) { accountMessage(error.message || "Could not send invitation.",true); }
  finally { if(button) button.disabled=!state.accessToken; }
}
async function signOut() {
  try {
    if(state.refreshToken) await fetch(state.apiBase+"/v1/auth/logout",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({refresh_token:state.refreshToken})});
  } finally {
    clearSession();
    if(state.mediaObjectUrl) URL.revokeObjectURL(state.mediaObjectUrl);
    state.mediaObjectUrl=""; state.mediaUrl=""; state.graph=null;
    $("#settings-modal")?.classList.add("hidden");
    render();
  }
}
async function authorizedFetch(url, options={}) {
  if(!state.accessToken) throw new Error("Sign in to access this project.");
  const send=()=>fetch(url,{...options,headers:{...(options.headers||{}),Authorization:"Bearer "+state.accessToken}});
  let response=await send();
  if(response.status===401 && state.refreshToken) {
    const refreshed=await fetch(state.apiBase+"/v1/auth/refresh",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({refresh_token:state.refreshToken})});
    const body=await refreshed.json().catch(()=>({}));
    if(!refreshed.ok) { clearSession(); throw new Error("Your session expired. Sign in again."); }
    saveSession(body);
    response=await send();
  }
  return response;
}
async function loadGraph() {
  state.loading=true; state.error=""; render();
  try {
    const base=state.apiBase.replace(/\/$/,"");
    const url=`${base}/v1/projects/${encodeURIComponent(state.projectId)}/renders/${encodeURIComponent(state.jobId)}/story-continuity`;
    const response=await authorizedFetch(url,{headers:{Accept:"application/json"}});
    const body=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
    const graph=body.graph;
    if(!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) throw new Error("The API response does not contain a valid graph.");
    state.graph=graph;
    if(state.mediaObjectUrl) URL.revokeObjectURL(state.mediaObjectUrl);
    state.mediaObjectUrl=""; state.mediaUrl="";
    if(body.media_available && body.media_url) {
      const mediaResponse=await authorizedFetch(base + body.media_url,{headers:{Accept:"video/mp4"}});
      if(mediaResponse.ok) {
        state.mediaObjectUrl=URL.createObjectURL(await mediaResponse.blob());
        state.mediaUrl=state.mediaObjectUrl;
      }
    }
    state.playbackSeconds=0; state.playbackWasPlaying=false; state.pendingSeekSeconds=null; state.selectedId=null; state.selectedEdgeId=null; state.search=""; state.filter="all";
  } catch(error) {
    state.error=error.message || "Could not load the Story Continuity Graph.";
  } finally {
    state.loading=false; render();
  }
}
function bindExplorer() {
  $("#graph-search")?.addEventListener("input",e=>{state.search=e.target.value;const pos=e.target.selectionStart;render();const input=$("#graph-search");input.focus();input.setSelectionRange(pos,pos);});
  $$("[data-filter]").forEach(btn=>btn.addEventListener("click",()=>{state.filter=btn.dataset.filter;state.selectedId=null;state.selectedEdgeId=null;render();}));
  $$("[data-node]").forEach(el=>{
    const select=()=>selectGraphNode(el.dataset.node);
    el.addEventListener("click",select);
    el.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();select();}});
  });
  $$("[data-edge]").forEach(el=>{
    const inspect=()=>inspectEdge(el.dataset.edge);
    el.addEventListener("click",inspect);
    el.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();inspect();}});
  });
  bindInspectorActions();
  $$("[data-evidence-node]").forEach(el=>el.addEventListener("click",()=>{
    selectGraphNode(el.dataset.evidenceNode, false);
    seekToTimestamp(el.dataset.jumpTime);
  }));
  $$("[data-jump-time]:not([data-evidence-node])").forEach(el=>el.addEventListener("click",()=>seekToTimestamp(el.dataset.jumpTime)));
  $("#zoom-in")?.addEventListener("click",()=>scaleGraph(1.15));
  $("#zoom-out")?.addEventListener("click",()=>scaleGraph(.87));
  $("#fit-graph")?.addEventListener("click",()=>{state.zoom=1;applyZoom();});
  applyZoom();
  bindVideoPlayer();
}
function scaleGraph(factor) { state.zoom=Math.max(.65,Math.min(1.8,state.zoom*factor));applyZoom(); }
function applyZoom() {
  const svg=$(".graph-svg");
  if(svg) svg.style.transform=`scale(${state.zoom})`;
}
render();
