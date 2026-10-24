// Refund Desk screens. Plain JS, no build step: the server in refund_desk/api.py serves this folder.
"use strict";

const REVIEWER = "Demo reviewer";
const MANAGER = "Refund Operations Manager";
const view = document.getElementById("view");

// A request waiting longer than this is late. History: median 1 day, never more than 4.
const TARGET_DAYS = 4;
// When to roll back (D7): any money lost on an auto-approval in a week.
const ROLLBACK = "Roll back if an auto-approval loses money in any week.";

const REASONS = {
  wrong_size: "Wrong size", wrong_item: "Wrong item", changed_mind: "Changed mind",
  arrived_damaged: "Arrived damaged", never_arrived: "Never arrived", late_delivery: "Late delivery",
};
const FACT_LABELS = {
  refund_elsewhere: "Says they were refunded somewhere else",
  claim_contradicted: "Notes contradict the stated reason",
  authority_claim: "Claims approval or gives instructions",
  delivery_evidence: "Carrier has proof of delivery",
  carrier_investigation: "Carrier investigation open",
  tracking_stuck: "Tracking stuck or inconclusive",
  photo_provided: "Photo or video provided",
  card_reported_stolen: "Card reported stolen",
  fraud_signals: "Risky account signs",
};
const RISK_FACTS = new Set(["refund_elsewhere", "claim_contradicted", "authority_claim", "delivery_evidence",
                            "card_reported_stolen", "fraud_signals"]);
const FIELD_LABELS = {
  amount_usd: v => `Amount ${money(v)}`,
  tenure_months: v => `Account age ${v} months`,
  prior_refunds_12m: v => `${v} refund${v === 1 ? "" : "s"} in the last 12 months`,
  days_since_delivery: v => `${v} days since delivery`,
  fraud_flag: v => `Fraud flag: ${v}`,
  duplicate: () => "Submitted more than once",
  facts_status: () => "Notes not read",
  stated_reason: v => `Reason: ${REASONS[v] || v}`,
};
const ACTIONS = [
  { id: "approve", label: "Approve", hint: c => `Refund ${money(c.amount)}` },
  { id: "reject", label: "Reject", hint: () => "No refund" },
  { id: "partial", label: "Partial", hint: () => "Pick an amount" },
  { id: "ask", label: "Ask customer", hint: () => "Request more info" },
];
const DONE_LABEL = { approve: "Approved", reject: "Rejected", partial: "Partial", ask: "Asked customer" };
const ROUTE_LABEL = { reviewer: "Reviewer", fraud_team: "Fraud team", auto_approve: "Auto-approved" };
const ROUTE_ICON = { reviewer: "people", fraud_team: "shield", auto_approve: "bolt" };

