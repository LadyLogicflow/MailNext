// MailNext Betreiber-Oberfläche - CSP 'self' konform (keine Inline-Scripts)

const API_BASE = '/api/v1/betreiber';
let state = {
    mandanten: [],
    currentView: 'liste'
};

// Hilfsfunktionen
function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast show';
    if (type === 'error') toast.classList.add('toast-error');
    if (type === 'success') toast.classList.add('toast-success');

    setTimeout(() => {
        toast.className = 'toast';
    }, 4000);
}

async function apiCall(path, options = {}) {
    const response = await fetch(API_BASE + path, {
        ...options,
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
            ...options.headers
        }
    });

    // Nicht-JSON-Antworten abfangen (503/Proxy)
    let data;
    try {
        data = await response.json();
    } catch (e) {
        if (response.status === 401 || response.status === 403) {
            throw new Error('Bitte im Portal als Betreiber anmelden');
        }
        throw new Error(`Fehler ${response.status}: ${response.statusText || 'Keine Antwort vom Server'}`);
    }

    if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
            throw new Error('Bitte im Portal als Betreiber anmelden');
        }
        throw new Error(data.meldung || data.error || 'Ein Fehler ist aufgetreten');
    }

    return data;
}

// Navigation
function showView(view) {
    state.currentView = view;
    renderNav();

    switch (view) {
        case 'liste':
            renderMandantenListe();
            break;
        case 'anlegen':
            renderMandantAnlegen();
            break;
        default:
            renderMandantenListe();
    }
}

function renderNav() {
    const nav = document.getElementById('nav');
    nav.innerHTML = '';

    const buttons = [
        { id: 'liste', label: 'Mandanten' },
        { id: 'anlegen', label: 'Neuer Mandant' }
    ];

    buttons.forEach(btn => {
        const button = document.createElement('button');
        button.textContent = btn.label;
        button.className = state.currentView === btn.id ? 'active' : '';
        button.addEventListener('click', () => showView(btn.id));
        nav.appendChild(button);
    });
}

