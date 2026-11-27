// State management
const state = {
  queue: [], // { id, path, name, ext, size, category, format, formatLabel, mismatch, supported, targetFormat, status, duration, error }
  history: [],
  outputFolder: null,
  isConverting: false,
  progress: null, // { current, total } pendant une conversion
  notice: null // { text, tone } : retour visible de la dernière action
};

// Formats de sortie proposés par catégorie
const IMAGE_TARGETS = [
  { val: 'webp', name: 'WEBP' },
  { val: 'png', name: 'PNG' },
  { val: 'jpg', name: 'JPG' },
  { val: 'jfif', name: 'JFIF' },
  { val: 'jxl', name: 'JXL' },
  { val: 'ico', name: 'ICO' },
  { val: 'gif', name: 'GIF' },
  { val: 'bmp', name: 'BMP' }
];

// Formats d'entrée image que le moteur sait lire (format_detector, supported=True).
const IMAGE_SOURCES = ['png', 'jpeg', 'jfif', 'webp', 'gif', 'bmp', 'ico', 'tiff', 'svg', 'heic', 'jxl'];

const DOCUMENT_TARGET_NAMES = {
  pdf: 'PDF',
  png: 'PNG (Image)',
  jpg: 'JPG (Image)',
  html: 'HTML',
  txt: 'TXT',
  md: 'Markdown'
};

// Sorties réellement produites par le moteur pour chaque document, d'après
// DocumentConverter.OUTPUTS_BY_SOURCE (src/backend/converters/document_converter.py).
// tests/test_ux_options_par_format.py croise cette table avec le moteur réel :
// une sortie proposée qui échouerait fait échouer le test.
const DOCUMENT_TARGETS_BY_FORMAT = {
  pdf: ['png', 'jpg', 'txt', 'md', 'html'],
  docx: ['pdf', 'html', 'txt', 'md'],
  md: ['pdf', 'html', 'txt'],
  html: ['pdf', 'txt'],
  txt: ['pdf', 'html', 'md']
};

// DOM Elements
const dropzone = document.getElementById('dropzone');
const btnSelectFiles = document.getElementById('btn-select-files');
const fileQueueEl = document.getElementById('file-queue');
const fileCountEl = document.getElementById('file-count');
const emptyStateEl = document.getElementById('empty-state');
const btnClearQueue = document.getElementById('btn-clear-queue');

const globalFormatSelect = document.getElementById('global-format-select');
const outputFolderPathInput = document.getElementById('output-folder-path');
const btnBrowseFolder = document.getElementById('btn-browse-folder');

const optQuality = document.getElementById('opt-quality');
const optQualityVal = document.getElementById('opt-quality-val');
const optWidth = document.getElementById('opt-width');
const optHeight = document.getElementById('opt-height');
const optKeepAspect = document.getElementById('opt-keep-aspect');
const optDpi = document.getElementById('opt-dpi');
const optDpiVal = document.getElementById('opt-dpi-val');

const btnConvertAll = document.getElementById('btn-convert-all');
const historyListEl = document.getElementById('history-list');
const emptyHistoryEl = document.getElementById('empty-history');
const btnClearHistory = document.getElementById('btn-clear-history');
const statusNoticeEl = document.getElementById('status-notice');

const BRIDGE_MISSING = "Aperçu navigateur : l'ajout et la conversion de fichiers fonctionnent seulement dans l'application. Ouvrez File Transformer depuis son lanceur.";
const UNEXPECTED_ERROR = "Erreur inattendue de l'application pendant la conversion. Réessayez ; si le problème continue, relancez File Transformer.";

// Wait for PyWebView API or initialization
document.addEventListener('DOMContentLoaded', () => {
  initEventListeners();
  renderQueue();
});

// Appelé depuis Python lors d'un glisser-déposer : les fichiers ont déjà été
// analysés côté backend (chemin réel + format détecté par signature).
// Accepte la liste seule (ancien format) ou { files, ignored }.
window.onNativeFilesDropped = function (payload) {
  dropzone.classList.remove('dragover');
  receiveFiles(payload);
};

