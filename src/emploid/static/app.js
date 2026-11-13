"use strict";

const $ = (s, r = document) => r.querySelector(s);
const TYPE_LABEL = { internship: "Internship", part_time: "Part-time", full_time: "Full-time", freelance: "Freelance" };
const SOURCE_NAMES = {
  remotive: "Remotive", arbeitnow: "Arbeitnow", remoteok: "RemoteOK", jobicy: "Jobicy", himalayas: "Himalayas",
  weworkremotely: "We Work Remotely", feeds: "Custom feeds", adzuna: "Adzuna", jooble: "Jooble",
  simplify: "Curated internship lists", google_careers: "Google Careers", amazon_jobs: "Amazon Jobs",
  microsoft_jobs: "Microsoft Careers", workday: "Workday (24 large employers)", workingnomads: "Working Nomads",
  jobspresso: "Jobspresso", eures: "EURES (EU job portal)", landing: "Landing.jobs", programs: "International programs",
  greenhouse: "Greenhouse boards", lever: "Lever boards", ashby: "Ashby boards",
  smartrecruiters: "SmartRecruiters boards", workable: "Workable boards", recruitee: "Recruitee boards",
};

const S = { countries: [], world: null, regions: [], sort: "best", chips: new Set(), stage: "", profile: null, lastUndo: null, presets: [], name: "", st: null, running: false, tab: "results", jobs: [], counts: {}, selected: new Set(), current: null, filter: "", runStarted: null, polling: false };

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
}

async function api(path, body, method) {
  const opt = method ? { method } : body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let r;
  try {
    r = await fetch(path, opt);
  } catch (e) {  // server stopped, restarted or unreachable
    offline();
    throw e;
  }
  if (!r.ok) throw new Error((await r.text()).slice(0, 200));
  return r.json();
}

function offline() {
  toast("Can't reach the app. It may have been restarted: reload this page, or start Emploid again.", 8000);
}

window.addEventListener("unhandledrejection", e => {
  if (!$("#toast") || e.reason instanceof TypeError) return;  // network failures already showed the message above
  toast("Something went wrong: " + String(e.reason && e.reason.message || e.reason).slice(0, 120), 6000);
});

function toast(msg, ms = 3500, action) {
  const t = $("#toast"); t.replaceChildren(msg); t.classList.remove("hidden");
  if (action) t.append(el("button", { class: "toast-act", onclick: () => { t.classList.add("hidden"); action.fn(); } }, action.label));
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add("hidden"), ms);
}

function ago(iso) {
  if (!iso) return "";
  const d = new Date(iso); if (isNaN(d)) return "";
  const days = Math.floor((Date.now() - d) / 864e5);
  if (days < 1) return "Today";
  if (days === 1) return "1 day ago";
  if (days < 30) return days + " days ago";
  const m = Math.floor(days / 30);
  return m < 12 ? m + (m === 1 ? " month ago" : " months ago") : "Over a year ago";
}

const STAGE_LABEL = { applied: "Applied", interviewing: "Interviewing", offer: "Offer", rejected: "Rejected", withdrawn: "Withdrawn" };
const SEASON_IDX = { Spring: 0, Summer: 1, Fall: 2, Winter: 3 };
const SOURCE_KEYS = { "Remotive": "remotive", "Arbeitnow": "arbeitnow", "RemoteOK": "remoteok", "Jobicy": "jobicy", "Himalayas": "himalayas",
  "We Work Remotely": "weworkremotely", "Greenhouse": "greenhouse", "Lever": "lever", "Ashby": "ashby", "SmartRecruiters": "smartrecruiters",
  "Workable": "workable", "Recruitee": "recruitee", "Google Careers": "google_careers", "Amazon Jobs": "amazon_jobs",
  "Microsoft Careers": "microsoft_jobs", "Workday": "workday", "Working Nomads": "workingnomads", "Jobspresso": "jobspresso",
  "SimplifyJobs": "simplify", "Internship list (vanshb03)": "simplify", "Adzuna": "adzuna", "Jooble": "jooble", "Custom feed": "feeds",
  "EURES": "eures", "Landing.jobs": "landing", "Programs": "programs" };

function daysUntil(day) { return Math.ceil((Date.parse(day + "T23:59:59") - Date.now()) / 864e5); }
function shortDay(day) { return new Date(day + "T12:00:00").toLocaleDateString([], { month: "short", day: "numeric" }); }
function agoEpoch(sec) {
  const m = Math.floor((Date.now() / 1000 - sec) / 60);
  return m < 1 ? "just now" : m < 60 ? m + " min ago" : m < 1440 ? Math.floor(m / 60) + " h ago" : Math.floor(m / 1440) + " d ago";
}

/* company logo: the server finds and verifies it; initials when there is none */
function logoEl(j, big) {
  const box = el("div", { class: "logo" + (big ? " lg" : "") });
  const initials = () => { box.classList.add("fb"); box.replaceChildren(((j.company || "?").trim()[0] || "?").toUpperCase()); };
  if (!j.company) { initials(); return box; }
  box.append(el("img", { src: `/api/logo?company=${encodeURIComponent(j.company)}&url=${encodeURIComponent((j.extra && j.extra.website) || j.url || "")}`, alt: "", loading: "lazy", onerror: initials }));
  return box;
}

