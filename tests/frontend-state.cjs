const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
// Test de logique uniquement : DOM et pont Python simulés, aucune conversion réelle.
const elements = new Map();
let alertCalls = 0;
function element() {
  return {
    style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {},
    removeAttribute() {},
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
  alert() { alertCalls++; }
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

  // m11 : escapeHtml conserve 0 et false, n'efface que null/undefined
  assert.equal(run('escapeHtml(0)'), '0');
  assert.equal(run('escapeHtml(false)'), 'false');
  assert.equal(run('escapeHtml(null)'), '');
  assert.equal(run('escapeHtml(undefined)'), '');
  elements.get('history-list').children = [];
  run(`state.history = [{ name: 'CANARY_TEST.png', outputName: 'CANARY_TEST.webp', outputPath: 'CANARY_TEST.webp', duration: 0, status: 'success' }]; renderHistory();`);
  assert.ok(elements.get('history-list').children.map(c => c.innerHTML).join('').includes('Temps: 0s'), 'Durée 0 affichée vide');


  // --- Correctifs UX pôle 3 (données fictives CANARY_TEST_) ---
  const notice = () => elements.get('status-notice').textContent;
  const summary = () => elements.get('queue-summary').textContent;
  const queueNow = () => { elements.get('file-queue').children = []; run('renderQueue()'); return elements.get('file-queue').children.map(c => c.innerHTML).join('\n'); };
  const doc = (format, name) => `{path:'${name}',name:'${name}',ext:'.${format}',size:10,category:'document',format:'${format}',supported:true}`;
  const img = (format, name) => `{path:'${name}',name:'${name}',ext:'.${format}',size:10,category:'image',format:'${format}',supported:true}`;
  delete context.window.pywebview;

  // UX1 : un HTML ne propose que PDF et TXT ; la liste globale ne lui impose pas PNG.
  run(`state.queue=[];state.history=[];addFilesToQueue([${doc('html', 'CANARY_TEST_page.html')}])`);
  let html = queueNow();
  assert.ok(html.includes('value="pdf"') && html.includes('value="txt"'), 'HTML : PDF et TXT attendus');
  for (const dead of ['png', 'jpg', 'html', 'md']) assert.equal(html.includes(`value="${dead}"`), false, `HTML : option morte ${dead}`);
  run(`applyTargetFormat('png', null)`); assert.equal(run('state.queue[0].targetFormat'), 'pdf');

  // UX3 : aucun clic muet (raccourcis et liste globale).
  run(`applyPreset('png-webp')`); assert.equal(notice(), 'Aucun fichier PNG dans la liste.');
  run(`applyPreset('img-ico')`); assert.equal(notice(), 'Aucune image dans la liste.');
  run(`addFilesToQueue([${img('png', 'CANARY_TEST_photo.png')}, ${img('png', 'CANARY_TEST_photo2.png')}])`);
  run(`applyPreset('png-webp')`); assert.equal(notice(), 'Appliqué à 2 fichiers : PNG vers WebP.');
  run(`applyGlobalFormat('txt')`); assert.equal(notice(), 'Appliqué à 1 fichier : sortie TXT.');
  assert.equal(run('state.queue[0].targetFormat'), 'txt'); assert.equal(run('state.queue[1].targetFormat'), 'webp');
  run(`applyGlobalFormat('md')`); assert.equal(notice(), 'Aucun fichier de la liste ne peut être converti en MD.');
  assert.equal(run('PRESETS["jfif-jpg"]'), undefined, 'Code mort jfif-jpg');
  run(`state.queue=[];renderQueue();applyPreset('png-webp')`); assert.equal(notice(), "La liste est vide : ajoutez d'abord des fichiers.");
  run(`applyGlobalFormat('png')`); assert.equal(notice(), "La liste est vide : ajoutez d'abord des fichiers.");

  // UX3 : éléments déposés ignorés et doublons annoncés.
  run(`window.onNativeFilesDropped({ files: [], ignored: [{ name: 'CANARY_TEST_dossier', reason: 'folder' }] })`);
  assert.equal(notice(), '1 élément ignoré (CANARY_TEST_dossier) : les dossiers ne sont pas pris en charge.');
  run(`window.onNativeFilesDropped({ files: [${img('png', 'CANARY_TEST_a.png')}], ignored: [
    { name: 'CANARY_TEST_d1', reason: 'folder' }, { name: 'CANARY_TEST_d2', reason: 'folder' },
    { name: 'CANARY_TEST_lien.lnk', reason: 'shortcut' }, { name: 'NUL', reason: 'reserved' }] })`);
  assert.equal(run('state.queue.length'), 1);
  assert.equal(notice(), '4 éléments ignorés : CANARY_TEST_d1, CANARY_TEST_d2 (les dossiers ne sont pas pris en charge) ; CANARY_TEST_lien.lnk (les raccourcis ne sont pas pris en charge) ; NUL (nom réservé par Windows).');
  run(`window.onNativeFilesDropped([${img('png', 'CANARY_TEST_a.png')}])`);
  assert.equal(notice(), '1 fichier déjà dans la liste.');
  run(`window.onNativeFilesDropped({ files: [], ignored: [{ name: '<img src=x onerror=alert(1)>', reason: '<b>' }] })`);
  assert.equal(notice().startsWith('1 élément ignoré'), true);
  assert.equal(elements.get('status-notice').innerHTML.includes('<img'), false, 'Avis : texte seulement');

  // UX3 : plus aucun alert() natif, message intégré à la place.
  await run('startBatchConversion()');
  assert.ok(notice().includes("seulement dans l'application"), notice());
  run('state.queue=[];renderQueue()'); await run('startBatchConversion()');
  assert.equal(notice(), "Ajoutez d'abord des fichiers à convertir.");
  await run('selectFilesFromDialog()');
  assert.ok(notice().includes("seulement dans l'application"), notice());
  assert.equal(alertCalls, 0, 'alert() natif encore appelé');

  // UX3 : progression chiffrée « Conversion 2 sur 3 ».
  const seen = [];
  context.window.pywebview = { api: { async convert_single_file(path) {
    seen.push([summary(), elements.get('btn-convert-all').innerHTML.includes(`Conversion ${seen.length + 1} sur 3`)]);
    return { success: true, duration: 0.1, output_name: path + '.webp', output_path: path + '.webp' };
  } } };
  run(`state.queue=[];state.history=[];addFilesToQueue([${img('png', 'CANARY_TEST_1.png')}, ${img('png', 'CANARY_TEST_2.png')}, ${img('png', 'CANARY_TEST_3.png')}])`);
  await run('startBatchConversion()');
  assert.deepEqual(seen, [['Conversion 1 sur 3…', true], ['Conversion 2 sur 3…', true], ['Conversion 3 sur 3…', true]]);
  assert.equal(notice(), 'Terminé : 3 fichiers convertis.');
  assert.equal(elements.get('btn-convert-all').innerHTML.includes('Lancer la conversion'), true);

  // UX2 : la cause de l'erreur est écrite sous le fichier (plus seulement en infobulle).
  context.window.pywebview.api.convert_single_file = async (path) => (path === 'CANARY_TEST_2.png'
    ? { success: false, error: 'CANARY_TEST_ cause lisible <b>' }
    : { success: true, duration: 0.1, output_name: 'x.webp', output_path: 'x.webp' });
  await run('startBatchConversion()');
  assert.equal(notice(), 'Terminé : 2 fichiers convertis, 1 échec (cause indiquée sous le fichier).');
  html = queueNow();
  assert.ok(html.includes('<span class="file-error">CANARY_TEST_ cause lisible &lt;b&gt;</span>'), html);
  assert.equal(/title="[^"]*cause lisible/.test(html), false, 'Erreur encore cachée dans une infobulle');
  assert.ok(html.includes('>Échec<') && html.includes('>Terminé<'), 'Même vocabulaire que l\'historique');

  // UX2 : une erreur JavaScript inattendue est écrite sous le fichier ET dans l'historique.
  context.window.pywebview.api.convert_single_file = async () => { throw new Error('CANARY_TEST_boom C:\\Users\\CANARY_TEST_prive'); };
  run('state.queue=[];state.history=[];addFilesToQueue([' + img('png', 'CANARY_TEST_js.png') + '])');
  await run('startBatchConversion()');
  assert.equal(run('state.queue[0].status'), 'error');
  assert.equal(run('state.history.length'), 1); assert.equal(run('state.history[0].status'), 'error');
  assert.ok(run('state.history[0].error').startsWith('Erreur inattendue'), run('state.history[0].error'));
  assert.equal(run('state.history[0].error').includes('CANARY_TEST_prive'), false, 'Chemin privé affiché');
  assert.equal(run('state.isConverting'), false);
  context.window.pywebview.api.convert_single_file = async () => null;
  await run('startBatchConversion()');
  assert.equal(run('state.queue[0].status'), 'error'); assert.ok(run('state.queue[0].error'));

  console.log('OK : file vide, formats/preset, absence de pont, succès/erreur simulés, format non pris en charge, anti-XSS, formatBytes, escapeHtml(0), restauration des commandes, correctifs UX pôle 3 (options par format, avis d\'état, progression, erreurs sous le fichier, zéro alert).');
})().catch(e => { console.error(e); process.exitCode = 1; });
