const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
// Test de logique uniquement : DOM et pont Python simulés, aucune conversion réelle.
const elements = new Map();
function element() {
  return {
    style: {},
    classList: { remove() {} },
    value: '',
    checked: true,
    children: [],
    addEventListener() {},
    appendChild(child) { this.children.push(child); },
    querySelector() { return element(); },
    innerHTML: ''
  };
}
const context = vm.createContext({
  console,
  document: {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    },
    querySelectorAll() { return []; },
    createElement: element,
    addEventListener() {}
  },
  window: {},
  alert() {}
});
vm.runInContext(fs.readFileSync(__dirname + '/../src/frontend/app.js', 'utf8'), context);
const run = code => vm.runInContext(code, context);
(async () => {
  run('renderQueue()'); assert.equal(elements.get('btn-convert-all').disabled, true);
  run(`addFilesToQueue([{path:'mock.png',name:'mock.png',ext:'.png',size:123,category:'image',format:'png',supported:true}])`);
  assert.equal(run('state.queue[0].targetFormat'), 'webp');
  assert.equal(elements.get('btn-convert-all').disabled, false);
  run(`applyPreset('docx-pdf')`); assert.equal(run('state.queue[0].targetFormat'), 'webp');
  await run('startBatchConversion()'); assert.equal(run('state.isConverting'), false);
  context.window.pywebview = { api: { async convert_single_file() { return { success: true, duration: .1, output_name: 'mock.webp', output_path: 'mock.webp' }; } } };
  await run('startBatchConversion()');
  assert.equal(run('state.queue[0].status'), 'success'); assert.equal(run('state.history.length'), 1);
  assert.equal(elements.get('btn-select-files').disabled, false);
  context.window.pywebview.api.convert_single_file = async () => ({ success: false, error: 'Erreur simulée' });
  await run('startBatchConversion()'); assert.equal(run('state.queue[0].status'), 'error');
  assert.equal(run('state.isConverting'), false);
  run(`state.queue=[];addFilesToQueue([{path:'mock.bin',name:'mock.bin',ext:'.bin',size:1,category:'unknown',supported:false}])`);
  assert.equal(elements.get('btn-convert-all').disabled, true);
  run('state.queue=[];renderQueue()'); assert.equal(elements.get('btn-clear-queue').disabled, true);

  // FT-08 : échappement XSS strict sur item.category, item.id, item.status, getStatusText et h.duration
  const xssPayload = '"><img src=x onerror=alert(1)>';
  elements.get('file-queue').children = [];
  run(`state.queue = [{
    id: ${JSON.stringify(xssPayload)},
    path: 'canary.png',
    name: 'CANARY_TEST.png',
    ext: '.png',
    size: 512,
    category: ${JSON.stringify(xssPayload)},
    format: 'png',
    formatLabel: 'PNG',
    mismatch: false,
    supported: true,
    targetFormat: 'webp',
    status: ${JSON.stringify(xssPayload)},
    duration: null,
    error: null
  }]; renderQueue();`);
  const queueHtml = elements.get('file-queue').children.map(c => c.innerHTML).join('\n');
  assert.equal(queueHtml.includes('<img src=x'), false, 'XSS non échappé dans renderQueue()');
  assert.equal(run(`getStatusText(${JSON.stringify(xssPayload)})`).includes('<img'), false, 'XSS non échappé dans getStatusText()');

  elements.get('history-list').children = [];
  run(`state.history = [{
    name: 'CANARY_TEST.png',
    outputName: 'CANARY_TEST.webp',
    outputPath: 'CANARY_TEST.webp',
    duration: ${JSON.stringify(xssPayload)},
    status: 'success'
  }]; renderHistory();`);
  const historyHtml = elements.get('history-list').children.map(c => c.innerHTML).join('\n');
  assert.equal(historyHtml.includes('<img src=x'), false, 'XSS non échappé dans renderHistory()');

  // FT-08 / FT-11 : formatBytes sécurisé pour valeurs négatives, nulles et très grandes
  assert.equal(run('formatBytes(-5)'), '0 o');
  assert.equal(run('formatBytes(0)'), '0 o');
  assert.equal(run('formatBytes(NaN)'), '0 o');
  assert.equal(run('formatBytes(1024 ** 6)').includes('undefined'), false);

  console.log('OK : file vide, formats/preset, absence de pont, succès/erreur simulés, format non pris en charge, anti-XSS, formatBytes, restauration des commandes.');
})().catch(e => { console.error(e); process.exitCode = 1; });