/* highlight the words of the current search inside a text */
function searchTerms() {
  const roles = (S.st && S.st.interpreted && S.st.interpreted.roles) || [];
  const base = (roles.length ? roles.join(" ") : $("#f-query").value || "").toLowerCase();
  const words = base.split(/[^\p{L}\p{N}+#]+/u).filter(w => w.length >= 3 && !["and", "the", "for", "with", "not"].includes(w));
  return [...new Set(words.map(w => (w.length > 6 ? w.replace(/(ings|ing|ers|er|ions|ion|s)$/, "") : w)))];
}
function highlight(text, terms) {
  if (!terms.length || !text) return [text];
  const rx = new RegExp("(\\b(?:" + terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")[\\p{L}\\p{N}]*)", "giu");
  return text.split(rx).map((part, i) => (i % 2 ? el("mark", {}, part) : part));
}

/* ---------------------------------------------------------------- search form */

function readForm() {
  return {
    query: $("#f-query").value.trim(),
    companies: $("#f-companies").value.trim(),
    season: $("#f-season").value,
    start_year: +$("#f-year").value,
    require_start: $("#f-require").checked,
    types: [...document.querySelectorAll("input[name=type]:checked")].map(i => i.value),
    location: $("#f-location").value.trim(),
    countries: [...S.countries],
    visa: $("#f-visa").value,
    exclude: $("#f-exclude").value.trim(),
    hide_phd: $("#f-phd").checked,
    remote: $("#f-remote").value,
    posted_days: +$("#f-days").value,
  };
}

function writeForm(p) {
  $("#f-query").value = p.query || "";
  $("#f-companies").value = p.companies || "";
  $("#f-season").value = p.season || "";
  $("#f-year").value = String(p.start_year || 0);
  $("#f-require").checked = !!p.require_start;
  document.querySelectorAll("input[name=type]").forEach(i => (i.checked = (p.types || []).includes(i.value)));
  $("#f-location").value = p.location || "";
  S.countries = [...(p.countries || [])]; renderWhere();
  $("#f-visa").value = p.visa || "all";
  $("#f-exclude").value = p.exclude || "";
  $("#f-phd").checked = !!p.hide_phd;
  $("#f-remote").value = p.remote || "any";
  $("#f-days").value = String(p.posted_days || 0);
}

async function startSearch() {
  const p = readForm();
  if (!p.query && !p.companies && !p.types.length && !p.countries.length) { toast("Add a specialization, a country or a job type first"); return; }
  await api("/api/search", p);
  S.tab = "results"; syncTabs();
  pollSearch();
}

async function pollSearch() {
  if (S.polling) return;
  S.polling = true;
  try {
    for (;;) {
      const st = await api("/api/search/status");
      renderRun(st);
      if (!st.running) break;
      await new Promise(r => setTimeout(r, 1000));
    }
  } finally { S.polling = false; }
  api("/api/presets").then(p => { S.presets = p; renderPresets(); }).catch(() => {});  // picks up "last run / new" badges
  await loadJobs();
  $("#list").classList.add("fade");
  setTimeout(() => $("#list").classList.remove("fade"), 600);
  if (S.st && !S.st.error) toast(`Found ${S.st.matched} ${S.st.matched === 1 ? "opportunity" : "opportunities"}` + (S.st.new ? `, ${S.st.new} new` : "") + (S.st.hidden ? ` (${S.st.hidden} already handled hidden)` : ""));
}

function renderInterpreted(st) {
  const box = $("#interpreted"), i = st.interpreted;
  if (!i || (!i.roles.length && !i.companies.length)) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const parts = [];
  if (i.roles.length) parts.push(el("span", {}, "Role: ", el("b", {}, i.roles.join(", "))));
  if (i.companies.length) parts.push(el("span", {}, (parts.length ? " · " : "") + "Company: ", el("b", {}, i.companies.join(", "))));
  box.replaceChildren("Understood as ", ...parts);
}

const STEP_WEIGHT = { sources: 25, boards: 30, match: 5, read: 12, verify: 8, translate: 15, save: 5 };

function overallProgress(steps) {
  let total = 0, got = 0;
  for (const s of steps) {
    if (s.status === "skipped") continue;
    const w = STEP_WEIGHT[s.key] || 10;
    total += w;
    got += w * (s.status === "done" ? 1 : s.status === "active" ? (s.total ? s.done / s.total : 0.1) : 0);
  }
  return total ? Math.min(0.99, got / total) : 0;
}

function setTopline(frac) {
  const bar = $("#topline-bar"), line = $("#topline");
  line.classList.toggle("busy", frac !== null && frac < 0.02);
  bar.classList.toggle("wait", frac !== null && frac < 0.02);
  bar.style.width = frac === null ? "0" : frac < 0.02 ? "" : Math.round(frac * 100) + "%";
}

function renderRun(st) {
  S.st = st; S.running = st.running;
  renderInterpreted(st);
  renderPresets();
  const btn = $("#search-btn");
  btn.disabled = st.running; btn.textContent = st.running ? "Searching…" : "Search";
  const box = $("#run-status"); box.replaceChildren();
  if (st.running) {
    setTopline(overallProgress(st.steps || []));
    if (S.tab === "results") renderProgress(st);
  } else {
    setTopline(null);
    if (st.started) {
      if (st.error) box.append(el("div", { class: "phase" }, "Search failed: " + st.error));
      else if (st.finished) box.append(el("div", { class: "phase" }, `${st.matched} matching, ${st.new} new`),
        st.hidden ? el("div", {}, `${st.hidden} more already applied, saved or dismissed`) : null,
        el("div", {}, "Updated " + new Date(st.finished * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })));
      for (const [name, v] of Object.entries(st.per_source || {})) {
        const unit = v.unit || "postings";
        box.append(el("div", { class: "src" }, el("span", {}, SOURCE_NAMES[name] || name), el("b", {}, v.error ? "error" : `${v.read} ${unit}`)));
      }
    }
  }
  renderHello();
}

/* search in progress: staged checklist, live source counts, skeleton cards */

function renderProgress(st) {
  const ul = $("#list");
  if (!$("#prog")) {
    ul.replaceChildren(el("li", { class: "progress", id: "prog" },
      el("h3", { id: "prog-title" }),
      el("div", { class: "sub", id: "prog-sub" }),
      el("div", { class: "pbar" }, el("i", { id: "prog-bar" })),
      el("div", { class: "pmeta" }, el("span", { id: "prog-pct" }), el("span", { id: "prog-time" })),
      el("ul", { class: "steps", id: "prog-steps" }),
      el("div", { class: "meta", id: "prog-chips", style: "margin-top:10px" })),
      ...[0, 1, 2, 3].map(() => el("li", { class: "skel" }, el("div", { class: "box" }),
        el("div", { style: "flex:1" }, el("div", { class: "ln", style: "width:70%;height:13px" }),
          el("div", { class: "ln", style: "width:40%" }), el("div", { class: "ln", style: "width:55%" })))));
    $("#list-title").replaceChildren("Searching ", el("span", {}, "this usually takes under a minute"));
    $("#bulk").classList.add("hidden");
  }
  const i = st.interpreted || {};
  const what = [(i.roles || []).join(", ") || "all roles", (i.companies || []).length ? "at " + i.companies.join(", ") : ""].filter(Boolean).join(" ");
  $("#prog-title").textContent = "Looking for " + what;
  const active = (st.steps || []).find(s => s.status === "active");
  $("#prog-sub").textContent = active ? active.label + (active.detail ? " · " + active.detail : "") : "Getting started";
  const frac = overallProgress(st.steps || []);
  $("#prog-bar").style.width = Math.round(frac * 100) + "%";
  $("#prog-pct").textContent = Math.round(frac * 100) + "%";
  $("#prog-time").textContent = Math.max(0, Math.round(Date.now() / 1000 - st.started)) + " s elapsed";
  const stepsUl = $("#prog-steps");
  for (const s of st.steps || []) {
    let li = stepsUl.querySelector(`[data-key="${s.key}"]`);
    if (!li) {
      li = el("li", { class: "step", "data-key": s.key }, el("span", { class: "ic" }),
        el("div", {}, el("div", { class: "nm" }, s.label), el("div", { class: "dt" })));
      stepsUl.append(li);
    }
    li.className = "step " + s.status;
    li.querySelector(".dt").textContent = s.status === "skipped" ? "Not needed for this search" : s.status === "pending" ? "" : s.detail || "";
  }
  const chips = $("#prog-chips"); chips.replaceChildren();
  for (const [name, v] of Object.entries(st.per_source || {}).filter(([, v]) => !v.unit && v.read > 0))
    chips.append(el("span", { class: "tag" }, `${SOURCE_NAMES[name] || name} ${v.read.toLocaleString()}`));
}

/* greeting + avatar */

async function refreshMe() {
  try {
    const p = await api("/api/profile");
    S.profile = p;
    S.name = [p.first_name, p.last_name].map(x => (x || "").trim()).filter(Boolean).join(" ");
    $("#avatar").textContent = S.name ? S.name[0].toUpperCase() : "·";
  } catch (e) { /* greeting works without a name */ }
  renderHello();
  if (!S.current) renderDetail();
}

function renderHello() {
  const h = new Date().getHours();
  const greet = h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  $("#hello-title").textContent = greet + (S.name ? ", " + S.name : "");
  const c = S.counts || {}, st = S.st || {};
  const bits = [];
  if (S.running) bits.push("Search in progress");
  else if (!st.started && !(c.results || c.saved || c.applied)) bits.push("Set your criteria on the left to start a search");
  else {
    if (c.results) bits.push(`${c.results} ${c.results === 1 ? "opportunity matches" : "opportunities match"} your search` + (st.new ? `, ${st.new} new` : ""));
    else if (st.started) bits.push("No matches yet. Try widening the criteria");
    if (c.saved) bits.push(`${c.saved} saved`);
    if (c.applied) bits.push(`${c.applied} applied`);
    if (c.followups) bits.push(`${c.followups} ${c.followups === 1 ? "follow-up" : "follow-ups"} due`);
  }
  $("#hello-sub").textContent = bits.join(" · ");
}

/* ---------------------------------------------------------------- list */

async function loadJobs() {
  const d = await api("/api/jobs?tab=" + S.tab);
  S.jobs = d.jobs; S.counts = d.counts; S.runStarted = d.run_started;
  for (const k of ["results", "saved", "applied", "dismissed"]) $("#n-" + k).textContent = d.counts[k];
  S.selected = new Set([...S.selected].filter(id => S.jobs.some(j => j.id === id)));
  if (!S.jobs.some(j => j.id === S.current)) S.current = null;
  renderList(); renderDetail(); renderBulk(); renderHello();
  if (S.jobs.some(j => j.apply_state && ["queued", "running"].includes(j.apply_state.state))) setTimeout(loadJobs, 2500);
  translatePending();
}

async function refreshCounts() {  // counts only: re-rendering would disturb a note being typed
  const d = await api("/api/jobs?tab=" + S.tab);
  S.counts = d.counts;
  for (const k of ["results", "saved", "applied", "dismissed"]) $("#n-" + k).textContent = d.counts[k];
  renderHello();
}

let translating = false;
async function translatePending() {  // postings the server could not translate during the search
  if (translating) return;
  translating = true;
  try {
    for (const j of S.jobs.filter(x => x.lang && x.lang !== "en" && !x.translated).slice(0, 25)) {
      const r = await api(`/api/jobs/${j.id}/translate`, {});
      if (!r.ok) break;
      Object.assign(j, r.job);
      renderList();
      if (S.current === j.id) renderDetail();
    }
  } catch (e) { /* retried on the next load */ } finally { translating = false; }
}

const CHIPS = [
  ["auto", "Auto-apply", j => j.auto],
  ["start", "Start stated", j => j.type === "internship" && j.start_label],
  ["remote", "Remote", j => j.remote],
  ["visa", "Visa or relocation", j => (j.extra && j.extra.flags || []).some(f => ["visa_offered", "relocation", "uk_sponsor"].includes(f))],
  ["new", "New", j => S.runStarted && j.first_seen >= S.runStarted - 1],
];

function startRank(j) {
  if (!j.starts || !j.starts.length) return 9e9;
  return Math.min(...j.starts.map(s => (s.year || 9999) * 10 + (SEASON_IDX[s.season] || 0)));
}

function visibleJobs() {
  const f = S.filter.toLowerCase();
  let jobs = S.jobs.filter(j => !f || (j.title + " " + j.company + " " + j.location).toLowerCase().includes(f));
  for (const [key, , pred] of CHIPS) if (S.chips.has(key) && S.tab !== "applied") jobs = jobs.filter(pred);
  if (S.tab === "applied" && S.stage) jobs = jobs.filter(j => (j.stage || "applied") === S.stage);
  const by = {
    newest: (a, b) => (Date.parse(b.posted_at) || 0) - (Date.parse(a.posted_at) || 0),
    start: (a, b) => startRank(a) - startRank(b),
    company: (a, b) => (a.company || "").localeCompare(b.company || ""),
  }[S.sort];
  return by ? [...jobs].sort(by) : jobs;
}

function renderChips() {
  const box = $("#chips"); box.replaceChildren();
  $("#export-csv").classList.toggle("hidden", S.tab !== "applied");
  $("#sort-by").classList.toggle("hidden", S.tab === "applied");
  if (S.tab === "applied") {
    for (const [k, l] of [["", "All"], ...Object.entries(STAGE_LABEL)])
      box.append(el("button", { class: "chip" + (S.stage === k ? " on" : ""), onclick: () => { S.stage = k; renderChips(); renderList(); renderBulk(); } }, l));
    return;
  }
  for (const [key, label] of CHIPS)
    box.append(el("button", { class: "chip" + (S.chips.has(key) ? " on" : ""), onclick: () => {
      S.chips.has(key) ? S.chips.delete(key) : S.chips.add(key); renderChips(); renderList(); renderBulk(); } }, label));
}

const FLAG_TAG = { visa_offered: ["Visa support", "tag visa"], relocation: ["Relocation", "tag visa"], uk_sponsor: ["UK licensed sponsor", "tag visa"],
  no_sponsorship: ["No sponsorship", "tag warn"], citizens_only: ["Citizens only", "tag warn"], clearance: ["Clearance needed", "tag warn"],
  auth_required: ["Work authorization needed", "tag"] };

function visaTags(j) {
  const flags = (j.extra && j.extra.flags) || [];
  return [...(j.extra && j.extra.program ? [el("span", { class: "tag prog" }, "Program")] : []),
    ...flags.filter(f => FLAG_TAG[f]).map(f => el("span", { class: FLAG_TAG[f][1] }, FLAG_TAG[f][0]))];
}

function followUpTag(j) {
  if (!j.follow_up || !["applied", "interviewing"].includes(j.stage || "applied")) return null;
  const d = daysUntil(j.follow_up);
  return el("span", { class: d <= 0 ? "tag warn" : "tag" }, d < 0 ? "Follow up overdue" : d === 0 ? "Follow up today" : "Follow up " + shortDay(j.follow_up));
}

function deadlineTag(j) {
  const dl = j.extra && j.extra.deadline;
  if (!dl) return null;
  const d = daysUntil(dl);
  return d <= 14 ? el("span", { class: "tag warn" }, d <= 0 ? "Closes today" : `Closes in ${d} ${d === 1 ? "day" : "days"}`) : null;
}

function renderList() {
  if (S.running && S.tab === "results") { if (S.st) renderProgress(S.st); return; }
  renderChips();
  $("#sort-by").value = S.sort;
  const jobs = visibleJobs();
  const terms = searchTerms();
  const label = { results: "Results", saved: "Saved", applied: "Applied", dismissed: "Dismissed" }[S.tab];
  $("#list-title").replaceChildren(label + " ", el("span", {}, `${jobs.length} ${jobs.length === 1 ? "opportunity" : "opportunities"}`));
  const ul = $("#list"); ul.replaceChildren();
  if (!jobs.length) {
    ul.append(el("li", { class: "empty" }, S.jobs.length ? "Nothing matches these filters." : S.tab === "results"
      ? "No results yet. Set your parameters on the left, or run a preset."
      : "Nothing here yet."));
    return;
  }
  for (const j of jobs) {
    const isNew = S.runStarted && j.first_seen >= S.runStarted - 1 && S.tab === "results";
    const as = j.apply_state;
    const nLoc = (j.extra && j.extra.variants && j.extra.variants.length) || 0;
    const li = el("li", { class: "item" + (j.id === S.current ? " sel" : ""), onclick: () => { S.current = j.id; renderList(); renderDetail(); } },
      el("input", { type: "checkbox", checked: S.selected.has(j.id), onclick: e => { e.stopPropagation(); toggleSel(j.id, e.target.checked); } }),
      logoEl(j),
      el("div", { class: "body" },
        el("div", { class: "t" }, ...highlight(j.title, terms)),
        el("div", { class: "c" }, j.company || "Company not listed"),
        el("div", { class: "l" }, (j.location || "Location not listed") + (j.remote && !/remote/i.test(j.location) ? " (Remote)" : "")),
        el("div", { class: "meta" },
          isNew && el("span", { class: "tag new" }, "New"),
          el("span", { class: "tag" }, TYPE_LABEL[j.type] || j.type),
          j.type === "internship" && el("span", { class: j.start_label ? "tag start" : "tag" }, j.start_label || "Start not stated"),
          j.duration && el("span", { class: "tag" }, j.duration),
          nLoc > 1 && el("span", { class: "tag" }, `${nLoc} locations`),
          ...visaTags(j),
          deadlineTag(j),
          j.auto && el("span", { class: "tag auto" }, "Auto-apply"),
          as && ["queued", "running"].includes(as.state) && el("span", { class: "tag warn" }, "Applying…"),
          j.status === "manual" && el("span", { class: "tag warn" }, "Needs you"),
          j.status === "applied" && S.tab !== "applied" && el("span", { class: "tag ok" }, "Applied"),
          j.status === "applied" && S.tab === "applied" && j.stage && j.stage !== "applied" && el("span", { class: "tag stage-" + j.stage }, STAGE_LABEL[j.stage]),
          j.status === "applied" && followUpTag(j),
          el("span", {}, ago(j.posted_at)),
          el("span", {}, "via " + j.source))));
    ul.append(li);
  }
}

function toggleSel(id, on) {
  on ? S.selected.add(id) : S.selected.delete(id);
  renderBulk();
}

function renderBulk() {
  if (S.running && S.tab === "results") return;
  const n = S.selected.size;
  $("#bulk").classList.toggle("hidden", n === 0);
  $("#sel-count").textContent = n + " selected";
  const all = visibleJobs();
  $("#select-all").checked = n > 0 && all.every(j => S.selected.has(j.id));
  const inResults = S.tab === "results" || S.tab === "saved";
  $("#bulk-apply").classList.toggle("hidden", !inResults);
  $("#bulk-save").classList.toggle("hidden", S.tab !== "results");
  $("#bulk-dismiss").textContent = S.tab === "dismissed" ? "Restore" : "Dismiss";
  document.querySelectorAll("#list .item input").forEach((cb, i) => (cb.checked = S.selected.has(all[i]?.id)));
}

/* ---------------------------------------------------------------- detail */

function renderReady(box) {
  const p = S.profile || {}, f = p.fixed || {};
  const items = [
    ["Profile details", !!(p.first_name && p.last_name && p.email && p.phone), openProfile],
    ["Resume uploaded", !!p.resume && !(p._missing || []).includes("resume"), openProfile],
    ["Standard questions answered", !!(f.work_auth && f.sponsorship), openProfile],
    ["Home country set (for remote jobs and visa hints)", !!(S.settings && S.settings.home_country), openSettings],
    ["Run your first search", !!(S.st && S.st.started) || S.presets.some(x => x.last_run) || (S.counts.results || 0) > 0, null],
  ];
  const todo = items.filter(i => !i[1]).length;
  const keys = [["j / k", "Next / previous"], ["d", "Dismiss"], ["s", "Save"], ["a", "Apply"], ["o", "Open posting"], ["x", "Select"], ["u", "Undo"], ["?", "All shortcuts"]];
  box.append(el("div", { class: "ready" },
    el("h2", {}, todo ? "Get ready to apply" : "You're all set"),
    el("p", {}, todo ? "A few things make auto-apply work smoothly." : "Select an opportunity to see the details."),
    el("ul", {}, items.map(([label, done, fn]) => el("li", { class: done ? "done" : "" },
      el("span", { class: "mark " + (done ? "ok" : "warn") }, done ? "✓" : "!"),
      el("button", { onclick: () => !done && fn && fn() }, label)))),
    el("div", { class: "keys" }, keys.flatMap(([k, d]) => [el("span", {}, el("kbd", {}, k)), el("span", {}, d)]))));
}

function trackerCard(j) {
  let timer;
  const save = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      Object.assign(j, { stage: stage.value, follow_up: follow.value, user_note: notes.value });
      await api(`/api/jobs/${j.id}/track`, { stage: stage.value, follow_up: follow.value, user_note: notes.value });
      renderList(); refreshCounts();
    }, 500);
  };
  const stage = el("select", { onchange: save }, Object.entries(STAGE_LABEL).map(([k, l]) => el("option", { value: k, selected: (j.stage || "applied") === k }, l)));
  const follow = el("input", { type: "date", value: j.follow_up || "", onchange: save });
  const notes = el("textarea", { rows: 3, placeholder: "Notes: who you spoke to, next steps…", oninput: save }); notes.value = j.user_note || "";
  return el("div", { class: "tracker" }, el("h3", {}, "Application"),
    el("div", { class: "row" }, el("div", {}, el("label", {}, "Stage"), stage), el("div", {}, el("label", {}, "Follow up on"), follow)),
    el("label", {}, "Notes"), notes);
}

