// State management
const state = {
  queue: [], // { id, path, name, ext, size, category, format, formatLabel, mismatch, supported, targetFormat, status, duration, error }
  history: [],
  outputFolder: null,
  isConverting: false
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

const DOCUMENT_TARGETS = [
  { val: 'pdf', name: 'PDF' },
  { val: 'png', name: 'PNG (Image)' },
  { val: 'jpg', name: 'JPG (Image)' },
  { val: 'html', name: 'HTML' },
  { val: 'txt', name: 'TXT' },
  { val: 'md', name: 'Markdown' }
];

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

// Wait for PyWebView API or initialization
document.addEventListener('DOMContentLoaded', () => {
  initEventListeners();
  renderQueue();
});

// Appelé depuis Python lors d'un glisser-déposer : les fichiers ont déjà été
// analysés côté backend (chemin réel + format détecté par signature).
window.onNativeFilesDropped = function (files) {
  dropzone.classList.remove('dragover');
  if (files && files.length > 0) {
    addFilesToQueue(files);
  }
};

function initEventListeners() {
  // Range sliders live value update
  optQuality.addEventListener('input', (e) => {
    optQualityVal.textContent = `${e.target.value}%`;
  });
  optDpi.addEventListener('input', (e) => {
    optDpiVal.textContent = `${e.target.value} DPI`;
  });

  // Browse files
  btnSelectFiles.addEventListener('click', async () => {
    if (window.pywebview && window.pywebview.api) {
      const files = await window.pywebview.api.select_files();
      if (files && files.length > 0) {
        addFilesToQueue(files);
      }
    } else {
      alert("Mode prévisualisation web : PyWebView non connecté.");
    }
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
    renderQueue();
  });

  // Global format select change
  globalFormatSelect.addEventListener('change', (e) => {
    const fmt = e.target.value;
    if (!fmt) return;
    applyTargetFormat(fmt, null);
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
  files.forEach(f => {
    // Avoid exact duplicates
    if (!state.queue.some(item => item.path === f.path)) {
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
        targetFormat: getDefaultTargetFormat(f),
        status: f.supported === false ? 'unsupported' : 'ready',
        duration: null,
        error: null
      });
    }
  });
  renderQueue();
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

function getTargets(category) {
  return category === 'image' ? IMAGE_TARGETS : DOCUMENT_TARGETS;
}

// N'applique un format cible qu'aux fichiers capables de le produire.
// sourceFormats (optionnel) restreint aux formats d'entrée réellement détectés.
function applyTargetFormat(fmt, categoryFilter, sourceFormats) {
  let applied = 0;
  state.queue.forEach(item => {
    if (categoryFilter && item.category !== categoryFilter) return;
    if (sourceFormats && sourceFormats.indexOf(item.format) === -1) return;
    if (!getTargets(item.category).some(t => t.val === fmt)) return;
    item.targetFormat = fmt;
    applied++;
  });
  renderQueue();
  return applied;
}

// Les presets ciblent le format réellement détecté, pas l'extension du fichier.
const PRESETS = {
  'png-webp': { target: 'webp', category: 'image', sources: ['png'] },
  'jpg-png': { target: 'png', category: 'image', sources: ['jpeg', 'jfif'] },
  'jfif-jpg': { target: 'jpg', category: 'image', sources: ['jfif'] },
  'jxl-png': { target: 'png', category: 'image', sources: ['jxl'] },
  'img-ico': { target: 'ico', category: 'image', sources: null },
  'pdf-png': { target: 'png', category: 'document', sources: ['pdf'] },
  'md-pdf': { target: 'pdf', category: 'document', sources: ['md'] },
  'docx-pdf': { target: 'pdf', category: 'document', sources: ['docx'] }
};

function applyPreset(presetKey) {
  const preset = PRESETS[presetKey];
  if (!preset) return;

  globalFormatSelect.value = '';
  applyTargetFormat(preset.target, preset.category, preset.sources);
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
    ? 'Conversion en cours…'
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

    const optionsHtml = getTargetOptionsHtml(item.category, item.targetFormat);
    const badge = (item.format || item.ext.replace('.', '') || '?');

    itemEl.innerHTML = `
      <div class="file-info">
        <span class="file-icon-badge ${escapeHtml(item.category)}" title="${escapeHtml(item.formatLabel)}">${escapeHtml(badge)}</span>
        <div class="file-details">
          <span class="file-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span>
          <span class="file-size">${formatBytes(item.size)} • ${escapeHtml(item.formatLabel)}${detectionNote(item)}</span>
        </div>
      </div>
      <div class="file-actions">
        <select class="item-format-select" aria-label="Format de sortie pour ${escapeHtml(item.name)}" data-id="${escapeHtml(item.id)}" ${item.supported && !state.isConverting ? '' : 'disabled'}>
          ${optionsHtml}
        </select>
        <span class="status-pill ${escapeHtml(item.status)}" title="${escapeHtml(item.error || '')}">${getStatusText(item.status)}</span>
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

function getTargetOptionsHtml(category, currentTarget) {
  return getTargets(category)
    .map(o => `<option value="${o.val}" ${o.val === currentTarget ? 'selected' : ''}>${o.name}</option>`)
    .join('');
}

function getStatusText(status) {
  switch (status) {
    case 'ready': return 'Prêt';
    case 'processing': return 'En cours...';
    case 'success': return 'Succès';
    case 'error': return 'Erreur';
    case 'unsupported': return 'Non supporté';
    default: return escapeHtml(status);
  }
}

async function startBatchConversion() {
  if (state.queue.length === 0) {
    alert("Veuillez d'abord ajouter des fichiers à convertir.");
    return;
  }

  if (state.isConverting) return;

  const convertible = state.queue.filter(item => item.supported);
  if (convertible.length === 0) {
    alert("Aucun fichier de la liste n'est dans un format pris en charge.");
    return;
  }

  if (!window.pywebview || !window.pywebview.api) {
    alert("La conversion est disponible dans l'application desktop. Ouvrez File Transformer depuis son lanceur.");
    return;
  }
  state.isConverting = true;
  btnConvertAll.disabled = true;
  btnConvertAll.innerHTML = `<svg class="spinner" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" stroke-dasharray="32" stroke-dashoffset="10"/></svg> Conversion en cours...`;

  const options = {
    quality: parseInt(optQuality.value),
    width: optWidth.value ? parseInt(optWidth.value) : null,
    height: optHeight.value ? parseInt(optHeight.value) : null,
    keep_aspect_ratio: optKeepAspect.checked,
    dpi: parseInt(optDpi.value)
  };

  for (let i = 0; i < convertible.length; i++) {
    const item = convertible[i];
    item.status = 'processing';
    renderQueue();

    try {
      if (window.pywebview && window.pywebview.api) {
        const res = await window.pywebview.api.convert_single_file(
          item.path,
          item.targetFormat,
          options,
          state.outputFolder
        );

        if (res.success) {
          item.status = 'success';
          item.duration = res.duration;
          item.error = null;
          addHistoryItem({
            name: item.name,
            outputName: res.output_name,
            outputPath: res.output_path,
            duration: res.duration,
            status: 'success'
          });
        } else {
          item.status = 'error';
          item.error = res.error;
          addHistoryItem({
            name: item.name,
            outputName: '-',
            outputPath: null,
            duration: 0,
            status: 'error',
            error: res.error
          });
        }
      }
    } catch (err) {
      item.status = 'error';
      item.error = err.toString();
    }
    renderQueue();
  }

  state.isConverting = false;
  renderQueue();
  btnConvertAll.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> Lancer la conversion`;
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
  if (!str) return '';
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}