// Mandantenliste
async function loadMandanten() {
    try {
        const data = await apiCall('/mandanten');
        state.mandanten = data.mandanten || [];
        renderMandantenListe();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderMandantenListe() {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = 'Mandanten';
    card.appendChild(title);

    if (state.mandanten.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'loading';
        empty.textContent = 'Noch keine Mandanten vorhanden. Legen Sie den ersten an.';
        card.appendChild(empty);
        main.innerHTML = '';
        main.appendChild(card);
        return;
    }

    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');

    ['Slug', 'Name', 'Status', 'Abonnenten'].forEach(text => {
        const th = document.createElement('th');
        th.textContent = text;
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    state.mandanten.forEach(m => {
        const row = document.createElement('tr');

        const slugCell = document.createElement('td');
        slugCell.textContent = m.slug;
        row.appendChild(slugCell);

        const nameCell = document.createElement('td');
        const nameBtn = document.createElement('button');
        nameBtn.textContent = m.name;
        nameBtn.style.all = 'unset';
        nameBtn.style.cursor = 'pointer';
        nameBtn.style.textDecoration = 'underline';
        nameBtn.addEventListener('click', () => showMandantDetails(m.id));
        nameCell.appendChild(nameBtn);
        row.appendChild(nameCell);

        const statusCell = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = m.aktiv ? 'badge badge-success' : 'badge badge-warning';
        badge.textContent = m.aktiv ? 'Aktiv' : 'Inaktiv';
        statusCell.appendChild(badge);
        row.appendChild(statusCell);

        const aboCell = document.createElement('td');
        const abo = m.abonnenten || {};
        const bestaetigt = abo.bestaetigt || 0;
        const unbestaetigt = abo.unbestaetigt || 0;
        aboCell.textContent = unbestaetigt > 0
            ? `${bestaetigt} bestätigt, ${unbestaetigt} unbestätigt`
            : `${bestaetigt} bestätigt`;
        row.appendChild(aboCell);

        tbody.appendChild(row);
    });
    table.appendChild(tbody);
    card.appendChild(table);

    main.innerHTML = '';
    main.appendChild(card);
}

// Mandant anlegen
function renderMandantAnlegen() {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = 'Neuen Mandanten anlegen';
    card.appendChild(title);

    const errorDiv = document.createElement('div');
    errorDiv.className = 'error hidden';
    errorDiv.id = 'anlegen-error';
    card.appendChild(errorDiv);

    const form = document.createElement('form');
    form.id = 'anlegen-form';

    // Slug
    const slugGroup = document.createElement('div');
    slugGroup.className = 'form-group';
    const slugLabel = document.createElement('label');
    slugLabel.textContent = 'Kennung (Slug)';
    slugGroup.appendChild(slugLabel);
    const slugInput = document.createElement('input');
    slugInput.type = 'text';
    slugInput.id = 'slug';
    slugInput.required = true;
    slugInput.pattern = '[a-z0-9][a-z0-9-]{1,30}';
    slugInput.placeholder = 'z.B. mein-verein';
    slugGroup.appendChild(slugInput);
    const slugHelp = document.createElement('small');
    slugHelp.textContent = '2-31 Zeichen, nur a-z, 0-9 und Bindestrich';
    slugGroup.appendChild(slugHelp);
    form.appendChild(slugGroup);

    // Name
    const nameGroup = document.createElement('div');
    nameGroup.className = 'form-group';
    const nameLabel = document.createElement('label');
    nameLabel.textContent = 'Name';
    nameGroup.appendChild(nameLabel);
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.id = 'name';
    nameInput.required = true;
    nameInput.maxLength = 100;
    nameInput.placeholder = 'z.B. Mein Verein e.V.';
    nameGroup.appendChild(nameInput);
    const nameHelp = document.createElement('small');
    nameHelp.textContent = 'Bis zu 100 Zeichen';
    nameGroup.appendChild(nameHelp);
    form.appendChild(nameGroup);

    // Buttons
    const actions = document.createElement('div');
    actions.className = 'form-actions';

    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = 'Mandant anlegen';
    actions.appendChild(submitBtn);

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn btn-secondary';
    cancelBtn.textContent = 'Abbrechen';
    cancelBtn.addEventListener('click', () => showView('liste'));
    actions.appendChild(cancelBtn);

    form.appendChild(actions);

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const errorDiv = document.getElementById('anlegen-error');
        errorDiv.className = 'error hidden';

        const slug = document.getElementById('slug').value.trim().toLowerCase();
        const name = document.getElementById('name').value.trim();

        if (!slug || !name) {
            errorDiv.textContent = 'Bitte füllen Sie alle Felder aus.';
            errorDiv.className = 'error';
            return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Wird angelegt...';

        try {
            await apiCall('/mandanten', {
                method: 'POST',
                body: JSON.stringify({ slug, name })
            });

            showToast('Mandant erfolgreich angelegt', 'success');
            await loadMandanten();
            showView('liste');
        } catch (err) {
            errorDiv.textContent = err.message;
            errorDiv.className = 'error';
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Mandant anlegen';
        }
    });

    card.appendChild(form);

    main.innerHTML = '';
    main.appendChild(card);
}

// Mandant Details + Design (Schritt 2 - Basis-Version)
async function showMandantDetails(mandantId, tab = 'details') {
    try {
        const m = await apiCall(`/mandanten/${mandantId}`);
        state.currentMandant = m;
        state.currentTab = tab;
        if (tab === 'abonnenten') {
            renderAbonnenten(m);
        } else if (tab === 'versand') {
            renderVersand(m);
        } else {
            renderMandantDetails(m);
        }
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderMandantDetails(m) {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = m.name;
    card.appendChild(title);

    // Tabs
    const tabsNav = document.createElement('div');
    tabsNav.style.marginBottom = '1.5rem';
    tabsNav.style.borderBottom = '1px solid var(--color-border)';
    const tabs = [{id: 'details', label: 'Einstellungen'}, {id: 'versand', label: 'Versand'}, {id: 'abonnenten', label: 'Abonnenten'}];
    tabs.forEach(tab => {
        const btn = document.createElement('button');
        btn.textContent = tab.label;
        btn.style.padding = '0.5rem 1rem';
        btn.style.background = 'none';
        btn.style.border = 'none';
        btn.style.borderBottom = state.currentTab === tab.id ? '2px solid var(--color-primary)' : '2px solid transparent';
        btn.style.cursor = 'pointer';
        btn.style.fontWeight = state.currentTab === tab.id ? '600' : 'normal';
        btn.addEventListener('click', () => showMandantDetails(m.id, tab.id));
        tabsNav.appendChild(btn);
    });
    card.appendChild(tabsNav);

    const errorDiv = document.createElement('div');
    errorDiv.className = 'error hidden';
    errorDiv.id = 'details-error';
    card.appendChild(errorDiv);

    const form = document.createElement('form');
    form.id = 'details-form';

    // Name
    const nameGroup = document.createElement('div');
    nameGroup.className = 'form-group';
    const nameLabel = document.createElement('label');
    nameLabel.textContent = 'Name';
    nameGroup.appendChild(nameLabel);
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.id = 'edit-name';
    nameInput.value = m.name;
    nameInput.maxLength = 100;
    nameGroup.appendChild(nameInput);
    form.appendChild(nameGroup);

    // Aktiv
    const aktivGroup = document.createElement('div');
    aktivGroup.className = 'form-group';
    const aktivLabel = document.createElement('label');
    const aktivCheckbox = document.createElement('input');
    aktivCheckbox.type = 'checkbox';
    aktivCheckbox.id = 'edit-aktiv';
    aktivCheckbox.checked = m.aktiv;
    aktivLabel.appendChild(aktivCheckbox);
    aktivLabel.appendChild(document.createTextNode(' Aktiv'));
    aktivGroup.appendChild(aktivLabel);
    form.appendChild(aktivGroup);

    // Farben (Basis)
    const farbGroup = document.createElement('div');
    farbGroup.className = 'form-group';
    const farbTitle = document.createElement('h3');
    farbTitle.textContent = 'Farben';
    farbGroup.appendChild(farbTitle);

    ['farbe_primaer', 'farbe_akzent', 'farbe_hintergrund', 'farbe_text'].forEach(f => {
        const label = document.createElement('label');
        label.textContent = f.replace('farbe_', '').replace('_', ' ');
        const input = document.createElement('input');
        input.type = 'color';
        input.id = `edit-${f}`;
        input.value = m.design[f] || '#000000';
        label.appendChild(input);
        farbGroup.appendChild(label);
    });
    form.appendChild(farbGroup);

    // Schrift
    const schriftGroup = document.createElement('div');
    schriftGroup.className = 'form-group';
    const schriftLabel = document.createElement('label');
    schriftLabel.textContent = 'Schrift';
    schriftGroup.appendChild(schriftLabel);
    const schriftSelect = document.createElement('select');
    schriftSelect.id = 'edit-schrift';
    ['sans', 'serif'].forEach(s => {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s === 'sans' ? 'Sans-Serif' : 'Serif';
        opt.selected = m.design.schrift === s;
        schriftSelect.appendChild(opt);
    });
    schriftGroup.appendChild(schriftSelect);
    form.appendChild(schriftGroup);

    // URLs und Texte
    const texteTitle = document.createElement('h3');
    texteTitle.textContent = 'Absender & Links';
    form.appendChild(texteTitle);

    [
        {id: 'logo_url', label: 'Logo-URL', type: 'url'},
        {id: 'absender_name', label: 'Absender-Name', type: 'text', max: 100},
        {id: 'absender_adresse', label: 'Absender-E-Mail', type: 'email', max: 254},
        {id: 'impressum_url', label: 'Impressum-URL', type: 'url'},
        {id: 'datenschutz_url', label: 'Datenschutz-URL', type: 'url'},
        {id: 'basis_url', label: 'Basis-URL', type: 'url'},
        {id: 'betreff_bestaetigung', label: 'Betreff Bestätigung', type: 'text', max: 150}
    ].forEach(feld => {
        const g = document.createElement('div');
        g.className = 'form-group';
        const l = document.createElement('label');
        l.textContent = feld.label;
        g.appendChild(l);
        const i = document.createElement('input');
        i.type = feld.type;
        i.id = `edit-${feld.id}`;
        i.value = m.design[feld.id] || '';
        if (feld.max) i.maxLength = feld.max;
        g.appendChild(i);
        form.appendChild(g);
    });

    // Firmenangaben (textarea)
    const firmaGroup = document.createElement('div');
    firmaGroup.className = 'form-group';
    const firmaLabel = document.createElement('label');
    firmaLabel.textContent = 'Firmenangaben';
    firmaGroup.appendChild(firmaLabel);
    const firmaText = document.createElement('textarea');
    firmaText.id = 'edit-firmenangaben';
    firmaText.value = m.design.firmenangaben || '';
    firmaText.maxLength = 1000;
    firmaText.rows = 3;
    firmaGroup.appendChild(firmaText);
    form.appendChild(firmaGroup);

    // Listen (JSON, vereinfacht)
    const listenTitle = document.createElement('h3');
    listenTitle.textContent = 'Rollen, Interessen, CORS';
    form.appendChild(listenTitle);

    const jsonErrors = {};
    const jsonTextareas = [];
    [
        {id: 'rollen', label: 'Rollen (JSON)', help: '[{"wert":"role1","label":"Rolle 1"}]'},
        {id: 'interessen', label: 'Interessen (JSON)', help: '[{"wert":"int1","label":"Interesse 1"}]'},
        {id: 'cors_ursprunge', label: 'CORS-Ursprünge (JSON)', help: '["https://example.com"]'}
    ].forEach(feld => {
        const g = document.createElement('div');
        g.className = 'form-group';
        const l = document.createElement('label');
        l.textContent = feld.label;
        g.appendChild(l);
        const t = document.createElement('textarea');
        t.id = `edit-${feld.id}`;
        t.value = JSON.stringify(m.design[feld.id] || [], null, 2);
        t.rows = 3;
        g.appendChild(t);
        const errorSpan = document.createElement('span');
        errorSpan.className = 'field-error hidden';
        errorSpan.id = `error-${feld.id}`;
        errorSpan.style.color = 'var(--color-error)';
        errorSpan.style.fontSize = '0.875rem';
        errorSpan.style.display = 'block';
        errorSpan.style.marginTop = '0.25rem';
        g.appendChild(errorSpan);
        const small = document.createElement('small');
        small.textContent = feld.help;
        g.appendChild(small);

        jsonTextareas.push({textarea: t, errorSpan, feldId: feld.id});

        form.appendChild(g);
    });

    // Einwilligungstext
    const einwTitle = document.createElement('h3');
    einwTitle.textContent = 'Einwilligungstext';
    form.appendChild(einwTitle);

    // Bestehende Einwilligungen anzeigen
    if (m.einwilligungen && m.einwilligungen.length > 0) {
        const einwListe = document.createElement('div');
        einwListe.style.marginBottom = '1rem';
        einwListe.style.padding = '0.75rem';
        einwListe.style.background = '#f9fafb';
        einwListe.style.borderRadius = '6px';
        const einwListeTitle = document.createElement('strong');
        einwListeTitle.textContent = 'Bestehende Versionen:';
        einwListe.appendChild(einwListeTitle);
        const einwUl = document.createElement('ul');
        einwUl.style.marginTop = '0.5rem';
        einwUl.style.marginBottom = '0';
        m.einwilligungen.forEach(e => {
            const li = document.createElement('li');
            li.textContent = `${e.version} (SHA-256: ${e.sha256.substring(0, 16)}...) gültig ab ${e.gueltig_ab}`;
            einwUl.appendChild(li);
        });
        einwListe.appendChild(einwUl);
        form.appendChild(einwListe);
    }

    const einwVersionGroup = document.createElement('div');
    einwVersionGroup.className = 'form-group';
    const einwVersionLabel = document.createElement('label');
    einwVersionLabel.textContent = 'Version';
    einwVersionGroup.appendChild(einwVersionLabel);
    const einwVersionInput = document.createElement('input');
    einwVersionInput.type = 'text';
    einwVersionInput.id = 'einw-version';
    einwVersionInput.placeholder = 'z.B. v1.0';
    einwVersionGroup.appendChild(einwVersionInput);
    form.appendChild(einwVersionGroup);

    const einwTextGroup = document.createElement('div');
    einwTextGroup.className = 'form-group';
    const einwTextLabel = document.createElement('label');
    einwTextLabel.textContent = 'Text (einzeilig, 20-1000 Zeichen)';
    einwTextGroup.appendChild(einwTextLabel);
    const einwTextInput = document.createElement('input');
    einwTextInput.type = 'text';
    einwTextInput.id = 'einw-text';
    einwTextInput.maxLength = 1000;
    // Enter abfangen (verhindert implizites Submit des Formulars)
    einwTextInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') e.preventDefault();
    });
    einwTextGroup.appendChild(einwTextInput);
    const einwSmall = document.createElement('small');
    einwSmall.textContent = 'Nach Speichern wird SHA-256 angezeigt';
    einwTextGroup.appendChild(einwSmall);
    form.appendChild(einwTextGroup);

    const einwBtn = document.createElement('button');
    einwBtn.type = 'button';
    einwBtn.className = 'btn btn-secondary';
    einwBtn.textContent = 'Einwilligungstext speichern';
    einwBtn.addEventListener('click', async () => {
        const version = document.getElementById('einw-version').value.trim();
        const text = document.getElementById('einw-text').value.trim();
        if (!version || !text) {
            showToast('Version und Text erforderlich', 'error');
            return;
        }
        try {
            const result = await apiCall(`/mandanten/${m.id}/einwilligungen`, {
                method: 'POST',
                body: JSON.stringify({version, text})
            });
            showToast(`Gespeichert: ${result.version} (SHA-256: ${result.sha256.substring(0,12)}...)`, 'success');
            document.getElementById('einw-version').value = '';
            document.getElementById('einw-text').value = '';
        } catch (err) {
            showToast(err.message, 'error');
        }
    });
    form.appendChild(einwBtn);

    // Buttons
    const actions = document.createElement('div');
    actions.className = 'form-actions';

    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = 'Speichern';
    actions.appendChild(submitBtn);

    // Live-Validation für JSON-Felder (nach submitBtn-Definition)
    function updateSubmitButton() {
        const hasErrors = Object.keys(jsonErrors).length > 0;
        submitBtn.disabled = hasErrors;
        submitBtn.title = hasErrors ? 'Bitte JSON-Fehler beheben' : '';
    }

    jsonTextareas.forEach(({textarea, errorSpan, feldId}) => {
        textarea.addEventListener('input', () => {
            try {
                JSON.parse(textarea.value);
                errorSpan.className = 'field-error hidden';
                delete jsonErrors[feldId];
            } catch (err) {
                errorSpan.textContent = 'Ungültiges JSON: ' + err.message;
                errorSpan.className = 'field-error';
                jsonErrors[feldId] = err.message;
            }
            updateSubmitButton();
        });
    });

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn btn-secondary';
    cancelBtn.textContent = 'Zurück';
    cancelBtn.addEventListener('click', () => showView('liste'));
    actions.appendChild(cancelBtn);

    form.appendChild(actions);

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const errorDiv = document.getElementById('details-error');
        errorDiv.className = 'error hidden';

        const name = document.getElementById('edit-name').value.trim();
        const aktiv = document.getElementById('edit-aktiv').checked;

        // Listen parsen
        let rollen, interessen, cors_ursprunge;
        try {
            rollen = JSON.parse(document.getElementById('edit-rollen').value);
            interessen = JSON.parse(document.getElementById('edit-interessen').value);
            cors_ursprunge = JSON.parse(document.getElementById('edit-cors_ursprunge').value);
        } catch (err) {
            errorDiv.textContent = 'JSON-Fehler in Listen (Rollen/Interessen/CORS): ' + err.message;
            errorDiv.className = 'error';
            return;
        }

        const design = {
            farbe_primaer: document.getElementById('edit-farbe_primaer').value,
            farbe_akzent: document.getElementById('edit-farbe_akzent').value,
            farbe_hintergrund: document.getElementById('edit-farbe_hintergrund').value,
            farbe_text: document.getElementById('edit-farbe_text').value,
            schrift: document.getElementById('edit-schrift').value,
            logo_url: document.getElementById('edit-logo_url').value.trim(),
            absender_name: document.getElementById('edit-absender_name').value.trim(),
            absender_adresse: document.getElementById('edit-absender_adresse').value.trim(),
            firmenangaben: document.getElementById('edit-firmenangaben').value.trim(),
            impressum_url: document.getElementById('edit-impressum_url').value.trim(),
            datenschutz_url: document.getElementById('edit-datenschutz_url').value.trim(),
            basis_url: document.getElementById('edit-basis_url').value.trim(),
            betreff_bestaetigung: document.getElementById('edit-betreff_bestaetigung').value.trim(),
            rollen,
            interessen,
            cors_ursprunge
        };

        submitBtn.disabled = true;
        submitBtn.textContent = 'Wird gespeichert...';

        try {
            await apiCall(`/mandanten/${m.id}`, {
                method: 'PUT',
                body: JSON.stringify({ name, aktiv, design })
            });

            showToast('Änderungen gespeichert', 'success');
            await loadMandanten();
            showView('liste');
        } catch (err) {
            errorDiv.textContent = err.message;
            errorDiv.className = 'error';
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Speichern';
        }
    });

    card.appendChild(form);

    main.innerHTML = '';
    main.appendChild(card);
}

// Versand (Schritt 3)
async function renderVersand(m) {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = m.name;
    card.appendChild(title);

    // Tabs
    const tabsNav = document.createElement('div');
    tabsNav.style.marginBottom = '1.5rem';
    tabsNav.style.borderBottom = '1px solid var(--color-border)';
    const tabs = [{id: 'details', label: 'Einstellungen'}, {id: 'versand', label: 'Versand'}, {id: 'abonnenten', label: 'Abonnenten'}];
    tabs.forEach(tab => {
        const btn = document.createElement('button');
        btn.textContent = tab.label;
        btn.style.padding = '0.5rem 1rem';
        btn.style.background = 'none';
        btn.style.border = 'none';
        btn.style.borderBottom = state.currentTab === tab.id ? '2px solid var(--color-primary)' : '2px solid transparent';
        btn.style.cursor = 'pointer';
        btn.style.fontWeight = state.currentTab === tab.id ? '600' : 'normal';
        btn.addEventListener('click', () => showMandantDetails(m.id, tab.id));
        tabsNav.appendChild(btn);
    });
    card.appendChild(tabsNav);

    const form = document.createElement('form');
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error hidden';
    errorDiv.id = 'versand-error';
    form.appendChild(errorDiv);

    // Modus
    const modusGroup = document.createElement('div');
    modusGroup.className = 'form-group';
    const modusLabel = document.createElement('label');
    modusLabel.textContent = 'Versandmodus';
    modusGroup.appendChild(modusLabel);
    ['aus', 'datei', 'smtp'].forEach(mode => {
        const lbl = document.createElement('label');
        lbl.style.display = 'block';
        lbl.style.marginBottom = '0.5rem';
        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = 'versandmodus';
        radio.value = mode;
        radio.checked = m.versand.versandmodus === mode;
        radio.addEventListener('change', () => {
            document.getElementById('smtp-fields').style.display = mode === 'smtp' ? 'block' : 'none';
        });
        lbl.appendChild(radio);
        lbl.appendChild(document.createTextNode(' ' + mode.toUpperCase()));
        modusGroup.appendChild(lbl);
    });
    form.appendChild(modusGroup);

    // SMTP-Felder
    const smtpDiv = document.createElement('div');
    smtpDiv.id = 'smtp-fields';
    smtpDiv.style.display = m.versand.versandmodus === 'smtp' ? 'block' : 'none';
    [
        {id: 'smtp_host', label: 'Host', type: 'text', placeholder: 'smtp.example.com'},
        {id: 'smtp_port', label: 'Port', type: 'number', placeholder: '587'},
        {id: 'smtp_benutzer', label: 'Benutzer', type: 'text'},
        {id: 'smtp_passwort', label: 'Passwort', type: 'password'},
    ].forEach(f => {
        const g = document.createElement('div');
        g.className = 'form-group';
        const l = document.createElement('label');
        l.textContent = f.label + (m.versand.gesetzt[f.id] ? ' (gesetzt)' : '');
        g.appendChild(l);
        const i = document.createElement('input');
        i.type = f.type;
        i.id = f.id;
        if (f.placeholder) i.placeholder = f.placeholder;
        g.appendChild(i);
        smtpDiv.appendChild(g);
    });

    const verschlGroup = document.createElement('div');
    verschlGroup.className = 'form-group';
    const verschlLabel = document.createElement('label');
    verschlLabel.textContent = 'Verschlüsselung';
    verschlGroup.appendChild(verschlLabel);
    const verschlSelect = document.createElement('select');
    verschlSelect.id = 'smtp_verschluesselung';
    ['ssl', 'starttls'].forEach(v => {
        const opt = document.createElement('option');
        opt.value = v;
        opt.textContent = v.toUpperCase();
        verschlSelect.appendChild(opt);
    });
    verschlGroup.appendChild(verschlSelect);
    smtpDiv.appendChild(verschlGroup);
    form.appendChild(smtpDiv);

    // Submit
    const actions = document.createElement('div');
    actions.className = 'form-actions';
    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = 'Speichern';
    actions.appendChild(submitBtn);
    form.appendChild(actions);

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorDiv.className = 'error hidden';
        const modus = form.querySelector('input[name="versandmodus"]:checked').value;
        const body = {versandmodus: modus};
        if (modus === 'smtp') {
            ['smtp_host', 'smtp_port', 'smtp_benutzer', 'smtp_passwort', 'smtp_verschluesselung'].forEach(f => {
                const val = document.getElementById(f).value.trim();
                if (val) body[f] = f === 'smtp_port' ? parseInt(val) : val;
            });
        }
        submitBtn.disabled = true;
        submitBtn.textContent = 'Wird gespeichert...';
        try {
            await apiCall(`/mandanten/${m.id}/versand`, {method: 'PUT', body: JSON.stringify(body)});
            showToast('Versand-Einstellungen gespeichert', 'success');
            await showMandantDetails(m.id, 'versand');
        } catch (err) {
            errorDiv.textContent = err.message;
            errorDiv.className = 'error';
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Speichern';
        }
    });

    card.appendChild(form);
    main.innerHTML = '';
    main.appendChild(card);
}