function renderDetail() {
  const box = $("#detail"); box.replaceChildren();
  const j = S.jobs.find(x => x.id === S.current);
  if (!j) { renderReady(box); return; }
  const terms = searchTerms();
  const as = j.apply_state;
  const busy = as && ["queued", "running"].includes(as.state);
  const adv = { advance: S.tab === "results" };
  const actions = el("div", { class: "actions" });
  if (j.status === "applied") actions.append(el("span", { class: "tag ok" }, "Applied"));
  else if (j.auto) actions.append(el("button", { class: "btn primary", disabled: busy, onclick: () => confirmApply([j.id]) }, busy ? "Applying…" : "Apply automatically"));
  else actions.append(el("a", { class: "btn primary", href: j.apply_url, target: "_blank", rel: "noopener", onclick: () => { if (j.status === "new") setStatus([j.id], "manual", null, { silent: true }); } }, "Apply on company site ↗"));
  if (j.auto) actions.append(el("a", { class: "btn", href: j.apply_url, target: "_blank", rel: "noopener" }, "Open posting ↗"));
  if (j.status !== "applied") actions.append(el("button", { class: "btn", onclick: () => setStatus([j.id], "applied", "Marked as applied by me", adv) }, "Mark as applied"));
  if (j.status !== "saved") actions.append(el("button", { class: "btn", onclick: () => setStatus([j.id], "saved", null, adv) }, "Save"));
  actions.append(el("button", { class: "btn gray", onclick: () => setStatus([j.id], j.status === "dismissed" ? "new" : "dismissed", null, adv) }, j.status === "dismissed" ? "Restore" : "Dismiss"));

  const srcKey = SOURCE_KEYS[j.source];
  const more = el("div", { class: "linkrow" },
    j.company && j.status !== "applied" && el("button", { onclick: () => hideCompany(j) }, `Hide ${j.company}`),
    srcKey && j.status !== "applied" && el("button", { onclick: () => stopSource(j, srcKey) }, `Stop searching ${j.source}`));

  box.append(
    el("div", { class: "dhead" }, logoEl(j, true), el("div", {},
      el("h1", {}, ...highlight(j.title, terms)),
      el("div", { class: "co" }, j.company),
      el("div", { class: "sub" }, [j.location, j.remote ? "Remote" : null, ago(j.posted_at)].filter(Boolean).join(" · ")))),
    actions, more, facts(j));

  const variants = j.extra && j.extra.variants;
  if (variants && variants.length > 1)
    box.append(el("h3", {}, `Open in ${variants.length} places`),
      el("ul", { class: "locs" }, variants.map(v => el("li", {}, el("a", { href: v.url, target: "_blank", rel: "noopener" }, v.location)))));
  if (j.status === "applied") box.append(trackerCard(j));

  if (j.note && (j.status === "manual" || j.status === "applied")) {
    const cls = j.status === "applied" ? "note ok" : "note warn";
    const n = el("div", { class: cls }, j.note);
    if (j.status === "manual") n.append(" ", el("a", { href: j.apply_url, target: "_blank", rel: "noopener" }, "Open the application"));
    box.append(n);
    if (j.ats) box.append(el("img", { class: "shot", src: `/api/jobs/${j.id}/screenshot`, alt: "", onerror: e => e.target.remove() }));
  }
  if (j.tags.length) box.append(el("div", { class: "meta" }, j.tags.slice(0, 8).map(t => el("span", { class: "tag" }, t))));
  box.append(...[el("h3", {}, "About the job"), translationNote(j),
    el("div", { class: "desc", id: "desc" }, ...highlight(j.description || "No description provided by the source. Open the posting for details.", terms))].filter(Boolean));
  if (j.lang && j.lang !== "en" && !j.translated) lazyTranslate(j);
}

