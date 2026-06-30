/* =========================================
   idin9-srs Frontend
   ========================================= */

const API_BASE = '/api/v1';

// ── API Key Management ──────────────────────
let currentUserRole = null;
let currentOffset = 0;
const LIMIT = 50;

// ── Timezone (loaded from server config) ────
let displayTimezone = 'UTC';

// ── Session Idle Timeout ────────────────────
const SESSION_TIMEOUT_MS = 300000;
let sessionTimer = null;

function resetSessionTimer() {
  if (sessionTimer) clearTimeout(sessionTimer);
  sessionTimer = setTimeout(logout, SESSION_TIMEOUT_MS);
}

function startSessionWatchdog() {
  const events = ['click', 'keydown', 'mousemove', 'scroll', 'touchstart'];
  events.forEach(ev => document.addEventListener(ev, resetSessionTimer));
  resetSessionTimer();
}

function getAuthHeader() {
  const token = sessionStorage.getItem('idin9_auth_token');
  if (token) return `Bearer ${token}`;
  return null;
}

function getApiKey() {
  return sessionStorage.getItem('idin9_api_key') || '';
}

function setApiKey(key) {
  sessionStorage.setItem('idin9_api_key', key);
}

function setAuthToken(token) {
  sessionStorage.setItem('idin9_auth_token', token);
}

function logout() {
  if (sessionTimer) clearTimeout(sessionTimer);
  sessionStorage.removeItem('idin9_auth_token');
  sessionStorage.removeItem('idin9_api_key');
  document.getElementById('app-shell').style.display = 'none';
  document.getElementById('login-modal').style.display = 'flex';
  currentUserRole = null;
}

async function apiFetch(url, options = {}) {
  const headers = options.headers || {};
  
  const token = getAuthHeader();
  if (token) {
    headers['Authorization'] = token;
  }
  
  const apiKey = getApiKey();
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
  }
  
  const res = await fetch(url, { ...options, headers });

  if (res.status === 401) {
    logout();
    return;
  }
  if (res.status === 403) {
    throw new Error('Access denied');
  }

  return res;
}

// Check if auth is needed on load
(async function checkAuth() {
  let authRequired = true;
  try {
    const res = await fetch(`${API_BASE}/info`);
    if (res.ok) {
      const info = await res.json();
      
      if (info.font_family && info.font_family !== 'system') {
        document.body.style.fontFamily = info.font_family;
      }

      if (info.timezone) {
        displayTimezone = info.timezone;
      }

      if (info.auth_required !== undefined) {
        authRequired = info.auth_required;
      }
    }
  } catch {}

  if (!authRequired) {
    document.getElementById('app-shell').style.display = 'flex';
    document.getElementById('login-modal').style.display = 'none';
    return;
  }

  if (getAuthHeader() || getApiKey()) {
    await showApp();
  }
})();

async function showApp() {
  try {
    const meRes = await apiFetch(`${API_BASE}/auth/me`);
    if (meRes && meRes.ok) {
      const user = await meRes.json();
      currentUserRole = user.role;
      document.getElementById('app-shell').style.display = 'flex';
      document.getElementById('login-modal').style.display = 'none';
      startSessionWatchdog();
      applyRolePermissions();
      // Auto-load recordings so the Auditor pane isn't empty on login
      searchRecordings(0);
    } else {
      document.getElementById('app-shell').style.display = 'none';
      document.getElementById('login-modal').style.display = 'flex';
    }
  } catch {
    document.getElementById('app-shell').style.display = 'none';
    document.getElementById('login-modal').style.display = 'flex';
  }
}

function applyRolePermissions() {
  const adminBtn = document.querySelector('[data-tab="admin"]');
  if (currentUserRole === 'auditor') {
    // Hide Admin tab (Utility is now a sub-tab of Admin)
    if (adminBtn) adminBtn.style.display = 'none';
    if (document.querySelector('.tab-btn.active').dataset.tab !== 'auditor') {
      switchTab('auditor');
    }
  } else {
    if (adminBtn) adminBtn.style.display = 'block';
  }
}