// Retour visible de la dernière action (zone d'état, lue par les lecteurs d'écran).
function showNotice(text, tone = 'info') {
  state.notice = text ? { text: String(text), tone } : null;
  renderNotice();
}

function renderNotice() {
  const notice = state.notice;
  statusNoticeEl.textContent = notice ? notice.text : '';
  statusNoticeEl.hidden = !notice;
  statusNoticeEl.className = 'status-notice' + (notice && notice.tone === 'error' ? ' is-error' : '');
}

function plural(count, singular, pluralForm) {
  return `${count} ${count > 1 ? (pluralForm || singular + 's') : singular}`;
}

const IGNORED_REASONS = {
  folder: 'les dossiers ne sont pas pris en charge',
  shortcut: 'les raccourcis ne sont pas pris en charge',
  reserved: 'nom réservé par Windows',
  missing: 'fichier introuvable',
  invalid: "ce n'est pas un fichier lisible"
};

function describeIgnored(ignored) {
  const groups = [];
  ignored.forEach(entry => {
    const reason = Object.prototype.hasOwnProperty.call(IGNORED_REASONS, entry && entry.reason)
      ? IGNORED_REASONS[entry.reason] : IGNORED_REASONS.invalid;
    let group = groups.find(g => g.reason === reason);
    if (!group) { group = { reason, names: [] }; groups.push(group); }
    group.names.push(String((entry && entry.name) || 'sans nom'));
  });
  const names = list => list.length > 3 ? `${list.slice(0, 3).join(', ')}…` : list.join(', ');
  const head = plural(ignored.length, 'élément ignoré', 'éléments ignorés');
  if (groups.length === 1) return `${head} (${names(groups[0].names)}) : ${groups[0].reason}.`;
  return `${head} : ${groups.map(g => `${names(g.names)} (${g.reason})`).join(' ; ')}.`;
}

// Point d'entrée commun du sélecteur et du glisser-déposer.
function receiveFiles(payload) {
  const files = Array.isArray(payload) ? payload : ((payload && payload.files) || []);
  const ignored = Array.isArray(payload) ? [] : ((payload && payload.ignored) || []);
  const { duplicates } = addFilesToQueue(files);
  const parts = [];
  if (ignored.length) parts.push(describeIgnored(ignored));
  if (duplicates) parts.push(`${plural(duplicates, 'fichier')} déjà dans la liste.`);
  showNotice(parts.join(' '), ignored.length ? 'error' : 'info');
}

async function selectFilesFromDialog() {
  if (!(window.pywebview && window.pywebview.api)) {
    showNotice(BRIDGE_MISSING, 'error');
    return;
  }
  receiveFiles(await window.pywebview.api.select_files());
}

function initEventListeners() {
  // Range sliders live value update
  optQuality.addEventListener('input', (e) => {
    optQualityVal.textContent = `${e.target.value}%`;
  });
  optDpi.addEventListener('input', (e) => {
    optDpiVal.textContent = `${e.target.value} DPI`;
  });

  // Browse files
  btnSelectFiles.addEventListener('click', () => {
    selectFilesFromDialog().catch(err => {
      console.error(err);
      showNotice("Impossible d'ouvrir la fenêtre de choix des fichiers. Réessayez.", 'error');
    });
  });

  // Drag & Drop : le retour visuel est géré ici, les chemins réels des fichiers
  // arrivent par window.onNativeFilesDropped (voir main.py).
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropzone.addEventListener(eventName, preventDefaults, false);
    document.body.addEventListener(eventName, preventDefaults, false);
  });

  // Compteur : dragleave se déclenche aussi en passant d'un enfant à l'autre.
  let dragDepth = 0;
  document.body.addEventListener('dragenter', () => {
    dragDepth++;
    dropzone.classList.add('dragover');
  }, false);

  document.body.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) dropzone.classList.remove('dragover');
  }, false);

  document.body.addEventListener('drop', () => {
    dragDepth = 0;
    dropzone.classList.remove('dragover');
  }, false);

  // Clear queue
  btnClearQueue.addEventListener('click', () => {
    if (state.isConverting) return;
    state.queue = [];
    showNotice(null);
    renderQueue();
  });

  // Global format select change
  globalFormatSelect.addEventListener('change', (e) => {
    const fmt = e.target.value;
    if (!fmt) return;
    applyGlobalFormat(fmt);
  });

  // Presets click
  document.querySelectorAll('.chip[data-preset]').forEach(chip => {
    chip.addEventListener('click', () => {
      const preset = chip.getAttribute('data-preset');
      applyPreset(preset);
    });
  });

  // Browse Output Folder
  btnBrowseFolder.addEventListener('click', async () => {
    if (window.pywebview && window.pywebview.api) {
      const folder = await window.pywebview.api.select_output_folder();
      if (folder) {
        state.outputFolder = folder;
        outputFolderPathInput.value = folder;
      }
    }
  });

  // Convert All Button
  btnConvertAll.addEventListener('click', () => {
    startBatchConversion();
  });

  // Clear history
  btnClearHistory.addEventListener('click', () => {
    state.history = [];
    renderHistory();
  });
}

