/* =========================================
   idin9-srs Frontend
   ========================================= */

const API_BASE = '/api/v1';

// ── API Key Management ──────────────────────
function getApiKey() {
  return localStorage.getItem('idin9_api_key') || '';
}

function setApiKey(key) {
  localStorage.setItem('idin9_api_key', key);
}

async function apiFetch(url, options = {}) {
  const headers = options.headers || {};
  const apiKey = getApiKey();
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
  }
  const res = await fetch(url, { ...options, headers });

  if (res.status === 403) {
    const key = prompt('API key required. Enter your API key:');
    if (key) {
      setApiKey(key);
      headers['X-API-Key'] = key;
      const retry = await fetch(url, { ...options, headers });
      if (retry.status === 403) {
        setApiKey('');
        alert('Invalid API key.');
        return retry;
      }
      return retry;
    }
  }

  return res;
}

// Check if auth is needed on load
(async function checkAuth() {
  try {
    const res = await fetch(`${API_BASE}/info`);
    if (res.ok) {
      const info = await res.json();
      if (info.auth_required && !getApiKey()) {
        const key = prompt('This server requires an API key. Please enter it:');
        if (key) setApiKey(key);
      }
    }
  } catch {}
})();

// ============ TAB SWITCHING ============
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

  if (tab === 'admin') loadAdminConfig();
  if (tab === 'auditor') searchRecordings();
  if (tab === 'console') initConsoleTab();
}