async function handleLogin(e) {
  e.preventDefault();
  const username = document.getElementById('login-username').value;
  const password = document.getElementById('login-password').value;
  const errorEl = document.getElementById('login-error');
  
  try {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    
    if (res.ok) {
      const data = await res.json();
      setAuthToken(data.access_token);
      await showApp();
    } else {
      errorEl.style.display = 'block';
      if (res.status === 400) {
          const errData = await res.json();
          errorEl.textContent = errData.detail;
      } else {
          errorEl.textContent = 'Invalid credentials';
      }
    }
  } catch (err) {
    errorEl.style.display = 'block';
    errorEl.textContent = 'Connection error';
  }
}

// ============ TAB SWITCHING ============
function toggleLocalConfig(providerName, configId) {
  const select = document.querySelector(`[name="${providerName}"]`);
  const configDiv = document.getElementById(configId);
  if (select && configDiv) {
    configDiv.style.display = select.value === 'local' ? 'block' : 'none';
  }
}

function toggleCardEnabled(cardBodyId, enabled) {
  const cardBody = document.getElementById(cardBodyId);
  if (!cardBody) return;
  if (enabled) {
    cardBody.classList.remove('card-body-disabled');
  } else {
    cardBody.classList.add('card-body-disabled');
  }
}

function switchTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.remove('active', 'text-white', 'bg-primary');
    b.classList.add('link-dark');
  });
  document.querySelectorAll('.tab-content').forEach(c => {
    c.style.display = 'none';
  });

  const activeBtn = document.querySelector(`.tab-btn[data-tab="${tab}"]`);
  if (activeBtn) {
    activeBtn.classList.add('active', 'text-white', 'bg-primary');
    activeBtn.classList.remove('link-dark');
  }
  
  const activeTab = document.getElementById(`tab-${tab}`);
  if (activeTab) {
    activeTab.style.display = 'block';
  }

  if (tab === 'admin') {
    switchAdminSubTab('settings');
  }
  if (tab === 'auditor') searchRecordings(0);
}

function switchAdminSubTab(subTab) {
  document.querySelectorAll('#tab-admin .nav-link').forEach(b => b.classList.remove('active'));
  document.getElementById(`btn-sub-${subTab}`).classList.add('active');
  
  document.querySelectorAll('.admin-sub-content').forEach(c => c.style.display = 'none');
  document.getElementById(`sub-admin-${subTab}`).style.display = 'block';
  
  if (subTab === 'settings') loadAdminConfig();
  if (subTab === 'users') loadUsers();
  if (subTab === 'console') initConsoleTab();
}