function preventDefaults(e) {
  e.preventDefault();
  e.stopPropagation();
}

function addFilesToQueue(files) {
  let added = 0;
  let duplicates = 0;
  (files || []).forEach(f => {
    // Avoid exact duplicates
    if (state.queue.some(item => item.path === f.path)) {
      duplicates++;
    } else {
      added++;
      state.queue.push({
        id: 'file_' + Math.random().toString(36).substring(2, 9),
        path: f.path,
        name: f.name,
        ext: f.ext,
        size: f.size,
        category: f.category,
        format: f.format,
        formatLabel: f.format_label || 'Format inconnu',
        formatExt: f.format_ext || f.ext,
        detectionMethod: f.detection_method,
        mismatch: !!f.mismatch,
        supported: f.supported !== false,
        targetFormat: getDefaultTarget(f),
        status: f.supported === false ? 'unsupported' : 'ready',
        duration: null,
        error: null
      });
    }
  });
  renderQueue();
  return { added, duplicates };
}

// Le format cible par défaut découle du format réellement détecté.
function getDefaultTargetFormat(f) {
  switch (f.format) {
    case 'png': return 'webp';
    case 'jpeg':
    case 'jfif':
    case 'webp':
    case 'gif':
    case 'bmp':
    case 'tiff':
    case 'heic':
    case 'jxl':
    case 'ico': return 'png';
    case 'svg': return 'png';
    case 'pdf': return 'png';
    case 'docx':
    case 'md':
    case 'html':
    case 'txt': return 'pdf';
  }
  return f.category === 'image' ? 'webp' : 'pdf';
}

function getDefaultTarget(f) {
  const targets = getTargets(f).map(t => t.val);
  const preferred = getDefaultTargetFormat(f);
  if (targets.indexOf(preferred) !== -1) return preferred;
  return targets.length ? targets[0] : null;
}

// Sorties proposées pour un fichier : uniquement celles que le moteur sait produire
// à partir de son format réellement détecté. Aucune pour un format non pris en charge.
function getTargets(item) {
  if (!item || item.supported === false) return [];
  if (item.category === 'image') {
    return IMAGE_SOURCES.indexOf(item.format) !== -1 ? IMAGE_TARGETS : [];
  }
  if (item.category === 'document') {
    const vals = Object.prototype.hasOwnProperty.call(DOCUMENT_TARGETS_BY_FORMAT, item.format)
      ? DOCUMENT_TARGETS_BY_FORMAT[item.format] : [];
    return vals.map(val => ({ val, name: DOCUMENT_TARGET_NAMES[val] }));
  }
  return [];
}