function facts(j) {
  const rows = [];
  const add = (k, v, dim) => rows.push(el("dt", {}, k), el("dd", { class: dim ? "dim" : "" }, v));
  add("Type", TYPE_LABEL[j.type] || j.type);
  if (j.type === "internship") {
    j.start_label ? add("Starts", j.start_label) : add("Starts", "Not stated in the posting", true);
    j.duration ? add("Duration", j.duration) : add("Duration", "Not stated", true);
  }
  if (j.extra && j.extra.deadline) add("Deadline", shortDay(j.extra.deadline) + ` (${Math.max(0, daysUntil(j.extra.deadline))} days left)`);
  if (j.salary) add("Pay", j.salary);
  if (j.extra && j.extra.sponsorship) add("Visa", j.extra.sponsorship);
  if (j.extra && j.extra.degrees && j.extra.degrees.length) add("Degree", j.extra.degrees.join(", "));
  const flags = (j.extra && j.extra.flags) || [];
  if (flags.length) add("Visa and eligibility", flags.filter(f => FLAG_TAG[f]).map(f => FLAG_TAG[f][0]).join(" · "));
  const cs = (j.extra && j.extra.countries) || [];
  if (cs.length) add("Country", cs.slice(0, 6).map(countryName).join(", ") + (cs.length > 6 ? ` +${cs.length - 6}` : ""));
  if (j.extra && j.extra.why) add("Why it matched", j.extra.why, true);
  add("Found on", j.source);
  return el("dl", { class: "facts" }, rows);
}

const LANGS = { de: "German", fr: "French", es: "Spanish", it: "Italian", nl: "Dutch", pt: "Portuguese", pl: "Polish", ar: "Arabic", tr: "Turkish", ru: "Russian", sv: "Swedish", da: "Danish", fi: "Finnish", cs: "Czech", ro: "Romanian", zh: "Chinese", ja: "Japanese", ko: "Korean" };

function translationNote(j) {
  if (!j.lang || j.lang === "en") return null;
  const from = LANGS[j.lang] || j.lang.toUpperCase();
  if (!j.translated) return el("div", { class: "tr-note", id: "tr-note" }, `Translating from ${from}…`);
  let showing = "en";
  const note = el("div", { class: "tr-note", id: "tr-note" }, `Translated from ${from}.`);
  const btn = el("button", { onclick: () => {
    showing = showing === "en" ? "orig" : "en";
    $("#desc").textContent = showing === "en" ? j.description : j.orig_description;
    btn.textContent = showing === "en" ? "Show original" : "Show translation";
  } }, "Show original");
  note.append(btn);
  return note;
}

async function lazyTranslate(j) {
  try {
    const r = await api(`/api/jobs/${j.id}/translate`, {});
    if (r.ok) {
      Object.assign(j, r.job);
      if (S.current === j.id) { renderDetail(); renderList(); }
    } else if ($("#tr-note")) $("#tr-note").textContent = "Translation service unavailable right now. Showing the original text.";
  } catch (e) { /* leave the original text */ }
}

const STATUS_WORD = { dismissed: "Dismissed", saved: "Saved", applied: "Marked as applied", new: "Restored", manual: "Updated", failed: "Updated" };

function nextAfter(ids) {
  const list = visibleJobs(), i = list.findIndex(x => x.id === S.current);
  if (i < 0 || !ids.includes(S.current)) return null;
  const rest = list.slice(i + 1).concat(list.slice(0, i)).find(x => !ids.includes(x.id));
  return rest ? rest.id : null;
}

async function setStatus(ids, status, note, opts = {}) {
  const prev = {};
  ids.forEach(id => { const x = S.jobs.find(y => y.id === id); if (x) prev[id] = x.status; });
  const next = opts.advance ? nextAfter(ids) : null;
  await api("/api/jobs/status", { ids, status, note });
  ids.forEach(id => S.selected.delete(id));
  if (opts.advance) S.current = next;
  await loadJobs();
  if (opts.silent) return;
  S.lastUndo = () => undoStatus(prev);
  toast(STATUS_WORD[status] + (ids.length > 1 ? ` ${ids.length} jobs` : ""), 7000, { label: "Undo", fn: S.lastUndo });
}

async function undoStatus(prev) {
  const byStatus = {};
  for (const [id, st] of Object.entries(prev)) (byStatus[st] = byStatus[st] || []).push(id);
  for (const [st, ids] of Object.entries(byStatus)) await api("/api/jobs/status", { ids, status: st });
  S.lastUndo = null;
  await loadJobs();
  toast("Undone");
}

async function hideCompany(job) {
  await api("/api/hidden", { company: job.company });
  S.current = nextAfter([job.id]);
  await loadJobs();
  S.lastUndo = async () => { await api("/api/hidden?company=" + encodeURIComponent(job.company), undefined, "DELETE"); S.lastUndo = null; await loadJobs(); toast("Undone"); };
  toast(`Hiding ${job.company} from future results`, 8000, { label: "Undo", fn: S.lastUndo });
}

async function stopSource(job, key) {
  const s = await api("/api/settings");
  s.sources[key] = false;
  await api("/api/settings", { sources: s.sources });
  toast(`${job.source} won't be searched next time. Turn it back on in Settings.`, 7000, {
    label: "Undo", fn: async () => { s.sources[key] = true; await api("/api/settings", { sources: s.sources }); toast("Undone"); } });
}

/* ---------------------------------------------------------------- applying */

async function ensureProfile() {
  const p = await api("/api/profile");
  if (p._missing.length) {
    toast("Complete your profile first (missing: " + p._missing.join(", ").replace(/_/g, " ") + ")");
    openProfile();
    return false;
  }
  return true;
}