// ============ AUDITOR ============
async function searchRecordings(offset = 0) {
  currentOffset = offset;
  const tbody = document.getElementById('results-body');
  tbody.innerHTML = '<tr><td colspan="8" class="empty-msg">Searching...</td></tr>';

  const params = new URLSearchParams();

  let startVal = document.getElementById('filter-start').value;
  const endVal = document.getElementById('filter-end').value;
  
  // Default to 7 days if empty and initial load
  if (!startVal && !endVal) {
      const d = new Date();
      d.setDate(d.getDate() - 7);
      // Format to YYYY-MM-DDTHH:mm:ss for input
      startVal = d.toISOString().slice(0,19);
      document.getElementById('filter-start').value = startVal;
  }

  const queryVal = document.getElementById('filter-query').value.trim();
  const minSent = document.getElementById('filter-min-sent').value;
  const maxSent = document.getElementById('filter-max-sent').value;
  const limitVal = parseInt(document.getElementById('filter-limit').value) || LIMIT;

  if (startVal) params.set('start_time_from', new Date(startVal).toISOString());
  if (endVal) params.set('start_time_to', new Date(endVal).toISOString());
  if (queryVal) params.set('query', queryVal);
  if (minSent) params.set('min_sentiment', minSent);
  if (maxSent) params.set('max_sentiment', maxSent);
  params.set('limit', String(limitVal));
  params.set('offset', String(currentOffset));

  try {
    const res = await apiFetch(`${API_BASE}/recordings?${params}`);
    if (!res || !res.ok) throw new Error(`HTTP ${res?.status || 'Unknown'}`);

    const data = await res.json();
    renderResults(data.recordings);
    renderPagination(data.total_count, limitVal, currentOffset);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-msg">Error: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderPagination(total, limit, offset) {
  const info = document.getElementById('pagination-info');
  const controls = document.getElementById('pagination-controls');
  
  if (total === 0) {
    info.textContent = 'Showing 0 of 0';
    controls.innerHTML = '';
    return;
  }
  
  const start = offset + 1;
  const end = Math.min(offset + limit, total);
  info.textContent = `Showing ${start}-${end} of ${total}`;
  
  const totalPages = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;
  
  let html = '';
  
  // Prev button
  html += `<button class="btn btn-outline-secondary btn-sm" ${currentPage === 1 ? 'disabled' : ''} onclick="searchRecordings(${(currentPage - 2) * limit})">&laquo;</button>`;
  
  // Page numbers
  for (let i = 1; i <= totalPages; i++) {
    // Smart display logic (show first, last, and +-2 from current)
    if (i === 1 || i === totalPages || (i >= currentPage - 2 && i <= currentPage + 2)) {
      html += `<button class="btn ${i === currentPage ? 'btn-primary' : 'btn-outline-secondary'} btn-sm" onclick="searchRecordings(${(i - 1) * limit})">${i}</button>`;
    } else if (i === currentPage - 3 || i === currentPage + 3) {
      html += `<button class="btn btn-outline-secondary btn-sm" disabled>...</button>`;
    }
  }
  
  // Next button
  html += `<button class="btn btn-outline-secondary btn-sm" ${currentPage === totalPages ? 'disabled' : ''} onclick="searchRecordings(${currentPage * limit})">&raquo;</button>`;
  
  controls.innerHTML = html;
}

function renderResults(recordings) {
  const tbody = document.getElementById('results-body');
  const statsBar = document.getElementById('stats-bar');

  if (!recordings || recordings.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-msg">No recordings found.</td></tr>';
    statsBar.innerHTML = '';
    return;
  }

  statsBar.innerHTML = `Found ${recordings.length} recording(s)`;

  tbody.innerHTML = recordings.map(r => {
    const score = r.sentiment_score || 1.0;
    const label = (r.sentiment_label || 'neutral').toLowerCase();
    const sentStyle = sentimentColor(label, score);
    const badWordPct = r.bad_word_percentage || 0.0;
    const dt = formatDateTime(r.end_time);
    const dur = formatDuration(r.duration);

    const hasTranscript = r.transcript && r.transcript.length > 0 && r.transcript !== '[transcription disabled]' && r.transcript !== '[transcription failed]';
    const needsGen = !hasTranscript || score === 1.0;
    // Show Gen button only when transcript or sentiment is missing (Issue 6)
    const genBtn = needsGen
      ? `<button class="btn btn-info btn-sm gen-btn" data-session="${encodeURIComponent(r.session_id)}" onclick="generateSingle(this.dataset.session)"><i class="bi bi-magic"></i> Gen</button>`
      : '';

    // XML metadata column (Issue 7) — show truncated icon if XML exists
    const xmlCell = r.xml_metadata
      ? `<span class="badge bg-secondary" title="${escapeAttr(r.xml_metadata.substring(0, 200))}"><i class="bi bi-file-code"></i></span>`
      : '<span class="text-muted">-</span>';

    const transcriptCell = hasTranscript 
      ? `<button class="btn btn-outline-secondary btn-sm" onclick="showTranscript('${encodeURIComponent(r.session_id)}')"><i class="bi bi-file-text"></i> View</button>`
      : '<span class="text-muted">-</span>';

    return `<tr>
      <td title="${escapeAttr(r.end_time)}">${dt}</td>
      <td>${escapeHtml(r.caller || '-')}</td>
      <td>${escapeHtml(r.callee || '-')}</td>
      <td>${xmlCell}</td>
      <td>${dur}</td>
      <td>
        <span class="sentiment-badge" style="${sentStyle}" title="Sentiment: ${escapeAttr(label)} (${score.toFixed(1)})">${escapeHtml(label)} ${score.toFixed(1)}</span>
        ${badWordPct > 0 ? `<span class="badword-badge" title="Bad words: ${badWordPct}% of transcript"><i class="bi bi-emoji-frown"></i>${badWordPct.toFixed(1)}%</span>` : ''}
      </td>
      <td>${transcriptCell}</td>
      <td class="actions-cell">
        <button class="btn btn-primary btn-sm" data-sid="${encodeURIComponent(r.session_id)}" onclick="playAudio(this.dataset.sid)">Play</button>
        <a href="${API_BASE}/recordings/${encodeURIComponent(r.session_id)}/audio" class="btn btn-secondary btn-sm" download>Export</a>
        ${genBtn}
      </td>
    </tr>`;
  }).join('');
}

function resetFilters() {
  document.getElementById('filter-start').value = '';
  document.getElementById('filter-end').value = '';
  document.getElementById('filter-query').value = '';
  document.getElementById('filter-min-sent').value = '';
  document.getElementById('filter-max-sent').value = '';
  document.getElementById('filter-limit').value = '50';
  searchRecordings(0);
}

// ============ TRANSCRIPT VIEWER ============
async function showTranscript(sessionId) {
  const modal = document.getElementById('transcript-modal');
  const content = document.getElementById('transcript-content');
  const title = document.getElementById('transcript-modal-title');

  title.textContent = `Session: ${sessionId}`;
  content.textContent = 'Loading transcript...';
  modal.style.display = 'flex';

  try {
    const res = await apiFetch(`${API_BASE}/record/${sessionId}`);
    if (res.ok) {
      const data = await res.json();
      content.textContent = data.transcript || '(no transcript)';
    } else {
      content.textContent = `Error: HTTP ${res.status}`;
    }
  } catch (err) {
    content.textContent = `Error: ${err.message}`;
  }
}

function closeTranscriptModal() {
  document.getElementById('transcript-modal').style.display = 'none';
}

// Close transcript modal on backdrop click
document.addEventListener('click', function(e) {
  const modal = document.getElementById('transcript-modal');
  if (e.target === modal) closeTranscriptModal();
});

// ============ AUDIO PLAYER ============
async function playAudio(sessionId) {
  const player = document.getElementById('audio-player');
  const modal = document.getElementById('audio-modal');
  const title = document.getElementById('audio-modal-title');
  const info = document.getElementById('audio-info');
  const downloadLink = document.getElementById('audio-download-link');

  title.textContent = `Session: ${sessionId}`;
  info.textContent = 'Loading audio...';
  modal.style.display = 'flex';

  const audioUrl = `${API_BASE}/recordings/${sessionId}/audio`;

  // Fetch with auth headers for the audio player
  const apiKey = getApiKey();
  if (apiKey) {
    player.src = audioUrl;
    // Set auth header via fetch + blob for audio
    try {
      const res = await apiFetch(audioUrl);
      if (res.ok) {
        const blob = await res.blob();
        player.src = URL.createObjectURL(blob);
      }
    } catch {}
  } else {
    player.src = audioUrl;
  }
  player.load();

  downloadLink.href = audioUrl;
  downloadLink.download = `${sessionId}.wav`;

  // Fetch session details
  try {
    const res = await apiFetch(`${API_BASE}/record/${sessionId}`);
    if (res.ok) {
      const data = await res.json();
      const sentLabel = (data.sentiment_label || 'neutral').toLowerCase();
      const sentScoreNum = data.sentiment_score !== undefined ? data.sentiment_score : 1.0;
      const sentScore = sentScoreNum.toFixed(1);
      const sentStyle = sentimentColor(sentLabel, sentScoreNum);
      const badWordInfo = data.bad_word_percentage !== undefined && data.bad_word_percentage > 0
        ? `<br><strong>Bad Words:</strong> ${data.bad_word_percentage.toFixed(1)}%`
        : '';
      info.innerHTML = `
        <strong>Transcript:</strong> ${escapeHtml(data.transcript || 'N/A')}<br>
        <strong>Sentiment:</strong> <span class="sentiment-badge" style="${sentStyle}">${escapeHtml(sentLabel)} ${sentScore}</span>${badWordInfo}
      `;
    }
  } catch {}
}

function closeAudioModal() {
  const player = document.getElementById('audio-player');
  player.pause();
  player.src = '';
  document.getElementById('audio-modal').style.display = 'none';
}

// Close modal on backdrop click
document.addEventListener('click', function(e) {
  const modal = document.getElementById('audio-modal');
  if (e.target === modal) closeAudioModal();
});

// ============ ADMIN ============
async function loadAdminConfig() {
  const form = document.getElementById('admin-form');
  const loading = document.getElementById('admin-loading');

  form.style.display = 'none';
  loading.style.display = 'block';
  loading.innerHTML = '<div class="spinner-border text-primary mb-2" role="status"></div><div>Loading configuration parameters...</div>';

  try {
    const res = await apiFetch(`${API_BASE}/admin/settings`);
    if (!res || !res.ok) throw new Error(`HTTP ${res?.status || 'Unknown'}`);

    const config = await res.json();
    populateAdminForm(config);
    loading.style.display = 'none';
    form.style.display = 'block';
  } catch (err) {
    loading.style.display = 'block';
    loading.innerHTML = `<div class="text-danger"><i class="bi bi-exclamation-triangle me-2"></i>Error loading config: ${escapeHtml(err.message)}</div><div class="mt-2"><button class="btn btn-sm btn-outline-danger" onclick="loadAdminConfig()">Retry</button></div>`;
  }
}

function populateAdminForm(config) {
  const fields = [
    'sip_listen_host', 'sip_listen_port',
    'rtp_min_port', 'rtp_max_port',
    'session_timeout_seconds',
    'api_key', 'auth_mode', 'jwt_secret', 'timezone', 'locale', 'font_family',
    'transcription_provider', 'transcription_api_key', 'transcription_api_url', 'transcription_api_model',
    'whisper_device', 'whisper_cache_dir', 'whisper_compute_type', 'whisper_language',
    'sentiment_provider', 'sentiment_api_key', 'sentiment_api_url', 'sentiment_api_model',
    'sentiment_model', 'hf_cache_dir',
    'output_dir', 'index_db', 'retention_years',
    'transcription_enabled', 'sentiment_enabled',
    'audio_format', 'encryption_enabled', 'encryption_password',
  ];

  fields.forEach(name => {
    const el = document.querySelector(`[name="${name}"]`);
    if (el && config[name] !== undefined) {
      if (el.type === 'checkbox') {
        el.checked = Boolean(config[name]);
      } else {
        el.value = String(config[name]);
      }
    }
  });

  const modelEl = document.querySelector('[name="whisper_model_size"]');
  if (modelEl && config.whisper_model_size) modelEl.value = config.whisper_model_size;

  const mappingEl = document.querySelector('[name="sentiment_mapping"]');
  if (mappingEl && config.sentiment_mapping) {
    try {
      const parsed = JSON.parse(config.sentiment_mapping);
      mappingEl.value = JSON.stringify(parsed, null, 2);
    } catch {
      mappingEl.value = config.sentiment_mapping;
    }
  }

  // Trigger conditional display for local config sections (Issue 4)
  toggleLocalConfig('transcription_provider', 'transcription-local-config');
  toggleLocalConfig('sentiment_provider', 'sentiment-local-config');

  // Update timezone from config so date display reflects current setting
  const tzEl = document.querySelector('[name="timezone"]');
  if (tzEl && tzEl.value) {
    displayTimezone = tzEl.value;
  }

  // Trigger gray-out for disabled AI cards (Issue 5)
  toggleCardEnabled('transcription-card-body',
    document.querySelector('[name="transcription_enabled"]').checked);
  toggleCardEnabled('sentiment-card-body',
    document.querySelector('[name="sentiment_enabled"]').checked);
}

async function saveSettings(event) {
  event.preventDefault();
  const statusEl = document.getElementById('save-status');
  statusEl.textContent = 'Saving...';
  statusEl.style.color = '#666';

  const mappingRaw = document.querySelector('[name="sentiment_mapping"]').value.trim();
  let mappingParsed;
  if (!mappingRaw) {
    mappingParsed = '{}';
  } else {
    try {
      mappingParsed = JSON.parse(mappingRaw);
      mappingParsed = JSON.stringify(mappingParsed);
    } catch {
      statusEl.textContent = 'Invalid JSON in sentiment mapping';
      statusEl.style.color = '#dc3545';
      return;
    }
  }

  const MASKED = '********';

  const getVal = (name) => {
    const el = document.querySelector(`[name="${name}"]`);
    if (!el) return undefined;
    if (el.type === 'checkbox') return el.checked;
    const val = el.value.trim();
    return val === MASKED ? undefined : val;
  };

  const payload = {
    sip_listen_host: getVal('sip_listen_host'),
    sip_listen_port: getVal('sip_listen_port'),
    rtp_min_port: getVal('rtp_min_port'),
    rtp_max_port: getVal('rtp_max_port'),
    session_timeout_seconds: parseInt(getVal('session_timeout_seconds')) || 0,
    api_key: getVal('api_key'),
    auth_mode: getVal('auth_mode'),
    jwt_secret: getVal('jwt_secret') || undefined,
    timezone: getVal('timezone'),
    locale: getVal('locale'),
    font_family: getVal('font_family'),
    transcription_provider: getVal('transcription_provider'),
    transcription_api_key: getVal('transcription_api_key'),
    transcription_api_url: getVal('transcription_api_url'),
    transcription_api_model: getVal('transcription_api_model'),
    whisper_model_size: getVal('whisper_model_size'),
    whisper_device: getVal('whisper_device'),
    whisper_cache_dir: getVal('whisper_cache_dir'),
    whisper_compute_type: getVal('whisper_compute_type'),
    whisper_language: getVal('whisper_language'),
    sentiment_provider: getVal('sentiment_provider'),
    sentiment_api_key: getVal('sentiment_api_key'),
    sentiment_api_url: getVal('sentiment_api_url'),
    sentiment_api_model: getVal('sentiment_api_model'),
    sentiment_model: getVal('sentiment_model'),
    sentiment_mapping: mappingParsed,
    hf_cache_dir: getVal('hf_cache_dir'),
    transcription_enabled: getVal('transcription_enabled'),
    sentiment_enabled: getVal('sentiment_enabled'),
    retention_years: parseInt(getVal('retention_years')) || 7,
    output_dir: getVal('output_dir'),
    index_db: getVal('index_db'),
    audio_format: getVal('audio_format'),
    encryption_enabled: getVal('encryption_enabled'),
    encryption_password: getVal('encryption_password') || undefined,
  };

  // Strip undefined fields so masked/empty secrets aren't overwritten
  Object.keys(payload).forEach(k => payload[k] === undefined && delete payload[k]);

  try {
    const res = await apiFetch(`${API_BASE}/admin/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res.status}`);
    }

    statusEl.textContent = 'Configuration saved successfully. Some changes may require a server restart.';
    statusEl.style.color = '#28a745';

    // Update display timezone immediately without requiring reload
    if (payload.timezone) {
      displayTimezone = payload.timezone;
    }
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    statusEl.style.color = '#dc3545';
  }
}