// N'applique un format cible qu'aux fichiers capables de le produire.
// sourceFormats (optionnel) restreint aux formats d'entrée réellement détectés.
function applyTargetFormat(fmt, categoryFilter, sourceFormats) {
  let applied = 0;
  state.queue.forEach(item => {
    if (categoryFilter && item.category !== categoryFilter) return;
    if (sourceFormats && sourceFormats.indexOf(item.format) === -1) return;
    if (!getTargets(item).some(t => t.val === fmt)) return;
    item.targetFormat = fmt;
    applied++;
  });
  renderQueue();
  return applied;
}

// Les presets ciblent le format réellement détecté, pas l'extension du fichier.
const PRESETS = {
  'png-webp': { target: 'webp', category: 'image', sources: ['png'], label: 'PNG vers WebP', none: 'Aucun fichier PNG dans la liste.' },
  'jpg-png': { target: 'png', category: 'image', sources: ['jpeg', 'jfif'], label: 'JPG vers PNG', none: 'Aucun fichier JPG dans la liste.' },
  'jxl-png': { target: 'png', category: 'image', sources: ['jxl'], label: 'JXL vers PNG', none: 'Aucun fichier JXL dans la liste.' },
  'img-ico': { target: 'ico', category: 'image', sources: null, label: 'Image vers ICO', none: 'Aucune image dans la liste.' },
  'pdf-png': { target: 'png', category: 'document', sources: ['pdf'], label: 'PDF vers PNG', none: 'Aucun fichier PDF dans la liste.' },
  'md-pdf': { target: 'pdf', category: 'document', sources: ['md'], label: 'Markdown vers PDF', none: 'Aucun fichier Markdown dans la liste.' },
  'docx-pdf': { target: 'pdf', category: 'document', sources: ['docx'], label: 'DOCX vers PDF', none: 'Aucun fichier DOCX dans la liste.' }
};

const EMPTY_QUEUE = "La liste est vide : ajoutez d'abord des fichiers.";

function applyPreset(presetKey) {
  const preset = Object.prototype.hasOwnProperty.call(PRESETS, presetKey) ? PRESETS[presetKey] : null;
  if (!preset) return;

  globalFormatSelect.value = '';
  if (!state.queue.length) { showNotice(EMPTY_QUEUE, 'error'); return; }
  const applied = applyTargetFormat(preset.target, preset.category, preset.sources);
  showNotice(applied ? `Appliqué à ${plural(applied, 'fichier')} : ${preset.label}.` : preset.none,
    applied ? 'info' : 'error');
}

function applyGlobalFormat(fmt) {
  if (!state.queue.length) { showNotice(EMPTY_QUEUE, 'error'); return; }
  const applied = applyTargetFormat(fmt, null);
  const label = String(fmt).toUpperCase();
  showNotice(applied ? `Appliqué à ${plural(applied, 'fichier')} : sortie ${label}.`
    : `Aucun fichier de la liste ne peut être converti en ${label}.`, applied ? 'info' : 'error');
}

