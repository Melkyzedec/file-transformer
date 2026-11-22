const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
// Test de logique uniquement : DOM et pont Python simulÃ©s, aucune conversion rÃ©elle.
const elements = new Map();
function element() { return {style:{}, classList:{remove(){}}, value:'', checked:true,
  addEventListener(){}, appendChild(){}, querySelector(){return element();}, innerHTML:''}; }
const context = vm.createContext({console, document:{getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},
  querySelectorAll(){return [];},createElement:element,addEventListener(){}},window:{},alert(){}});
vm.runInContext(fs.readFileSync(__dirname+'/../src/frontend/app.js','utf8'),context);
const run = code => vm.runInContext(code,context);
(async()=>{
  run('renderQueue()'); assert.equal(elements.get('btn-convert-all').disabled,true);
  run(`addFilesToQueue([{path:'mock.png',name:'mock.png',ext:'.png',size:123,category:'image',format:'png',supported:true}])`);
  assert.equal(run('state.queue[0].targetFormat'),'webp');
  assert.equal(elements.get('btn-convert-all').disabled,false);
  run(`applyPreset('docx-pdf')`); assert.equal(run('state.queue[0].targetFormat'),'webp');
  await run('startBatchConversion()'); assert.equal(run('state.isConverting'),false);
  context.window.pywebview={api:{async convert_single_file(){return {success:true,duration:.1,output_name:'mock.webp',output_path:'mock.webp'};}}};
  await run('startBatchConversion()');
  assert.equal(run('state.queue[0].status'),'success');assert.equal(run('state.history.length'),1);
  assert.equal(elements.get('btn-select-files').disabled,false);
  context.window.pywebview.api.convert_single_file=async()=>({success:false,error:'Erreur simulÃ©e'});
  await run('startBatchConversion()');assert.equal(run('state.queue[0].status'),'error');
  assert.equal(run('state.isConverting'),false);
  run(`state.queue=[];addFilesToQueue([{path:'mock.bin',name:'mock.bin',ext:'.bin',size:1,category:'unknown',supported:false}])`);
  assert.equal(elements.get('btn-convert-all').disabled,true);
  run('state.queue=[];renderQueue()');assert.equal(elements.get('btn-clear-queue').disabled,true);
  console.log('OK : file vide, formats/preset, absence de pont, succÃ¨s/erreur simulÃ©s, format non pris en charge, restauration des commandes.');
})().catch(e=>{console.error(e);process.exitCode=1;});