// Abonnenten (Schritt 3)
async function renderAbonnenten(m) {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = m.name;
    card.appendChild(title);

    // Tabs
    const tabsNav = document.createElement('div');
    tabsNav.style.marginBottom = '1.5rem';
    tabsNav.style.borderBottom = '1px solid var(--color-border)';
    const tabs = [{id: 'details', label: 'Einstellungen'}, {id: 'versand', label: 'Versand'}, {id: 'abonnenten', label: 'Abonnenten'}];
    tabs.forEach(tab => {
        const btn = document.createElement('button');
        btn.textContent = tab.label;
        btn.style.padding = '0.5rem 1rem';
        btn.style.background = 'none';
        btn.style.border = 'none';
        btn.style.borderBottom = state.currentTab === tab.id ? '2px solid var(--color-primary)' : '2px solid transparent';
        btn.style.cursor = 'pointer';
        btn.style.fontWeight = state.currentTab === tab.id ? '600' : 'normal';
        btn.addEventListener('click', () => showMandantDetails(m.id, tab.id));
        tabsNav.appendChild(btn);
    });
    card.appendChild(tabsNav);

    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading';
    loadingDiv.textContent = 'Lade Abonnenten...';
    card.appendChild(loadingDiv);

    main.innerHTML = '';
    main.appendChild(card);

    try {
        const data = await apiCall(`/mandanten/${m.id}/abonnenten`);
        loadingDiv.remove();

        // Kennzahlen
        const stats = data.kennzahlen || {};
        const statsDiv = document.createElement('div');
        statsDiv.style.display = 'grid';
        statsDiv.style.gridTemplateColumns = 'repeat(4, 1fr)';
        statsDiv.style.gap = '1rem';
        statsDiv.style.marginBottom = '1.5rem';
        [{label: 'Bestätigt', value: stats.bestaetigt || 0, color: 'success'},
         {label: 'Unbestätigt', value: stats.unbestaetigt || 0, color: 'warning'},
         {label: 'Abgemeldet', value: stats.abgemeldet || 0, color: 'error'},
         {label: 'Unzustellbar', value: stats.unzustellbar || 0, color: 'error'}
        ].forEach(s => {
            const box = document.createElement('div');
            box.style.padding = '1rem';
            box.style.background = '#f9fafb';
            box.style.borderRadius = '6px';
            box.style.textAlign = 'center';
            const num = document.createElement('div');
            num.style.fontSize = '2rem';
            num.style.fontWeight = '700';
            num.textContent = s.value;
            box.appendChild(num);
            const lbl = document.createElement('div');
            lbl.style.fontSize = '0.875rem';
            lbl.style.color = '#6b7280';
            lbl.textContent = s.label;
            box.appendChild(lbl);
            statsDiv.appendChild(box);
        });
        card.appendChild(statsDiv);

        // Tabelle
        const table = document.createElement('table');
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        ['E-Mail', 'Status', 'Rolle', 'Interessen', 'Angemeldet'].forEach(h => {
            const th = document.createElement('th');
            th.textContent = h;
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        (data.abonnenten || []).forEach(a => {
            const row = document.createElement('tr');

            const emailCell = document.createElement('td');
            emailCell.textContent = a.email || '(pseudonymisiert)';
            row.appendChild(emailCell);

            const statusCell = document.createElement('td');
            const badge = document.createElement('span');
            badge.className = 'badge';
            if (a.bestaetigt_am) badge.classList.add('badge-success');
            else if (a.abgemeldet_am) badge.classList.add('badge-error');
            else if (a.unzustellbar) badge.classList.add('badge-error');
            else badge.classList.add('badge-warning');
            badge.textContent = a.bestaetigt_am ? 'Bestätigt' : a.abgemeldet_am ? 'Abgemeldet' : a.unzustellbar ? 'Unzustellbar' : 'Unbestätigt';
            statusCell.appendChild(badge);
            row.appendChild(statusCell);

            const rolleCell = document.createElement('td');
            rolleCell.textContent = a.rolle || '-';
            row.appendChild(rolleCell);

            const interessenCell = document.createElement('td');
            interessenCell.textContent = (a.interessen || []).join(', ') || '-';
            row.appendChild(interessenCell);

            const dateCell = document.createElement('td');
            dateCell.textContent = a.angemeldet_am ? new Date(a.angemeldet_am).toLocaleDateString('de-DE') : '-';
            row.appendChild(dateCell);

            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        card.appendChild(table);

    } catch (err) {
        loadingDiv.textContent = 'Fehler: ' + err.message;
        loadingDiv.style.color = 'var(--color-error)';
    }
}

// Initialisierung
document.addEventListener('DOMContentLoaded', () => {
    renderNav();
    loadMandanten();
});