async function confirmApply(ids) {
  const r = await api("/api/apply/check", { ids });
  const picked = new Set(r.rows.filter(x => !x.blocked).map(x => x.id));
  const nameMissing = r.profile_missing.filter(k => k !== "resume").map(k => k.replace(/_/g, " "));
  const blocking = r.profile_missing.length > 0;

  const mark = (kind, ch) => el("span", { class: "mark " + kind }, ch);
  const check = (kind, title, detail) => el("div", { class: "rv-check" },
    mark(kind, kind === "ok" ? "✓" : kind === "warn" ? "!" : "✕"), el("span", {}, title), el("span", { class: "d" }, detail || ""));
  const checks = el("div", { class: "rv-checks" },
    check(nameMissing.length ? "bad" : "ok", "Profile details", nameMissing.length ? "Missing: " + nameMissing.join(", ") : "Complete"),
    check(r.resume_ok ? "ok" : "bad", "Resume", r.resume_ok ? "File found" : "Not uploaded"),
    check(r.questions_unset.length ? "warn" : "ok", "Standard questions",
      r.questions_unset.length ? "Not set: " + r.questions_unset.join(", ") + ". Forms asking these come back to you." : "Answered"),
    check(r.cover_letter ? "ok" : "warn", "Cover letter template", r.cover_letter ? "Ready" : "Empty"),
    r.auto_count > 30 ? check("warn", "Batch size", `${r.auto_count} applications run one after another, roughly ${Math.round(r.auto_count * 0.7)} minutes. Consider a smaller batch.`) : null);

  const needAuto = r.rows.some(x => x.auto && !x.blocked);
  const setupBar = el("div", { class: "hidden" });
  const setup = () => {
    if (!needAuto) return;
    if (!r.auto_enabled) {
      setupBar.className = "warnbar";
      setupBar.replaceChildren("Auto-apply is off. Links open for you to apply yourself unless you turn it on. ",
        el("button", { class: "btn sm", onclick: async () => {
          await api("/api/settings", { auto_apply: true }); r.auto_enabled = true; setup(); refresh();
        } }, "Turn on auto-apply"));
    } else if (!r.browser_ok) {
      setupBar.className = "warnbar";
      const b = el("button", { class: "btn sm" }, "Install browser (about 150 MB)");
      b.addEventListener("click", async () => {
        b.disabled = true; b.textContent = "Installing...";
        await api("/api/apply/install-browser", {});
        const t = setInterval(async () => {
          const st = await api("/api/apply/install-browser");
          if (st.state === "done") { clearInterval(t); r.browser_ok = true; setup(); refresh(); }
          if (st.state === "error") { clearInterval(t); b.disabled = false; b.textContent = "Retry install"; toast(st.message); }
        }, 2000);
      });
      setupBar.replaceChildren("Auto-apply needs a browser that isn't installed yet. ", b);
    } else { setupBar.className = "hidden"; }
  };
  const ready = () => !needAuto || (r.auto_enabled && r.browser_ok);
  const summary = el("div", { class: "rv-sum" });
  const submit = el("button", { class: "btn primary" }, "Submit");
  const sure = el("input", { type: "checkbox", checked: ids.length === 1 });
  const refresh = () => {
    const chosen = r.rows.filter(x => picked.has(x.id));
    const auto = chosen.filter(x => x.auto).length;
    summary.textContent = `${auto} will be submitted automatically · ${chosen.length - auto} manual ${chosen.length - auto === 1 ? "link" : "links"} to open yourself`;
    submit.textContent = auto ? `Submit ${auto} ${auto === 1 ? "application" : "applications"}` : "Continue";
    submit.disabled = !chosen.length || !sure.checked || blocking || !ready();
    document.querySelectorAll(".rv-job").forEach(n => n.classList.toggle("off", !picked.has(n.dataset.id)));
  };
  sure.addEventListener("change", refresh);

  const list = el("div", { class: "rv-list" }, r.rows.map(x => el("label", { class: "rv-job", "data-id": x.id },
    el("input", { type: "checkbox", checked: picked.has(x.id), disabled: x.blocked, onchange: e => { e.target.checked ? picked.add(x.id) : picked.delete(x.id); refresh(); } }),
    el("div", {}, el("div", { class: "t" }, x.title),
      el("div", { class: "l" }, x.company + (x.auto ? "" : " · manual link")),
      ...x.warnings.map(w => el("div", { class: "w" }, w))))));

  submit.addEventListener("click", async () => {
    const chosen = r.rows.filter(x => picked.has(x.id));
    closeModal();
    const res = await api("/api/apply", { ids: chosen.map(x => x.id) });
    if (res.error) { toast(res.error); return; }
    S.selected.clear();
    await loadJobs();
    const manual = S.jobs.filter(j => chosen.some(x => x.id === j.id) && !j.auto);
    if (manual.length) showManual(manual);
    else toast(r.dry_run ? "Dry run started: forms are filled but not submitted" : "Applying in the background. Status updates here.");
  });

  openModal(el("div", {},
    el("h2", {}, "Review before applying"),
    el("p", { class: "sub" }, `${ids.length} selected. Nothing is sent until you confirm below.`),
    setupBar,
    r.dry_run ? el("div", { class: "warnbar" }, "Dry run is on: forms will be filled and checked but not submitted. Turn it off in Settings.") : null,
    checks,
    el("div", { class: "hint", style: "margin-bottom:6px" }, "Untick any you don't want to include."),
    list, summary,
    el("label", { class: ids.length === 1 ? "hidden" : "check", style: "margin-top:12px" }, sure, "I've looked through this list"),
    el("div", { class: "foot" },
      blocking ? el("button", { class: "btn", onclick: () => { closeModal(); openProfile(); } }, "Complete profile") : null,
      el("button", { class: "btn", onclick: closeModal }, "Cancel"), submit)));
  setup();
  refresh();
}

function showManual(jobs) {
  openModal(el("div", {},
    el("h2", {}, "Apply manually"),
    el("p", { class: "sub" }, "These sites can't be automated. Open each link; mark it applied when you're done."),
    ...jobs.map(j => el("div", { class: "manual-row" },
      el("div", {}, el("div", { class: "t" }, j.title), el("div", { class: "l" }, j.company)),
      el("a", { class: "btn sm", href: j.apply_url, target: "_blank", rel: "noopener" }, "Open ↗"),
      el("button", { class: "btn sm", onclick: async e => { await api("/api/jobs/status", { ids: [j.id], status: "applied", note: "Marked as applied by me" }); e.target.textContent = "Done"; e.target.disabled = true; loadJobs(); } }, "Mark applied"))),
    el("div", { class: "foot" }, el("button", { class: "btn primary", onclick: closeModal }, "Close"))));
}

/* ---------------------------------------------------------------- modals */

function openModal(content, wide) { const b = $("#modal-box"); b.className = "modal-box" + (wide ? " wide" : ""); b.replaceChildren(content); $("#modal").classList.remove("hidden"); }
function closeModal() { $("#modal").classList.add("hidden"); }

function field(label, id, value = "", type = "text", ph = "") {
  return el("div", {}, el("label", { for: id }, label), el("input", { id, type, value, placeholder: ph }));
}

async function openProfile() {
  const p = await api("/api/profile");
  const fixed = { ...p.fixed };
  const custom = p.custom.map(a => ({ ...a }));

  // fixed questions, grouped; yes/no ones are a dropdown, the rest free text
  const groups = {};
  p._questions.forEach(q => (groups[q.group] = groups[q.group] || []).push(q));
  const fixedBox = el("div", {}, Object.entries(groups).map(([g, qs]) => el("div", {},
    el("h3", { class: "grp" }, g),
    qs.map(q => el("div", { class: "fq" },
      el("span", {}, q.label),
      q.kind === "yesno"
        ? el("select", { onchange: e => (fixed[q.key] = e.target.value) },
            ["", "Yes", "No"].map(v => el("option", { value: v, selected: (fixed[q.key] || "") === v }, v || "Not set")))
        : el("input", { type: "text", value: fixed[q.key] || "", oninput: e => (fixed[q.key] = e.target.value) }))))));

  // the user's own questions
  const customBox = el("div");
  const drawCustom = () => customBox.replaceChildren(...custom.map((a, i) => el("div", { class: "qa" },
    el("input", { type: "text", value: a.match, placeholder: "Question contains… (use | for alternatives)", oninput: e => (a.match = e.target.value) }),
    el("input", { type: "text", value: a.answer, placeholder: "Your answer", oninput: e => (a.answer = e.target.value) }),
    el("button", { title: "Remove", onclick: () => { custom.splice(i, 1); drawCustom(); } }, "×"))));
  drawCustom();

  // questions that stopped earlier applications
  const suggBox = el("div");
  if (p._unanswered.length) {
    suggBox.append(el("h3", { class: "grp" }, "Questions that stopped an application"),
      el("div", { class: "hint", style: "margin-bottom:6px" }, "Answer these once and the tool can submit similar forms next time."),
      ...p._unanswered.slice(0, 12).map(u => el("div", { class: "sugg" },
        el("span", {}, u.label + (u.count > 1 ? ` (${u.count}x)` : "")),
        el("button", { class: "btn sm", onclick: async e => {
          custom.push({ match: u.label.replace(/[.*+?^${}()[\]\\]/g, "\\$&").slice(0, 60), answer: "" });
          drawCustom();
          await api("/api/profile/unanswered/dismiss", { label: u.label });
          e.target.closest(".sugg").remove();
        } }, "Answer"))));
  }

  const resumeNote = el("div", { class: "hint" }, p.resume ? "Current file: " + p.resume.split("/").pop() : "No resume uploaded yet");
  const file = el("input", { type: "file", accept: ".pdf,.doc,.docx", onchange: async e => {
    const fd = new FormData(); fd.append("file", e.target.files[0]);
    const r = await fetch("/api/profile/resume", { method: "POST", body: fd });
    resumeNote.textContent = r.ok ? "Uploaded: " + e.target.files[0].name : "Upload failed (PDF or Word only)";
  } });
  const cover = el("textarea", { id: "p-cover", rows: 6 }); cover.value = p.cover_letter;
  openModal(el("div", {},
    el("h2", {}, "Profile"),
    el("p", { class: "sub" }, "Used to fill in applications. Stays on this computer."),
    el("div", { class: "row" }, field("First name", "p-first", p.first_name), field("Last name", "p-last", p.last_name)),
    el("div", { class: "row" }, field("Email", "p-email", p.email, "email"), field("Phone (with country code)", "p-phone", p.phone)),
    el("div", { class: "row" }, field("Location (city, country)", "p-loc", p.location), field("University or current company", "p-co", p.current_company)),
    el("div", { class: "row" }, field("LinkedIn URL", "p-li", p.linkedin), field("GitHub URL", "p-gh", p.github)),
    field("Website / portfolio", "p-web", p.website),
    el("label", {}, "Resume"), file, resumeNote,
    el("label", { for: "p-cover" }, "Cover letter template"), cover,
    el("div", { class: "hint" }, "Placeholders: {title} {company} {first_name} {last_name}"),
    el("h3", {}, "Standard questions"),
    el("div", { class: "hint" }, "Most application forms ask these. Leave one as Not set and any form that asks it is handed back to you instead of being submitted."),
    fixedBox,
    el("h3", { class: "grp" }, "Your own questions"),
    el("div", { class: "hint", style: "margin-bottom:8px" }, "For anything else. If a form question contains the text on the left, the answer on the right is used. These take priority over the standard ones."),
    customBox,
    el("button", { class: "btn sm", onclick: () => { custom.push({ match: "", answer: "" }); drawCustom(); } }, "Add question"),
    suggBox,
    el("div", { class: "foot" },
      el("button", { class: "btn", onclick: closeModal }, "Cancel"),
      el("button", { class: "btn primary", onclick: async () => {
        await api("/api/profile", {
          first_name: $("#p-first").value.trim(), last_name: $("#p-last").value.trim(), email: $("#p-email").value.trim(),
          phone: $("#p-phone").value.trim(), location: $("#p-loc").value.trim(), current_company: $("#p-co").value.trim(),
          linkedin: $("#p-li").value.trim(), github: $("#p-gh").value.trim(), website: $("#p-web").value.trim(),
          cover_letter: $("#p-cover").value, fixed, custom: custom.filter(a => a.match.trim()),
        });
        closeModal(); toast("Profile saved"); refreshMe();
      } }, "Save"))));
}