// ============ AUDITOR ============
async function searchRecordings() {
  const tbody = document.getElementById('results-body');
  tbody.innerHTML = '<tr><td colspan="6" class="empty-msg">Searching...</td></tr>';

  const params = new URLSearchParams();

  const startVal = document.getElementById('filter-start').value;
  const endVal = document.getElementById('filter-end').value;
  const callerVal = document.getElementById('filter-caller').value.trim();
  const calleeVal = document.getElementById('filter-callee').value.trim();
  const minSent = document.getElementById('filter-min-sent').value;
  const maxSent = document.getElementById('filter-max-sent').value;
  const limit = parseInt(document.getElementById('filter-limit').value) || 50;

  if (startVal) params.set('start_time_from', new Date(startVal).toISOString());
  if (endVal) params.set('start_time_to', new Date(endVal).toISOString());
  if (callerVal) params.set('caller', callerVal);
  if (calleeVal) params.set('callee', calleeVal);
  if (minSent) params.set('min_sentiment', minSent);
  if (maxSent) params.set('max_sentiment', maxSent);
  params.set('limit', String(limit));

  try {
    const res = await apiFetch(`${API_BASE}/recordings?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    renderResults(data);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-msg">Error: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderResults(recordings) {
  const tbody = document.getElementById('results-body');
  const statsBar = document.getElementById('stats-bar');

  if (!recordings || recordings.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-msg">No recordings found.</td></tr>';
    statsBar.innerHTML = '';
    return;
  }

  statsBar.innerHTML = `Found ${recordings.length} recording(s)`;

  tbody.innerHTML = recordings.map(r => {
    const score = r.sentiment_score || 1.0;
    const scoreClass = score >= 7 ? 'sentiment-high' : score >= 4 ? 'sentiment-mid' : 'sentiment-low';
    const dt = formatDateTime(r.end_time);
    const dur = formatDuration(r.duration);

    return `<tr>
      <td title="${r.end_time}">${dt}</td>
      <td>${escapeHtml(r.caller || '-')}</td>
      <td>${escapeHtml(r.callee || '-')}</td>
      <td>${dur}</td>
      <td><span class="sentiment-badge ${scoreClass}">${score.toFixed(1)}</span></td>
      <td class="actions-cell">
        <button class="btn btn-primary btn-sm" onclick="playAudio('${encodeURIComponent(r.session_id)}')">Play</button>
        <a href="${API_BASE}/recordings/${encodeURIComponent(r.session_id)}/audio" class="btn btn-secondary btn-sm" download>Export</a>
      </td>
    </tr>`;
  }).join('');
}

function resetFilters() {
  document.getElementById('filter-start').value = '';
  document.getElementById('filter-end').value = '';
  document.getElementById('filter-caller').value = '';
  document.getElementById('filter-callee').value = '';
  document.getElementById('filter-min-sent').value = '';
  document.getElementById('filter-max-sent').value = '';
  document.getElementById('filter-limit').value = '50';
  searchRecordings();
}

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
      info.innerHTML = `
        <strong>Transcript:</strong> ${escapeHtml(data.transcript || 'N/A')}<br>
        <strong>Sentiment:</strong> ${data.sentiment_score !== undefined ? data.sentiment_score.toFixed(1) + ' (' + (data.sentiment_label || '') + ')' : 'N/A'}
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

  try {
    const res = await apiFetch(`${API_BASE}/admin/settings`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const config = await res.json();
    populateAdminForm(config);
    loading.style.display = 'none';
    form.style.display = 'block';
  } catch (err) {
    loading.textContent = `Error loading config: ${err.message}`;
  }
}

function populateAdminForm(config) {
  const fields = [
    'sip_listen_host', 'sip_listen_port',
    'rtp_min_port', 'rtp_max_port',
    'api_key',
    'transcription_provider', 'transcription_api_key', 'transcription_api_url', 'transcription_api_model',
    'whisper_device', 'whisper_cache_dir',
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
}

async function saveSettings(event) {
  event.preventDefault();
  const statusEl = document.getElementById('save-status');
  statusEl.textContent = 'Saving...';
  statusEl.style.color = '#666';

  const mappingRaw = document.querySelector('[name="sentiment_mapping"]').value;
  let mappingParsed;
  try {
    mappingParsed = JSON.parse(mappingRaw);
    mappingParsed = JSON.stringify(mappingParsed);
  } catch {
    statusEl.textContent = 'Invalid JSON in sentiment mapping';
    statusEl.style.color = '#dc3545';
    return;
  }

  const payload = {
    api_key: document.querySelector('[name="api_key"]').value.trim(),
    transcription_provider: document.querySelector('[name="transcription_provider"]').value,
    transcription_api_key: document.querySelector('[name="transcription_api_key"]').value.trim(),
    transcription_api_url: document.querySelector('[name="transcription_api_url"]').value.trim(),
    transcription_api_model: document.querySelector('[name="transcription_api_model"]').value.trim(),
    whisper_model_size: document.querySelector('[name="whisper_model_size"]').value,
    whisper_device: document.querySelector('[name="whisper_device"]').value,
    whisper_cache_dir: document.querySelector('[name="whisper_cache_dir"]').value.trim(),
    sentiment_provider: document.querySelector('[name="sentiment_provider"]').value,
    sentiment_api_key: document.querySelector('[name="sentiment_api_key"]').value.trim(),
    sentiment_api_url: document.querySelector('[name="sentiment_api_url"]').value.trim(),
    sentiment_api_model: document.querySelector('[name="sentiment_api_model"]').value.trim(),
    sentiment_model: document.querySelector('[name="sentiment_model"]').value.trim(),
    sentiment_mapping: mappingParsed,
    hf_cache_dir: document.querySelector('[name="hf_cache_dir"]').value.trim(),
    transcription_enabled: document.querySelector('[name="transcription_enabled"]').checked,
    sentiment_enabled: document.querySelector('[name="sentiment_enabled"]').checked,
    retention_years: parseInt(document.querySelector('[name="retention_years"]').value) || 7,
    output_dir: document.querySelector('[name="output_dir"]').value,
    audio_format: document.querySelector('[name="audio_format"]').value,
    encryption_enabled: document.querySelector('[name="encryption_enabled"]').checked,
    encryption_password: document.querySelector('[name="encryption_password"]').value.trim(),
  };

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

// ============ UTILITY FUNCTIONS ============
function formatDateTime(isoStr) {
  if (!isoStr) return '-';
  try {
    const d = new Date(isoStr);
    return d.toLocaleString('en-US', {
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
        <td>${escapeHtml(s.session_id)}</td>
        <td>${escapeHtml(s.caller || '-')}</td>
        <td>${escapeHtml(s.callee || '-')}</td>
        <td>${escapeHtml(s.state)}</td>
        <td>${formatDateTime(s.start_time)}</td>
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