function renderQueue() {
  fileCountEl.textContent = state.queue.length;
  const readyCount = state.queue.filter(item => item.supported).length;
  btnConvertAll.disabled = state.isConverting || readyCount === 0;
  btnClearQueue.disabled = state.isConverting || state.queue.length === 0;
  btnSelectFiles.disabled = state.isConverting;
  globalFormatSelect.disabled = state.isConverting;
  btnBrowseFolder.disabled = state.isConverting;
  document.querySelectorAll('.chip[data-preset]').forEach(chip => { chip.disabled = state.isConverting; });
  document.getElementById('queue-summary').textContent = state.isConverting
    ? (state.progress ? `Conversion ${state.progress.current} sur ${state.progress.total}…` : 'Conversion en cours…')
    : readyCount ? `${readyCount} fichier${readyCount > 1 ? 's' : ''} à convertir.`
    : state.queue.length ? 'Aucun format pris en charge dans la liste.' : 'Ajoutez des fichiers pour commencer.';

  if (state.queue.length === 0) {
    emptyStateEl.style.display = 'flex';
    fileQueueEl.innerHTML = '';
    fileQueueEl.appendChild(emptyStateEl);
    return;
  }

  emptyStateEl.style.display = 'none';
  fileQueueEl.innerHTML = '';

  state.queue.forEach(item => {
    const itemEl = document.createElement('div');
    itemEl.className = 'file-item' + (item.mismatch ? ' has-warning' : '');
    itemEl.id = `item-${item.id}`;

    const optionsHtml = getTargetOptionsHtml(item, item.targetFormat);
    const badge = (item.format || item.ext.replace('.', '') || '?');

    itemEl.innerHTML = `
      <div class="file-info">
        <span class="file-icon-badge ${escapeHtml(item.category)}" title="${escapeHtml(item.formatLabel)}">${escapeHtml(badge)}</span>
        <div class="file-details">
          <span class="file-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span>
          <span class="file-size">${formatBytes(item.size)} • ${escapeHtml(item.formatLabel)}${detectionNote(item)}</span>
          ${item.status === 'error' && item.error ? `<span class="file-error">${escapeHtml(item.error)}</span>` : ''}
        </div>
      </div>
      <div class="file-actions">
        <select class="item-format-select" aria-label="Format de sortie pour ${escapeHtml(item.name)}" data-id="${escapeHtml(item.id)}" ${item.supported && !state.isConverting ? '' : 'disabled'}>
          ${optionsHtml}
        </select>
        <span class="status-pill ${escapeHtml(item.status)}">${getStatusText(item.status)}</span>
        <button class="btn-icon" data-remove-id="${escapeHtml(item.id)}" title="Retirer de la liste" aria-label="Retirer ${escapeHtml(item.name)} de la liste" ${state.isConverting ? 'disabled' : ''}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
    `;

    fileQueueEl.appendChild(itemEl);

    // Event listener for format select
    const sel = itemEl.querySelector('.item-format-select');
    sel.addEventListener('change', (e) => {
      item.targetFormat = e.target.value;
    });

    // Event listener for remove button
    const btnRem = itemEl.querySelector('[data-remove-id]');
    btnRem.addEventListener('click', () => {
      if (state.isConverting) return;
      state.queue = state.queue.filter(q => q.id !== item.id);
      showNotice(null);
      renderQueue();
    });
  });
}

// Petit texte expliquant ce que la détection automatique a trouvé.
function detectionNote(item) {
  if (!item.supported) {
    return ' • <span class="detect-warning">non pris en charge</span>';
  }
  if (item.mismatch) {
    const declared = item.ext || 'sans extension';
    return ` • <span class="detect-warning">contenu réel, l'extension ${escapeHtml(declared)} est trompeuse</span>`;
  }
  return '';
}

function getTargetOptionsHtml(item, currentTarget) {
  const targets = getTargets(item);
  if (!targets.length) return '<option value="">Aucune sortie</option>';
  return targets
    .map(o => `<option value="${escapeHtml(o.val)}" ${o.val === currentTarget ? 'selected' : ''}>${escapeHtml(o.name)}</option>`)
    .join('');
}

function getStatusText(status) {
  switch (status) {
    case 'ready': return 'Prêt';
    case 'processing': return 'En cours…';
    case 'success': return 'Terminé';
    case 'error': return 'Échec';
    case 'unsupported': return 'Non pris en charge';
    default: return escapeHtml(status);
  }
}

const PLAY_ICON = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
const SPINNER_ICON = '<svg class="spinner" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10" stroke-dasharray="32" stroke-dashoffset="10"/></svg>';

