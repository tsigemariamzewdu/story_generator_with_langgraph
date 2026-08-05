// API base URL: injected via window.API_BASE_URL when deployed, otherwise the
// local dev server, or same-origin ('' ) when FastAPI serves the frontend.
const API = window.API_BASE_URL ||
  (['localhost', '127.0.0.1', ''].includes(location.hostname)
    ? 'http://localhost:8000'
    : '');
const POLL_INTERVAL = 2500;

let currentThreadId = null;
let pollTimer = null;

// ── DOM refs ────────────────────────────────────────────────────────────────
const inputCard    = document.getElementById('inputCard');
const progressCard = document.getElementById('progressCard');
const hitlCard     = document.getElementById('hitlCard');
const reportCard   = document.getElementById('reportCard');
const rejectedCard = document.getElementById('rejectedCard');

const companyInput  = document.getElementById('companyInput');
const offlineToggle = document.getElementById('offlineToggle');
const runBtn        = document.getElementById('runBtn');
const threadBadge   = document.getElementById('threadBadge');
const statusText    = document.getElementById('statusText');
const spinner       = document.getElementById('spinner');

const approveBtn = document.getElementById('approveBtn');
const rejectBtn  = document.getElementById('rejectBtn');
const newRunBtn  = document.getElementById('newRunBtn');
const exportBtn  = document.getElementById('exportBtn');

// ── Pipeline steps in order ─────────────────────────────────────────────────
const STEPS = ['researcher', 'analyzer', 'evaluator', 'human_approval', 'drafter'];

// ── Utility ─────────────────────────────────────────────────────────────────
function show(el)  { el.classList.remove('hidden'); }
function hide(el)  { el.classList.add('hidden'); }
function hideAll() {
  [progressCard, hitlCard, reportCard, rejectedCard].forEach(hide);
}

function markStep(name, state) {
  const el = document.getElementById(`step-${name}`);
  if (!el) return;
  el.classList.remove('active', 'done');
  if (state === 'active') el.classList.add('active');
  if (state === 'done')   el.classList.add('done');
}

function markConnector(afterIndex, done) {
  const connectors = document.querySelectorAll('.pipeline-connector');
  if (connectors[afterIndex]) {
    connectors[afterIndex].classList.toggle('done', done);
  }
}

function advancePipeline(completedUpTo) {
  // completedUpTo: index of last completed step (0-based)
  STEPS.forEach((name, i) => {
    if (i < completedUpTo)       markStep(name, 'done');
    else if (i === completedUpTo) markStep(name, 'active');
    else                          markStep(name, '');
    if (i < completedUpTo) markConnector(i, true);
  });
}

function val(v, fallback = '—') {
  if (v === null || v === undefined || v === '') return fallback;
  return v;
}

