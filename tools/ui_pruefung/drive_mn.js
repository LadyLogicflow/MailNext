// Treibt Webys MailNext-Betreiberoberfläche in jsdom gegen den echten MailNext-Testserver. Eingabe: JSON-Argument, Ausgabe: eine Zeile RESULT {...}
const {JSDOM, VirtualConsole} = require('jsdom');
const arg = JSON.parse(process.argv[2]);
const BASE = `http://127.0.0.1:${arg.port}`;
const jar = {bst_session: 'tok'};
const requests = [];
const toasts = [];
function cookieHeader() { return Object.entries(jar).map(([k, v]) => `${k}=${v}`).join('; '); }
async function shimFetch(url, opts = {}) {
  const u = new URL(url, BASE + '/');
  const headers = Object.assign({}, opts.headers || {}, {Cookie: cookieHeader()});
  const res = await fetch(u, {method: opts.method || 'GET', headers, body: opts.body, redirect: 'manual'});
  const rec = {m: opts.method || 'GET', p: u.pathname, s: res.status};
  if (opts.body && String(opts.body).length < 4000) { try { rec.body = JSON.parse(opts.body); if (rec.body.daten) rec.body.daten = '<' + rec.body.daten.length + ' Zeichen>'; } catch (e) {} }
  requests.push(rec);
  return res;
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
async function main() {
  const vc = new VirtualConsole();
  const fehler = [];
  vc.on('jsdomError', (e) => fehler.push('jsdomError: ' + (e.detail && e.detail.message || e.message)));
  const dom = await JSDOM.fromURL(BASE + '/betreiber/', {runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(win) { win.fetch = (u, o) => shimFetch(u, o); win.confirm = () => true; win.alert = () => {}; }});
  const win = dom.window; const doc = win.document;
  const klick = async (text, wo) => {
    const b = [...(wo || doc).querySelectorAll('button')].find(x => x.textContent.trim() === text);
    if (!b) throw new Error('Knopf nicht gefunden: ' + text);
    b.click(); await sleep(arg.warte || 700);
  };
  const out = {};
  await sleep(1200);
  out.nav = [...doc.querySelectorAll('#nav button')].map(b => b.textContent);
  await klick(arg.mandant_name);
  out.tabs = [...doc.querySelectorAll('button')].map(b => b.textContent.trim());
  const toastText = () => doc.getElementById('toast').textContent;
  const sichtbarFehler = () => [...doc.querySelectorAll('.error:not(.hidden),.field-error:not(.hidden)')].map(e => e.textContent);
  if (arg.szenario === 'abonnenten') {
    await klick('Abonnenten');
    out.kopf = [...doc.querySelectorAll('th')].map(t => t.textContent);
    out.zeilen = [...doc.querySelectorAll('tbody tr')].map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent));
  }
  if (arg.szenario === 'newsletter') {
    await klick('Newsletter');
    await sleep(800);
    const cbs = (k) => [...doc.querySelectorAll('.segment-' + k)].map(c => ({wert: c.value, label: c.parentElement.textContent.trim()}));
    out.rollen = cbs('rolle'); out.interessen = cbs('interesse'); out.tags = cbs('tag');
    out.empfaenger_start = doc.getElementById('empfaenger-anzahl').textContent;
    out.fehler_start = sichtbarFehler();
    out.schritte = [];
    for (const schritt of arg.schritte || []) {
      for (const cls of ['rolle', 'interesse', 'tag']) for (const cb of doc.querySelectorAll('.segment-' + cls)) cb.checked = (schritt[cls] || []).includes(cb.value) || (schritt[cls + '_label'] || []).some(l => cb.parentElement.textContent.includes(l));
      for (const r of doc.querySelectorAll('input[name="tags_modus"]')) r.checked = r.value === (schritt.modus || 'oder');
      const vor = requests.length;
      const geaendert = [...doc.querySelectorAll('.segment-rolle,.segment-interesse,.segment-tag,input[name="tags_modus"]')].find(c => c.checked) || doc.querySelector('input[name="tags_modus"]');
      geaendert.dispatchEvent(new win.Event('change', {bubbles: true}));
      await sleep(700);
      out.schritte.push({schritt, empfaenger: doc.getElementById('empfaenger-anzahl').textContent, fehler: sichtbarFehler(), requests: requests.slice(vor).map(r => `${r.m} ${r.p} ${r.s} ${r.body ? JSON.stringify(r.body) : ''}`)});
    }
  }
  if (arg.szenario === 'import') {
    await klick('Import');
    const datei = doc.getElementById('import-file');
    const fake = {name: 'export.csv', size: arg.csv.length, text: async () => arg.csv};
    Object.defineProperty(datei, 'files', {value: [fake], configurable: true});
    doc.getElementById('import-quelle').value = arg.quelle || '';
    for (const id of ['import-quelle']) doc.getElementById(id).dispatchEvent(new win.Event('input', {bubbles: true}));
    datei.dispatchEvent(new win.Event('change', {bubbles: true}));
    const rolle = doc.getElementById('import-rolle');
    out.rolle_optionen = rolle ? [...rolle.options].map(o => ({value: o.value, text: o.textContent})) : null;
    out.interessen_boxen = [...doc.querySelectorAll('.import-interesse')].map(c => ({wert: c.value, label: c.parentElement.textContent.trim()}));
    if (arg.rolle && rolle) rolle.value = arg.rolle;
    for (const c of doc.querySelectorAll('.import-interesse')) c.checked = (arg.interessen || []).includes(c.value);
    out.knoepfe_vor = {pruefen: doc.getElementById('btn-pruefen').disabled, import: doc.getElementById('btn-importieren').disabled};
    const vor = requests.length;
    await klick('Prüfen', doc);
    out.pruefung = {requests: requests.slice(vor).map(r => `${r.m} ${r.p} ${r.s} ${r.body ? JSON.stringify(r.body) : ''}`), fehler: sichtbarFehler(), vorschau_sichtbar: !doc.getElementById('import-vorschau').classList.contains('hidden'),
      vorschau_text: doc.getElementById('import-vorschau').textContent.replace(/\s+/g, ' ').trim(), dl_anzahl: doc.querySelectorAll('#import-vorschau dl').length,
      import_knopf_gesperrt: doc.getElementById('btn-importieren').disabled, einwilligung_sichtbar: !doc.getElementById('import-einwilligung').classList.contains('hidden')};
    if (arg.importieren) {
      const check = doc.getElementById('import-einwilligung-check');
      check.checked = true; check.dispatchEvent(new win.Event('change', {bubbles: true}));
      out.import_knopf_nach_haken_gesperrt = doc.getElementById('btn-importieren').disabled;
      const v2 = requests.length;
      await klick('Importieren', doc);
      out.import = {requests: requests.slice(v2).map(r => `${r.m} ${r.p} ${r.s} ${r.body ? JSON.stringify(r.body) : ''}`), fehler: sichtbarFehler(), ergebnis_text: doc.getElementById('import-ergebnis').textContent.replace(/\s+/g, ' ').trim(),
        ergebnis_sichtbar: !doc.getElementById('import-ergebnis').classList.contains('hidden'), toast: toastText()};
    }
  }
  out.toast = toastText();
  out.fehler_js = fehler.slice(0, 5);
  return out;
}
(async () => {
  let out;
  try { out = await main(); out.ok = true; } catch (e) { out = {ok: false, fehler: String(e.message || e)}; }
  console.log('RESULT ' + JSON.stringify(out));
  process.exit(0);
})();