const ACCENTS = { blue: "#0a66c2", teal: "#0f766e", green: "#2f7d32", orange: "#c2410c", plum: "#8a3a6b", graphite: "#3b4a5a" };

function store(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode: the look just won't persist */ } }
function stored(k, d) { try { return localStorage.getItem(k) || d; } catch (e) { return d; } }

function applyLook() {
  const d = document.documentElement, a = stored("js-accent", "blue"), t = stored("js-theme", "system");
  d.dataset.accent = a;
  const dark = t === "dark" || (t === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  if (dark) d.dataset.theme = "dark"; else delete d.dataset.theme;
}

function appearanceBlock() {
  const sw = el("div", { class: "swatches" }), seg = el("div", { class: "seg" });
  const draw = () => {
    sw.replaceChildren(...Object.entries(ACCENTS).map(([k, c]) => el("button", {
      class: "swatch" + (stored("js-accent", "blue") === k ? " on" : ""), style: `background:${c}`, title: k, "aria-label": k,
      onclick: () => { store("js-accent", k); applyLook(); draw(); } })));
    seg.replaceChildren(...[["system", "System"], ["light", "Light"], ["dark", "Dark"]].map(([k, l]) =>
      el("button", { class: stored("js-theme", "system") === k ? "on" : "", onclick: () => { store("js-theme", k); applyLook(); draw(); } }, l)));
  };
  draw();
  return el("div", {}, el("h3", {}, "Appearance"), el("div", { class: "hint" }, "Accent color"), sw, el("div", { class: "hint", style: "margin-top:10px" }, "Theme"), seg);
}

async function openSettings() {
  const s = await api("/api/settings");
  const srcBox = el("div", { class: "row" }, Object.entries(s.sources).map(([k, v]) =>
    el("label", { class: "check" }, el("input", { type: "checkbox", "data-src": k, checked: v }), SOURCE_NAMES[k] || k)));
  const keys = s.keys || {};
  await loadWorld();
  const homeSelect = el("select", { id: "s-home", style: "margin-top:6px" }, el("option", { value: "" }, "Not set"),
    ...[...S.world.countries].sort((a, b) => a.n.localeCompare(b.n)).map(c => el("option", { value: c.c, selected: s.home_country === c.c }, c.n)));
  const healthBox = el("div");
  api("/api/sources/health").then(h => {
    healthBox.replaceChildren(h.sources.length ? el("table", { class: "health" },
      el("tr", {}, ["Source", "Read", "In results", "Status"].map(t => el("th", {}, t))),
      ...h.sources.map(x => el("tr", {},
        el("td", {}, SOURCE_NAMES[x.key] || x.key), el("td", {}, `${x.read} ${x.unit === "companies" ? "boards" : ""}`.trim()),
        el("td", {}, x.kept), el("td", { class: x.streak ? "bad" : "" }, !x.enabled ? "Off" : x.error ? "Error" : x.streak ? `Nothing for ${x.streak} run${x.streak > 1 ? "s" : ""}` : "OK"))))
      : el("div", { class: "hint" }, "Run a search first."));
  }).catch(() => {});
  const hiddenBox = el("div", { style: "margin-top:6px" });
  const drawHidden = async names => {
    hiddenBox.replaceChildren(...(names.length ? names.map(n => el("div", { class: "sugg" }, el("span", {}, n),
      el("button", { class: "btn sm", onclick: async () => drawHidden(await api("/api/hidden?company=" + encodeURIComponent(n), undefined, "DELETE")) }, "Show again")))
      : [el("div", { class: "hint" }, "None")]));
  };
  api("/api/hidden").then(drawHidden);
  openModal(el("div", {},
    el("h2", {}, "Settings"),
    el("p", { class: "sub" }, "Look, sources, extra companies and optional API keys."),
    appearanceBlock(),
    el("h3", {}, "Sources"), srcBox,
    el("h3", {}, "Companies to check"),
    el("div", { class: "hint" }, "About 400 company career boards are checked by default. Add more by their board name, one per line (the part after jobs.lever.co/, boards.greenhouse.io/ or jobs.ashbyhq.com/)."),
    el("textarea", { id: "s-companies", rows: 4 }, (s.companies || []).join("\n")),
    el("h3", {}, "About you"),
    el("div", { class: "hint" }, "Your home country decides which country-limited remote jobs you are eligible for."),
    homeSelect,
    el("h3", {}, "Source health"),
    el("div", { class: "hint" }, "What each source returned in its last search, and how much of it reached your results."),
    healthBox,
    el("h3", {}, "Hidden companies"),
    el("div", { class: "hint" }, "Their postings never show up. Hide a company from any job's detail page."),
    hiddenBox,
    el("h3", {}, "Custom feeds"),
    el("div", { class: "hint" }, "RSS or Atom URLs of any job site, one per line."),
    el("textarea", { id: "s-feeds", rows: 3 }, (s.feeds || []).join("\n")),
    el("h3", {}, "Optional API keys"),
    el("div", { class: "hint" }, "Free keys unlock Adzuna and Jooble, which cover many more countries and local job sites."),
    el("div", { class: "row" }, field("Adzuna app id", "k-aid", keys.adzuna_id || ""), field("Adzuna app key", "k-akey", keys.adzuna_key || "", "password")),
    el("div", { class: "row" }, field("Adzuna countries (codes)", "k-ac", keys.adzuna_countries || "gb,us,fr,de"), field("Jooble key", "k-jk", keys.jooble_key || "", "password")),
    field("DeepL API key (translation; free tier works)", "k-dl", keys.deepl_key || "", "password"),
    el("div", { class: "hint" }, "Without it, translation uses Google's public endpoint, which can throttle heavy use."),
    el("h3", {}, "Auto-apply"),
    el("label", { class: "check" }, el("input", { type: "checkbox", id: "s-auto", checked: !!s.auto_apply }), "Allow auto-apply (off by default)"),
    el("div", { class: "hint" }, "A browser fills and submits application forms for you, as you, with your saved answers. It works on Greenhouse, Lever and Ashby forms only, and can get things wrong. You always get a review screen first; check each application's status afterwards."),
    el("label", { class: "check" }, el("input", { type: "checkbox", id: "s-headed", checked: !!s.headed }), "Show the browser window while applying"),
    el("label", { class: "check" }, el("input", { type: "checkbox", id: "s-dry", checked: !!s.dry_run }), "Dry run: fill the forms but never submit"),
    el("div", { class: "foot" },
      el("button", { class: "btn", onclick: closeModal }, "Cancel"),
      el("button", { class: "btn primary", onclick: async () => {
        const lines = id => $(id).value.split("\n").map(x => x.trim()).filter(Boolean);
        const sources = {}; document.querySelectorAll("[data-src]").forEach(c => (sources[c.dataset.src] = c.checked));
        await api("/api/settings", {
          sources, companies: lines("#s-companies"), feeds: lines("#s-feeds"),
          keys: { adzuna_id: $("#k-aid").value.trim(), adzuna_key: $("#k-akey").value.trim(), adzuna_countries: $("#k-ac").value.trim(), jooble_key: $("#k-jk").value.trim(), deepl_key: $("#k-dl").value.trim() },
          auto_apply: $("#s-auto").checked, headed: $("#s-headed").checked, dry_run: $("#s-dry").checked, home_country: $("#s-home").value,
        });
        S.settings = await api("/api/settings");
        closeModal(); toast("Settings saved. They apply to the next search.");
      } }, "Save"))));
}

/* ---------------------------------------------------------------- presets */

function presetSummary(p) {
  const bits = [];
  if (p.query) bits.push(p.query.replace(/\s*\n\s*/g, ", "));
  if (p.companies) bits.push("at " + p.companies);
  if (p.types && p.types.length) bits.push(p.types.map(t => TYPE_LABEL[t] || t).join(" / "));
  if (p.season || p.start_year) bits.push([p.season ? p.season[0].toUpperCase() + p.season.slice(1) : "", p.start_year || ""].filter(Boolean).join(" "));
  if (p.countries && p.countries.length) bits.push(p.countries.length > 3 ? p.countries.length + " countries" : p.countries.map(countryName).join(", "));
  if (p.location) bits.push(p.location);
  if (p.visa === "hide_blocked" || p.visa === "offered") bits.push("Visa-friendly");
  if (p.remote === "only") bits.push("Remote");
  return bits.join(" · ") || "All opportunities";
}

function renderPresets() {
  $("#presets-box").classList.toggle("hidden", !S.presets.length);
  const ul = $("#presets"); ul.replaceChildren();
  for (const p of S.presets) {
    let armed = false;
    const del = el("button", { onclick: async () => {
      if (!armed) { armed = true; del.textContent = "Confirm delete?"; setTimeout(() => { armed = false; del.textContent = "Delete"; }, 3000); return; }
      S.presets = await api(`/api/presets/${p.id}`, undefined, "DELETE");
      renderPresets();
    } }, "Delete");
    ul.append(el("li", { class: "preset" },
      el("div", { class: "nm", title: p.name }, p.name),
      el("button", { class: "btn sm run", disabled: S.running, onclick: () => runPreset(p) }, "Run"),
      el("div", { class: "sm", title: presetSummary(p.params) }, presetSummary(p.params)),
      p.last_run ? el("div", { class: "pm" }, "Last run " + agoEpoch(p.last_run), p.last_new ? [" · ", el("b", {}, `${p.last_new} new`)] : null) : null,
      el("div", { class: "acts" },
        el("button", { onclick: () => editPreset(p) }, "Edit"), del)));
  }
}

async function runPreset(p) {
  const r = await api(`/api/presets/${p.id}/run`, {});
  if (!r.started) { toast("A search is already running"); return; }
  writeForm(r.params);
  S.tab = "results"; syncTabs();
  pollSearch();
}

function editPreset(p) {
  writeForm(p.params);
  $("#save-preset-btn").classList.add("hidden");
  $("#save-preset-form").classList.remove("hidden");
  $("#preset-name").value = p.name;
  $("#preset-name").focus();
  toast("Loaded into the form. Change it, then Save to update the preset.");
}

function closePresetForm() {
  $("#save-preset-form").classList.add("hidden");
  $("#save-preset-btn").classList.remove("hidden");
}

$("#save-preset-btn").addEventListener("click", () => {
  const p = readForm();
  if (!p.query && !p.companies && !p.types.length && !p.countries.length) { toast("Fill in the search first, then save it as a preset"); return; }
  $("#save-preset-btn").classList.add("hidden");
  $("#save-preset-form").classList.remove("hidden");
  $("#preset-name").value = "";
  $("#preset-name").focus();
});
$("#preset-cancel").addEventListener("click", closePresetForm);
$("#save-preset-form").addEventListener("submit", async e => {
  e.preventDefault();
  const name = $("#preset-name").value.trim();
  if (!name) { $("#preset-name").focus(); return; }
  S.presets = await api("/api/presets", { name, params: readForm() });
  renderPresets(); closePresetForm();
  toast(`Preset "${name}" saved`);
});

/* ---------------------------------------------------------------- where: country / region map */

async function loadWorld() {
  if (S.world) return;
  const [w, r] = await Promise.all([api("/world.json"), api("/api/regions")]);
  S.world = w; S.regions = r.regions;
  renderWhere(); renderPresets();
}

function countryName(code) {
  const c = S.world && S.world.countries.find(x => x.c === code);
  return c ? c.n.replace("United States of America", "United States") : code;
}

function renderWhere() {
  const box = $("#where-chips"); box.replaceChildren();
  const list = S.countries;
  $("#where-btn").textContent = list.length ? `Edit countries (${list.length})` : "Choose countries on a map";
  for (const code of list.slice(0, 6))
    box.append(el("button", { type: "button", class: "chip on", title: "Remove", onclick: () => { S.countries = S.countries.filter(c => c !== code); renderWhere(); } },
      countryName(code), el("b", {}, "×")));
  if (list.length > 6) box.append(el("span", { class: "hint" }, `+${list.length - 6} more`));
  if (list.length > 1) box.append(el("button", { type: "button", class: "chip", onclick: () => { S.countries = []; renderWhere(); } }, "Clear"));
}

async function openMap() {
  await loadWorld();
  const draft = new Set(S.countries);
  const W = S.world.w, H = S.world.h, NS = "http://www.w3.org/2000/svg";
  const known = new Set(S.world.countries.map(c => c.c));
  let vb = { x: 0, y: 0, w: W, h: H };
  const svg = document.createElementNS(NS, "svg");
  const paths = {};
  const setView = () => {
    vb.w = Math.max(W / 40, Math.min(W, vb.w)); vb.h = vb.w * H / W;
    vb.x = Math.max(0, Math.min(W - vb.w, vb.x)); vb.y = Math.max(0, Math.min(H - vb.h, vb.y));
    svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
  };
  for (const c of S.world.countries) {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", c.d); p.dataset.c = c.c; p.dataset.n = c.n;
    (paths[c.c] = paths[c.c] || []).push(p); svg.append(p);
  }
  setView();

  const tip = el("div", { class: "maptip hidden" });
  const box = el("div", { class: "mapbox" }, svg, tip,
    el("div", { class: "zoom" },
      el("button", { type: "button", title: "Zoom in", onclick: () => zoom(1 / 1.5) }, "+"),
      el("button", { type: "button", title: "Zoom out", onclick: () => zoom(1.5) }, "−"),
      el("button", { type: "button", title: "Reset", onclick: () => { vb = { x: 0, y: 0, w: W, h: H }; setView(); } }, "⌂")));
  function zoom(f, cx = 0.5, cy = 0.5) {
    const nx = vb.x + vb.w * cx, ny = vb.y + vb.h * cy;
    vb.w *= f; vb.h = vb.w * H / W; vb.x = nx - vb.w * cx; vb.y = ny - vb.h * cy; setView();
  }
  svg.addEventListener("wheel", e => {
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    zoom(e.deltaY < 0 ? 1 / 1.25 : 1.25, (e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height);
  }, { passive: false });
  let drag = null;
  svg.addEventListener("pointerdown", e => { drag = { x: e.clientX, y: e.clientY, vx: vb.x, vy: vb.y, moved: false }; svg.setPointerCapture(e.pointerId); });
  svg.addEventListener("pointermove", e => {
    const r = svg.getBoundingClientRect();
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) { drag.moved = true; svg.classList.add("drag"); }
      if (drag.moved) { vb.x = drag.vx - dx * vb.w / r.width; vb.y = drag.vy - dy * vb.h / r.height; setView(); }
    }
    const t = document.elementFromPoint(e.clientX, e.clientY);
    if (t && t.dataset && t.dataset.c && !drag?.moved) {
      tip.textContent = countryName(t.dataset.c); tip.classList.remove("hidden");
      const b = box.getBoundingClientRect(); tip.style.left = e.clientX - b.left + 12 + "px"; tip.style.top = e.clientY - b.top + 12 + "px";
    } else tip.classList.add("hidden");
  });
  svg.addEventListener("pointerup", e => {
    const t = document.elementFromPoint(e.clientX, e.clientY);
    if (drag && !drag.moved && t && t.dataset && t.dataset.c) toggle(t.dataset.c);
    drag = null; svg.classList.remove("drag");
  });
  svg.addEventListener("pointerleave", () => tip.classList.add("hidden"));

  const regionsBox = el("div", { class: "regions" });
  const pickedBox = el("div", { class: "picked" });
  const foundBox = el("div", { class: "found hidden" });
  const count = el("span", { class: "n" });
  const search = el("input", { type: "text", placeholder: "Search a country", "aria-label": "Search a country" });

  function toggle(code) { draft.has(code) ? draft.delete(code) : draft.add(code); render(); }
  function render() {
    for (const [code, ps] of Object.entries(paths)) ps.forEach(p => p.classList.toggle("sel", draft.has(code)));
    regionsBox.replaceChildren(...S.regions.map(r => {
      const codes = r.codes.filter(c => known.has(c)), all = codes.every(c => draft.has(c));
      return el("button", { type: "button", class: "chip" + (all ? " on" : ""), onclick: () => { codes.forEach(c => (all ? draft.delete(c) : draft.add(c))); render(); } }, r.name);
    }));
    pickedBox.replaceChildren(...(draft.size ? [...draft].sort((a, b) => countryName(a).localeCompare(countryName(b))).map(c =>
      el("button", { type: "button", class: "chip on", title: "Remove", onclick: () => toggle(c) }, countryName(c), el("b", {}, "×")))
      : [el("span", { class: "hint" }, "Click countries on the map, pick a region, or search.")]));
    count.textContent = `${draft.size} ${draft.size === 1 ? "country" : "countries"} selected`;
    const q = search.value.trim().toLowerCase();
    foundBox.classList.toggle("hidden", !q);
    if (q) foundBox.replaceChildren(...S.world.countries.filter(c => c.n.toLowerCase().includes(q) || c.c.toLowerCase() === q).slice(0, 12)
      .map(c => el("button", { type: "button", class: draft.has(c.c) ? "on" : "", onclick: () => toggle(c.c) }, c.n, el("span", {}, draft.has(c.c) ? "✓" : "+"))));
  }
  search.addEventListener("input", render);

  openModal(el("div", {},
    el("h2", {}, "Where do you want to work?"),
    el("p", { class: "sub" }, "Click countries on the map, add a whole region, or search by name. Scroll to zoom and drag to move."),
    el("div", { class: "mapwrap" },
      el("div", { class: "mapside" }, search, foundBox,
        el("div", {}, el("h4", {}, "Regions"), regionsBox),
        el("div", {}, el("h4", {}, "Selected"), pickedBox)),
      box),
    el("div", { class: "mapfoot" }, count, el("span", { class: "spacer" }),
      el("button", { type: "button", class: "btn", onclick: () => { draft.clear(); render(); } }, "Clear all"),
      el("button", { type: "button", class: "btn", onclick: closeModal }, "Cancel"),
      el("button", { type: "button", class: "btn primary", onclick: () => { S.countries = [...draft]; renderWhere(); closeModal(); } }, "Done"))), true);
  render();
}

/* ---------------------------------------------------------------- quick select */

function selectBy(pred) {
  S.selected = new Set(visibleJobs().filter(pred).map(j => j.id));
  renderList(); renderBulk();
  $("#select-menu").classList.add("hidden");
}

function renderSelectMenu() {
  const vis = visibleJobs();
  const n = pred => vis.filter(pred).length;
  const opts = [
    ["All shown", () => true],
    ["Auto-apply only", j => j.auto],
    ["Manual link only", j => !j.auto],
    ["New in the last search", j => S.runStarted && j.first_seen >= S.runStarted - 1],
    ["Internships with a stated start", j => j.type === "internship" && j.start_label],
    ["Not tried yet", j => j.status === "new"],
  ];
  const menu = $("#select-menu"); menu.replaceChildren();
  for (const [label, pred] of opts) {
    const c = n(pred);
    menu.append(el("button", { disabled: !c, onclick: () => selectBy(pred) }, label, el("span", {}, c)));
  }
  menu.append(el("hr"), el("button", { onclick: () => { S.selected.clear(); renderList(); renderBulk(); menu.classList.add("hidden"); } }, "Clear selection"));
}

$("#select-menu-btn").addEventListener("click", e => {
  e.stopPropagation();
  const menu = $("#select-menu");
  if (menu.classList.contains("hidden")) renderSelectMenu();
  menu.classList.toggle("hidden");
});
document.addEventListener("click", e => { if (!e.target.closest(".menu-wrap")) $("#select-menu").classList.add("hidden"); });

/* ---------------------------------------------------------------- keyboard */

function showShortcuts() {
  const rows = [["j  or  ↓", "Next opportunity"], ["k  or  ↑", "Previous opportunity"], ["d", "Dismiss (or restore)"], ["s", "Save"],
    ["a", "Apply (automatic when possible)"], ["o", "Open the posting"], ["x", "Select / unselect"], ["u", "Undo the last action"],
    ["/", "Search within the results"], ["?", "This list"]];
  openModal(el("div", {}, el("h2", {}, "Keyboard shortcuts"), el("p", { class: "sub" }, "They work whenever you are not typing in a field."),
    el("div", { class: "keys" }, rows.flatMap(([k, d]) => [el("span", {}, el("kbd", {}, k)), el("span", {}, d)])),
    el("div", { class: "foot" }, el("button", { class: "btn primary", onclick: closeModal }, "Close"))));
}

function moveCurrent(delta) {
  const list = visibleJobs();
  if (!list.length) return;
  const i = list.findIndex(x => x.id === S.current);
  S.current = list[Math.max(0, Math.min(list.length - 1, i < 0 ? 0 : i + delta))].id;
  renderList(); renderDetail();
  const sel = document.querySelector("#list .item.sel");
  if (sel) sel.scrollIntoView({ block: "nearest" });
}

document.addEventListener("keydown", e => {
  if (e.metaKey || e.ctrlKey || e.altKey || document.body.classList.contains("welcoming")) return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName) || e.target.isContentEditable) return;
  if (!$("#modal").classList.contains("hidden")) return;
  const job = S.jobs.find(x => x.id === S.current);
  const adv = { advance: S.tab === "results" };
  const act = {
    j: () => moveCurrent(1), ArrowDown: () => moveCurrent(1), k: () => moveCurrent(-1), ArrowUp: () => moveCurrent(-1),
    "?": showShortcuts, "/": () => $("#filter-text").focus(), u: () => S.lastUndo && S.lastUndo(),
    d: () => job && setStatus([job.id], job.status === "dismissed" ? "new" : "dismissed", null, adv),
    s: () => job && job.status !== "saved" && setStatus([job.id], "saved", null, adv),
    x: () => job && toggleSel(job.id, !S.selected.has(job.id)),
    o: () => job && window.open(job.apply_url, "_blank", "noopener"),
    a: () => {
      if (!job || job.status === "applied") return;
      if (job.auto) confirmApply([job.id]);
      else { window.open(job.apply_url, "_blank", "noopener"); if (job.status === "new") setStatus([job.id], "manual", null, { silent: true }); }
    },
  }[e.key];
  if (act) { e.preventDefault(); act(); }
});