// ── Start run ────────────────────────────────────────────────────────────────
runBtn.addEventListener('click', async () => {
  const company = companyInput.value.trim();
  if (!company) { companyInput.focus(); return; }

  runBtn.disabled = true;
  hideAll();
  show(progressCard);
  STEPS.forEach(n => markStep(n, ''));
  document.querySelectorAll('.pipeline-connector').forEach(c => c.classList.remove('done'));
  statusText.textContent = 'Starting pipeline…';
  show(spinner);

  try {
    const res = await fetch(`${API}/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company, offline: offlineToggle.checked }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    currentThreadId = data.thread_id;
    threadBadge.textContent = currentThreadId;
    startPolling();
  } catch (e) {
    statusText.textContent = `Error: ${e.message}`;
    hide(spinner);
    runBtn.disabled = false;
  }
});

// ── Polling ──────────────────────────────────────────────────────────────────
function startPolling() {
  stopPolling();
  pollTimer = setInterval(poll, POLL_INTERVAL);
  poll();
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function poll() {
  if (!currentThreadId) return;
  try {
    const res = await fetch(`${API}/runs/${currentThreadId}`);
    if (!res.ok) return;
    const data = await res.json();
    handleStatus(data);
  } catch (_) {}
}

function handleStatus(data) {
  const status = data.status;

  if (status === 'running') {
    show(progressCard);
    // Infer progress from what's populated in state
    if (data.metrics_preview)       advancePipeline(3); // human_approval active
    else if (data.quality_score > 0) advancePipeline(2); // evaluator active
    else if (data.source_records > 0) advancePipeline(1); // analyzer active
    else                              advancePipeline(0); // researcher active
    statusText.textContent = 'Pipeline running…';
    show(spinner);
    return;
  }

  stopPolling();
  hide(spinner);

  if (status === 'awaiting_approval') {
    advancePipeline(3);
    STEPS.forEach((n, i) => { if (i < 3) markStep(n, 'done'); });
    markStep('human_approval', 'active');
    hide(progressCard);
    renderHITL(data);
    show(hitlCard);
    return;
  }

  if (status === 'completed') {
    STEPS.forEach((n, i) => markStep(n, 'done'));
    document.querySelectorAll('.pipeline-connector').forEach(c => c.classList.add('done'));
    hide(progressCard);
    fetchAndRenderReport();
    return;
  }

  if (status === 'rejected') {
    hide(progressCard);
    show(rejectedCard);
    runBtn.disabled = false;
    return;
  }

  if (status === 'error') {
    statusText.textContent = `Pipeline error: ${data.error || 'unknown'}`;
    runBtn.disabled = false;
  }
}

// ── HITL render ──────────────────────────────────────────────────────────────
function renderHITL(data) {
  document.getElementById('qualityScore').textContent =
    data.quality_score != null ? (data.quality_score * 100).toFixed(1) + '%' : '—';
  document.getElementById('retryLoops').textContent   = val(data.iteration_count);
  document.getElementById('sourceRecords').textContent = val(data.source_records);

  const fb = data.feedback;
  const fbBox = document.getElementById('feedbackBox');
  if (fb) {
    document.getElementById('feedbackText').textContent = fb;
    show(fbBox);
  } else {
    hide(fbBox);
  }

  const grid = document.getElementById('metricsGrid');
  grid.innerHTML = '';
  const m = data.metrics_preview;
  if (!m) return;

  const cards = [
    { label: 'Company Overview',      value: m.company_overview,    type: 'text' },
    { label: 'Pricing Model',         value: m.pricing_model,       type: 'text' },
    { label: 'Target Audience',       value: m.target_audience,     type: 'text' },
    { label: 'Key Value Propositions',value: m.key_value_propositions, type: 'list' },
    { label: 'Strengths',             value: m.strengths,           type: 'list' },
    { label: 'Weaknesses',            value: m.weaknesses,          type: 'list' },
    { label: 'Competitors Mentioned', value: m.competitors_mentioned, type: 'list' },
    { label: 'Market Positioning',    value: m.market_positioning,  type: 'text' },
  ];

  cards.forEach(({ label, value, type }) => {
    const card = document.createElement('div');
    card.className = 'metric-card';
    const isEmpty = !value || (Array.isArray(value) && value.length === 0);
    card.innerHTML = `<h4>${label}</h4>` + (
      isEmpty
        ? `<p class="missing">Not identified</p>`
        : type === 'list'
          ? `<ul>${value.map(v => `<li>${esc(v)}</li>`).join('')}</ul>`
          : `<p>${esc(value)}</p>`
    );
    grid.appendChild(card);
  });
}

// ── Approve / Reject ─────────────────────────────────────────────────────────
approveBtn.addEventListener('click', async () => {
  approveBtn.disabled = true;
  rejectBtn.disabled  = true;
  hide(hitlCard);
  show(progressCard);
  markStep('drafter', 'active');
  statusText.textContent = 'Drafting report…';
  show(spinner);

  try {
    const res = await fetch(`${API}/runs/${currentThreadId}/approve`, { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
    startPolling();
  } catch (e) {
    statusText.textContent = `Error: ${e.message}`;
    hide(spinner);
    approveBtn.disabled = false;
    rejectBtn.disabled  = false;
    show(hitlCard);
    hide(progressCard);
  }
});

rejectBtn.addEventListener('click', async () => {
  await fetch(`${API}/runs/${currentThreadId}/reject`, { method: 'POST' });
  hide(hitlCard);
  show(rejectedCard);
  runBtn.disabled = false;
});

newRunBtn.addEventListener('click', () => {
  hide(rejectedCard);
  companyInput.value = '';
  companyInput.focus();
  runBtn.disabled = false;
});

// ── Fetch & render report ────────────────────────────────────────────────────
async function fetchAndRenderReport() {
  try {
    const res = await fetch(`${API}/runs/${currentThreadId}/report`);
    if (!res.ok) throw new Error(await res.text());
    const report = await res.json();
    renderReport(report);
    show(reportCard);
    runBtn.disabled = false;
  } catch (e) {
    statusText.textContent = `Failed to load report: ${e.message}`;
    show(progressCard);
    runBtn.disabled = false;
  }
}

function renderReport(data) {
  const rr = data.research_report || {};
  const od = data.outreach_draft  || {};
  const m  = rr.metrics || {};

  document.getElementById('reportTitle').textContent =
    `Intelligence Report: ${rr.target_company || '—'}`;
  document.getElementById('reportMeta').textContent =
    `Quality score: ${((rr.quality_score || 0) * 100).toFixed(1)}%  ·  ` +
    `${rr.iteration_count || 0} retry loop(s)  ·  ` +
    `Generated ${rr.generated_at ? new Date(rr.generated_at).toLocaleString() : '—'}`;

  // Overview tab
  setOvBlock('ov-summary',     'Company Overview',       m.company_overview,         'text');
  setOvBlock('ov-pricing',     'Pricing Model',          m.pricing_model,            'text');
  setOvBlock('ov-audience',    'Target Audience',        m.target_audience,          'text');
  setOvBlock('ov-vps',         'Key Value Propositions', m.key_value_propositions,   'list');
  setOvBlock('ov-strengths',   'Strengths',              m.strengths,                'list');
  setOvBlock('ov-weaknesses',  'Weaknesses',             m.weaknesses,               'list');
  setOvBlock('ov-positioning', 'Market Positioning',     m.market_positioning,       'text');
  setOvBlock('ov-competitors', 'Competitors Mentioned',  m.competitors_mentioned,    'tags');

  const srcEl = document.getElementById('ov-sources');
  srcEl.innerHTML = `<h4>Source URLs</h4>` + (
    (m.source_urls || []).length
      ? (m.source_urls || []).map(u => `<a class="source-link" href="${esc(u)}" target="_blank">${esc(u)}</a>`).join('')
      : `<p class="missing">None recorded</p>`
  );

  // Outreach tab
  document.getElementById('emailContent').textContent = od.cold_outreach_email || '—';

  // Follow-ups tab
  const fuEl = document.getElementById('followupsContent');
  fuEl.innerHTML = '';
  (od.recommended_follow_ups || []).forEach((fu, i) => {
    const div = document.createElement('div');
    div.className = 'followup-item';
    const num = document.createElement('div');
    num.className = 'followup-num';
    num.textContent = `Follow-up ${i + 1}`;
    const body = document.createElement('div');
    body.textContent = fu;
    div.appendChild(num);
    div.appendChild(body);
    fuEl.appendChild(div);
  });

  // Raw JSON tab
  document.getElementById('rawJson').textContent = JSON.stringify(data, null, 2);

  // Export
  exportBtn.onclick = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${currentThreadId}.json`;
    a.click();
  };
}

function setOvBlock(id, label, value, type) {
  const el = document.getElementById(id);
  const isEmpty = !value || (Array.isArray(value) && value.length === 0);
  el.innerHTML = `<h4>${label}</h4>` + (
    isEmpty
      ? `<p class="missing">Not identified</p>`
      : type === 'list'
        ? `<ul>${value.map(v => `<li>${esc(v)}</li>`).join('')}</ul>`
        : type === 'tags'
          ? value.map(v => `<span class="tag">${esc(v)}</span>`).join('')
          : `<p>${esc(value)}</p>`
  );
}

// ── Tabs ─────────────────────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
  });
});

// ── Escape HTML ───────────────────────────────────────────────────────────────
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