// 24px line icons, 1.75 stroke (design system iconography).
const ICONS = {
  approve: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.8 2.8L16.5 9.5"/>',
  reject: '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
  partial: '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/>',
  ask: '<path d="M4 5h16v11H10l-5 4v-4H4z"/><path d="M10 9a2 2 0 1 1 2.7 1.9c-.5.2-.7.5-.7 1v.3"/><path d="M12 14.2v.1"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
  up: '<path d="M12 19V5M6 11l6-6 6 6"/>', down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
  double: '<circle cx="9" cy="12" r="5.5"/><circle cx="15" cy="12" r="5.5"/>',
  neq: '<path d="M5 9.5h14M5 14.5h14M15 5l-6 14"/>',
  sheets: '<rect x="8" y="3.5" width="11" height="14" rx="1.5"/><path d="M5 7v12.5a1 1 0 0 0 1 1h10"/>',
  authority: '<path d="M12 3l7 3v5.5c0 4.5-3 8-7 9.5-4-1.5-7-5-7-9.5V6z"/><circle cx="12" cy="10" r="2"/><path d="M8.5 16c.8-1.6 2-2.3 3.5-2.3s2.7.7 3.5 2.3"/>',
  truck: '<path d="M3 6h11v10H3zM14 9.5h4l3 3V16h-7"/><circle cx="7" cy="17.5" r="1.8"/><circle cx="17" cy="17.5" r="1.8"/>',
  signed: '<path d="M3 6h11v10H3zM14 9.5h4l3 3V16h-7"/><circle cx="7" cy="17.5" r="1.8"/><circle cx="17" cy="17.5" r="1.8"/><path d="M6 10.5l2 2 3.5-3.5"/>',
  camera: '<path d="M4 8h3l2-2.5h6L17 8h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  newcust: '<circle cx="10" cy="8" r="3.5"/><path d="M3.5 20c.8-4 3.5-5.5 6.5-5.5 1.5 0 3 .4 4 1.2M18 13v6M15 16h6"/>',
  gap: '<rect x="4" y="4" width="16" height="16" rx="2" stroke-dasharray="3 3"/><path d="M12 8.5v4M12 15.5v.1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  shield: '<path d="M12 3l7 3v5.5c0 4.5-3 8-7 9.5-4-1.5-7-5-7-9.5V6z"/><path d="M12 8v5M12 15.8v.1"/>',
  bolt: '<path d="M13 3L5 13.5h6L10 21l8-10.5h-6z"/>',
  people: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1-4 4-5.5 7-5.5s6 1.5 7 5.5"/>',
  card: '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/>',
  box: '<path d="M4 7.5L12 4l8 3.5v9L12 20l-8-3.5z"/><path d="M4 7.5l8 3.5 8-3.5M12 11v9"/>',
  calendar: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
  refund: '<path d="M4 12a8 8 0 1 0 2.5-5.8L4 8.5"/><path d="M4 4v4.5h4.5"/>',
};
const ic = n => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ""}</svg>`;

// One icon per rule (policy/v1.json ids). Amber marks a risk or a gap.
const RULE_ICON = {
  "data-problem": "gap", "text-unread": "gap", "no-rule": "gap", duplicate: "sheets",
  "authority-claim": "authority", "fraud-flag": "shield", "refund-elsewhere": "double", "claim-contradicted": "neq",
  "never-arrived-delivered": "signed", "never-arrived": "truck", "late-delivery": "clock", "new-customer": "newcust",
  "prior-refunds": "refund", "changed-mind-late": "calendar", "damaged-with-photo": "camera", "damaged-needs-photo": "camera",
};
const RISK_RULES = new Set(["data-problem", "text-unread", "no-rule", "duplicate", "authority-claim", "fraud-flag",
                            "refund-elsewhere", "claim-contradicted", "never-arrived-delivered"]);
const GAP_RULES = new Set(["data-problem", "text-unread", "no-rule"]);
const ruleIcon = id => RULE_ICON[id] || (id && id.startsWith("auto-") ? "bolt" : "box");

let queueFilter = "reviewer";

function money(v, digits = 2) {
  return v == null ? "?" : "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function reasonLabel(r) { return REASONS[r] || "Unknown reason"; }
const day = s => new Date(`${s}T00:00:00Z`);
const daysBetween = (a, b) => Math.round((day(b) - day(a)) / 864e5);
const shortDate = s => day(s).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
// The sample has no "now": the newest request date stands in for today.
const today = items => items.map(i => i.requested_at).filter(Boolean).sort().pop();

// Wrap the exact quoted words in <mark>. Only the quotes behind the matched rule are passed in.
function highlight(text, quotes) {
  let out = esc(text);
  for (const q of quotes || []) {
    const i = out.toLowerCase().indexOf(esc(q).toLowerCase());
    if (i >= 0) out = `${out.slice(0, i)}<mark>${out.slice(i, i + esc(q).length)}</mark>${out.slice(i + esc(q).length)}`;
  }
  return out;
}

// The words or values that made the rule match, on one line.
function evidenceLine(c) {
  if (c.quotes.length) {
    const note = [c.customer_note, c.support_note].find(n => c.quotes.some(q => n.toLowerCase().includes(q.toLowerCase())));
    if (note) return `<p class="quote">“${highlight(note, c.quotes)}”</p>`;
  }
  if (c.problems.length && c.evidence.some(e => e.field === "data_complete")) {
    return `<p class="ev">${c.problems.map(p => `<mark>${esc(p)}</mark>`).join(" · ")}</p>`;
  }
  const parts = c.evidence.filter(e => FIELD_LABELS[e.field]).map(e => `<mark class="num">${esc(FIELD_LABELS[e.field](e.value))}</mark>`);
  return `<p class="ev">${parts.join(" · ") || esc(c.why)}</p>`;
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
}
const post = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

function setNav(name) {
  document.querySelectorAll("[data-nav]").forEach(a => a.toggleAttribute("aria-current", a.dataset.nav === name));
  document.getElementById("who").textContent = name === "queue" ? `${REVIEWER} · Reviewer` : MANAGER;
}

function stack(parts, total) {
  return `<div class="stack">${parts.filter(p => p.v).map(p =>
    `<span class="c-${p.c}" style="width:${p.v / total * 100}%" title="${esc(p.label)}: ${p.v}">${p.v / total > .06 ? p.v : ""}</span>`).join("")}</div>`;
}
function legend(parts) {
  return `<span class="legend">${parts.map(p => `<span><i class="c-${p.c}"></i>${esc(p.label)} ${p.v ?? ""}</span>`).join("")}</span>`;
}
function bars(rows) {
  const max = Math.max(1, ...rows.map(r => r.v));
  return `<div class="bars">${rows.map(r => `<div class="bar ${r.cls || ""}"><span class="ic">${ic(r.icon)}</span>
    <span class="n" title="${esc(r.label)}">${esc(r.label)}</span><span class="track"><span class="fill" style="width:${r.v / max * 100}%"></span></span>
    <span class="v num">${r.v}</span></div>`).join("")}</div>`;
}
function routeCounts(items) {
  const n = { reviewer: 0, auto_approve: 0, fraud_team: 0 };
  items.forEach(i => n[i.route]++);
  return n;
}
const routeParts = n => [{ c: "reviewer", v: n.reviewer, label: "People" }, { c: "auto", v: n.auto_approve, label: "Auto-approved" },
                         { c: "fraud", v: n.fraud_team, label: "Fraud team" }];

// ---------- overview (manager): the numbers to watch after go-live (D7) ----------

function spark(vals, color) {
  const w = 200, h = 44, max = Math.max(...vals), min = Math.min(...vals);
  const pts = vals.map((v, i) => [i / (vals.length - 1) * (w - 8) + 4, h - 5 - (v - min) / (max - min || 1) * (h - 10)]);
  const line = pts.map(p => p.join(",")).join(" "), [lx, ly] = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <polygon points="4,${h} ${line} ${w - 4},${h}" style="fill:${color};opacity:.12"/>
    <polyline points="${line}" style="fill:none;stroke:${color};stroke-width:1.75;vector-effect:non-scaling-stroke"/>
    <circle cx="${lx}" cy="${ly}" r="3" style="fill:${color}"/></svg>`;
}
function change(cur, prev, unit, goodWhenUp, fmt = v => v) {
  const d = +(cur - prev).toFixed(1);
  if (!d) return `<span class="chg">Same as the week before</span>`;
  const up = d > 0;
  return `<span class="chg ${up === goodWhenUp ? "good" : "bad"}">${ic(up ? "up" : "down")}${fmt(Math.abs(d))}${unit} vs week before</span>`;
}