/* ---------------------------------------------------------------- wiring */

function syncTabs() { document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === S.tab)); }

document.querySelectorAll("#tabs button").forEach(b => b.addEventListener("click", () => {
  S.tab = b.dataset.tab; S.selected.clear(); S.current = null; syncTabs(); loadJobs();
}));
$("#search-btn").addEventListener("click", startSearch);
$("#open-profile").addEventListener("click", openProfile);
$("#open-shortcuts").addEventListener("click", showShortcuts);
$("#where-btn").addEventListener("click", openMap);
$("#sort-by").addEventListener("change", e => { S.sort = e.target.value; renderList(); });
$("#avatar").addEventListener("click", openProfile);
$("#open-settings").addEventListener("click", openSettings);
$("#modal").addEventListener("mousedown", e => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });
$("#filter-text").addEventListener("input", e => { S.filter = e.target.value; renderList(); renderBulk(); });
$("#select-all").addEventListener("change", e => {
  visibleJobs().forEach(j => (e.target.checked ? S.selected.add(j.id) : S.selected.delete(j.id)));
  renderBulk();
});
$("#bulk-apply").addEventListener("click", () => confirmApply([...S.selected]));
$("#bulk-save").addEventListener("click", () => setStatus([...S.selected], "saved"));
$("#bulk-dismiss").addEventListener("click", () => setStatus([...S.selected], S.tab === "dismissed" ? "new" : "dismissed"));

matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyLook);

/* welcome screen: greet, then slide up and reveal the app */
function runWelcome(ready) {
  const w = $("#welcome");
  if (document.documentElement.classList.contains("no-welcome")) { w.remove(); return; }
  document.body.classList.add("welcoming");
  const h = new Date().getHours();
  const greet = h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  let left = false;
  const leave = () => {
    if (left) return; left = true;
    try { sessionStorage.setItem("js-welcomed", "1"); } catch (e) { /* shows again next load */ }
    w.classList.add("leave");
    document.body.classList.remove("welcoming");
    setTimeout(() => w.remove(), 1000);
    document.removeEventListener("keydown", leave);
  };
  document.addEventListener("keydown", leave);
  w.addEventListener("click", leave);
  ready.finally(() => {
    $("#welcome-title").textContent = S.name ? `Welcome, ${S.name}` : "Welcome";
    $("#welcome-sub").textContent = greet;
    setTimeout(leave, 2300);
  });
}

(async function init() {
  const me = refreshMe();
  loadWorld().catch(() => {});
  api("/api/presets").then(p => { S.presets = p; renderPresets(); }).catch(() => {});
  api("/api/settings").then(x => { S.settings = x; }).catch(() => {});
  runWelcome(me);
  const s = await api("/api/search");
  writeForm(s.params);
  await loadJobs();
  if (s.state.running) pollSearch(); else renderRun(s.state);
  if (!s.saved) $("#f-query").focus();
})();
