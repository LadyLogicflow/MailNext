// Treibt Webys MailNext-Betreiberoberfläche in jsdom gegen den echten MailNext-Testserver. Eingabe: JSON-Argument, Ausgabe: eine Zeile RESULT {...}
const {JSDOM, VirtualConsole} = require('jsdom');
const arg = JSON.parse(process.argv[2]);
const BASE = `http://127.0.0.1:${arg.port}`;
const jar = {bst_session: 'tok'};
const requests = [];
const toasts = [];
const alerts = [];
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
    beforeParse(win) { win.fetch = (u, o) => shimFetch(u, o); win.__bestaetigen = true; win.__prompt = ''; win.confirm = (t) => { alerts.push('confirm: ' + t); return win.__bestaetigen; }; win.prompt = (t) => { alerts.push('prompt: ' + t); return win.__prompt; }; win.alert = (t) => { alerts.push('alert: ' + t); }; }});
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
    await klick('Neuer Entwurf');
    await sleep(800);
    const cbs = (k) => [...doc.querySelectorAll('.segment-' + k)].map(c => ({wert: c.value, label: c.parentElement.textContent.trim()}));
    out.rollen = cbs('rolle'); out.interessen = cbs('interesse'); out.tags = cbs('tag');
    out.empfaenger_start = doc.getElementById('vorschau-anzahl').textContent;
    out.fehler_start = sichtbarFehler();
    out.schritte = [];
    for (const schritt of arg.schritte || []) {
      for (const cls of ['rolle', 'interesse', 'tag']) for (const cb of doc.querySelectorAll('.segment-' + cls)) cb.checked = (schritt[cls] || []).includes(cb.value) || (schritt[cls + '_label'] || []).some(l => cb.parentElement.textContent.includes(l));
      for (const r of doc.querySelectorAll('input[name="tags_modus"]')) r.checked = r.value === (schritt.modus || 'oder');
      const vor = requests.length;
      await klick('Empfänger aktualisieren');
      await sleep(700);
      out.schritte.push({schritt, empfaenger: doc.getElementById('vorschau-anzahl').textContent, fehler: sichtbarFehler(), requests: requests.slice(vor).map(r => `${r.m} ${r.p} ${r.s} ${r.body ? JSON.stringify(r.body) : ''}`)});
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
  if (arg.szenario === 'ki_global') {
    await klick('Einstellungen', doc.getElementById('nav'));
    const feld = doc.getElementById('ki-schluessel');
    out.feld = {typ: feld ? feld.type : null, wert: feld ? feld.value : null, autocomplete: feld ? feld.autocomplete : null};
    out.seite_vor = doc.getElementById('main').textContent.replace(/\s+/g, ' ').trim();
    if (arg.schluessel_eingeben !== undefined) {
      feld.value = arg.schluessel_eingeben;
      const vor = requests.length;
      doc.getElementById('ki-form').dispatchEvent(new win.Event('submit', {bubbles: true, cancelable: true}));
      await sleep(900);
      out.speichern = {requests: requests.slice(vor).map(r => `${r.m} ${r.p} ${r.s}`), fehler: sichtbarFehler(), feld_danach: doc.getElementById('ki-schluessel').value, toast: toastText(),
        dom_hat_schluessel: doc.documentElement.outerHTML.includes(arg.schluessel_eingeben)};
    }
  }
  if (arg.szenario === 'ki_tab') {
    await klick('KI');
    await sleep(500);
    out.seite = doc.getElementById('main').textContent.replace(/\s+/g, ' ').trim();
    const cb = doc.getElementById('ki-aktiv');
    out.aktiv_vorher = cb ? cb.checked : null;
    if (cb && arg.aktiv !== undefined) {
      cb.checked = arg.aktiv;
      const vor = requests.length;
      const form = cb.closest('form');
      form.dispatchEvent(new win.Event('submit', {bubbles: true, cancelable: true}));
      await sleep(900);
      out.speichern = {requests: requests.slice(vor).map(r => `${r.m} ${r.p} ${r.s} ${r.body ? JSON.stringify(r.body) : ''}`), toast: toastText(), aktiv_danach: doc.getElementById('ki-aktiv') ? doc.getElementById('ki-aktiv').checked : null};
    }
  }
  if (arg.szenario === 'editor') {
    await klick('Newsletter');
    await sleep(800);
    out.schritte = [];
    const sichtbar = () => ({vorschau: doc.getElementById('vorschau-anzahl') ? doc.getElementById('vorschau-anzahl').textContent : null,
      knoepfe: [...doc.querySelectorAll('#main button')].map(b => b.textContent.trim()), fehler: sichtbarFehler(), toast: toastText(),
      betreff: doc.getElementById('newsletter-betreff') ? doc.getElementById('newsletter-betreff').value : null,
      text: doc.getElementById('newsletter-text') ? doc.getElementById('newsletter-text').value : null,
      ki_knopf: [...doc.querySelectorAll('#main button')].some(b => b.textContent.trim() === 'Text verbessern'),
      ki_hinweis: ([...doc.querySelectorAll('#main p')].find(e => e.textContent.includes('Anthropic')) || {textContent: null}).textContent,
      ki_vorschau_sichtbar: doc.getElementById('ki-vorschau-container') ? !doc.getElementById('ki-vorschau-container').classList.contains('hidden') : null,
      ki_vorschau_text: doc.getElementById('ki-vorschau-text') ? doc.getElementById('ki-vorschau-text').textContent : null,
      ki_vorschau_betreff: doc.getElementById('ki-vorschau-betreff') && !doc.getElementById('ki-vorschau-betreff').classList.contains('hidden') ? doc.getElementById('ki-vorschau-betreff-text').textContent : null,
      ki_fehler: doc.getElementById('ki-verbesserung-error') && !doc.getElementById('ki-verbesserung-error').classList.contains('hidden') ? doc.getElementById('ki-verbesserung-error').textContent : null,
      dom_hat_schluessel: arg.schluessel ? doc.documentElement.outerHTML.includes(arg.schluessel) : null,
      listen_zeilen: [...doc.querySelectorAll('#main tbody tr')].map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim()))});
    for (const op of arg.ops) {
      const vor = requests.length; alerts.length = 0;
      if (op.op === 'neu') await klick('Neuer Entwurf');
      if (op.op === 'oeffnen') {
        const zeile = [...doc.querySelectorAll('#main tbody tr')].find(tr => tr.textContent.includes(op.betreff));
        if (!zeile) throw new Error('Entwurf nicht in der Liste: ' + op.betreff);
        zeile.click(); await sleep(900);
      }
      if (op.op === 'fuellen') {
        if (op.betreff !== undefined) doc.getElementById('newsletter-betreff').value = op.betreff;
        if (op.text !== undefined) doc.getElementById('newsletter-text').value = op.text;
        if (op.ziel) for (const r of doc.querySelectorAll('input[name="ziel"]')) r.checked = r.value === op.ziel;
        if (op.tags) for (const cb of doc.querySelectorAll('.segment-tag')) cb.checked = op.tags.includes(cb.value);
        if (op.modus) for (const r of doc.querySelectorAll('input[name="tags_modus"]')) r.checked = r.value === op.modus;
        if (op.rollen) for (const cb of doc.querySelectorAll('.segment-rolle')) cb.checked = op.rollen.includes(cb.value);
        if (op.interessen) for (const cb of doc.querySelectorAll('.segment-interesse')) cb.checked = op.interessen.includes(cb.value);
        if (op.aktualisieren) { await klick('Empfänger aktualisieren'); }
      }
      if (op.op === 'speichern') {
        doc.getElementById('newsletter-form').dispatchEvent(new win.Event('submit', {bubbles: true, cancelable: true}));
        await sleep(1200);
      }
      if (op.op === 'testmail') { win.__prompt = op.an === undefined ? '' : op.an; await klick('Testmail senden'); await sleep(600); }
      if (op.op === 'freigeben') { win.__bestaetigen = op.bestaetigen !== false; await klick('Freigeben & Versenden'); await sleep(900); }
      if (op.op === 'liste') await klick('Zurück zur Liste');
      if (op.op === 'ki_anweisung') doc.getElementById('ki-anweisung').value = op.wert;
      if (op.op === 'ki_verbessern') {
        out.knoepfe_vor_ki = [...doc.querySelectorAll('#main button')].map(b => b.textContent.trim());
        await klick('Text verbessern'); await sleep(600);
        out.knoepfe_nach_ki = [...doc.querySelectorAll('#main button')].map(b => b.textContent.trim());
      }
      if (op.op === 'ki_uebernehmen') await klick('Übernehmen');
      if (op.op === 'ki_verwerfen') await klick('Verwerfen');
      out.schritte.push({op, requests: requests.slice(vor).map(r => `${r.m} ${r.p} ${r.s} ${r.body ? JSON.stringify(r.body) : ''}`), alerts: alerts.slice(), zustand: sichtbar()});
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
