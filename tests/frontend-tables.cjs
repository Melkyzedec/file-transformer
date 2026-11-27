// Outil de test : charge src/frontend/app.js avec un DOM simulé et affiche, en JSON,
// les formats de sortie que l'interface propose pour chaque format d'entrée.
// Appelé par tests/test_ux_options_par_format.py pour croiser l'interface avec le moteur Python.
// Usage : node tests/frontend-tables.cjs '[{"category":"document","format":"pdf"}, ...]'
const fs = require('node:fs');
const vm = require('node:vm');

function element() {
  return {
    style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    value: '',
    checked: true,
    hidden: false,
    children: [],
    addEventListener() {},
    appendChild(child) { this.children.push(child); },
    querySelector() { return element(); },
    querySelectorAll() { return []; },
    setAttribute() {},
    removeAttribute() {},
    innerHTML: '',
    textContent: ''
  };
}
const elements = new Map();
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
  alert() { throw new Error('alert() natif appelé'); }
});
vm.runInContext(fs.readFileSync(__dirname + '/../src/frontend/app.js', 'utf8'), context);

const sources = JSON.parse(process.argv[2] || '[]');
context.__sources = sources;
const result = vm.runInContext(
  '__sources.map(s => ({ category: s.category, format: s.format, ' +
  'targets: getTargets({ category: s.category, format: s.format }).map(t => t.val) }))',
  context
);
process.stdout.write(JSON.stringify(result));