async function triggerCleanup() {
  const statusEl = document.getElementById('cleanup-status');
  statusEl.textContent = 'Running cleanup...';
  statusEl.style.color = '#666';

  try {
    const res = await apiFetch(`${API_BASE}/maintenance/cleanup`, { method: 'POST' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    statusEl.textContent = `Cleanup complete: ${data.deleted_recordings} recording(s) deleted (retention: ${data.retention_years} years)`;
    statusEl.style.color = '#28a745';
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    statusEl.style.color = '#dc3545';
  }
}

async function exportSipPcap() {
  const statusEl = document.getElementById('pcap-status');
  statusEl.textContent = 'Preparing pcap export...';
  statusEl.style.color = '#666';

  try {
    const res = await apiFetch(`${API_BASE}/maintenance/sip-pcap`);
    if (!res || !res.ok) {
      const errData = await res?.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res?.status || 'Unknown'}`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'sip_capture.pcap';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    statusEl.textContent = 'PCAP exported successfully. Open with Wireshark.';
    statusEl.style.color = '#28a745';
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    statusEl.style.color = '#dc3545';
  }
}

// ============ USER MANAGEMENT ============
async function loadUsers() {
  const tbody = document.getElementById('users-table-body');
  try {
    const res = await apiFetch(`${API_BASE}/admin/users`);
    if (!res || !res.ok) throw new Error(`HTTP ${res?.status || 'Unknown'}`);
    
    const users = await res.json();
    if (users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted">No users found</td></tr>';
      return;
    }
    
    tbody.innerHTML = users.map(u => {
      const isRoot = u.username === 'root';
      const roleBadgeClass = u.role === 'admin' ? 'bg-danger' : 'bg-primary';
      
      let actions = '';
      if (!isRoot) {
        actions = `
          <button class="btn btn-sm btn-outline-danger" onclick="deleteUser('${escapeHtml(u.username)}')">Delete</button>
        `;
      }
      
      return `<tr>
        <td class="fw-semibold">${escapeHtml(u.username)}</td>
        <td><span class="badge ${roleBadgeClass}">${escapeHtml(u.role)}</span></td>
        <td class="text-end px-3">${actions}</td>
      </tr>`;
    }).join('');
    
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="3" class="text-center text-danger">Error: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function showAddUserModal() {
  document.getElementById('add-user-modal').style.display = 'flex';
  document.getElementById('add-user-error').style.display = 'none';
  document.getElementById('add-user-form').reset();
}

function closeAddUserModal() {
  document.getElementById('add-user-modal').style.display = 'none';
}

async function submitAddUser(e) {
  e.preventDefault();
  const errorEl = document.getElementById('add-user-error');
  const btn = e.target.querySelector('button[type="submit"]');
  
  const payload = {
    username: document.getElementById('new-username').value.trim(),
    password: document.getElementById('new-password').value,
    role: document.getElementById('new-role').value
  };
  
  try {
    btn.disabled = true;
    const res = await apiFetch(`${API_BASE}/admin/users`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    
    if (!res || !res.ok) {
      const errData = await res?.json().catch(() => ({}));
      throw new Error(errData.detail || 'Failed to create user');
    }
    
    closeAddUserModal();
    loadUsers();
  } catch (err) {
    errorEl.style.display = 'block';
    errorEl.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

async function deleteUser(username) {
  if (!confirm(`Are you sure you want to delete user '${username}'?`)) return;
  
  try {
    const res = await apiFetch(`${API_BASE}/admin/users/${username}`, { method: 'DELETE' });
    if (!res || !res.ok) throw new Error('Failed to delete user');
    loadUsers();
  } catch (err) {
    alert(err.message);
  }
}

async function generateSingle(sessionId) {
  // Find the button and show loading state
  const btn = document.querySelector(`.gen-btn[data-session="${encodeURIComponent(sessionId)}"]`);
  if (!btn) return;
  
  const originalHTML = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  
  try {
    const res = await apiFetch(`${API_BASE}/recordings/${sessionId}/generate`, {
      method: 'POST',
    });
    
    if (!res || !res.ok) {
      const errData = await res?.json().catch(() => ({}));
      throw new Error(errData.detail || 'Failed to generate');
    }
    
    const data = await res.json();
    btn.innerHTML = '<i class="bi bi-check-lg"></i>';
    btn.classList.remove('btn-info');
    btn.classList.add('btn-success');
    
    setTimeout(() => {
      btn.innerHTML = originalHTML;
      btn.classList.remove('btn-success');
      btn.classList.add('btn-info');
      btn.disabled = false;
    }, 2000);
    
    // Refresh the results to show updated data
    searchRecordings(currentOffset);
  } catch (err) {
    btn.innerHTML = originalHTML;
    btn.disabled = false;
    alert(`Generation failed: ${err.message}`);
  }
}

// ============ UTILITY FUNCTIONS ============

// Color psychology mapping: emotion → HSL hue + saturation
// Based on color psychology guidelines (verywellmind.com/color-psychology-2795824)
//   Red    (0°)   = anger, frustration, hostility, negative
//   Orange (30°)  = surprise, excitement, agitation
//   Yellow (50°)  = joy, happiness, optimism
//   Green  (120°) = positive, calm, growth, balance
//   Blue   (210°) = sadness, calm, serenity
//   Purple (270°) = fear, anxiety
//   Olive  (60°)  = disgust, contempt
//   Teal/Slate = neutral, apathy
const SENTIMENT_HUE_MAP = {
  anger:       { h: 0,   s: 75 },
  negative:    { h: 0,   s: 75 },
  frustration: { h: 10,  s: 70 },
  hostility:   { h: 0,   s: 80 },
  disgust:     { h: 60,  s: 55 },
  contempt:    { h: 60,  s: 55 },
  fear:        { h: 270, s: 65 },
  anxiety:     { h: 270, s: 60 },
  sadness:     { h: 210, s: 65 },
  surprise:    { h: 30,  s: 80 },
  joy:         { h: 50,  s: 85 },
  happiness:   { h: 50,  s: 85 },
  positive:    { h: 120, s: 60 },
  neutral:     { h: 200, s: 30 },
};

function sentimentColor(label, score) {
  const key = (label || 'neutral').toLowerCase().trim();
  const cfg = SENTIMENT_HUE_MAP[key] || SENTIMENT_HUE_MAP['neutral'];
  // Map score 1-10 to lightness 85%-50%: mild emotion = lighter, intense = bolder, avoiding black
  const lightness = 85 - ((score - 1) / 9) * 35;
  const bg = `hsl(${cfg.h}, ${cfg.s}%, ${lightness.toFixed(0)}%)`;
  // Use dark text on light backgrounds, white text on dark backgrounds
  const textColor = lightness > 65 ? '#212529' : '#ffffff';
  return `background-color: ${bg}; color: ${textColor};`;
}

function formatDateTime(isoStr) {
  if (!isoStr) return '-';
  try {
    // Ensure UTC format to prevent browser from shifting via local time assumption
    const parsedStr = isoStr.endsWith('Z') ? isoStr : isoStr + 'Z';
    const d = new Date(parsedStr);
    return d.toLocaleString('en-US', {
      timeZone: displayTimezone,
      year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
  } catch { return isoStr; }
}

function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return '-';
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ============ LIVE CONSOLE ============
let logsInterval = null;

function initConsoleTab() {
  fetchLiveSessions();
  fetchLiveLogs();
  if (document.getElementById('auto-refresh-logs').checked) {
    startLogsPolling();
  }
}

async function fetchLiveSessions() {
  const tbody = document.getElementById('live-sessions-body');
  try {
    const res = await apiFetch(`${API_BASE}/sessions`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const sessions = await res.json();
    
    if (sessions.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-msg">No active sessions</td></tr>';
      return;
    }
    
    tbody.innerHTML = sessions.map(s => {
      return `<tr>
        <td title="${escapeAttr(s.start_time)}">${formatDateTime(s.start_time)}</td>
        <td>${escapeHtml(s.session_id)}</td>
        <td>${escapeHtml(s.caller || '-')}</td>
        <td>${escapeHtml(s.callee || '-')}</td>
        <td>${escapeHtml(s.state)}</td>
      </tr>`;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty-msg">Error: ${escapeHtml(err.message)}</td></tr>`;
  }
}

async function fetchLiveLogs() {
  const container = document.getElementById('live-logs-container');
  try {
    const res = await apiFetch(`${API_BASE}/logs`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.logs && data.logs.length > 0) {
      container.textContent = data.logs.join('\n');
    } else {
      container.textContent = 'No logs available yet...';
    }
    // Auto-scroll to bottom
    container.scrollTop = container.scrollHeight;
  } catch (err) {
    container.textContent = `Error fetching logs: ${err.message}`;
  }
}

function startLogsPolling() {
  if (logsInterval) clearInterval(logsInterval);
  logsInterval = setInterval(() => {
    fetchLiveSessions();
    fetchLiveLogs();
  }, 2000); // refresh every 2 seconds
}

function stopLogsPolling() {
  if (logsInterval) {
    clearInterval(logsInterval);
    logsInterval = null;
  }
}

function toggleLogRefresh() {
  const isChecked = document.getElementById('auto-refresh-logs').checked;
  if (isChecked) {
    startLogsPolling();
  } else {
    stopLogsPolling();
  }
}

// ============ BATCH GENERATE ============
async function batchGenerate() {
  const statusEl = document.getElementById('batch-status');
  const progressEl = document.getElementById('batch-progress');
  const progressBar = document.getElementById('batch-progress-bar');
  const progressText = document.getElementById('batch-progress-text');
  
  statusEl.textContent = 'Starting batch generation...';
  statusEl.style.color = '#666';
  progressEl.style.display = 'block';
  progressBar.style.width = '0%';
  progressBar.textContent = '0%';
  progressText.textContent = 'Analyzing recordings...';
  
  try {
    const res = await apiFetch(`${API_BASE}/maintenance/batch-generate`, {
      method: 'POST',
    });
    
    if (!res || !res.ok) {
      const errData = await res?.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${res?.status || 'Unknown'}`);
    }
    
    const data = await res.json();
    
    progressBar.style.width = '100%';
    progressBar.textContent = '100%';
    progressText.textContent = data.message;
    statusEl.textContent = 'Complete!';
    statusEl.style.color = '#28a745';
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    statusEl.style.color = '#dc3545';
    progressText.textContent = 'Generation failed.';
  }
}