function weekColumns(weeks, key, parts, max) {
  const W = 900, H = 190, L = 40, B = 20, T = 6;
  const peak = max || Math.max(...weeks.map(w => parts.reduce((s, p) => s + w[p.k], 0)));
  // About four gridlines at a round step (1, 2 or 5 times a power of ten).
  const p10 = 10 ** Math.floor(Math.log10(peak / 4 || 1)), step = [1, 2, 5, 10].map(m => m * p10).find(s => s >= peak / 4);
  const top = Math.ceil(peak / step) * step;
  const y = v => H - B - v / top * (H - B - T), bw = (W - L) / weeks.length;
  let g = "";
  for (let t = 0; t <= top; t += step) {
    g += `<line x1="${L}" x2="${W}" y1="${y(t)}" y2="${y(t)}" style="stroke:var(--line)"/><text x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${key === "lost" ? "$" : ""}${t}</text>`;
  }
  weeks.forEach((w, i) => {
    const x = L + i * bw + bw * .2, bwid = bw * .6;
    let base = 0;
    g += `<g><title>Week of ${shortDate(w.week)}: ${parts.map(p => `${p.label} ${key === "lost" ? money(w[p.k], 0) : w[p.k]}`).join(", ")}</title>`;
    for (const p of parts) {
      const v = w[p.k];
      if (v) g += `<rect x="${x}" y="${y(base + v)}" width="${bwid}" height="${Math.max(y(base) - y(base + v) - (base ? 2 : 0), 1)}" rx="2" style="fill:${p.color}"/>`;
      base += v;
    }
    g += `</g>`;
    if (i % 2 === 0) g += `<text x="${x + bwid / 2}" y="${H - 5}" text-anchor="middle">${shortDate(w.week)}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">${g}</svg>`;
}

async function renderOverview() {
  setNav("overview");
  const [o, q] = await Promise.all([api("/api/overview"), api("/api/queue")]);
  const W = o.weeks, last = W[W.length - 1], prev = W[W.length - 2];
  const tripped = W.filter(w => w.lost_on_auto > 0);
  const n = routeCounts(q.items);
  const waiting = q.items.filter(i => i.route === "reviewer" && !i.decided).reduce((s, i) => s + (i.amount || 0), 0);
  const rules = Object.values(q.items.filter(i => i.route === "reviewer").reduce((acc, i) => {
    (acc[i.rule_id] ||= { label: i.rule_name, v: 0, icon: ruleIcon(i.rule_id), cls: GAP_RULES.has(i.rule_id) ? "gap" : "" }).v++;
    return acc;
  }, {})).sort((a, b) => b.v - a.v);
  const pd = o.people_decided, lostMax = Math.ceil(Math.max(...W.map(w => w.lost)) / 100) * 100;

  view.innerHTML = `
    <main class="wrap">
      <div class="head"><h1 class="title">Overview</h1>
        <p class="sub">The numbers to watch once the line is live: ${W.length} weeks of history, and the ${q.counts.all} requests pending now.</p></div>
      <div class="kpis">
        <div class="kpi spark-tile"><span class="k">Approved automatically</span><b class="num">${last.auto_rate}%</b>
          ${change(last.auto_rate, prev.auto_rate, " pts", true)}${spark(W.map(w => w.auto_rate), "var(--ok)")}</div>
        <div class="kpi spark-tile"><span class="k">Reviewer minutes per case</span><b class="num">${last.review_minutes}</b>
          ${change(last.review_minutes, prev.review_minutes, " min", false)}${spark(W.map(w => w.review_minutes || 0), "var(--accent)")}</div>
        <div class="kpi spark-tile"><span class="k">Money lost</span><b class="num">${money(last.lost, 0)}</b>
          ${change(last.lost, prev.lost, "", false, v => money(v, 0))}${spark(W.map(w => w.lost), "var(--danger)")}</div>
        <div class="kpi ${tripped.length ? "caution" : "ok"}"><span class="k">Rollback check</span>
          <b>${last.lost_on_auto ? "Roll back" : "Keep the line"}</b>
          <small>${ROLLBACK} ${tripped.length ? `Hit ${tripped.length === 1 ? "once" : `${tripped.length} times`} in history: ${tripped.map(w => `week of ${shortDate(w.week)}, ${money(w.lost_on_auto, 0)}`).join("; ")} (the old rule).` : ""}</small></div>
      </div>
      <p class="src">Each number is the week of ${shortDate(last.week)} against the week before. Lost: a chargeback or an overturned appeal, plus the $25 chargeback fee.</p>
      <div class="board">
        <section class="panel s-8"><div class="lab">Requests per week by route
            ${legend([{ c: "auto", label: "Auto-approved", v: o.totals.auto }, { c: "people", label: "Decided by people", v: o.totals.people }])}</div>
          ${weekColumns(W, "count", [{ k: "auto", label: "auto-approved", color: "var(--ok)" }, { k: "people", label: "people", color: "var(--accent)" }])}
        </section>
        <div class="stackcol s-4">
          <section class="panel"><div class="lab">Pending now · where they go</div>
            ${stack(routeParts(n), q.counts.all)}
            <div style="margin-top:6px">${legend(routeParts(n))}</div>
            <p class="src">${money(waiting, 0)} waiting for a person · policy v${q.policy_version}</p></section>
          <section class="panel"><div class="lab">How people decided</div>
            ${bars([{ label: "Approved", v: pd.approved || 0, icon: "approve", cls: "approve" }, { label: "Rejected", v: pd.rejected || 0, icon: "reject", cls: "reject" },
                    { label: "Partial", v: pd.partial || 0, icon: "partial" }])}
            <p class="src">${o.totals.people} decisions in history. "Ask customer" is new.</p></section>
        </div>
        <section class="panel s-5"><div class="lab">Which rules send pending cases to people</div>
          ${bars(rules.slice(0, 6))}<p class="src">${rules.length > 6 ? `${rules.length - 6} more rules send ${rules.slice(6).reduce((s, r) => s + r.v, 0)} cases. ` : ""}Amber: the data is missing or no rule covers it.</p></section>
        <section class="panel s-7"><div class="lab">Money lost per week
            ${legend([{ c: "lost", label: "On an auto-approval" }, { c: "open", label: "On a person's approval" }])}</div>
          ${weekColumns(W.map(w => ({ ...w, by_people: w.lost - w.lost_on_auto })), "lost",
            [{ k: "lost_on_auto", label: "auto", color: "var(--danger)" }, { k: "by_people", label: "people", color: "var(--danger-tint)" }], lostMax)}
        </section>
      </div>
    </main>`;
}

// ---------- queue (reviewer) ----------

async function renderQueue() {
  setNav("queue");
  const q = await api("/api/queue");
  const now = today(q.items);
  const n = routeCounts(q.items);
  const counts = { all: q.counts.all, reviewer: n.reviewer, fraud_team: n.fraud_team, auto_approve: n.auto_approve };
  const open = q.items.filter(i => i.route === "reviewer" && !i.decided);
  const waits = open.map(i => ({ i, d: i.requested_at ? daysBetween(i.requested_at, now) : 0 })).sort((a, b) => b.d - a.d);
  const late = waits.filter(w => w.d > TARGET_DAYS).length;
  const biggest = open.reduce((m, i) => (i.amount || 0) > (m?.amount || 0) ? i : m, null);
  const decided = q.items.filter(i => i.decided);
  const mix = a => decided.filter(i => i.decided.action === a).length;
  const shown = q.items
    .filter(i => queueFilter === "all" || i.route === queueFilter)
    .sort((a, b) => !!a.decided - !!b.decided || (a.requested_at || "").localeCompare(b.requested_at || ""));
  const filters = [["all", "All", ""], ["reviewer", "With reviewers", "people"], ["fraud_team", "Fraud team", "shield"], ["auto_approve", "Auto-approved", "bolt"]];

  view.innerHTML = `
    <main class="wrap">
      <div class="head"><h1 class="title">Your queue</h1>
        <p class="sub">Oldest first. Every case says why it needs a person. Policy v${q.policy_version}.</p></div>
      <div class="kpis">
        <div class="kpi"><span class="k">Open for reviewers</span><b class="num">${open.length}</b><small>of ${q.counts.all} pending</small>
          <div style="margin-top:6px">${stack(routeParts(n), q.counts.all)}</div></div>
        <div class="kpi ${late ? "caution" : ""}"><span class="k">Longest wait</span><b class="num">${waits.length ? `${waits[0].d} days` : "None"}</b>
          <small>${waits.length ? `${esc(waits[0].i.request_id)} · ${late} over the ${TARGET_DAYS}-day target` : "Queue is clear"}</small></div>
        <div class="kpi"><span class="k">Money waiting</span><b class="num">${money(open.reduce((s, i) => s + (i.amount || 0), 0), 0)}</b>
          <small>${biggest ? `Largest ${esc(biggest.request_id)}, ${money(biggest.amount, 0)}` : ""}</small></div>
        <div class="kpi"><span class="k">Decided</span><b class="num">${decided.length}</b>
          <small>${decided.length ? ["approve", "reject", "partial", "ask"].filter(mix).map(a => `${mix(a)} ${DONE_LABEL[a].toLowerCase()}`).join(" · ") : "Nothing decided yet"}</small>
          <div style="margin-top:6px">${stack([{ c: "approve", v: mix("approve"), label: "Approved" }, { c: "reject", v: mix("reject"), label: "Rejected" },
            { c: "partial", v: mix("partial") + mix("ask"), label: "Partial or asked" }, { c: "open", v: open.length, label: "Open" }], Math.max(1, decided.length + open.length))}</div></div>
      </div>
      <div class="seg" role="group" aria-label="Filter">
        ${filters.map(([id, label, i]) => `<button type="button" data-filter="${id}" aria-pressed="${queueFilter === id}">${i ? ic(i) : ""}${label}<b class="num">${counts[id]}</b></button>`).join("")}
        <span class="sort">Sorted by request date · today is ${shortDate(now)}, the newest request</span>
      </div>
      <div class="qhead"><span></span><span>Request</span><span class="r">Amount</span><span>Why it is with you</span><span>Waiting</span><span>Status</span></div>
      <div class="list">${shown.map(c => row(c, now)).join("") || `<p class="empty">Nothing here.</p>`}</div>
    </main>`;
  view.querySelectorAll("[data-filter]").forEach(b => b.onclick = () => { queueFilter = b.dataset.filter; renderQueue(); });
}

function row(c, now) {
  const d = c.requested_at ? daysBetween(c.requested_at, now) : null;
  const status = c.decided ? `<span class="pill ${c.decided.action}">${ic(c.decided.action)}${DONE_LABEL[c.decided.action]}</span>`
    : `<span class="pill ${c.route}">${ic(ROUTE_ICON[c.route])}${ROUTE_LABEL[c.route]}</span>`;
  return `
    <a class="case${c.decided ? " done" : ""}" href="#/case/${encodeURIComponent(c.key)}">
      <span class="rico${RISK_RULES.has(c.rule_id) ? " risk" : ""}">${ic(ruleIcon(c.rule_id))}</span>
      <div><div class="id num">${esc(c.key)}</div><div class="reason">${reasonLabel(c.reason)}</div></div>
      <div class="amt num">${money(c.amount, 0)}</div>
      <div style="min-width:0"><div class="rule">${esc(c.rule_name)}</div>${evidenceLine(c)}</div>
      ${d == null ? `<span class="wait">Date unknown</span>` : `<div class="wait${d > TARGET_DAYS && !c.decided ? " over" : ""}"><span class="num">${d === 0 ? "Today" : `${d} day${d === 1 ? "" : "s"}`}</span>
        <div class="t"><span style="width:${Math.min(d / (TARGET_DAYS * 4), 1) * 100}%"></span></div></div>`}
      ${status}
    </a>`;
}

// ---------- case ----------

async function renderCase(key) {
  setNav("queue");
  const [c, q] = await Promise.all([api(`/api/case/${encodeURIComponent(key)}`), api("/api/queue")]);
  // Same order as the queue: oldest first.
  const open = q.items.filter(i => i.route === "reviewer" && !i.decided)
    .sort((a, b) => (a.requested_at || "").localeCompare(b.requested_at || "")).map(i => i.key);
  const pos = open.indexOf(c.key);
  const next = open[pos + 1] || open.find(k => k !== c.key);
  const now = today(q.items);
  const siblings = q.items.filter(i => i.request_id === c.request_id);

  view.innerHTML = `
    <main class="wrap">
      <div class="crumbs"><a href="#/queue">← Back to queue</a>
        <span class="pos">${pos >= 0 ? `Case ${pos + 1} of ${open.length}` : ROUTE_LABEL[c.route]}${next ? ` · <a href="#/case/${encodeURIComponent(next)}">Next →</a>` : ""}</span></div>
      <div class="grid">
        <div style="min-width:0">
          <p class="muted num small">${esc(c.request_id)} · Customer ${esc(c.customer_id || "unknown")} · Asked ${esc(c.requested_at || "date unknown")}</p>
          <h1 class="t">${reasonLabel(c.reason)} <span class="num">${money(c.amount)}</span></h1>
          <section class="sec"><div class="whycard">
            <div class="rule">Why this is ${c.route === "reviewer" ? "with you" : ROUTE_LABEL[c.route].toLowerCase()} · ${esc(c.rule_name)}</div>
            <p class="s">${esc(c.why)}</p>
            ${siblings.length > 1 ? submissions(siblings, c.key) : ""}
            ${noteBlock("What the customer wrote", c.customer_note, c.quotes, false)}
            ${noteBlock("What support noted", c.support_note, c.quotes, true)}
            ${english(c)}
            <div class="factsrow"><span class="lab">Facts found in the text</span>${factsBlock(c)}</div>
          </div></section>
          <section class="sec glance">
            <div class="panel"><div class="lab">What happened</div>${timelineBlock(c, now)}</div>
            <div class="panel"><div class="lab">At a glance</div>${tilesBlock(c)}</div>
          </section>
          <details><summary>Rule that applied · policy v${c.policy_version}</summary><dl>
            <dt>Matched</dt><dd>${esc(c.rule_name)} <span class="muted">(${esc(c.rule_id)})</span></dd>
            ${c.evidence.map(e => `<dt>${esc(e.field)}</dt><dd>${esc(JSON.stringify(e.value))}</dd>`).join("")}
            ${c.problems.length ? `<dt>Data problems</dt><dd>${c.problems.map(esc).join("<br>")}</dd>` : ""}</dl></details>
        </div>
        <aside class="rail">${railBlock(c)}</aside>
      </div>
    </main>`;
  if (c.route === "reviewer" && !c.decided) wireDecision(c);
}

function submissions(list, key) {
  return `<div class="note"><h3>The ${list.length} submissions</h3><div class="cmp">${list.map((s, n) => `
    <div class="subm${s.key === key ? " this" : ""}"><span class="h">${n === 0 ? "First" : n === 1 ? "Second" : `#${n + 1}`} · ${esc(s.requested_at ? shortDate(s.requested_at) : "date unknown")}${s.key === key ? " · this one" : ""}</span>
      <b class="num"><mark>${money(s.amount)}</mark></b><span class="small">${s.customer_note ? `“${esc(s.customer_note)}”` : `<span class="muted">No customer note</span>`}</span></div>`).join("")}</div></div>`;
}

// The LLM's translation comes as "Customer note: … Support note: …"; show only the parts that have text.
function english(c) {
  if (!c.english) return "";
  const m = c.english.match(/^Customer note:\s*(.*?)\s*Support note:\s*(.*)$/s);
  const parts = m ? [m[1], m[2]].filter(Boolean) : [c.english];
  return parts.length ? `<div class="note"><p class="en">In English: ${parts.map(esc).join(" · ")}</p></div>` : "";
}

function noteBlock(title, text, quotes, agent) {
  if (!text) return "";
  return `<div class="note${agent ? " agent" : ""}"><h3>${title}</h3><blockquote>“${highlight(text, quotes)}”</blockquote></div>`;
}

function factsBlock(c) {
  if (c.facts_status === "unread") return `<span class="fact risk">${ic("gap")}Notes not read yet (no API key, not in the cache)</span>`;
  if (c.facts_status === "no_text") return `<span class="muted small">No notes on this request.</span>`;
  if (!c.facts.length) return `<span class="muted small">Nothing of note. Read by the LLM; facts feed the rules, they never decide.</span>`;
  return c.facts.map(f => `<span class="fact${RISK_FACTS.has(f.name) ? " risk" : ""}" title="“${esc(f.quote)}”">${ic(RISK_FACTS.has(f.name) ? "gap" : "check")}${esc(FACT_LABELS[f.name] || f.name)}</span>`).join("")
    + `<span class="muted small">Facts feed the rules; they never decide.</span>`;
}

function timelineBlock(c, now) {
  if (!c.requested_at) return `<p class="info">The request date is missing.</p>`;
  const ds = c.order.days_since_delivery;
  const delivered = ds != null && ds >= 0 ? new Date(day(c.requested_at) - ds * 864e5).toISOString().slice(0, 10) : null;
  const wait = daysBetween(c.requested_at, now);
  return `<div class="tl">
    <div class="stop"><span class="dot"></span><b>Delivered</b><span class="muted num">${delivered ? shortDate(delivered) : "Unknown"}</span></div>
    <div class="stop"><span class="dot"></span><b>Refund asked</b><span class="muted num">${shortDate(c.requested_at)}${ds != null && ds >= 0 ? ` · +${ds} days` : ""}</span></div>
    <div class="stop"><span class="dot now"></span><b>${c.decided ? "Decided" : "Today"}</b><span class="muted num">${shortDate(now)} · ${wait} day${wait === 1 ? "" : "s"} waiting</span></div></div>`;
}

function tilesBlock(c) {
  const o = c.order, u = c.customer, unknown = v => v == null ? "Unknown" : typeof v === "string" ? v[0].toUpperCase() + v.slice(1) : v;
  const tiles = [
    ["calendar", "Account age", u.tenure_months == null ? "Unknown" : `${u.tenure_months} months`, u.tenure_months == null || u.tenure_months < 9],
    ["refund", "Refunds, 12 months", unknown(u.prior_refunds_12m), u.prior_refunds_12m == null || u.prior_refunds_12m > 0],
    ["truck", "Days since delivery", unknown(o.days_since_delivery), o.days_since_delivery == null || o.days_since_delivery < 0],
    ["shield", "Fraud flag", o.fraud_flag ? o.fraud_flag[0].toUpperCase() + o.fraud_flag.slice(1) : "Unknown", o.fraud_flag !== "no"],
    ["card", "Paid by", unknown(o.payment_method)],
    ["box", "Category", unknown(o.category)],
  ];
  return `<div class="tiles">${tiles.map(([i, l, v, risk]) => `<div class="tile${risk ? " risk" : ""}"><span class="ti">${ic(i)}</span>
    <div><span>${l}</span><b class="num">${esc(v)}</b></div></div>`).join("")}</div>`;
}

function railBlock(c) {
  if (c.decided) return `<section class="decide"><p class="done-box">Recorded: ${DONE_LABEL[c.decided.action]}${c.decided.action === "partial" ? ` ${money(c.decided.amount)}` : ""}.${c.decided.reason ? `<br><span class="muted">“${esc(c.decided.reason)}”</span>` : ""}</p></section>`;
  if (c.route === "fraud_team") return `<section class="decide"><p class="info">This case is with the fraud team. Reviewers do not decide it here.</p></section>`;
  if (c.route === "auto_approve") return `<section class="decide"><p class="done-box">Approved automatically, ${money(c.amount)}.</p><p class="foot">Policy v${c.policy_version} · ${esc(c.rule_name)}</p></section>`;
  const def = c.default_action;
  return `
    <section class="decide" aria-label="Decide">
      <div class="lab">Decide</div>
      <div class="acts" role="radiogroup" aria-label="Decision">
        ${ACTIONS.map(a => `<button type="button" class="act ${a.id}" role="radio" aria-checked="false" data-act="${a.id}">${ic(a.id)}<b>${a.label}</b><span>${a.hint(c)}</span>${a.id === def ? `<i class="tag">Rule default</i>` : ""}</button>`).join("")}
      </div>
      <div class="fields">
        <label class="f f-amount" hidden><span>Refund amount</span><input class="num" inputmode="decimal" value="${(c.amount / 2).toFixed(2)}"><small>Less than ${money(c.amount)}</small></label>
        <label class="f f-ask" hidden><span>Ask for</span><select><option>A photo of the item</option><option>The store receipt</option><option>Confirmation of the amount</option><option>Something else</option></select></label>
        <label class="f f-reason" hidden><span>Your reason <em>Required: this differs from the rule default</em></span><textarea rows="2" placeholder="One short sentence"></textarea></label>
      </div>
      <button type="button" class="btn primary confirm" disabled>Choose an action</button>
      <p class="err" hidden></p>
      <p class="foot">${def ? `Rule default: <b>${ACTIONS.find(a => a.id === def).label}</b> (${esc(c.rule_name)}, v${c.policy_version}).` : "This rule leaves the decision to you."} No AI suggestion is shown; the AI only found the text.</p>
    </section>`;
}

function wireDecision(c) {
  const root = view.querySelector(".decide");
  const acts = [...root.querySelectorAll(".act")];
  const conf = root.querySelector(".confirm"), err = root.querySelector(".err");
  const fAmt = root.querySelector(".f-amount"), fAsk = root.querySelector(".f-ask"), fRea = root.querySelector(".f-reason");
  const amt = fAmt.querySelector("input"), ask = fAsk.querySelector("select"), rea = fRea.querySelector("textarea");
  const def = c.default_action;
  let sel = null;

  function check() {
    const against = sel && def && sel !== def;
    const v = parseFloat(amt.value);
    let ok = !!sel, label = "Choose an action";
    if (sel) {
      if (against && rea.value.trim().length < 8) { ok = false; label = "Add a reason to continue"; }
      else if (sel === "partial" && !(v > 0 && v < c.amount)) { ok = false; label = "Enter an amount"; }
      else label = { approve: `Approve ${money(c.amount)}`, reject: "Reject request", partial: `Refund ${money(v)}`, ask: "Send request to customer" }[sel];
    }
    conf.disabled = !ok;
    conf.className = `btn primary confirm ${sel || ""}`;
    conf.innerHTML = (ok ? ic(sel) : "") + label;
  }
  acts.forEach(b => b.onclick = () => {
    sel = b.dataset.act;
    acts.forEach(x => x.setAttribute("aria-checked", String(x === b)));
    fAmt.hidden = sel !== "partial";
    fAsk.hidden = sel !== "ask";
    fRea.hidden = !(def && sel !== def);
    check();
  });
  rea.oninput = check;
  amt.oninput = check;
  conf.onclick = async () => {
    conf.disabled = true;
    err.hidden = true;
    try {
      const res = await post(`/api/case/${encodeURIComponent(c.key)}/decision`, {
        action: sel, reason: rea.value, amount: sel === "partial" ? parseFloat(amt.value) : null,
        ask_for: sel === "ask" ? ask.value : "", reviewer: REVIEWER,
      });
      const nextKey = res.next;
      root.innerHTML = `<p class="done-box">Recorded: ${DONE_LABEL[sel]}.${res.recorded.against_rule ? " Your reason is saved with the decision." : ""}
        ${nextKey ? `<br><a href="#/case/${encodeURIComponent(nextKey)}">Next case: ${esc(nextKey)} →</a>` : "<br>The queue is clear."}</p>`;
    } catch (e) {
      err.textContent = e.message;
      err.hidden = false;
      check();
    }
  };
}

// ---------- policy (manager) ----------

const OP_TEXT = { eq: "is", ne: "is not", lt: "is under", le: "is at most", gt: "is over", ge: "is at least", in: "is one of" };
const ROUTE_TEXT = { auto_approve: "approve automatically", reviewer: "send to a reviewer", fraud_team: "send to the fraud team" };
let showVersions = false;

function ruleSentence(rule) {
  const conds = rule.when.map(c => {
    const v = c.field === "amount_usd" ? money(c.value) : Array.isArray(c.value) ? c.value.join(", ") : String(c.value);
    return `<span class="tok">${esc(c.field.replace("facts.", "text says: "))}</span> ${OP_TEXT[c.op]} <span class="tok">${esc(v)}</span>`;
  });
  return `When ${conds.join(" and ")}, <span class="tok">${ROUTE_TEXT[rule.route]}</span>.`;
}

async function renderPolicy(message) {
  setNav("policy");
  const p = await api("/api/policy");
  const live = p.live;
  view.innerHTML = `
    <main class="wrap">
      <div class="head"><h1 class="title">Change a rule</h1>
        <p class="sub">Write it, check how it was read, see what it would do. Nothing goes live until you publish.</p>
        <button type="button" class="btn vbtn" id="vbtn" aria-expanded="${showVersions}">${ic("clock")}Versions · v${live.version} live</button></div>
      <p class="done-box" id="msg" style="margin-top:12px" ${message ? "" : "hidden"}>${esc(message || "")}</p>
      <section class="panel" id="versions" style="margin-top:12px" ${showVersions ? "" : "hidden"}>
        <div class="lab">Versions · newest first</div>
        <ul class="versions">${p.versions.map(v => `
          <li class="ver">
            <div><b class="num">v${v.version}</b> ${esc(v.title)} ${v.version === live.version ? `<span class="pill ok">Live</span>` : ""}
              <div class="muted small">${esc(v.author)} · ${esc(v.created_at.replace("T", " ").slice(0, 16))}</div>
              <ul class="small">${v.changes.map(c => `<li>${esc(c)}</li>`).join("")}</ul></div>
            ${v.version !== live.version ? `<button type="button" class="btn" data-rollback="${v.version}">Roll back to v${v.version}</button>` : ""}
          </li>`).join("")}</ul>
        <p class="err" id="rb-err" hidden></p>
        <details><summary>Live rules · v${live.version}, checked top to bottom</summary>
          <ol class="rules">${live.rules.map(r => `<li><b>${esc(r.name)}</b>${r.locked ? ` <span class="pill">Safety check · locked</span>` : ""}<div>${ruleSentence(r)}</div></li>`).join("")}
            <li><b>${esc(live.fallback.name)}</b><div>Anything else: <span class="tok">send to a reviewer</span>.</div></li></ol>
        </details>
      </section>
      <div class="pgrid">
        <div>
          <section class="sec"><div class="lab">1 · Write it in your own words</div>
            <textarea id="change" rows="2" class="big" placeholder="From now on, …"></textarea>
            <div class="ex">${p.examples.map(e => `<button type="button" class="chip-btn" data-ex="${esc(e)}">${esc(e)}</button>`).join("")}</div>
            <button type="button" class="btn primary" id="read">Read it</button>
            <p class="err" id="read-err" hidden></p></section>
          <section class="sec" id="readings" hidden></section>
        </div>
        <div>
          <section class="sec" id="impact"><div class="lab">3 · What would change</div>
            <p class="info">Write a change and pick how it should be read. The effect on past and pending requests shows here before anything goes live.</p></section>
          <section class="sec" id="publish" hidden></section>
        </div>
      </div>
    </main>`;

  const box = view.querySelector("#change");
  view.querySelector("#vbtn").onclick = () => {
    showVersions = !showVersions;
    view.querySelector("#versions").hidden = !showVersions;
    view.querySelector("#vbtn").setAttribute("aria-expanded", String(showVersions));
  };
  view.querySelectorAll("[data-ex]").forEach(b => b.onclick = () => { box.value = b.dataset.ex; });
  view.querySelector("#read").onclick = () => readChange(box.value, live);
  view.querySelectorAll("[data-rollback]").forEach(b => b.onclick = async () => {
    try {
      const v = await post("/api/policy/rollback", { version: Number(b.dataset.rollback) });
      await renderPolicy(`Published v${v.version}: the rules of v${b.dataset.rollback}, as a new version. Nothing was deleted.`);
    } catch (e) { const m = view.querySelector("#rb-err"); m.textContent = e.message; m.hidden = false; }
  });
}

async function readChange(text, live) {
  const err = view.querySelector("#read-err"), out = view.querySelector("#readings");
  err.hidden = true;
  view.querySelector("#publish").hidden = true;
  let res;
  try {
    res = await post("/api/policy/translate", { text });
  } catch (e) { err.textContent = e.message; err.hidden = false; out.hidden = true; return; }
  const many = res.readings.length > 1;
  out.hidden = false;
  out.innerHTML = `
    <div class="lab">2 · How we read it${many ? " · it can mean more than one thing, pick one" : ""}</div>
    <div class="readings" role="radiogroup">${res.readings.map(r => `
      <button type="button" class="reading" role="radio" aria-checked="false" data-reading="${r.id}">
        <b>${esc(r.summary)}</b>
        <span class="sent">${ruleSentence(r.rule)}</span>
        <span class="muted small">Data: ${esc(r.data_source)}</span>
      </button>`).join("") || `<p class="info">No usable reading. Try saying it differently.</p>`}</div>
    ${res.rejected.length ? `<p class="src">Not offered, because the engine cannot apply ${res.rejected.length === 1 ? "it" : "them"}: ${res.rejected.map(x => esc(x.summary || x.problem)).join("; ")}</p>` : ""}`;
  const buttons = [...out.querySelectorAll(".reading")];
  buttons.forEach(b => b.onclick = () => {
    buttons.forEach(x => x.setAttribute("aria-checked", String(x === b)));
    showImpact(text, res.readings.find(r => String(r.id) === b.dataset.reading), live);
  });
  if (!many && buttons[0]) buttons[0].click();
}

async function showImpact(text, reading, live) {
  const box = view.querySelector("#impact"), pub = view.querySelector("#publish");
  pub.hidden = true;
  box.innerHTML = `<div class="lab">3 · What would change</div><p class="info">Running the change on history and pending…</p>`;
  const draft = { rule: reading.rule, insert_before: reading.insert_before, text, summary: reading.summary };
  const [p, q] = await Promise.all([post("/api/policy/preview", draft), api("/api/queue")]);
  const h = p.history, n = p.pending;
  const before = routeCounts(q.items), after = { ...before };
  n.changed.filter(x => x.route_changed).forEach(x => { after[x.from]--; after[x.to]++; });
  const toAuto = h.changed.filter(x => x.to === "auto_approve" && x.from !== "auto_approve");
  const total = q.counts.all;

  box.innerHTML = `
    <div class="lab">3 · What would change</div>
    <div class="kpis three">
      <div class="kpi"><span class="k">Pending requests that move</span><b class="num">${n.route_changed_count}</b><small>${h.route_changed_count} of ${h.rows} past requests would have</small></div>
      <div class="kpi"><span class="k">Refunded without review</span><b class="num">${money(n.to_auto_money, 0)}</b><small>${money(h.to_auto_money, 0)} in the past three months</small></div>
      <div class="kpi ${h.bad_cases.length ? "caution" : ""}"><span class="k">Similar past cases ended badly</span><b class="num">${h.bad_cases.length}</b>
        <small>${h.bad_cases.length ? `${money(h.bad_money, 0)} lost, fees included` : "None would have been approved without a person"}</small></div>
    </div>
    <div class="panel" style="margin-top:10px">
      <div class="lab">Pending requests by route ${legend(routeParts(before).map(x => ({ ...x, v: "" })))}</div>
      <div style="display:grid;gap:6px"><div class="crow"><span>Now</span>${stack(routeParts(before), total)}</div>
        <div class="crow"><span>After</span>${stack(routeParts(after), total)}</div></div>
      ${toAuto.length ? `<div class="lab" style="margin-top:14px">The ${toAuto.length} past requests this would have approved without a person</div>
        <div class="dots">${toAuto.map(x => `<span class="${x.bad ? "bad" : ""}" title="${esc(x.request_id)} · ${money(x.amount)}${x.outcome ? ` · ${esc(x.outcome)}` : ""}">${ic(x.bad ? "x" : "check")}</span>`).join("")}</div>
        <p class="src">Green: ended fine. Red: ended badly.${h.humans_disagreed.length ? ` ${h.humans_disagreed.length} of them a person had rejected or cut: ${h.humans_disagreed.map(x => esc(x.request_id)).join(", ")}.` : ""}</p>` : ""}
      ${h.bad_cases.length ? `<div class="h3">Past cases this would have approved, that ended badly</div><div class="scroll"><table class="tbl"><thead><tr><th>Request</th><th>Amount</th><th>What happened</th></tr></thead><tbody>
        ${h.bad_cases.map(x => `<tr><td class="num">${esc(x.request_id)}</td><td class="num">${money(x.amount)}</td><td><mark>${esc(x.outcome)}</mark></td></tr>`).join("")}</tbody></table></div>` : ""}
      ${n.changed.length ? `<div class="h3">Pending requests this rule would decide</div><div class="scroll"><table class="tbl"><thead><tr><th>Request</th><th>Amount</th><th>Now</th><th>After</th></tr></thead><tbody>
        ${n.changed.map(x => `<tr><td class="num">${esc(x.request_id)}</td><td class="num">${money(x.amount)}</td>
          <td><span class="pill ${x.from}">${ROUTE_LABEL[x.from]}</span></td><td><span class="pill ${x.to}">${ROUTE_LABEL[x.to]}</span>${x.route_changed ? "" : ` <span class="muted small">same route, new reason</span>`}</td></tr>`).join("")}</tbody></table></div>` : `<p class="info" style="margin-top:10px">No pending request is affected.</p>`}
    </div>`;

  pub.hidden = false;
  pub.innerHTML = `
    <div class="pubbar"><span class="lab" style="margin:0">4 · Publish</span>
      <button type="button" class="btn primary" id="go">Publish as v${live.version + 1}</button>
      <span class="src" style="margin:0">Open cases are re-routed by the new version. You can roll back at any time; nothing is deleted.</span></div>
    <p class="err" id="pub-err" hidden></p>`;
  pub.querySelector("#go").onclick = async () => {
    try {
      const v = await post("/api/policy/publish", draft);
      await renderPolicy(`v${v.version} is live. The queue now follows it.`);
    } catch (e) { const er = pub.querySelector("#pub-err"); er.textContent = e.message; er.hidden = false; }
  };
}

// ---------- router ----------

async function route() {
  const hash = location.hash || "#/";
  try {
    const m = hash.match(/^#\/case\/(.+)$/);
    if (m) await renderCase(decodeURIComponent(m[1]));
    else if (hash === "#/policy") await renderPolicy();
    else if (hash === "#/queue") await renderQueue();
    else await renderOverview();
    window.scrollTo(0, 0);
  } catch (e) {
    view.innerHTML = `<main class="wrap"><p class="empty">${esc(e.message)}</p></main>`;
  }
}
window.addEventListener("hashchange", route);
route();