async function startBatchConversion() {
  if (state.queue.length === 0) {
    showNotice("Ajoutez d'abord des fichiers à convertir.", 'error');
    return;
  }

  if (state.isConverting) return;

  const convertible = state.queue.filter(item => item.supported);
  if (convertible.length === 0) {
    showNotice("Aucun fichier de la liste n'est dans un format pris en charge.", 'error');
    return;
  }

  if (!window.pywebview || !window.pywebview.api) {
    showNotice(BRIDGE_MISSING, 'error');
    return;
  }
  state.isConverting = true;
  showNotice(null);
  btnConvertAll.disabled = true;

  const options = {
    quality: parseInt(optQuality.value),
    width: optWidth.value ? parseInt(optWidth.value) : null,
    height: optHeight.value ? parseInt(optHeight.value) : null,
    keep_aspect_ratio: optKeepAspect.checked,
    dpi: parseInt(optDpi.value)
  };

  let succeeded = 0;
  for (let i = 0; i < convertible.length; i++) {
    const item = convertible[i];
    item.status = 'processing';
    item.error = null;
    state.progress = { current: i + 1, total: convertible.length };
    btnConvertAll.innerHTML = `${SPINNER_ICON} Conversion ${i + 1} sur ${convertible.length}…`;
    renderQueue();

    let res = null;
    try {
      res = await window.pywebview.api.convert_single_file(
        item.path,
        item.targetFormat,
        options,
        state.outputFolder
      );
    } catch (err) {
      // Le détail technique reste dans la console de débogage, jamais à l'écran.
      console.error(err);
      res = { success: false, error: UNEXPECTED_ERROR };
    }

    if (res && res.success) {
      succeeded++;
      item.status = 'success';
      item.duration = res.duration;
      addHistoryItem({
        name: item.name,
        outputName: res.output_name,
        outputPath: res.output_path,
        duration: res.duration,
        status: 'success'
      });
    } else {
      item.status = 'error';
      item.error = (res && typeof res.error === 'string' && res.error.trim()) ? res.error : UNEXPECTED_ERROR;
      addHistoryItem({
        name: item.name,
        outputName: '-',
        outputPath: null,
        duration: 0,
        status: 'error',
        error: item.error
      });
    }
    renderQueue();
  }

  state.isConverting = false;
  state.progress = null;
  const failed = convertible.length - succeeded;
  showNotice(failed
    ? `Terminé : ${plural(succeeded, 'fichier converti', 'fichiers convertis')}, ${plural(failed, 'échec')} (cause indiquée sous ${failed > 1 ? 'chaque' : 'le'} fichier).`
    : `Terminé : ${plural(succeeded, 'fichier converti', 'fichiers convertis')}.`, failed ? 'error' : 'info');
  renderQueue();
  btnConvertAll.innerHTML = `${PLAY_ICON} Lancer la conversion`;
}

function addHistoryItem(item) {
  state.history.unshift(item);
  renderHistory();
}

function renderHistory() {
  if (state.history.length === 0) {
    emptyHistoryEl.style.display = 'block';
    historyListEl.innerHTML = '';
    historyListEl.appendChild(emptyHistoryEl);
    return;
  }

  emptyHistoryEl.style.display = 'none';
  historyListEl.innerHTML = '';

  state.history.forEach(h => {
    const hEl = document.createElement('div');
    hEl.className = 'history-item';

    if (h.status === 'success') {
      hEl.innerHTML = `
        <div class="history-item-left">
          <span class="status-pill success">Terminé</span>
          <div>
            <strong>${escapeHtml(h.outputName)}</strong>
            <div class="history-meta">Original: ${escapeHtml(h.name)} • Temps: ${escapeHtml(h.duration)}s</div>
          </div>
        </div>
        <button class="btn btn-secondary btn-sm" data-open-path="${escapeHtml(h.outputPath)}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          Ouvrir le dossier
        </button>
      `;

      const btnOpen = hEl.querySelector('[data-open-path]');
      btnOpen.addEventListener('click', () => {
        if (window.pywebview && window.pywebview.api) {
          window.pywebview.api.open_folder(h.outputPath);
        }
      });
    } else {
      hEl.innerHTML = `
        <div class="history-item-left">
          <span class="status-pill error">Échec</span>
          <div>
            <strong>${escapeHtml(h.name)}</strong>
            <div class="history-meta" style="color: var(--danger);">${escapeHtml(h.error || 'Erreur inconnue')}</div>
          </div>
        </div>
      `;
    }

    historyListEl.appendChild(hEl);
  });
}

function formatBytes(bytes, decimals = 2) {
  if (typeof bytes !== 'number' || !Number.isFinite(bytes) || bytes <= 0) return '0 o';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['o', 'Ko', 'Mo', 'Go', 'To'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}
