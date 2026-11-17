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
        if (response.status === 401) {
            throw new Error('Bitte im Portal als Betreiber anmelden');
        }
        if (response.status === 403) {
            // 403 mit meldung -> meldung anzeigen; ohne meldung (oder error="forbidden") -> Anmelde-Text
            if (data.meldung) {
                throw new Error(data.meldung);
            }
            throw new Error('Bitte im Portal als Betreiber anmelden');
        }
        const fehler = new Error(data.meldung || data.error || 'Ein Fehler ist aufgetreten');
        fehler.code = data.error || null;
        fehler.feld = data.feld || null;
        throw fehler;
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
        case 'einstellungen':
            renderEinstellungen();
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
        { id: 'anlegen', label: 'Neuer Mandant' },
        { id: 'einstellungen', label: 'Einstellungen' }
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
        nameBtn.className = 'tabelle-link';
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
        } else if (tab === 'newsletter') {
            renderNewsletter(m);
        } else if (tab === 'import') {
            renderImport(m);
        } else if (tab === 'bilder') {
            renderBilder(m);
        } else if (tab === 'ki') {
            renderMandantKI(m);
        } else {
            renderMandantDetails(m);
        }
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderTabs(m, card) {
    const tabsNav = document.createElement('div');
    tabsNav.style.marginBottom = '1.5rem';
    tabsNav.style.borderBottom = '1px solid var(--color-border)';
    const tabs = [{id: 'details', label: 'Einstellungen'}, {id: 'versand', label: 'Versand'}, {id: 'newsletter', label: 'Newsletter'}, {id: 'abonnenten', label: 'Abonnenten'}, {id: 'import', label: 'Import'}, {id: 'bilder', label: 'Bilder'}, {id: 'ki', label: 'KI'}];
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
}

function renderMandantDetails(m) {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = m.name;
    card.appendChild(title);

    renderTabs(m, card);

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
    aktivGroup.className = 'form-group checkbox-inline';
    const aktivLabel = document.createElement('label');
    const aktivCheckbox = document.createElement('input');
    aktivCheckbox.type = 'checkbox';
    aktivCheckbox.id = 'edit-aktiv';
    aktivCheckbox.checked = m.aktiv;
    aktivLabel.appendChild(aktivCheckbox);
    aktivLabel.appendChild(document.createTextNode('Aktiv'));
    aktivGroup.appendChild(aktivLabel);
    form.appendChild(aktivGroup);

    // Farben (Basis)
    const farbGroup = document.createElement('div');
    farbGroup.className = 'form-group';
    const farbTitle = document.createElement('h3');
    farbTitle.textContent = 'Farben';
    farbGroup.appendChild(farbTitle);

    const farbLabels = {
        farbe_primaer: 'Primärfarbe',
        farbe_akzent: 'Akzentfarbe',
        farbe_hintergrund: 'Hintergrund',
        farbe_text: 'Text'
    };

    ['farbe_primaer', 'farbe_akzent', 'farbe_hintergrund', 'farbe_text'].forEach(f => {
        const fieldGroup = document.createElement('div');
        fieldGroup.className = 'form-group';
        fieldGroup.style.marginBottom = '0.75rem';

        const label = document.createElement('label');
        label.textContent = farbLabels[f];
        fieldGroup.appendChild(label);

        const wrapper = document.createElement('div');
        wrapper.className = 'color-input-wrapper';

        const input = document.createElement('input');
        input.type = 'color';
        input.id = `edit-${f}`;
        input.value = m.design[f] || '#000000';
        wrapper.appendChild(input);

        const hexDisplay = document.createElement('span');
        hexDisplay.className = 'color-hex-display';
        hexDisplay.textContent = m.design[f] || '#000000';
        wrapper.appendChild(hexDisplay);

        const hint = document.createElement('small');
        hint.textContent = '#rrggbb';
        hint.style.marginLeft = '0.5rem';
        hint.style.color = '#9ca3af';
        wrapper.appendChild(hint);

        input.addEventListener('input', () => {
            hexDisplay.textContent = input.value;
        });

        fieldGroup.appendChild(wrapper);
        farbGroup.appendChild(fieldGroup);
    });

    // Balkenfarbe (Newsletter-Layout)
    const balkenFarbeGroup = document.createElement('div');
    balkenFarbeGroup.className = 'form-group';
    balkenFarbeGroup.style.marginBottom = '0.75rem';
    const balkenFarbeLabel = document.createElement('label');
    balkenFarbeLabel.textContent = 'Balkenfarbe (Newsletter)';
    balkenFarbeGroup.appendChild(balkenFarbeLabel);

    // Checkbox "Primärfarbe verwenden"
    const balkenPrimaerCheckbox = document.createElement('input');
    balkenPrimaerCheckbox.type = 'checkbox';
    balkenPrimaerCheckbox.id = 'edit-balken_primaer';
    balkenPrimaerCheckbox.checked = !m.design.balken_farbe;
    const balkenPrimaerLabel = document.createElement('label');
    balkenPrimaerLabel.style.display = 'block';
    balkenPrimaerLabel.style.marginBottom = '0.5rem';
    balkenPrimaerLabel.appendChild(balkenPrimaerCheckbox);
    balkenPrimaerLabel.appendChild(document.createTextNode(' Primärfarbe verwenden'));
    balkenFarbeGroup.appendChild(balkenPrimaerLabel);

    const balkenFarbeWrapper = document.createElement('div');
    balkenFarbeWrapper.className = 'color-input-wrapper';
    balkenFarbeWrapper.id = 'balken-farbe-wrapper';
    balkenFarbeWrapper.style.display = m.design.balken_farbe ? 'flex' : 'none';
    const balkenFarbeInput = document.createElement('input');
    balkenFarbeInput.type = 'color';
    balkenFarbeInput.id = 'edit-balken_farbe';
    balkenFarbeInput.value = m.design.balken_farbe || m.design.farbe_primaer || '#000000';
    balkenFarbeWrapper.appendChild(balkenFarbeInput);
    const balkenFarbeHex = document.createElement('span');
    balkenFarbeHex.className = 'color-hex-display';
    balkenFarbeHex.textContent = m.design.balken_farbe || m.design.farbe_primaer || '#000000';
    balkenFarbeWrapper.appendChild(balkenFarbeHex);
    balkenFarbeInput.addEventListener('input', () => {
        balkenFarbeHex.textContent = balkenFarbeInput.value;
    });
    balkenFarbeGroup.appendChild(balkenFarbeWrapper);

    // Toggle Farbfeld
    balkenPrimaerCheckbox.addEventListener('change', () => {
        balkenFarbeWrapper.style.display = balkenPrimaerCheckbox.checked ? 'none' : 'flex';
    });

    farbGroup.appendChild(balkenFarbeGroup);
    form.appendChild(farbGroup);

    // Logo aus Bildern (Newsletter-Layout)
    const logoGroup = document.createElement('div');
    logoGroup.className = 'form-group';
    const logoLabel = document.createElement('label');
    logoLabel.textContent = 'Logo (Newsletter)';
    logoGroup.appendChild(logoLabel);
    const logoSelect = document.createElement('select');
    logoSelect.id = 'edit-logo_bild_id';
    const logoEmptyOpt = document.createElement('option');
    logoEmptyOpt.value = '';
    logoEmptyOpt.textContent = '(kein Bild / logo_url nutzen)';
    logoSelect.appendChild(logoEmptyOpt);
    logoSelect.disabled = true;
    logoGroup.appendChild(logoSelect);
    const logoHint = document.createElement('small');
    logoHint.textContent = 'Bilder erst im Tab "Bilder" hochladen';
    logoHint.style.color = '#6b7280';
    logoGroup.appendChild(logoHint);
    form.appendChild(logoGroup);

    // Bilder für Logo-Auswahl laden
    (async () => {
        try {
            const bilder = await apiCall(`/mandanten/${m.id}/bilder`);
            logoSelect.disabled = false;
            if (bilder && bilder.length > 0) {
                bilder.forEach(b => {
                    const opt = document.createElement('option');
                    opt.value = b.id;
                    opt.textContent = `${b.alt} (${b.breite}×${b.hoehe})`;
                    opt.selected = m.design.logo_bild_id === b.id;
                    logoSelect.appendChild(opt);
                });
            }
        } catch (err) {
            // Bilder-API nicht verfügbar oder leer
        }
    })();

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
            balken_farbe: document.getElementById('edit-balken_primaer').checked ? '' : document.getElementById('edit-balken_farbe').value,
            schrift: document.getElementById('edit-schrift').value,
            logo_bild_id: document.getElementById('edit-logo_bild_id').value ? parseInt(document.getElementById('edit-logo_bild_id').value) : null,
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

    renderTabs(m, card);

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
        if (f.id === 'smtp_passwort') i.autocomplete = 'new-password';
        if (f.id === 'smtp_benutzer') i.autocomplete = 'off';
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
    const defaultOpt = document.createElement('option');
    defaultOpt.value = '';
    defaultOpt.textContent = '(unverändert)';
    verschlSelect.appendChild(defaultOpt);
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

    await renderVersandRate(m, card);
}

// Versandrate: Mails pro Stunde (GET/PUT /mandanten/<id>/versand-rate, Standard und Bereich kommen aus der GET-Antwort)
async function renderVersandRate(m, card) {
    const rateForm = document.createElement('form');
    rateForm.id = 'versandrate-form';
    rateForm.style.marginTop = '2rem';

    const titel = document.createElement('h3');
    titel.textContent = 'Versandrate';
    rateForm.appendChild(titel);
    card.appendChild(rateForm);

    let rate;
    try {
        rate = await apiCall(`/mandanten/${m.id}/versand-rate`);
    } catch (err) {
        const fehler = document.createElement('div');
        fehler.className = 'error';
        fehler.id = 'versandrate-ladefehler';
        fehler.textContent = 'Versandrate konnte nicht geladen werden: ' + err.message;
        rateForm.appendChild(fehler);
        return;
    }

    const von = rate.erlaubt_von;
    const bis = rate.erlaubt_bis;
    const gruppe = document.createElement('div');
    gruppe.className = 'form-group';
    const label = document.createElement('label');
    label.setAttribute('for', 'versandrate-limit');
    label.textContent = 'Mails pro Stunde';
    gruppe.appendChild(label);
    const eingabe = document.createElement('input');
    eingabe.type = 'number';
    eingabe.id = 'versandrate-limit';
    eingabe.min = String(von);
    eingabe.max = String(bis);
    eingabe.step = '1';
    eingabe.required = true;
    eingabe.value = String(rate.limit_pro_stunde);
    gruppe.appendChild(eingabe);
    const hinweis = document.createElement('small');
    hinweis.id = 'versandrate-hinweis';
    hinweis.textContent = `Standard ${rate.standard}, erlaubt ${von} bis ${bis}`;
    gruppe.appendChild(hinweis);
    const feldFehler = document.createElement('div');
    feldFehler.id = 'versandrate-fehler';
    feldFehler.className = 'field-error hidden';
    gruppe.appendChild(feldFehler);
    rateForm.appendChild(gruppe);

    const speichern = document.createElement('button');
    speichern.type = 'submit';
    speichern.className = 'btn btn-primary';
    speichern.textContent = 'Speichern';
    rateForm.appendChild(speichern);

    const zeigeFehler = (text) => {
        feldFehler.textContent = text || '';
        feldFehler.classList.toggle('hidden', !text);
        if (text) eingabe.setAttribute('aria-invalid', 'true');
        else eingabe.removeAttribute('aria-invalid');
    };
    // Nur ganze Zahlen im erlaubten Bereich; alles andere (leer, 0, 1.5, 601, -1) sperrt den Knopf und meldet am Feld
    const pruefen = () => {
        const roh = eingabe.value.trim();
        const gueltig = /^\d+$/.test(roh) && Number(roh) >= von && Number(roh) <= bis;
        speichern.disabled = !gueltig;
        zeigeFehler(gueltig ? '' : `Bitte eine ganze Zahl von ${von} bis ${bis} eingeben.`);
        return gueltig ? Number(roh) : null;
    };
    eingabe.addEventListener('input', pruefen);

    rateForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const wert = pruefen();
        if (wert === null) return;
        speichern.disabled = true;
        speichern.textContent = 'Wird gespeichert...';
        try {
            const antwort = await apiCall(`/mandanten/${m.id}/versand-rate`, {method: 'PUT', body: JSON.stringify({limit_pro_stunde: wert})});
            eingabe.value = String(antwort.limit_pro_stunde);
            zeigeFehler('');
            showToast('Mails pro Stunde gespeichert', 'success');
        } catch (err) {
            zeigeFehler(err.message);
        } finally {
            speichern.textContent = 'Speichern';
            speichern.disabled = false;
        }
    });
}

// Einstellungen (global)
async function renderEinstellungen() {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = 'Einstellungen';
    card.appendChild(title);

    // KI-Zugang
    const kiSection = document.createElement('div');
    kiSection.style.marginTop = '2rem';
    const kiTitle = document.createElement('h3');
    kiTitle.textContent = 'KI-Zugang';
    kiSection.appendChild(kiTitle);

    const kiForm = document.createElement('form');
    kiForm.id = 'ki-form';

    const kiGroup = document.createElement('div');
    kiGroup.className = 'form-group';
    const kiLabel = document.createElement('label');
    kiLabel.textContent = 'API-Schlüssel (Claude)';
    kiGroup.appendChild(kiLabel);
    const kiInput = document.createElement('input');
    kiInput.type = 'password';
    kiInput.id = 'ki-schluessel';
    kiInput.placeholder = 'sk-...';
    kiInput.autocomplete = 'off';
    kiGroup.appendChild(kiInput);
    const kiHint = document.createElement('small');
    kiHint.textContent = 'Wird verschlüsselt gespeichert, nie angezeigt. Leer lassen = nicht ändern.';
    kiGroup.appendChild(kiHint);
    kiForm.appendChild(kiGroup);

    const kiError = document.createElement('div');
    kiError.className = 'error hidden';
    kiError.id = 'ki-error';
    kiForm.appendChild(kiError);

    const kiBtn = document.createElement('button');
    kiBtn.type = 'submit';
    kiBtn.className = 'btn btn-primary';
    kiBtn.textContent = 'Schlüssel speichern';
    kiForm.appendChild(kiBtn);

    kiForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const errorDiv = document.getElementById('ki-error');
        errorDiv.classList.add('hidden');

        const schluessel = document.getElementById('ki-schluessel').value.trim();
        if (!schluessel) {
            errorDiv.textContent = 'Bitte Schlüssel eingeben';
            errorDiv.classList.remove('hidden');
            return;
        }

        try {
            await apiCall('/ki', {
                method: 'PUT',
                body: JSON.stringify({schluessel})
            });
            showToast('KI-Schlüssel gespeichert', 'success');
            document.getElementById('ki-schluessel').value = '';
        } catch (err) {
            errorDiv.textContent = err.message;
            errorDiv.classList.remove('hidden');
        }
    });

    kiSection.appendChild(kiForm);
    card.appendChild(kiSection);

    main.innerHTML = '';
    main.appendChild(card);
}

// KI-Einstellungen je Mandant
async function renderMandantKI(m) {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = m.name;
    card.appendChild(title);

    renderTabs(m, card);

    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading';
    loadingDiv.textContent = 'Lade KI-Einstellungen...';
    card.appendChild(loadingDiv);

    main.innerHTML = '';
    main.appendChild(card);

    try {
        const ki = await apiCall(`/mandanten/${m.id}/ki`);
        loadingDiv.remove();

        const subtitle = document.createElement('h3');
        subtitle.textContent = 'KI-Textverbesserung';
        card.appendChild(subtitle);

        // Hinweis
        if (ki.hinweis) {
            const hinweisDiv = document.createElement('div');
            hinweisDiv.style.marginTop = '1rem';
            hinweisDiv.style.padding = '1rem';
            hinweisDiv.style.background = '#f0f9ff';
            hinweisDiv.style.borderRadius = '6px';
            hinweisDiv.style.whiteSpace = 'pre-wrap';
            hinweisDiv.textContent = ki.hinweis;
            card.appendChild(hinweisDiv);
        }

        // Status
        const statusDiv = document.createElement('dl');
        statusDiv.style.marginTop = '1.5rem';
        const statusLabel = document.createElement('dt');
        statusLabel.textContent = 'Status';
        statusLabel.style.fontWeight = '600';
        statusDiv.appendChild(statusLabel);
        const statusValue = document.createElement('dd');
        statusValue.style.marginLeft = '1rem';
        statusValue.textContent = ki.schluessel_gesetzt ? '✓ Schlüssel gesetzt' : '✗ Kein Schlüssel (in globalen Einstellungen hinterlegen)';
        statusValue.style.color = ki.schluessel_gesetzt ? 'var(--color-success)' : 'var(--color-warning)';
        statusDiv.appendChild(statusValue);

        if (ki.modell) {
            const modellLabel = document.createElement('dt');
            modellLabel.textContent = 'Modell';
            modellLabel.style.fontWeight = '600';
            modellLabel.style.marginTop = '0.5rem';
            statusDiv.appendChild(modellLabel);
            const modellValue = document.createElement('dd');
            modellValue.style.marginLeft = '1rem';
            modellValue.textContent = ki.modell;
            statusDiv.appendChild(modellValue);
        }

        if (ki.limit_je_stunde) {
            const limitLabel = document.createElement('dt');
            limitLabel.textContent = 'Limit';
            limitLabel.style.fontWeight = '600';
            limitLabel.style.marginTop = '0.5rem';
            statusDiv.appendChild(limitLabel);
            const limitValue = document.createElement('dd');
            limitValue.style.marginLeft = '1rem';
            limitValue.textContent = `${ki.limit_je_stunde} Anfragen pro Stunde`;
            statusDiv.appendChild(limitValue);
        }

        card.appendChild(statusDiv);

        // Schalter
        const form = document.createElement('form');
        form.style.marginTop = '1.5rem';

        const aktivGroup = document.createElement('div');
        aktivGroup.className = 'form-group';
        const aktivLabel = document.createElement('label');
        const aktivCheckbox = document.createElement('input');
        aktivCheckbox.type = 'checkbox';
        aktivCheckbox.id = 'ki-aktiv';
        aktivCheckbox.checked = ki.aktiv;
        aktivLabel.appendChild(aktivCheckbox);
        aktivLabel.appendChild(document.createTextNode(' KI-Textverbesserung für diesen Mandanten aktivieren'));
        aktivGroup.appendChild(aktivLabel);
        form.appendChild(aktivGroup);

        const errorDiv = document.createElement('div');
        errorDiv.className = 'error hidden';
        errorDiv.id = 'ki-mandant-error';
        form.appendChild(errorDiv);

        const saveBtn = document.createElement('button');
        saveBtn.type = 'submit';
        saveBtn.className = 'btn btn-primary';
        saveBtn.textContent = 'Speichern';
        form.appendChild(saveBtn);

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const errorDiv = document.getElementById('ki-mandant-error');
            errorDiv.classList.add('hidden');

            const aktiv = document.getElementById('ki-aktiv').checked;

            try {
                await apiCall(`/mandanten/${m.id}/ki`, {
                    method: 'PUT',
                    body: JSON.stringify({aktiv})
                });
                showToast('KI-Einstellungen gespeichert', 'success');
                renderMandantKI(m);
            } catch (err) {
                errorDiv.textContent = err.message;
                errorDiv.classList.remove('hidden');
            }
        });

        card.appendChild(form);

    } catch (err) {
        loadingDiv.textContent = 'Fehler: ' + err.message;
        loadingDiv.style.color = 'var(--color-error)';
    }
}

// Abonnenten (Schritt 3)
// Newsletter
async function renderNewsletter(m) {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = m.name;
    card.appendChild(title);

    renderTabs(m, card);

    // Entwurfs-Liste laden
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading';
    loadingDiv.textContent = 'Lade Entwürfe...';
    card.appendChild(loadingDiv);

    main.innerHTML = '';
    main.appendChild(card);

    try {
        const data = await apiCall(`/mandanten/${m.id}/entwuerfe`);
        loadingDiv.remove();

        // Entwurfs-Liste
        if (data.entwuerfe && data.entwuerfe.length > 0) {
            const subtitle = document.createElement('h3');
            subtitle.textContent = 'Entwürfe';
            card.appendChild(subtitle);

            const table = document.createElement('table');
            const thead = document.createElement('thead');
            const headerRow = document.createElement('tr');
            ['Betreff', 'Format', 'Status', 'Ziel', 'Erstellt'].forEach(h => {
                const th = document.createElement('th');
                th.textContent = h;
                headerRow.appendChild(th);
            });
            thead.appendChild(headerRow);
            table.appendChild(thead);

            const tbody = document.createElement('tbody');
            data.entwuerfe.forEach(e => {
                const row = document.createElement('tr');
                row.style.cursor = 'pointer';
                row.addEventListener('click', () => renderNewsletterEditor(m, e.id));

                const betreffCell = document.createElement('td');
                betreffCell.textContent = e.betreff;
                row.appendChild(betreffCell);

                const formatCell = document.createElement('td');
                formatCell.textContent = e.format === 'layout' ? 'Layout' : 'Text';
                row.appendChild(formatCell);

                const statusCell = document.createElement('td');
                statusCell.textContent = e.status;
                row.appendChild(statusCell);

                const zielCell = document.createElement('td');
                zielCell.textContent = e.ziel;
                row.appendChild(zielCell);

                const erstelltCell = document.createElement('td');
                erstelltCell.textContent = new Date(e.erstellt).toLocaleString('de-DE');
                row.appendChild(erstelltCell);

                tbody.appendChild(row);
            });
            table.appendChild(tbody);
            card.appendChild(table);
        } else {
            const noEntwuerfe = document.createElement('p');
            noEntwuerfe.textContent = 'Noch keine Entwürfe vorhanden.';
            noEntwuerfe.style.color = '#6b7280';
            card.appendChild(noEntwuerfe);
        }

        // Neuen Entwurf erstellen Button
        const newBtn = document.createElement('button');
        newBtn.type = 'button';
        newBtn.className = 'btn btn-primary';
        newBtn.textContent = 'Neuer Entwurf';
        newBtn.style.marginTop = '1rem';
        newBtn.addEventListener('click', () => renderNewsletterEditor(m, null));
        card.appendChild(newBtn);

        // Testlisten-Verwaltung
        await renderTestliste(m, card);

    } catch (err) {
        loadingDiv.textContent = 'Fehler: ' + err.message;
        loadingDiv.style.color = 'var(--color-error)';
    }
}

// Testlisten-Verwaltung
// Backend: GET /api/v1/betreiber/mandanten/<id>/testliste liefert {"adressen": […]} (betreiber.py Z. 419)
async function renderTestliste(m, card) {
    const subtitle = document.createElement('h3');
    subtitle.textContent = 'Testliste';
    subtitle.style.marginTop = '2rem';
    card.appendChild(subtitle);

    const description = document.createElement('p');
    description.textContent = 'E-Mail-Adressen für Test-Versendungen (max. 50)';
    description.style.color = '#6b7280';
    description.style.marginBottom = '1rem';
    card.appendChild(description);

    const testlisteContainer = document.createElement('div');
    testlisteContainer.id = 'testliste-container';
    card.appendChild(testlisteContainer);

    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading';
    loadingDiv.textContent = 'Lade Testliste...';
    testlisteContainer.appendChild(loadingDiv);

    try {
        const data = await apiCall(`/mandanten/${m.id}/testliste`);
        loadingDiv.remove();

        const adressen = data.adressen || [];
        renderTestlisteUI(m, testlisteContainer, adressen);
    } catch (err) {
        loadingDiv.textContent = 'Fehler beim Laden der Testliste: ' + err.message;
        loadingDiv.style.color = 'var(--color-error)';
    }
}

function renderTestlisteUI(m, container, adressen) {
    container.innerHTML = '';

    // Empfänger-Zähler
    const counter = document.createElement('div');
    counter.id = 'testliste-counter';
    counter.textContent = `Empfänger: ${adressen.length}`;
    counter.style.marginBottom = '1rem';
    counter.style.fontWeight = 'bold';
    container.appendChild(counter);

    // Eingabefeld + Button
    const inputGroup = document.createElement('div');
    inputGroup.style.display = 'flex';
    inputGroup.style.gap = '0.5rem';
    inputGroup.style.marginBottom = '1rem';

    const emailInput = document.createElement('input');
    emailInput.type = 'email';
    emailInput.id = 'testliste-email-input';
    emailInput.placeholder = 'E-Mail-Adresse eingeben';
    emailInput.style.flex = '1';
    emailInput.style.padding = '0.5rem';
    emailInput.style.border = '1px solid var(--color-border)';
    emailInput.style.borderRadius = '0.25rem';

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'btn btn-primary';
    addBtn.textContent = 'Hinzufügen';
    addBtn.disabled = true;

    // Live-Validierung
    emailInput.addEventListener('input', () => {
        const email = emailInput.value.trim();
        const isValid = email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
        addBtn.disabled = !isValid;
        emailInput.style.borderColor = email && !isValid ? 'var(--color-error)' : 'var(--color-border)';
    });

    // Hinzufügen
    const addEmail = async () => {
        const email = emailInput.value.trim().toLowerCase();
        if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            return;
        }

        if (adressen.includes(email)) {
            showToast('E-Mail-Adresse ist bereits in der Testliste', 'error');
            return;
        }

        if (adressen.length >= 50) {
            showToast('Maximal 50 Adressen erlaubt', 'error');
            return;
        }

        const neueAdressen = [...adressen, email];
        const success = await saveTestliste(m, neueAdressen, container);
        if (success) {
            emailInput.value = '';
            addBtn.disabled = true;
        }
    };

    addBtn.addEventListener('click', addEmail);
    emailInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            addEmail();
        }
    });

    inputGroup.appendChild(emailInput);
    inputGroup.appendChild(addBtn);
    container.appendChild(inputGroup);

    // Fehlermeldung
    const errorDiv = document.createElement('div');
    errorDiv.id = 'testliste-error';
    errorDiv.className = 'error hidden';
    container.appendChild(errorDiv);

    // Liste der Adressen
    if (adressen.length > 0) {
        const list = document.createElement('ul');
        list.style.listStyle = 'none';
        list.style.padding = '0';
        list.style.margin = '0';

        adressen.forEach(email => {
            const item = document.createElement('li');
            item.style.display = 'flex';
            item.style.justifyContent = 'space-between';
            item.style.alignItems = 'center';
            item.style.padding = '0.5rem';
            item.style.borderBottom = '1px solid var(--color-border)';

            const emailSpan = document.createElement('span');
            emailSpan.textContent = email;
            item.appendChild(emailSpan);

            const deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.className = 'btn btn-secondary';
            deleteBtn.textContent = 'Löschen';
            deleteBtn.style.padding = '0.25rem 0.75rem';
            deleteBtn.style.fontSize = '0.875rem';
            deleteBtn.addEventListener('click', async () => {
                const neueAdressen = adressen.filter(a => a !== email);
                await saveTestliste(m, neueAdressen, container);
            });
            item.appendChild(deleteBtn);

            list.appendChild(item);
        });

        container.appendChild(list);
    } else {
        const empty = document.createElement('p');
        empty.textContent = 'Noch keine Adressen in der Testliste.';
        empty.style.color = '#6b7280';
        container.appendChild(empty);
    }
}

// Backend: PUT /api/v1/betreiber/mandanten/<id>/testliste erwartet {"adressen": […]} (betreiber.py Z. 427)
async function saveTestliste(m, adressen, container) {
    const errorDiv = document.getElementById('testliste-error');
    errorDiv.className = 'error hidden';

    try {
        await apiCall(`/mandanten/${m.id}/testliste`, {
            method: 'PUT',
            body: JSON.stringify({ adressen: adressen })
        });

        showToast('Testliste erfolgreich gespeichert', 'success');
        renderTestlisteUI(m, container, adressen);
        return true;
    } catch (err) {
        errorDiv.textContent = err.message;
        errorDiv.className = 'error';
        showToast('Fehler beim Speichern: ' + err.message, 'error');
        return false;
    }
}

async function renderNewsletterEditor(m, entwurfId) {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = m.name;
    card.appendChild(title);

    renderTabs(m, card);

    const subtitle = document.createElement('h3');
    subtitle.textContent = entwurfId ? 'Entwurf bearbeiten' : 'Neuer Entwurf';
    card.appendChild(subtitle);

    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading';
    loadingDiv.textContent = 'Lade...';
    card.appendChild(loadingDiv);

    main.innerHTML = '';
    main.appendChild(card);

    let entwurf = null;
    let tagsData = null;
    let kiSettings = null;

    try {
        // Paralleles Laden
        const promises = [
            apiCall(`/mandanten/${m.id}/abonnenten/tags`),
            apiCall(`/mandanten/${m.id}/ki`)
        ];
        if (entwurfId) {
            promises.push(apiCall(`/mandanten/${m.id}/entwuerfe/${entwurfId}`));
        }
        const results = await Promise.all(promises);
        tagsData = results[0];
        kiSettings = results[1];
        if (entwurfId) entwurf = results[2];

        loadingDiv.remove();

        let format = entwurf && entwurf.format === 'layout' ? 'layout' : 'text';
        let layoutUi = null;
        let vorschauLauf = 0;                                                                  // nur die jüngste Empfängerzahl-Antwort zählt

        // Formular
        const form = document.createElement('form');
        form.id = 'newsletter-form';

        // Betreff
        const betreffGroup = document.createElement('div');
        betreffGroup.className = 'form-group';
        const betreffLabel = document.createElement('label');
        betreffLabel.textContent = 'Betreff *';
        betreffGroup.appendChild(betreffLabel);
        const betreffInput = document.createElement('input');
        betreffInput.type = 'text';
        betreffInput.id = 'newsletter-betreff';
        betreffInput.maxLength = 150;
        betreffInput.required = true;
        betreffInput.value = entwurf ? entwurf.betreff : '';
        betreffGroup.appendChild(betreffInput);
        const betreffHint = document.createElement('small');
        betreffHint.textContent = '1-150 Zeichen';
        betreffGroup.appendChild(betreffHint);
        form.appendChild(betreffGroup);

        // Format: Text oder Layout (bei bestehenden Entwürfen nicht änderbar)
        const formatGroup = document.createElement('div');
        formatGroup.className = 'form-group';
        formatGroup.id = 'format-gruppe';
        const formatLabel = document.createElement('label');
        formatLabel.textContent = 'Format';
        formatGroup.appendChild(formatLabel);
        [['text', 'Text'], ['layout', 'Layout (Balken, formatierter Text, Bilder)']].forEach(([wert, beschriftung]) => {
            const label = document.createElement('label');
            label.style.display = 'inline-block';
            label.style.marginRight = '1.5rem';
            const radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = 'format';
            radio.value = wert;
            radio.checked = format === wert;
            radio.disabled = !!entwurf;
            radio.addEventListener('change', () => { if (radio.checked) setzeFormat(wert); });
            label.appendChild(radio);
            label.appendChild(document.createTextNode(' ' + beschriftung));
            formatGroup.appendChild(label);
        });
        form.appendChild(formatGroup);

        // Text
        const textGroup = document.createElement('div');
        textGroup.className = 'form-group';
        textGroup.id = 'text-gruppe';
        const textLabel = document.createElement('label');
        textLabel.textContent = 'Text *';
        textGroup.appendChild(textLabel);
        const textInput = document.createElement('textarea');
        textInput.id = 'newsletter-text';
        textInput.rows = 12;
        textInput.maxLength = 50000;
        textInput.required = true;
        textInput.value = entwurf ? entwurf.text : '';
        textGroup.appendChild(textInput);
        const textHint = document.createElement('small');
        textHint.textContent = '1-50000 Zeichen. Leerzeilen sind Absätze, https-URLs werden automatisch verlinkt.';
        textGroup.appendChild(textHint);
        form.appendChild(textGroup);

        // KI-Textverbesserung
        if (kiSettings && kiSettings.aktiv && kiSettings.schluessel_gesetzt) {
            const kiGroup = document.createElement('div');
            kiGroup.className = 'form-group';
            kiGroup.id = 'ki-gruppe';
            kiGroup.style.marginTop = '1.5rem';
            kiGroup.style.padding = '1rem';
            kiGroup.style.background = '#f0f9ff';
            kiGroup.style.borderRadius = '6px';

            const kiTitle = document.createElement('h4');
            kiTitle.textContent = 'KI-Textverbesserung';
            kiTitle.style.marginBottom = '0.5rem';
            kiGroup.appendChild(kiTitle);

            if (kiSettings.hinweis) {
                const hinweisP = document.createElement('p');
                hinweisP.style.fontSize = '0.875rem';
                hinweisP.style.color = '#6b7280';
                hinweisP.style.marginBottom = '0.75rem';
                hinweisP.textContent = kiSettings.hinweis;
                kiGroup.appendChild(hinweisP);
            }

            const anweisungLabel = document.createElement('label');
            anweisungLabel.textContent = 'Anweisung (optional, max 300 Zeichen)';
            anweisungLabel.style.display = 'block';
            anweisungLabel.style.marginBottom = '0.25rem';
            anweisungLabel.style.fontSize = '0.875rem';
            kiGroup.appendChild(anweisungLabel);

            const anweisungInput = document.createElement('input');
            anweisungInput.type = 'text';
            anweisungInput.id = 'ki-anweisung';
            anweisungInput.maxLength = 300;
            anweisungInput.placeholder = 'z.B. "Kürzer und prägnanter"';
            anweisungInput.style.width = '100%';
            kiGroup.appendChild(anweisungInput);

            const verbessernBtn = document.createElement('button');
            verbessernBtn.type = 'button';
            verbessernBtn.className = 'btn btn-secondary';
            verbessernBtn.textContent = 'Text verbessern';
            verbessernBtn.id = 'ki-verbessern-btn';
            verbessernBtn.style.marginTop = '0.75rem';
            verbessernBtn.addEventListener('click', () => textVerbessern(m));
            kiGroup.appendChild(verbessernBtn);

            const kiError = document.createElement('div');
            kiError.className = 'error hidden';
            kiError.id = 'ki-verbesserung-error';
            kiError.style.marginTop = '0.75rem';
            kiGroup.appendChild(kiError);

            // Vorschau-Bereich
            const vorschauContainer = document.createElement('div');
            vorschauContainer.id = 'ki-vorschau-container';
            vorschauContainer.className = 'hidden';
            vorschauContainer.style.marginTop = '1rem';
            vorschauContainer.style.padding = '1rem';
            vorschauContainer.style.background = 'white';
            vorschauContainer.style.border = '1px solid var(--color-border)';
            vorschauContainer.style.borderRadius = '6px';

            const vorschauTitle = document.createElement('h5');
            vorschauTitle.textContent = 'Vorschlag';
            vorschauTitle.style.marginBottom = '0.75rem';
            vorschauContainer.appendChild(vorschauTitle);

            const vorschauBetreff = document.createElement('div');
            vorschauBetreff.id = 'ki-vorschau-betreff';
            vorschauBetreff.className = 'hidden';
            vorschauBetreff.style.marginBottom = '0.75rem';
            const vorschauBetreffLabel = document.createElement('strong');
            vorschauBetreffLabel.textContent = 'Betreff:';
            vorschauBetreff.appendChild(vorschauBetreffLabel);
            const vorschauBetreffText = document.createElement('div');
            vorschauBetreffText.id = 'ki-vorschau-betreff-text';
            vorschauBetreffText.style.marginTop = '0.25rem';
            vorschauBetreffText.style.padding = '0.5rem';
            vorschauBetreffText.style.background = '#f9fafb';
            vorschauBetreffText.style.borderRadius = '4px';
            vorschauBetreff.appendChild(vorschauBetreffText);
            vorschauContainer.appendChild(vorschauBetreff);

            const vorschauTextDiv = document.createElement('div');
            const vorschauTextLabel = document.createElement('strong');
            vorschauTextLabel.textContent = 'Text:';
            vorschauTextDiv.appendChild(vorschauTextLabel);
            const vorschauTextContent = document.createElement('div');
            vorschauTextContent.id = 'ki-vorschau-text';
            vorschauTextContent.style.marginTop = '0.25rem';
            vorschauTextContent.style.padding = '0.5rem';
            vorschauTextContent.style.background = '#f9fafb';
            vorschauTextContent.style.borderRadius = '4px';
            vorschauTextContent.style.whiteSpace = 'pre-wrap';
            vorschauTextDiv.appendChild(vorschauTextContent);
            vorschauContainer.appendChild(vorschauTextDiv);

            const vorschauActions = document.createElement('div');
            vorschauActions.style.marginTop = '0.75rem';
            vorschauActions.style.display = 'flex';
            vorschauActions.style.gap = '0.5rem';

            const uebernehmenBtn = document.createElement('button');
            uebernehmenBtn.type = 'button';
            uebernehmenBtn.className = 'btn btn-primary';
            uebernehmenBtn.textContent = 'Übernehmen';
            uebernehmenBtn.addEventListener('click', uebernehmenVorschlag);
            vorschauActions.appendChild(uebernehmenBtn);

            const verwerfenBtn = document.createElement('button');
            verwerfenBtn.type = 'button';
            verwerfenBtn.className = 'btn btn-secondary';
            verwerfenBtn.textContent = 'Verwerfen';
            verwerfenBtn.addEventListener('click', () => {
                document.getElementById('ki-vorschau-container').classList.add('hidden');
                delete state.kiVorschlag;
            });
            vorschauActions.appendChild(verwerfenBtn);

            vorschauContainer.appendChild(vorschauActions);
            kiGroup.appendChild(vorschauContainer);

            form.appendChild(kiGroup);
        }

        // Layout-Editor (Balken, formatierter Text, Bilder, Vorschau)
        const layoutHost = document.createElement('div');
        layoutHost.id = 'layout-host';
        form.appendChild(layoutHost);

        async function setzeFormat(f) {
            format = f;
            textGroup.classList.toggle('hidden', f === 'layout');
            textInput.required = f !== 'layout';
            const kiBereich = form.querySelector('#ki-gruppe');
            if (kiBereich) kiBereich.classList.toggle('hidden', f === 'layout');
            layoutHost.classList.toggle('hidden', f !== 'layout');
            if (f === 'layout' && !layoutUi) {
                // Bestehende Entwürfe im alten Layout (version 1, eine Spalte) bleiben im alten Editor; neue Entwürfe nutzen zwei Spalten (version 2)
                const altesLayout = !!(entwurf && entwurf.blocks && entwurf.blocks.version === 1);
                layoutUi = (altesLayout ? baueLayoutEditor : baueLayoutEditorV2)(m, entwurf, () => betreffInput.value);
                if (altesLayout) {
                    const hinweisAlt = document.createElement('p');
                    hinweisAlt.className = 'layout-hinweis-v1';
                    hinweisAlt.style.color = '#6b7280';
                    hinweisAlt.textContent = 'Dieser Entwurf nutzt das frühere Layout mit einer Spalte und bleibt so. Neue Entwürfe haben zwei Spalten.';
                    layoutHost.appendChild(hinweisAlt);
                }
                layoutHost.appendChild(layoutUi.el);
                try {
                    await layoutUi.ladeBilder();
                } catch (err) {
                    const fehlerFeld = document.getElementById('newsletter-error');
                    fehlerFeld.textContent = 'Bilder konnten nicht geladen werden: ' + err.message;
                    fehlerFeld.classList.remove('hidden');
                }
            }
        }

        // Ziel
        const zielGroup = document.createElement('div');
        zielGroup.className = 'form-group';
        const zielLabel = document.createElement('label');
        zielLabel.textContent = 'Versand an';
        zielGroup.appendChild(zielLabel);
        ['testliste', 'abonnenten'].forEach(ziel => {
            const label = document.createElement('label');
            label.style.display = 'inline-block';
            label.style.marginRight = '1.5rem';
            const radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = 'ziel';
            radio.value = ziel;
            radio.checked = entwurf ? entwurf.ziel === ziel : ziel === 'testliste';
            label.appendChild(radio);
            label.appendChild(document.createTextNode(' ' + (ziel === 'testliste' ? 'Testliste' : 'Abonnenten')));
            zielGroup.appendChild(label);
        });
        form.appendChild(zielGroup);

        // Zielgruppe Titel
        const zielgruppeTitle = document.createElement('h4');
        zielgruppeTitle.textContent = 'Zielgruppe (Segment)';
        zielgruppeTitle.style.marginTop = '1.5rem';
        form.appendChild(zielgruppeTitle);

        // Rollen
        if (m.design && m.design.rollen && m.design.rollen.length > 0) {
            const rollenGroup = document.createElement('div');
            rollenGroup.className = 'form-group';
            const rollenLabel = document.createElement('label');
            rollenLabel.textContent = 'Rollen';
            rollenGroup.appendChild(rollenLabel);
            m.design.rollen.forEach(rolle => {
                const label = document.createElement('label');
                label.style.display = 'block';
                label.style.marginTop = '0.25rem';
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'segment-rolle';
                checkbox.addEventListener('change', segmentGeaendert);
                checkbox.value = rolle.wert;
                if (entwurf && entwurf.segment.rollen && entwurf.segment.rollen.includes(rolle.wert)) {
                    checkbox.checked = true;
                }
                label.appendChild(checkbox);
                label.appendChild(document.createTextNode(' ' + rolle.label));
                rollenGroup.appendChild(label);
            });
            form.appendChild(rollenGroup);
        }

        // Interessen
        if (m.design && m.design.interessen && m.design.interessen.length > 0) {
            const interessenGroup = document.createElement('div');
            interessenGroup.className = 'form-group';
            const interessenLabel = document.createElement('label');
            interessenLabel.textContent = 'Interessen';
            interessenGroup.appendChild(interessenLabel);
            m.design.interessen.forEach(interesse => {
                const label = document.createElement('label');
                label.style.display = 'block';
                label.style.marginTop = '0.25rem';
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'segment-interesse';
                checkbox.addEventListener('change', segmentGeaendert);
                checkbox.value = interesse.wert;
                if (entwurf && entwurf.segment.interessen && entwurf.segment.interessen.includes(interesse.wert)) {
                    checkbox.checked = true;
                }
                label.appendChild(checkbox);
                label.appendChild(document.createTextNode(' ' + interesse.label));
                interessenGroup.appendChild(label);
            });
            form.appendChild(interessenGroup);
        }

        // Tags: Modus (vier Möglichkeiten) und Auswahl; bei "nur ohne jeden Tag" entfällt die Liste
        const gespeicherterModus = entwurf && entwurf.segment ? entwurf.segment.tags_modus : null;
        if ((tagsData.tags && tagsData.tags.length > 0) || gespeicherterModus === 'ohne_tags') {
            const tagsModusGroup = document.createElement('div');
            tagsModusGroup.className = 'form-group';
            tagsModusGroup.id = 'segment-modus-gruppe';
            const tagsModusLabel = document.createElement('label');
            tagsModusLabel.textContent = 'Tag-Auswahl';
            tagsModusGroup.appendChild(tagsModusLabel);
            [
                ['oder', 'mindestens einer der Tags'],
                ['und', 'alle Tags'],
                ['ausser', 'alle außer mit diesen Tags'],
                ['ohne_tags', 'nur ohne jeden Tag'],
            ].forEach(([mode, beschriftung]) => {
                const label = document.createElement('label');
                label.style.display = 'block';
                label.style.marginTop = '0.25rem';
                const radio = document.createElement('input');
                radio.type = 'radio';
                radio.name = 'tags_modus';
                radio.value = mode;
                radio.checked = entwurf ? (gespeicherterModus || 'oder') === mode : mode === 'oder';
                radio.addEventListener('change', () => { if (radio.checked) segmentGeaendert(); });
                label.appendChild(radio);
                label.appendChild(document.createTextNode(' ' + beschriftung));
                tagsModusGroup.appendChild(label);
            });
            const tagsModusHint = document.createElement('small');
            tagsModusHint.textContent = 'Zwischen Rolle, Interessen und Tags gilt immer UND.';
            tagsModusHint.style.display = 'block';
            tagsModusHint.style.marginTop = '0.25rem';
            tagsModusHint.style.color = '#6b7280';
            tagsModusGroup.appendChild(tagsModusHint);
            const segmentFehler = document.createElement('div');
            segmentFehler.id = 'segment-fehler';
            segmentFehler.className = 'field-error hidden';
            tagsModusGroup.appendChild(segmentFehler);
            form.appendChild(tagsModusGroup);

            const tagsGroup = document.createElement('div');
            tagsGroup.className = 'form-group';
            tagsGroup.id = 'segment-tags-gruppe';
            const tagsLabel = document.createElement('label');
            tagsLabel.textContent = 'Tags';
            tagsGroup.appendChild(tagsLabel);
            (tagsData.tags || []).forEach(tagObj => {
                const label = document.createElement('label');
                label.style.display = 'block';
                label.style.marginTop = '0.25rem';
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'segment-tag';
                checkbox.value = tagObj.tag;
                if (entwurf && entwurf.segment.tags && entwurf.segment.tags.includes(tagObj.tag)) {
                    checkbox.checked = true;
                }
                checkbox.addEventListener('change', segmentGeaendert);
                label.appendChild(checkbox);
                label.appendChild(document.createTextNode(' ' + tagObj.tag + ' (' + tagObj.anzahl + ')'));
                tagsGroup.appendChild(label);
            });
            form.appendChild(tagsGroup);
        }

        // Empfängerzahl-Vorschau
        const vorschauDiv = document.createElement('div');
        vorschauDiv.style.marginTop = '1.5rem';
        vorschauDiv.style.padding = '1rem';
        vorschauDiv.style.background = '#f0f9ff';
        vorschauDiv.style.borderRadius = '6px';
        const vorschauText = document.createElement('strong');
        vorschauText.id = 'vorschau-anzahl';
        vorschauText.textContent = 'Empfänger: ...';
        vorschauDiv.appendChild(vorschauText);
        const vorschauBtn = document.createElement('button');
        vorschauBtn.type = 'button';
        vorschauBtn.className = 'btn btn-secondary';
        vorschauBtn.textContent = 'Empfänger aktualisieren';
        vorschauBtn.style.marginLeft = '1rem';
        vorschauBtn.addEventListener('click', updateVorschau);
        vorschauDiv.appendChild(vorschauBtn);
        form.appendChild(vorschauDiv);

        const errorDiv = document.createElement('div');
        errorDiv.className = 'error hidden';
        errorDiv.id = 'newsletter-error';
        form.appendChild(errorDiv);

        // Buttons
        const actions = document.createElement('div');
        actions.className = 'form-actions';
        actions.style.marginTop = '1.5rem';

        const saveBtn = document.createElement('button');
        saveBtn.type = 'submit';
        saveBtn.className = 'btn btn-primary';
        saveBtn.textContent = entwurfId ? 'Speichern' : 'Entwurf anlegen';
        actions.appendChild(saveBtn);

        if (entwurfId && entwurf.status === 'entwurf') {
            const testmailBtn = document.createElement('button');
            testmailBtn.type = 'button';
            testmailBtn.className = 'btn btn-secondary';
            testmailBtn.textContent = 'Testmail senden';
            testmailBtn.addEventListener('click', () => sendTestmail(m, entwurfId));
            actions.appendChild(testmailBtn);

            const freigebenBtn = document.createElement('button');
            freigebenBtn.type = 'button';
            freigebenBtn.className = 'btn btn-primary';
            freigebenBtn.textContent = 'Freigeben & Versenden';
            freigebenBtn.addEventListener('click', () => freigebenEntwurf(m, entwurfId, entwurf.content_hash));
            actions.appendChild(freigebenBtn);
        }

        if (entwurf && entwurf.ansicht_url && /^(https?:\/\/|\/)/.test(entwurf.ansicht_url)) {
            const ansichtLink = document.createElement('a');
            ansichtLink.id = 'ansicht-link';
            ansichtLink.className = 'btn btn-secondary';
            ansichtLink.href = entwurf.ansicht_url;
            ansichtLink.target = '_blank';
            ansichtLink.rel = 'noopener noreferrer';
            ansichtLink.textContent = 'Im Browser ansehen';
            actions.appendChild(ansichtLink);
        }

        const backBtn = document.createElement('button');
        backBtn.type = 'button';
        backBtn.className = 'btn btn-secondary';
        backBtn.textContent = 'Zurück zur Liste';
        backBtn.addEventListener('click', () => renderNewsletter(m));
        actions.appendChild(backBtn);

        form.appendChild(actions);

        // Submit Handler
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            await saveEntwurf(m, entwurfId);
        });

        card.appendChild(form);

        if (format === 'layout') await setzeFormat('layout');

        segmentAnzeige();

        // Initial Vorschau laden wenn bestehender Entwurf
        if (entwurfId) {
            loadEmpfaengervorschau(m, entwurfId);
        } else {
            updateVorschau();
        }

        // Segment aus der Auswahl lesen. ohne_tags schickt nie tags (auch nicht leer), ausser verlangt mindestens einen Tag.
        function segmentLesen() {
            const rollen = Array.from(document.querySelectorAll('.segment-rolle:checked')).map(cb => cb.value);
            const interessen = Array.from(document.querySelectorAll('.segment-interesse:checked')).map(cb => cb.value);
            const tags = Array.from(document.querySelectorAll('.segment-tag:checked')).map(cb => cb.value);
            const modus = document.querySelector('input[name="tags_modus"]:checked')?.value || 'oder';

            const segment = {};
            if (rollen.length > 0) segment.rollen = rollen;
            if (interessen.length > 0) segment.interessen = interessen;
            let fehler = null;
            if (modus === 'ohne_tags') {
                segment.tags_modus = 'ohne_tags';
            } else if (tags.length > 0) {
                segment.tags = tags;
                segment.tags_modus = modus;
            } else if (modus === 'ausser') {
                fehler = 'Bitte mindestens einen Tag wählen, dessen Abonnentinnen ausgeschlossen werden.';
            }
            return {segment, fehler};
        }

        function zeigeSegmentFehler(text) {
            const feld = document.getElementById('segment-fehler');
            if (!feld) return;
            feld.textContent = text || '';
            feld.classList.toggle('hidden', !text);
        }

        // Tag-Liste bei "nur ohne jeden Tag" ausblenden, Pflicht bei "ausser" live prüfen, Speichern sperren
        function segmentAnzeige() {
            const modus = document.querySelector('input[name="tags_modus"]:checked')?.value || 'oder';
            const gruppe = document.getElementById('segment-tags-gruppe');
            if (gruppe) gruppe.classList.toggle('hidden', modus === 'ohne_tags');
            const {fehler} = segmentLesen();
            zeigeSegmentFehler(fehler);
            const speichern = document.querySelector('#newsletter-form button[type="submit"]');
            if (speichern) speichern.disabled = !!fehler;
            return fehler;
        }

        function segmentGeaendert() {
            segmentAnzeige();
            updateVorschau();
        }

        async function updateVorschau() {
            const errorDiv = document.getElementById('newsletter-error');
            errorDiv.classList.add('hidden');

            const {segment, fehler} = segmentLesen();
            if (fehler) {
                vorschauLauf++;
                document.getElementById('vorschau-anzahl').textContent = 'Empfänger: –';
                return;
            }

            const lauf = ++vorschauLauf;
            try {
                const result = await apiCall(`/mandanten/${m.id}/abonnenten/vorschau`, {
                    method: 'POST',
                    body: JSON.stringify({segment})
                });
                if (lauf !== vorschauLauf) return;
                document.getElementById('vorschau-anzahl').textContent = `Empfänger: ${result.anzahl}`;
                zeigeSegmentFehler('');
            } catch (err) {
                if (lauf !== vorschauLauf) return;
                if (err.code === 'segment_ungueltig') {
                    document.getElementById('vorschau-anzahl').textContent = 'Empfänger: –';
                    zeigeSegmentFehler(err.message);
                } else {
                    errorDiv.textContent = err.message;
                    errorDiv.classList.remove('hidden');
                }
            }
        }

        async function loadEmpfaengervorschau(mandant, eid) {
            try {
                const result = await apiCall(`/mandanten/${mandant.id}/entwuerfe/${eid}/empfaengervorschau`);
                document.getElementById('vorschau-anzahl').textContent = `Empfänger: ${result.anzahl}`;
            } catch (err) {
                document.getElementById('vorschau-anzahl').textContent = 'Fehler beim Laden';
            }
        }

        async function saveEntwurf(mandant, eid) {
            const errorDiv = document.getElementById('newsletter-error');
            errorDiv.classList.add('hidden');

            const betreff = document.getElementById('newsletter-betreff').value.trim();
            const text = document.getElementById('newsletter-text').value.trim();
            const ziel = document.querySelector('input[name="ziel"]:checked').value;
            const layoutModus = format === 'layout';

            if (!betreff || betreff.length < 1 || betreff.length > 150) {
                errorDiv.textContent = 'Betreff: 1-150 Zeichen erforderlich';
                errorDiv.classList.remove('hidden');
                return;
            }

            let blocks = null;
            if (layoutModus) {
                layoutUi.fehlerLoeschen();
                const gelesen = layoutUi.blocksLesen();
                if (gelesen.fehler.length > 0) {
                    layoutUi.zeigeClientFehler(gelesen.fehler);
                    errorDiv.textContent = 'Bitte die markierten Felder prüfen';
                    errorDiv.classList.remove('hidden');
                    return;
                }
                blocks = gelesen.blocks;
            } else if (!text || text.length < 1 || text.length > 50000) {
                errorDiv.textContent = 'Text: 1-50000 Zeichen erforderlich';
                errorDiv.classList.remove('hidden');
                return;
            }

            const {segment, fehler: segmentFehler} = segmentLesen();
            if (segmentFehler) {
                zeigeSegmentFehler(segmentFehler);
                errorDiv.textContent = 'Bitte die Zielgruppe prüfen';
                errorDiv.classList.remove('hidden');
                return;
            }

            try {
                if (eid) {
                    await apiCall(`/mandanten/${mandant.id}/entwuerfe/${eid}`, {
                        method: 'PUT',
                        body: JSON.stringify(layoutModus ? {betreff, ziel, segment, blocks} : {betreff, text, ziel, segment})
                    });
                    showToast('Entwurf gespeichert', 'success');
                    renderNewsletterEditor(mandant, eid);
                } else {
                    const result = await apiCall(`/mandanten/${mandant.id}/entwuerfe`, {
                        method: 'POST',
                        body: JSON.stringify(layoutModus ? {betreff, ziel, segment, format: 'layout', blocks} : {betreff, text, ziel, segment})
                    });
                    showToast('Entwurf erstellt', 'success');
                    renderNewsletterEditor(mandant, result.id);
                }
            } catch (err) {
                if (layoutModus && err.feld) layoutUi.fehlerZeigen(err.feld, err.message);
                if (err.code === 'segment_ungueltig') zeigeSegmentFehler(err.message);
                errorDiv.textContent = err.message;
                errorDiv.classList.remove('hidden');
            }
        }

        async function sendTestmail(mandant, eid) {
            try {
                const result = await apiCall(`/mandanten/${mandant.id}/entwuerfe/${eid}/testmail`, {
                    method: 'POST',
                    body: JSON.stringify({})
                });

                // Ergebnisse anzeigen
                if (result.status === 'gesendet') {
                    showToast(`Testmail versendet an ${result.gesendet} Adresse(n)`, 'success');
                } else if (result.status === 'teilweise') {
                    const fehlgeschlagen = result.ergebnisse.filter(e => e.ergebnis === 'fehler');
                    const fehlerText = fehlgeschlagen.map(e => `${e.adresse}: ${e.grund || 'Fehler'}`).join(', ');
                    showToast(`Teilweise: ${result.gesendet} OK, ${result.fehler} Fehler. ${fehlerText}`, 'error');
                }
                renderNewsletterEditor(mandant, eid);
            } catch (err) {
                alert('Fehler: ' + err.message);
            }
        }

        async function freigebenEntwurf(mandant, eid, contentHash) {
            try {
                const vorschauResult = await apiCall(`/mandanten/${mandant.id}/entwuerfe/${eid}/empfaengervorschau`);
                const anzahl = vorschauResult.anzahl;

                if (!confirm(`Newsletter jetzt an ${anzahl} Empfänger versenden?`)) {
                    return;
                }

                await apiCall(`/mandanten/${mandant.id}/entwuerfe/${eid}/freigeben`, {
                    method: 'POST',
                    body: JSON.stringify({content_hash: contentHash, bestaetigt: true})
                });
                showToast('Newsletter freigegeben & Versand gestartet', 'success');
                renderNewsletter(mandant);
            } catch (err) {
                alert('Fehler: ' + err.message);
            }
        }

        async function textVerbessern(mandant) {
            const errorDiv = document.getElementById('ki-verbesserung-error');
            errorDiv.classList.add('hidden');

            const betreff = document.getElementById('newsletter-betreff').value.trim();
            const text = document.getElementById('newsletter-text').value.trim();
            const anweisung = document.getElementById('ki-anweisung').value.trim() || null;

            if (!text || text.length > 8000) {
                errorDiv.textContent = 'Text: 1-8000 Zeichen für KI-Verbesserung';
                errorDiv.classList.remove('hidden');
                return;
            }

            if (betreff && betreff.length > 150) {
                errorDiv.textContent = 'Betreff: max 150 Zeichen';
                errorDiv.classList.remove('hidden');
                return;
            }

            const verbessernBtn = document.getElementById('ki-verbessern-btn');
            verbessernBtn.disabled = true;
            verbessernBtn.textContent = 'Wird verbessert...';

            try {
                const body = {text};
                if (betreff) body.betreff = betreff;
                if (anweisung) body.anweisung = anweisung;

                const result = await apiCall(`/mandanten/${mandant.id}/entwuerfe/text-verbessern`, {
                    method: 'POST',
                    body: JSON.stringify(body)
                });

                // Vorschlag speichern
                state.kiVorschlag = result.vorschlag;

                // Vorschau anzeigen
                const vorschauContainer = document.getElementById('ki-vorschau-container');
                const vorschauBetreffDiv = document.getElementById('ki-vorschau-betreff');
                const vorschauBetreffText = document.getElementById('ki-vorschau-betreff-text');
                const vorschauTextContent = document.getElementById('ki-vorschau-text');

                if (result.vorschlag.betreff) {
                    vorschauBetreffText.textContent = result.vorschlag.betreff;
                    vorschauBetreffDiv.classList.remove('hidden');
                } else {
                    vorschauBetreffDiv.classList.add('hidden');
                }

                vorschauTextContent.textContent = result.vorschlag.text;
                vorschauContainer.classList.remove('hidden');

                showToast('Vorschlag generiert', 'success');

            } catch (err) {
                // Fehlerbehandlung nach Docky's Spec
                let message = err.message;
                if (message.includes('funktion_nicht_aktiv')) {
                    message = 'KI-Textverbesserung ist nicht aktiviert';
                } else if (message.includes('kein_ki_zugang')) {
                    message = 'Kein KI-Zugang konfiguriert (in globalen Einstellungen hinterlegen)';
                } else if (message.includes('zeitueberschreitung')) {
                    message = 'Zeitüberschreitung (60 Sekunden). Bitte erneut versuchen.';
                } else if (message.includes('ki_fehler')) {
                    message = 'KI-Fehler. Bitte später erneut versuchen.';
                } else if (message.includes('limit_erreicht')) {
                    message = 'Limit erreicht. Bitte später erneut versuchen.';
                }
                errorDiv.textContent = message;
                errorDiv.classList.remove('hidden');
            } finally {
                verbessernBtn.disabled = false;
                verbessernBtn.textContent = 'Text verbessern';
            }
        }

        function uebernehmenVorschlag() {
            if (!state.kiVorschlag) return;

            if (state.kiVorschlag.betreff) {
                document.getElementById('newsletter-betreff').value = state.kiVorschlag.betreff;
            }
            document.getElementById('newsletter-text').value = state.kiVorschlag.text;

            document.getElementById('ki-vorschau-container').classList.add('hidden');
            delete state.kiVorschlag;

            showToast('Vorschlag übernommen (noch nicht gespeichert)', 'success');
        }

    } catch (err) {
        loadingDiv.textContent = 'Fehler: ' + err.message;
        loadingDiv.style.color = 'var(--color-error)';
    }
}

// Tag-Text wie im Backend (import_csv.tag_pruefen): nicht leer, höchstens 40 Zeichen, keine Steuerzeichen und kein , ; |
function abonnentTagPruefen(roh) {
    const t = (roh || '').trim();
    if (!t) return {tag: null, fehler: null};
    if (t.length > 40 || /[\x00-\x1f\x7f,;|]/.test(t)) {
        return {tag: null, fehler: 'Ein Tag darf höchstens 40 Zeichen haben und kein Komma, Semikolon, senkrechten Strich oder Steuerzeichen enthalten.'};
    }
    return {tag: t, fehler: null};
}

// Toast-Text mit Zahlen: geändert, unverändert, übersprungen (mit Gründen)
function abonnentTagsErgebnis(erg, art, tag) {
    const ueb = erg.uebersprungen || {};
    const summe = Object.values(ueb).reduce((n, w) => n + w, 0);
    let text = `Tag „${tag}“ ${art === 'hinzufuegen' ? 'hinzugefügt' : 'entfernt'}: ${erg.geaendert} geändert, ${erg.unveraendert} unverändert, ${summe} übersprungen`;
    const gruende = [];
    if (ueb.tag_limit) gruende.push(`${ueb.tag_limit} wegen Tag-Limit (höchstens 20 je Adresse)`);
    if (ueb.unbestaetigt) gruende.push(`${ueb.unbestaetigt} unbestätigt`);
    if (ueb.abgemeldet) gruende.push(`${ueb.abgemeldet} abgemeldet`);
    if (ueb.unzustellbar) gruende.push(`${ueb.unzustellbar} unzustellbar`);
    if (ueb.unbekannt) gruende.push(`${ueb.unbekannt} unbekannt`);
    if (gruende.length) text += ` (${gruende.join(', ')})`;
    // nur Hinweis, nicht Teil der Summe: bei diesen Adressen passte nicht jeder neue Tag in die 20er-Grenze
    if (erg.tag_limit_teilweise > 0) text += `; bei ${erg.tag_limit_teilweise} ${erg.tag_limit_teilweise === 1 ? 'Adresse' : 'Adressen'} passte nicht jeder neue Tag`;
    return text;
}

async function renderAbonnenten(m) {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = m.name;
    card.appendChild(title);

    renderTabs(m, card);

    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading';
    loadingDiv.textContent = 'Lade Abonnenten...';
    card.appendChild(loadingDiv);

    main.innerHTML = '';
    main.appendChild(card);

    try {
        const [data, tagsAntwort] = await Promise.all([
            apiCall(`/mandanten/${m.id}/abonnenten`),
            apiCall(`/mandanten/${m.id}/abonnenten/tags`).catch(() => null),
        ]);
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

        // Abonnent manuell hinzufügen
        await renderAbonnentHinzufuegen(m, card);

        // Tags nachträglich vergeben und entfernen (POST .../abonnenten/tags-aendern): Mehrfachauswahl oben, einzeln in der Zeile
        let zeilen = data.abonnenten || [];
        const auswahl = new Set();
        let offeneZeile = null;
        const TAGS_MAX_IDS = 2000;

        const leiste = document.createElement('div');
        leiste.id = 'tags-leiste';
        leiste.style.margin = '0 0 1rem';
        leiste.style.padding = '1rem';
        leiste.style.background = '#f9fafb';
        leiste.style.borderRadius = '6px';
        const leisteTitel = document.createElement('strong');
        leisteTitel.textContent = 'Tags für mehrere Adressen';
        leiste.appendChild(leisteTitel);
        const leisteZeile = document.createElement('div');
        leisteZeile.style.display = 'flex';
        leisteZeile.style.flexWrap = 'wrap';
        leisteZeile.style.gap = '0.75rem';
        leisteZeile.style.alignItems = 'center';
        leisteZeile.style.marginTop = '0.5rem';
        const alleLabel = document.createElement('label');
        const alleBox = document.createElement('input');
        alleBox.type = 'checkbox';
        alleBox.id = 'abo-alle';
        alleLabel.appendChild(alleBox);
        alleLabel.appendChild(document.createTextNode(' Alle auswählen'));
        leisteZeile.appendChild(alleLabel);
        const zaehler = document.createElement('span');
        zaehler.id = 'abo-auswahl-zaehler';
        leisteZeile.appendChild(zaehler);
        const tagEingabe = document.createElement('input');
        tagEingabe.type = 'text';
        tagEingabe.id = 'tags-eingabe';
        tagEingabe.placeholder = 'Tag';
        tagEingabe.setAttribute('list', 'tags-vorschlaege');
        tagEingabe.autocomplete = 'off';
        leisteZeile.appendChild(tagEingabe);
        const vorschlaege = document.createElement('datalist');
        vorschlaege.id = 'tags-vorschlaege';
        leisteZeile.appendChild(vorschlaege);
        const hinzuBtn = document.createElement('button');
        hinzuBtn.type = 'button';
        hinzuBtn.id = 'tags-hinzufuegen';
        hinzuBtn.className = 'btn btn-primary';
        hinzuBtn.textContent = 'Tag hinzufügen';
        leisteZeile.appendChild(hinzuBtn);
        const entfBtn = document.createElement('button');
        entfBtn.type = 'button';
        entfBtn.id = 'tags-entfernen';
        entfBtn.className = 'btn btn-secondary';
        entfBtn.textContent = 'Tag entfernen';
        leisteZeile.appendChild(entfBtn);
        leiste.appendChild(leisteZeile);
        const leisteFehler = document.createElement('div');
        leisteFehler.id = 'tags-fehler';
        leisteFehler.className = 'field-error hidden';
        leiste.appendChild(leisteFehler);
        const leisteHinweis = document.createElement('small');
        leisteHinweis.style.color = '#6b7280';
        leisteHinweis.textContent = 'Nur bestätigte Adressen können Tags bekommen. Groß-/Kleinschreibung ist egal, höchstens 40 Zeichen, höchstens 20 Tags je Adresse.';
        leiste.appendChild(leisteHinweis);
        card.appendChild(leiste);

        const zeigeLeistenFehler = (text) => {
            leisteFehler.textContent = text || '';
            leisteFehler.classList.toggle('hidden', !text);
            if (text) tagEingabe.setAttribute('aria-invalid', 'true');
            else tagEingabe.removeAttribute('aria-invalid');
        };
        const fuelleVorschlaege = (tags) => {
            vorschlaege.textContent = '';
            (tags || []).forEach(t => {
                const o = document.createElement('option');
                o.value = t.tag;
                vorschlaege.appendChild(o);
            });
        };
        fuelleVorschlaege(tagsAntwort ? tagsAntwort.tags : []);

        const auswaehlbar = () => zeilen.filter(z => z.status === 'bestaetigt');
        const aktualisiereLeiste = () => {
            const moeglich = auswaehlbar();
            const gewaehlt = moeglich.filter(z => auswahl.has(z.id)).length;
            alleBox.disabled = moeglich.length === 0;
            alleBox.checked = moeglich.length > 0 && gewaehlt === moeglich.length;
            alleBox.indeterminate = gewaehlt > 0 && gewaehlt < moeglich.length;
            zaehler.textContent = `${auswahl.size} ausgewählt`;
            const pruefung = abonnentTagPruefen(tagEingabe.value);
            let fehler = pruefung.fehler;
            if (!fehler && auswahl.size > TAGS_MAX_IDS) fehler = `Höchstens ${TAGS_MAX_IDS} Adressen je Vorgang auswählen.`;
            zeigeLeistenFehler(fehler);
            const gesperrt = auswahl.size === 0 || !pruefung.tag || !!fehler;
            hinzuBtn.disabled = gesperrt;
            entfBtn.disabled = gesperrt;
        };

        const tabelle = document.createElement('table');
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        ['', 'E-Mail', 'Status', 'Rolle', 'Interessen', 'Tags', 'Herkunft', 'Quelle', 'Angemeldet', 'Aktion'].forEach((h, i, alle) => {
            const th = document.createElement('th');
            th.textContent = h;
            if (i === 0 || i === alle.length - 1) th.className = 'abo-extra';
            if (i === 0) th.setAttribute('aria-label', 'Auswahl');
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        tabelle.appendChild(thead);
        const tbody = document.createElement('tbody');
        tabelle.appendChild(tbody);

        const neuLaden = async () => {
            const [liste, tags] = await Promise.all([
                apiCall(`/mandanten/${m.id}/abonnenten`),
                apiCall(`/mandanten/${m.id}/abonnenten/tags`).catch(() => null),
            ]);
            zeilen = liste.abonnenten || [];
            if (tags) fuelleVorschlaege(tags.tags);
            const gueltig = new Set(zeilen.filter(z => z.status === 'bestaetigt').map(z => z.id));
            Array.from(auswahl).forEach(id => { if (!gueltig.has(id)) auswahl.delete(id); });
            if (!zeilen.some(z => z.id === offeneZeile)) offeneZeile = null;
            zeichneZeilen();
            aktualisiereLeiste();
        };
        // Ein Aufruf an die Schnittstelle; Antwort als Toast mit Zahlen, danach Liste und Vorschläge neu laden
        const tagsAendern = async (ids, art, tag) => {
            const erg = await apiCall(`/mandanten/${m.id}/abonnenten/tags-aendern`, {method: 'POST', body: JSON.stringify({abonnent_ids: ids, [art]: [tag]})});
            showToast(abonnentTagsErgebnis(erg, art, tag), 'success');
            await neuLaden();
        };

        const zeichneZeilen = () => {
            tbody.textContent = '';
            zeilen.forEach(a => {
                const bestaetigt = a.status === 'bestaetigt';
                const row = document.createElement('tr');

                const auswahlCell = document.createElement('td');
                auswahlCell.className = 'abo-extra';
                const box = document.createElement('input');
                box.type = 'checkbox';
                box.className = 'abo-zeile-auswahl';
                box.dataset.id = String(a.id);
                box.disabled = !bestaetigt;
                box.checked = bestaetigt && auswahl.has(a.id);
                box.setAttribute('aria-label', 'Adresse auswählen');
                if (!bestaetigt) box.title = 'Nur bestätigte Adressen können Tags bekommen';
                box.addEventListener('change', () => {
                    if (box.checked) auswahl.add(a.id);
                    else auswahl.delete(a.id);
                    aktualisiereLeiste();
                });
                auswahlCell.appendChild(box);
                row.appendChild(auswahlCell);

                const emailCell = document.createElement('td');
                emailCell.textContent = a.email || '(pseudonymisiert)';
                row.appendChild(emailCell);

                const statusCell = document.createElement('td');
                const badge = document.createElement('span');
                badge.className = 'badge';
                if (a.status === 'bestaetigt') badge.classList.add('badge-success');
                else if (a.status === 'unzustellbar') badge.classList.add('badge-error');
                else badge.classList.add('badge-warning');
                badge.textContent = a.status === 'bestaetigt' ? 'Bestätigt' : a.status === 'unzustellbar' ? 'Unzustellbar' : 'Unbestätigt';
                statusCell.appendChild(badge);
                row.appendChild(statusCell);

                const rolleCell = document.createElement('td');
                rolleCell.textContent = a.rolle || '-';
                row.appendChild(rolleCell);

                const interessenCell = document.createElement('td');
                interessenCell.textContent = (a.interessen || []).join(', ') || '-';
                row.appendChild(interessenCell);

                const tagsCell = document.createElement('td');
                tagsCell.textContent = (a.tags || []).join(', ') || '-';
                row.appendChild(tagsCell);

                const herkunftCell = document.createElement('td');
                herkunftCell.textContent = a.herkunft || '-';
                row.appendChild(herkunftCell);

                const quelleCell = document.createElement('td');
                quelleCell.textContent = a.quelle || '-';
                row.appendChild(quelleCell);

                const dateCell = document.createElement('td');
                dateCell.textContent = a.einwilligung_am ? new Date(a.einwilligung_am).toLocaleDateString('de-DE') : '-';
                row.appendChild(dateCell);

                const aktionCell = document.createElement('td');
                aktionCell.className = 'abo-extra';
                const bearbeiten = document.createElement('button');
                bearbeiten.type = 'button';
                bearbeiten.className = 'btn btn-secondary btn-small abo-tags-bearbeiten';
                bearbeiten.textContent = 'Tags bearbeiten';
                bearbeiten.disabled = !bestaetigt;
                if (!bestaetigt) bearbeiten.title = 'Nur bestätigte Adressen können Tags bekommen';
                bearbeiten.addEventListener('click', () => {
                    offeneZeile = offeneZeile === a.id ? null : a.id;
                    zeichneZeilen();
                });
                aktionCell.appendChild(bearbeiten);
                row.appendChild(aktionCell);
                tbody.appendChild(row);

                if (offeneZeile === a.id && bestaetigt) tbody.appendChild(zeichneTagsZeile(a));
            });
        };

        // Einzelbearbeitung: vorhandene Tags als entfernbare Chips, Feld zum Hinzufügen
        const zeichneTagsZeile = (a) => {
            const zeile = document.createElement('tr');
            zeile.className = 'abo-tags-zeile';
            const zelle = document.createElement('td');
            zelle.colSpan = 10;
            zelle.style.background = '#f9fafb';
            const chips = document.createElement('div');
            chips.className = 'abo-tags-chips';
            chips.style.display = 'flex';
            chips.style.flexWrap = 'wrap';
            chips.style.gap = '0.5rem';
            chips.style.marginBottom = '0.5rem';
            const fehler = document.createElement('div');
            fehler.className = 'field-error hidden abo-tags-fehler';
            const zeigeFehler = (text) => { fehler.textContent = text || ''; fehler.classList.toggle('hidden', !text); };
            if ((a.tags || []).length === 0) {
                const leer = document.createElement('small');
                leer.textContent = 'Noch keine Tags.';
                chips.appendChild(leer);
            }
            (a.tags || []).forEach(tag => {
                const chip = document.createElement('span');
                chip.className = 'abo-tag-chip';
                chip.style.display = 'inline-flex';
                chip.style.alignItems = 'center';
                chip.style.gap = '0.25rem';
                chip.style.padding = '0.125rem 0.5rem';
                chip.style.border = '1px solid var(--color-border)';
                chip.style.borderRadius = '999px';
                chip.style.background = '#fff';
                const name = document.createElement('span');
                name.className = 'abo-tag-name';
                name.textContent = tag;
                chip.appendChild(name);
                const weg = document.createElement('button');
                weg.type = 'button';
                weg.className = 'abo-tag-entfernen';
                weg.textContent = '×';
                weg.setAttribute('aria-label', `Tag ${tag} entfernen`);
                weg.addEventListener('click', async () => {
                    zeigeFehler('');
                    try {
                        await tagsAendern([a.id], 'entfernen', tag);
                    } catch (err) {
                        zeigeFehler(err.message);
                    }
                });
                chip.appendChild(weg);
                chips.appendChild(chip);
            });
            zelle.appendChild(chips);
            const eingabeZeile = document.createElement('div');
            eingabeZeile.style.display = 'flex';
            eingabeZeile.style.gap = '0.5rem';
            const eingabe = document.createElement('input');
            eingabe.type = 'text';
            eingabe.className = 'abo-tag-eingabe';
            eingabe.placeholder = 'Tag hinzufügen';
            eingabe.setAttribute('list', 'tags-vorschlaege');
            eingabe.autocomplete = 'off';
            const hinzu = document.createElement('button');
            hinzu.type = 'button';
            hinzu.className = 'btn btn-primary btn-small abo-tag-hinzufuegen';
            hinzu.textContent = 'Hinzufügen';
            hinzu.disabled = true;
            const pruefe = () => {
                const p = abonnentTagPruefen(eingabe.value);
                zeigeFehler(p.fehler);
                hinzu.disabled = !p.tag || !!p.fehler;
            };
            eingabe.addEventListener('input', pruefe);
            hinzu.addEventListener('click', async () => {
                const p = abonnentTagPruefen(eingabe.value);
                if (!p.tag) return;
                try {
                    await tagsAendern([a.id], 'hinzufuegen', p.tag);
                } catch (err) {
                    zeigeFehler(err.message);
                }
            });
            eingabeZeile.appendChild(eingabe);
            eingabeZeile.appendChild(hinzu);
            zelle.appendChild(eingabeZeile);
            zelle.appendChild(fehler);
            zeile.appendChild(zelle);
            return zeile;
        };

        alleBox.addEventListener('change', () => {
            auswaehlbar().forEach(z => { if (alleBox.checked) auswahl.add(z.id); else auswahl.delete(z.id); });
            zeichneZeilen();
            aktualisiereLeiste();
        });
        tagEingabe.addEventListener('input', aktualisiereLeiste);
        const massenaenderung = (art) => async () => {
            const p = abonnentTagPruefen(tagEingabe.value);
            if (!p.tag || auswahl.size === 0) return;
            zeigeLeistenFehler('');
            try {
                await tagsAendern(Array.from(auswahl), art, p.tag);
                tagEingabe.value = '';
                aktualisiereLeiste();
            } catch (err) {
                zeigeLeistenFehler(err.message);
            }
        };
        hinzuBtn.addEventListener('click', massenaenderung('hinzufuegen'));
        entfBtn.addEventListener('click', massenaenderung('entfernen'));

        zeichneZeilen();
        aktualisiereLeiste();
        card.appendChild(tabelle);

    } catch (err) {
        loadingDiv.textContent = 'Fehler: ' + err.message;
        loadingDiv.style.color = 'var(--color-error)';
    }
}

// Abonnent manuell hinzufügen
async function renderAbonnentHinzufuegen(m, card) {
    const section = document.createElement('div');
    section.style.marginBottom = '2rem';
    section.style.padding = '1.5rem';
    section.style.background = '#f9fafb';
    section.style.borderRadius = '6px';

    const subtitle = document.createElement('h3');
    subtitle.textContent = 'Abonnent hinzufügen';
    subtitle.style.marginTop = '0';
    subtitle.style.marginBottom = '1rem';
    section.appendChild(subtitle);

    const form = document.createElement('form');
    form.id = 'abonnent-form';

    // E-Mail
    const emailGroup = document.createElement('div');
    emailGroup.className = 'form-group';
    const emailLabel = document.createElement('label');
    emailLabel.textContent = 'E-Mail-Adresse *';
    emailGroup.appendChild(emailLabel);
    const emailInput = document.createElement('input');
    emailInput.type = 'email';
    emailInput.id = 'abonnent-email';
    emailInput.required = true;
    emailInput.placeholder = 'beispiel@domain.de';
    emailInput.style.width = '100%';
    emailGroup.appendChild(emailInput);
    form.appendChild(emailGroup);

    // Quelle/Einwilligung
    const quelleGroup = document.createElement('div');
    quelleGroup.className = 'form-group';
    const quelleLabel = document.createElement('label');
    quelleLabel.textContent = 'Quelle/Einwilligung *';
    quelleGroup.appendChild(quelleLabel);
    const quelleInput = document.createElement('input');
    quelleInput.type = 'text';
    quelleInput.id = 'abonnent-quelle';
    quelleInput.required = true;
    quelleInput.minLength = 5;
    quelleInput.maxLength = 100;
    quelleInput.placeholder = 'z. B. Papierformular vom 12.11.';
    quelleInput.style.width = '100%';
    quelleGroup.appendChild(quelleInput);
    const quelleHelp = document.createElement('small');
    quelleHelp.textContent = 'Wie liegt die Einwilligung vor? z. B. Papierformular vom 12.11.';
    quelleHelp.style.color = '#6b7280';
    quelleGroup.appendChild(quelleHelp);
    form.appendChild(quelleGroup);

    // Rolle (optional)
    if (m.design && m.design.rollen && m.design.rollen.length > 0) {
        const rolleGroup = document.createElement('div');
        rolleGroup.className = 'form-group';
        const rolleLabel = document.createElement('label');
        rolleLabel.textContent = 'Rolle (optional)';
        rolleGroup.appendChild(rolleLabel);
        const rolleSelect = document.createElement('select');
        rolleSelect.id = 'abonnent-rolle';
        rolleSelect.style.width = '100%';
        const emptyOpt = document.createElement('option');
        emptyOpt.value = '';
        emptyOpt.textContent = '(keine)';
        rolleSelect.appendChild(emptyOpt);
        m.design.rollen.forEach(r => {
            const opt = document.createElement('option');
            opt.value = r.wert;
            opt.textContent = r.label;
            rolleSelect.appendChild(opt);
        });
        rolleGroup.appendChild(rolleSelect);
        form.appendChild(rolleGroup);
    }

    // Interessen (optional)
    if (m.design && m.design.interessen && m.design.interessen.length > 0) {
        const interessenGroup = document.createElement('div');
        interessenGroup.className = 'form-group';
        const interessenLabel = document.createElement('label');
        interessenLabel.textContent = 'Interessen (optional)';
        interessenGroup.appendChild(interessenLabel);
        m.design.interessen.forEach(i => {
            const label = document.createElement('label');
            label.style.display = 'block';
            label.style.marginBottom = '0.5rem';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'abonnent-interesse';
            checkbox.value = i.wert;
            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(' ' + i.label));
            interessenGroup.appendChild(label);
        });
        form.appendChild(interessenGroup);
    }

    // Live-Validierung
    emailInput.addEventListener('input', () => {
        const email = emailInput.value.trim();
        const isValid = email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
        emailInput.style.borderColor = email && !isValid ? 'var(--color-error)' : '';
    });

    // Backend validiert 1-100 Zeichen (betreiber.py Z. 169), UI Mindestlänge 5
    quelleInput.addEventListener('input', () => {
        const quelle = quelleInput.value.trim();
        const isValid = quelle.length >= 5 && quelle.length <= 100;
        quelleInput.style.borderColor = quelle && !isValid ? 'var(--color-error)' : '';
    });

    // Fehlermeldung
    const errorDiv = document.createElement('div');
    errorDiv.id = 'abonnent-error';
    errorDiv.className = 'error hidden';
    form.appendChild(errorDiv);

    // Erfolgsmeldung
    const successDiv = document.createElement('div');
    successDiv.id = 'abonnent-success';
    successDiv.className = 'hidden';
    successDiv.style.padding = '1rem';
    successDiv.style.marginTop = '1rem';
    successDiv.style.background = '#d1fae5';
    successDiv.style.color = '#065f46';
    successDiv.style.borderRadius = '6px';
    form.appendChild(successDiv);

    // Submit
    const actions = document.createElement('div');
    actions.className = 'form-actions';
    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = 'Abonnent hinzufügen';
    actions.appendChild(submitBtn);
    form.appendChild(actions);

    // Submit Handler
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const errorDiv = document.getElementById('abonnent-error');
        const successDiv = document.getElementById('abonnent-success');
        errorDiv.className = 'error hidden';
        successDiv.className = 'hidden';

        const email = emailInput.value.trim();
        const quelle = quelleInput.value.trim();

        if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            errorDiv.textContent = 'Bitte geben Sie eine gültige E-Mail-Adresse ein.';
            errorDiv.className = 'error';
            return;
        }

        if (quelle.length < 5 || quelle.length > 100) {
            errorDiv.textContent = 'Quelle/Einwilligung muss zwischen 5 und 100 Zeichen lang sein.';
            errorDiv.className = 'error';
            return;
        }

        const body = {
            daten: email,
            quelle: quelle,
            einwilligung_bestaetigt: true
        };

        // Rolle
        const rolleSelect = document.getElementById('abonnent-rolle');
        if (rolleSelect && rolleSelect.value) {
            body.rolle = rolleSelect.value;
        }

        // Interessen
        const interessenCheckboxes = document.querySelectorAll('.abonnent-interesse:checked');
        if (interessenCheckboxes.length > 0) {
            body.interessen = Array.from(interessenCheckboxes).map(cb => cb.value);
        }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Wird hinzugefügt...';

        try {
            const result = await apiCall(`/mandanten/${m.id}/abonnenten/import`, {
                method: 'POST',
                body: JSON.stringify(body)
            });

            // Antwort interpretieren (Backend: betreiber.py Z. 177, abonnenten.importieren)
            // Antwortfelder: neu, dublette, ungueltig, uebersprungen{abgemeldet, unzustellbar, unbestaetigt, status}
            let message = '';
            let isSuccess = false;

            if (result.neu > 0) {
                message = `Abonnent erfolgreich hinzugefügt: ${email}`;
                isSuccess = true;
            } else if (result.dublette > 0) {
                message = `Die E-Mail-Adresse ${email} ist bereits in der Liste.`;
            } else if (result.uebersprungen && result.uebersprungen.abgemeldet > 0) {
                message = `Die E-Mail-Adresse ${email} wurde bereits abgemeldet und wird nicht wieder aufgenommen.`;
            } else if (result.uebersprungen && result.uebersprungen.unzustellbar > 0) {
                message = `Die E-Mail-Adresse ${email} ist als unzustellbar markiert.`;
            } else if (result.uebersprungen && (result.uebersprungen.unbestaetigt > 0 || result.uebersprungen.status > 0)) {
                message = `Diese Adresse hat die Anmeldung noch nicht bestätigt und wurde nicht aufgenommen.`;
            } else if (result.ungueltig > 0) {
                message = `Die E-Mail-Adresse ${email} ist ungültig.`;
            } else {
                message = 'Unerwartete Antwort vom Server.';
            }

            // Nur bei Erfolg (neu > 0) im grünen Erfolgsfeld, sonst Warnung
            if (isSuccess) {
                successDiv.textContent = message;
                successDiv.className = '';
                showToast(message, 'success');

                // Formular zurücksetzen nur bei Erfolg
                emailInput.value = '';
                quelleInput.value = '';
                if (rolleSelect) rolleSelect.value = '';
                interessenCheckboxes.forEach(cb => cb.checked = false);

                // Liste neu laden
                setTimeout(() => {
                    showMandantDetails(m.id, 'abonnenten');
                }, 1500);
            } else {
                // Warnung anzeigen, Eingaben behalten
                errorDiv.textContent = message;
                errorDiv.className = 'error';
                errorDiv.style.background = '#fef3c7';
                errorDiv.style.color = '#92400e';
                showToast(message, 'error');
            }

        } catch (err) {
            errorDiv.textContent = err.message;
            errorDiv.className = 'error';
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Abonnent hinzufügen';
        }
    });

    section.appendChild(form);
    card.appendChild(section);
}

// Import
function renderImport(m) {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = m.name;
    card.appendChild(title);

    renderTabs(m, card);

    const subtitle = document.createElement('h3');
    subtitle.textContent = 'Abonnenten importieren';
    subtitle.style.marginBottom = '1rem';
    card.appendChild(subtitle);

    const form = document.createElement('form');
    form.id = 'import-form';

    // Datei
    const fileGroup = document.createElement('div');
    fileGroup.className = 'form-group';
    const fileLabel = document.createElement('label');
    fileLabel.textContent = 'CSV-Datei *';
    fileGroup.appendChild(fileLabel);
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.id = 'import-file';
    fileInput.accept = '.csv,text/csv';
    fileInput.required = true;
    fileGroup.appendChild(fileInput);
    const fileHint = document.createElement('small');
    fileHint.textContent = 'Maximal 3 MB, 20.000 Zeilen. Gelesen werden nur die Spalten E-Mail, Status und Tags.';
    fileHint.style.display = 'block';
    fileHint.style.marginTop = '0.25rem';
    fileHint.style.color = '#6b7280';
    fileGroup.appendChild(fileHint);
    form.appendChild(fileGroup);

    // Quelle
    const quelleGroup = document.createElement('div');
    quelleGroup.className = 'form-group';
    const quelleLabel = document.createElement('label');
    quelleLabel.textContent = 'Quelle *';
    quelleGroup.appendChild(quelleLabel);
    const quelleInput = document.createElement('input');
    quelleInput.type = 'text';
    quelleInput.id = 'import-quelle';
    quelleInput.placeholder = 'z.B. Mailchimp-Export 13.11.2026';
    quelleInput.maxLength = 100;
    quelleInput.required = true;
    quelleGroup.appendChild(quelleInput);
    const quelleError = document.createElement('div');
    quelleError.className = 'field-error hidden';
    quelleError.id = 'quelle-error';
    quelleGroup.appendChild(quelleError);
    form.appendChild(quelleGroup);

    // Rolle (optional)
    if (m.design && m.design.rollen && m.design.rollen.length > 0) {
        const rolleGroup = document.createElement('div');
        rolleGroup.className = 'form-group';
        const rolleLabel = document.createElement('label');
        rolleLabel.textContent = 'Rolle (optional, gilt für alle Zeilen)';
        rolleGroup.appendChild(rolleLabel);
        const rolleSelect = document.createElement('select');
        rolleSelect.id = 'import-rolle';
        const emptyOption = document.createElement('option');
        emptyOption.value = '';
        emptyOption.textContent = '(keine)';
        rolleSelect.appendChild(emptyOption);
        m.design.rollen.forEach(rolle => {
            const option = document.createElement('option');
            option.value = rolle.wert;
            option.textContent = rolle.label;
            rolleSelect.appendChild(option);
        });
        rolleGroup.appendChild(rolleSelect);
        form.appendChild(rolleGroup);
    }

    // Interessen (optional, Mehrfach)
    if (m.design && m.design.interessen && m.design.interessen.length > 0) {
        const interessenGroup = document.createElement('div');
        interessenGroup.className = 'form-group';
        const interessenLabel = document.createElement('label');
        interessenLabel.textContent = 'Interessen (optional, gelten für alle Zeilen)';
        interessenGroup.appendChild(interessenLabel);
        m.design.interessen.forEach(interesse => {
            const label = document.createElement('label');
            label.style.display = 'block';
            label.style.marginTop = '0.25rem';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'import-interesse';
            checkbox.value = interesse.wert;
            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(' ' + interesse.label));
            interessenGroup.appendChild(label);
        });
        form.appendChild(interessenGroup);
    }

    // Buttons
    const buttonGroup = document.createElement('div');
    buttonGroup.style.display = 'flex';
    buttonGroup.style.gap = '0.5rem';
    buttonGroup.style.marginTop = '1rem';

    const pruefenBtn = document.createElement('button');
    pruefenBtn.type = 'button';
    pruefenBtn.className = 'btn btn-secondary';
    pruefenBtn.textContent = 'Prüfen';
    pruefenBtn.id = 'btn-pruefen';
    pruefenBtn.disabled = true;
    buttonGroup.appendChild(pruefenBtn);

    const importierenBtn = document.createElement('button');
    importierenBtn.type = 'button';
    importierenBtn.className = 'btn btn-primary';
    importierenBtn.textContent = 'Importieren';
    importierenBtn.id = 'btn-importieren';
    importierenBtn.disabled = true;
    buttonGroup.appendChild(importierenBtn);

    form.appendChild(buttonGroup);

    const errorDiv = document.createElement('div');
    errorDiv.className = 'error hidden';
    errorDiv.id = 'import-error';
    form.appendChild(errorDiv);

    card.appendChild(form);

    // Vorschau
    const vorschauDiv = document.createElement('div');
    vorschauDiv.id = 'import-vorschau';
    vorschauDiv.className = 'hidden';
    vorschauDiv.style.marginTop = '1.5rem';
    card.appendChild(vorschauDiv);

    // Einwilligung
    const einwilligungDiv = document.createElement('div');
    einwilligungDiv.id = 'import-einwilligung';
    einwilligungDiv.className = 'hidden';
    einwilligungDiv.style.marginTop = '1.5rem';
    const einwilligungLabel = document.createElement('label');
    const einwilligungCheckbox = document.createElement('input');
    einwilligungCheckbox.type = 'checkbox';
    einwilligungCheckbox.id = 'import-einwilligung-check';
    einwilligungLabel.appendChild(einwilligungCheckbox);
    einwilligungLabel.appendChild(document.createTextNode(' Einwilligung liegt vor'));
    einwilligungDiv.appendChild(einwilligungLabel);
    card.appendChild(einwilligungDiv);

    // Ergebnis
    const ergebnisDiv = document.createElement('div');
    ergebnisDiv.id = 'import-ergebnis';
    ergebnisDiv.className = 'hidden';
    ergebnisDiv.style.marginTop = '1.5rem';
    card.appendChild(ergebnisDiv);

    main.innerHTML = '';
    main.appendChild(card);

    // Event-Listener
    fileInput.addEventListener('change', validateImportForm);
    quelleInput.addEventListener('input', () => {
        validateQuelle();
        validateImportForm();
    });
    einwilligungCheckbox.addEventListener('change', validateImportForm);

    pruefenBtn.addEventListener('click', () => importPruefen(m));
    importierenBtn.addEventListener('click', () => importDurchfuehren(m));

    function validateQuelle() {
        const value = quelleInput.value.trim();
        const error = document.getElementById('quelle-error');
        if (value && (value.length < 1 || value.length > 100)) {
            error.textContent = 'Quelle muss 1-100 Zeichen lang sein';
            error.classList.remove('hidden');
            return false;
        }
        error.classList.add('hidden');
        return true;
    }

    function validateImportForm() {
        const file = fileInput.files[0];
        const quelle = quelleInput.value.trim();
        const einwilligung = einwilligungCheckbox.checked;
        const vorschauSichtbar = !vorschauDiv.classList.contains('hidden');

        pruefenBtn.disabled = !(file && quelle && validateQuelle());
        importierenBtn.disabled = !(file && quelle && validateQuelle() && vorschauSichtbar && einwilligung);
    }
}

async function importPruefen(m) {
    const fileInput = document.getElementById('import-file');
    const quelleInput = document.getElementById('import-quelle');
    const errorDiv = document.getElementById('import-error');
    const vorschauDiv = document.getElementById('import-vorschau');
    const einwilligungDiv = document.getElementById('import-einwilligung');

    errorDiv.classList.add('hidden');
    vorschauDiv.classList.add('hidden');
    einwilligungDiv.classList.add('hidden');

    const file = fileInput.files[0];
    if (!file) {
        errorDiv.textContent = 'Bitte Datei wählen';
        errorDiv.classList.remove('hidden');
        return;
    }

    if (file.size > 3 * 1024 * 1024) {
        errorDiv.textContent = 'Datei zu groß (maximal 3 MB)';
        errorDiv.classList.remove('hidden');
        return;
    }

    try {
        const daten = await file.text();
        const quelle = quelleInput.value.trim();

        const body = {
            daten,
            quelle,
            nur_pruefen: true
        };

        const rolleSelect = document.getElementById('import-rolle');
        if (rolleSelect && rolleSelect.value) {
            body.rolle = rolleSelect.value;
        }

        const interessenCheckboxes = document.querySelectorAll('.import-interesse:checked');
        if (interessenCheckboxes.length > 0) {
            body.interessen = Array.from(interessenCheckboxes).map(cb => cb.value);
        }

        const result = await apiCall(`/mandanten/${m.id}/abonnenten/import`, {
            method: 'POST',
            body: JSON.stringify(body)
        });

        // Vorschau anzeigen
        vorschauDiv.innerHTML = '';
        const title = document.createElement('h3');
        title.textContent = 'Vorschau';
        vorschauDiv.appendChild(title);

        const stats = document.createElement('dl');
        stats.style.marginTop = '1rem';

        const addStat = (label, value, className = '') => {
            const dt = document.createElement('dt');
            dt.textContent = label;
            dt.style.fontWeight = '600';
            dt.style.marginTop = '0.5rem';
            stats.appendChild(dt);
            const dd = document.createElement('dd');
            dd.textContent = value;
            dd.style.marginLeft = '1rem';
            if (className) dd.className = className;
            stats.appendChild(dd);
        };

        addStat('Zeilen', result.zeilen);
        addStat('Neu', result.neu);
        addStat('Dublette', result.dublette);
        addStat('Ungültig', result.ungueltig);
        addStat('Übersprungen', result.uebersprungen_gesamt);
        if (result.zusammengefuehrt > 0) addStat('Zusammengeführt', result.zusammengefuehrt);
        if (result.rolle_konflikt > 0) addStat('Rolle-Konflikt', result.rolle_konflikt, 'warning-text');

        if (result.uebersprungen) {
            if (result.uebersprungen.abgemeldet > 0) addStat('  - Abgemeldet', result.uebersprungen.abgemeldet);
            if (result.uebersprungen.unzustellbar > 0) addStat('  - Unzustellbar', result.uebersprungen.unzustellbar);
            if (result.uebersprungen.unbestaetigt > 0) addStat('  - Unbestätigt', result.uebersprungen.unbestaetigt);
            if (result.uebersprungen.status > 0) addStat('  - Anderer Status', result.uebersprungen.status);
        }

        // Tags-Statistik
        if (result.tags) {
            if (result.tags.verschiedene > 0) addStat('Tags (verschiedene)', result.tags.verschiedene);
            if (result.tags.verworfen > 0) addStat('Tags (verworfen)', result.tags.verworfen, 'warning-text');
            if (result.tags.haeufigste && result.tags.haeufigste.length > 0) {
                const haeufigsteText = result.tags.haeufigste.map(t => `${t.tag} (${t.anzahl})`).join(', ');
                addStat('Tags (häufigste)', haeufigsteText);
            }
        }

        vorschauDiv.appendChild(stats);

        const kennzahlenTitle = document.createElement('h4');
        kennzahlenTitle.textContent = 'Aktuelle Kennzahlen';
        kennzahlenTitle.style.marginTop = '1.5rem';
        vorschauDiv.appendChild(kennzahlenTitle);

        const kennzahlenStats = document.createElement('dl');
        kennzahlenStats.style.marginTop = '0.5rem';
        if (result.kennzahlen) {
            [['Bestätigt', result.kennzahlen.bestaetigt], ['Unbestätigt', result.kennzahlen.unbestaetigt], ['Abgemeldet', result.kennzahlen.abgemeldet], ['Unzustellbar', result.kennzahlen.unzustellbar]].forEach(([label, wert]) => {
                const dt = document.createElement('dt');
                dt.textContent = label;
                dt.style.fontWeight = '600';
                dt.style.marginTop = '0.5rem';
                kennzahlenStats.appendChild(dt);
                const dd = document.createElement('dd');
                dd.textContent = wert;
                dd.style.marginLeft = '1rem';
                kennzahlenStats.appendChild(dd);
            });
        }
        vorschauDiv.appendChild(kennzahlenStats);

        vorschauDiv.classList.remove('hidden');
        einwilligungDiv.classList.remove('hidden');

        document.getElementById('import-einwilligung-check').checked = false;
        document.getElementById('btn-importieren').disabled = true;

    } catch (err) {
        errorDiv.textContent = err.message;
        errorDiv.classList.remove('hidden');
    }
}

async function importDurchfuehren(m) {
    const fileInput = document.getElementById('import-file');
    const quelleInput = document.getElementById('import-quelle');
    const errorDiv = document.getElementById('import-error');
    const ergebnisDiv = document.getElementById('import-ergebnis');
    const einwilligungCheck = document.getElementById('import-einwilligung-check');

    errorDiv.classList.add('hidden');
    ergebnisDiv.classList.add('hidden');

    if (!einwilligungCheck.checked) {
        errorDiv.textContent = 'Bitte Einwilligung bestätigen';
        errorDiv.classList.remove('hidden');
        return;
    }

    try {
        const daten = await fileInput.files[0].text();
        const quelle = quelleInput.value.trim();

        const body = {
            daten,
            quelle,
            nur_pruefen: false,
            einwilligung_bestaetigt: true
        };

        const rolleSelect = document.getElementById('import-rolle');
        if (rolleSelect && rolleSelect.value) {
            body.rolle = rolleSelect.value;
        }

        const interessenCheckboxes = document.querySelectorAll('.import-interesse:checked');
        if (interessenCheckboxes.length > 0) {
            body.interessen = Array.from(interessenCheckboxes).map(cb => cb.value);
        }

        const result = await apiCall(`/mandanten/${m.id}/abonnenten/import`, {
            method: 'POST',
            body: JSON.stringify(body)
        });

        // Ergebnis anzeigen
        ergebnisDiv.innerHTML = '';
        const successTitle = document.createElement('h3');
        successTitle.textContent = 'Import abgeschlossen';
        successTitle.style.color = 'var(--color-success)';
        ergebnisDiv.appendChild(successTitle);

        const stats = document.createElement('dl');
        stats.style.marginTop = '1rem';

        const addStat = (label, value) => {
            const dt = document.createElement('dt');
            dt.textContent = label;
            dt.style.fontWeight = '600';
            dt.style.marginTop = '0.5rem';
            stats.appendChild(dt);
            const dd = document.createElement('dd');
            dd.textContent = value;
            dd.style.marginLeft = '1rem';
            stats.appendChild(dd);
        };

        addStat('Neu', result.neu);
        addStat('Dublette', result.dublette);
        addStat('Ungültig', result.ungueltig);
        addStat('Übersprungen', result.uebersprungen_gesamt);
        if (result.zusammengefuehrt > 0) addStat('Zusammengeführt', result.zusammengefuehrt);
        if (result.rolle_konflikt > 0) addStat('Rolle-Konflikt', result.rolle_konflikt);

        // Tags-Statistik
        if (result.tags) {
            if (result.tags.verschiedene > 0) addStat('Tags (verschiedene)', result.tags.verschiedene);
            if (result.tags.verworfen > 0) addStat('Tags (verworfen)', result.tags.verworfen);
            if (result.tags.haeufigste && result.tags.haeufigste.length > 0) {
                const haeufigsteText = result.tags.haeufigste.map(t => `${t.tag} (${t.anzahl})`).join(', ');
                addStat('Tags (häufigste)', haeufigsteText);
            }
        }

        ergebnisDiv.appendChild(stats);
        ergebnisDiv.classList.remove('hidden');

        showToast('Import erfolgreich', 'success');

        // Formular zurücksetzen
        document.getElementById('import-form').reset();
        document.getElementById('import-vorschau').classList.add('hidden');
        document.getElementById('import-einwilligung').classList.add('hidden');
        document.getElementById('btn-pruefen').disabled = true;
        document.getElementById('btn-importieren').disabled = true;

    } catch (err) {
        errorDiv.textContent = err.message;
        errorDiv.classList.remove('hidden');
    }
}

// Bilder-Verwaltung (Newsletter-Layout Etappe 1)
// API: POST/GET/DELETE /api/v1/betreiber/mandanten/<id>/bilder
async function renderBilder(m) {
    const main = document.getElementById('main');
    const card = document.createElement('div');
    card.className = 'card';

    const title = document.createElement('h2');
    title.textContent = m.name;
    card.appendChild(title);

    renderTabs(m, card);

    const subtitle = document.createElement('h3');
    subtitle.textContent = 'Bilder';
    card.appendChild(subtitle);

    // Upload-Formular
    renderBilderUpload(m, card);

    // Bilder-Liste
    const listContainer = document.createElement('div');
    listContainer.id = 'bilder-list-container';
    card.appendChild(listContainer);

    main.innerHTML = '';
    main.appendChild(card);

    await loadBilderListe(m, listContainer);
}

function renderBilderUpload(m, card) {
    const section = document.createElement('div');
    section.style.marginBottom = '2rem';
    section.style.padding = '1.5rem';
    section.style.background = '#f9fafb';
    section.style.borderRadius = '6px';

    const uploadTitle = document.createElement('h4');
    uploadTitle.textContent = 'Bild hochladen';
    uploadTitle.style.marginTop = '0';
    section.appendChild(uploadTitle);

    const form = document.createElement('form');
    form.id = 'bild-upload-form';

    const fileGroup = document.createElement('div');
    fileGroup.className = 'form-group';
    const fileLabel = document.createElement('label');
    fileLabel.textContent = 'Bilddatei *';
    fileGroup.appendChild(fileLabel);
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.id = 'bild-file';
    fileInput.accept = 'image/jpeg,image/png,image/webp';
    fileInput.required = true;
    fileGroup.appendChild(fileInput);
    const fileHelp = document.createElement('small');
    fileHelp.textContent = 'JPG, PNG oder WebP, maximal 5 MB';
    fileHelp.style.color = '#6b7280';
    fileGroup.appendChild(fileHelp);
    form.appendChild(fileGroup);

    const altGroup = document.createElement('div');
    altGroup.className = 'form-group';
    const altLabel = document.createElement('label');
    altLabel.textContent = 'Alt-Text (Bildbeschreibung) *';
    altGroup.appendChild(altLabel);
    const altInput = document.createElement('input');
    altInput.type = 'text';
    altInput.id = 'bild-alt';
    altInput.required = true;
    altInput.minLength = 1;
    altInput.maxLength = 150;
    altInput.placeholder = 'z. B. Logo der Firma Muster';
    altInput.style.width = '100%';
    altGroup.appendChild(altInput);
    const altHelp = document.createElement('small');
    altHelp.textContent = '1-150 Zeichen';
    altHelp.style.color = '#6b7280';
    altGroup.appendChild(altHelp);
    form.appendChild(altGroup);

    fileInput.addEventListener('change', () => {
        const file = fileInput.files[0];
        if (file && file.size > 5 * 1024 * 1024) {
            showToast('Datei zu groß (maximal 5 MB)', 'error');
            fileInput.value = '';
        }
    });

    const errorDiv = document.createElement('div');
    errorDiv.id = 'bild-upload-error';
    errorDiv.className = 'error hidden';
    form.appendChild(errorDiv);

    const submitBtn = document.createElement('button');
    submitBtn.type = 'submit';
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = 'Hochladen';
    form.appendChild(submitBtn);

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorDiv.className = 'error hidden';

        const file = fileInput.files[0];
        const alt = altInput.value.trim();

        if (!file || !alt || alt.length < 1 || alt.length > 150) {
            errorDiv.textContent = 'Bitte Datei und Alt-Text (1-150 Zeichen) angeben.';
            errorDiv.className = 'error';
            return;
        }

        const formData = new FormData();
        formData.append('file', file);
        formData.append('alt', alt);

        submitBtn.disabled = true;
        submitBtn.textContent = 'Wird hochgeladen...';

        try {
            const response = await fetch(`${API_BASE}/mandanten/${m.id}/bilder`, {
                method: 'POST',
                credentials: 'same-origin',
                body: formData
            });

            let data;
            try {
                data = await response.json();
            } catch (e) {
                throw new Error('Keine Antwort vom Server');
            }

            if (!response.ok) {
                throw new Error(data.meldung || data.error || 'Fehler beim Hochladen');
            }

            showToast('Bild erfolgreich hochgeladen', 'success');
            fileInput.value = '';
            altInput.value = '';
            await loadBilderListe(m, document.getElementById('bilder-list-container'));
        } catch (err) {
            errorDiv.textContent = err.message;
            errorDiv.className = 'error';
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Hochladen';
        }
    });

    section.appendChild(form);
    card.appendChild(section);
}

async function loadBilderListe(m, container) {
    container.innerHTML = '';
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading';
    loadingDiv.textContent = 'Lade Bilder...';
    container.appendChild(loadingDiv);

    try {
        const data = await apiCall(`/mandanten/${m.id}/bilder`);
        loadingDiv.remove();

        if (!data || data.length === 0) {
            const empty = document.createElement('p');
            empty.textContent = 'Noch keine Bilder hochgeladen.';
            empty.style.color = '#6b7280';
            container.appendChild(empty);
            return;
        }

        const grid = document.createElement('div');
        grid.style.display = 'grid';
        grid.style.gridTemplateColumns = 'repeat(auto-fill, minmax(200px, 1fr))';
        grid.style.gap = '1rem';

        data.forEach(bild => {
            const item = document.createElement('div');
            item.className = 'bild-item';
            item.dataset.bildId = String(bild.id);
            item.style.border = '1px solid var(--color-border)';
            item.style.borderRadius = '6px';
            item.style.padding = '0.75rem';
            item.style.background = '#fff';

            const img = document.createElement('img');
            img.src = bild.url;
            img.alt = bild.alt;
            img.style.width = '100%';
            img.style.borderRadius = '4px';
            img.style.marginBottom = '0.5rem';
            item.appendChild(img);

            const altText = document.createElement('div');
            altText.textContent = bild.alt;
            altText.style.fontWeight = '600';
            altText.style.marginBottom = '0.25rem';
            item.appendChild(altText);

            const size = document.createElement('div');
            size.textContent = `${bild.breite}×${bild.hoehe} px, ${Math.round(bild.groesse_bytes / 1024)} KB`;
            size.style.fontSize = '0.875rem';
            size.style.color = '#6b7280';
            item.appendChild(size);

            if (bild.in_verwendung) {
                const usage = document.createElement('div');
                usage.textContent = 'In Verwendung';
                usage.style.color = '#059669';
                usage.style.fontSize = '0.875rem';
                usage.style.fontWeight = '600';
                usage.style.marginTop = '0.25rem';
                item.appendChild(usage);
            }

            const deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.className = 'btn btn-secondary';
            deleteBtn.textContent = 'Löschen';
            deleteBtn.style.width = '100%';
            deleteBtn.style.marginTop = '0.5rem';
            deleteBtn.addEventListener('click', async () => {
                if (!confirm(`Bild "${bild.alt}" wirklich löschen?`)) return;
                try {
                    await apiCall(`/mandanten/${m.id}/bilder/${bild.id}`, { method: 'DELETE' });
                    showToast('Bild gelöscht', 'success');
                    await loadBilderListe(m, container);
                } catch (err) {
                    showToast(err.message, 'error');
                }
            });
            item.appendChild(deleteBtn);

            grid.appendChild(item);
        });

        container.appendChild(grid);
    } catch (err) {
        loadingDiv.textContent = 'Fehler: ' + err.message;
        loadingDiv.style.color = 'var(--color-error)';
    }
}

// ===== Layout-Newsletter (Etappe 2 und 3) =====
// Der Server bereinigt text_html ohnehin; hier entstehen clientseitig nur erlaubte Tags, fremde HTML-Fassungen werden nie roh per innerHTML gesetzt.
const LAYOUT_MAX_BILDER = 6;
const LAYOUT_MAX_TEXT_HTML = 20000;
const LAYOUT_ERLAUBT = new Set(['p', 'br', 'strong', 'em', 'h2', 'h3', 'ul', 'ol', 'li', 'a']);
const LAYOUT_ALIAS = {b: 'strong', i: 'em', div: 'p'};
const LAYOUT_VERWERFEN = new Set(['script', 'style', 'iframe', 'object', 'embed', 'noscript', 'template', 'textarea', 'title', 'head', 'svg', 'math', 'select', 'option']);
const LAYOUT_BLOECKE = new Set(['p', 'h2', 'h3']);
const LAYOUT_INLINE = new Set(['strong', 'em', 'a', 'br', 'span']);

function layoutHrefOk(href) {
    const w = (href || '').trim();
    if (!w || w.length > 500 || /[\s\x00-\x1f\x7f<>"'`\\]/.test(w)) return false;
    if (w.toLowerCase().startsWith('https://')) return w.length > 8 && !(w.split('/')[2] || '').includes('@');
    return /^mailto:[^@\s?#]{1,64}@[A-Za-z0-9.-]{1,200}\.[A-Za-z]{2,}$/i.test(w);
}

function layoutHttpsOk(url) {
    return (url || '').trim().toLowerCase().startsWith('https://') && url.trim().length <= 300 && layoutHrefOk(url);
}

// mitFarbe (nur Layout v2): <span data-farbe="#rrggbb"> bleibt erhalten, jeder andere span wird entpackt; nie style oder class
function layoutBereinige(quelle, ziel, mitFarbe) {
    Array.from(quelle.childNodes).forEach(n => {
        if (n.nodeType === 3) { ziel.appendChild(document.createTextNode(n.nodeValue)); return; }
        if (n.nodeType !== 1) return;
        const roh = n.tagName.toLowerCase();
        if (LAYOUT_VERWERFEN.has(roh)) return;
        if (roh === 'span') {
            const farbe = n.getAttribute('data-farbe');
            if (mitFarbe && typeof farbe === 'string' && /^#[0-9a-f]{6}$/i.test(farbe)) {
                const sp = document.createElement('span');
                sp.setAttribute('data-farbe', farbe.toLowerCase());
                layoutBereinige(n, sp, mitFarbe);
                ziel.appendChild(sp);
            } else {
                layoutBereinige(n, ziel, mitFarbe);
            }
            return;
        }
        const tag = LAYOUT_ALIAS[roh] || roh;
        if (!LAYOUT_ERLAUBT.has(tag) || (tag === 'a' && !layoutHrefOk(n.getAttribute('href')))) {
            layoutBereinige(n, ziel, mitFarbe);
            return;
        }
        const el = document.createElement(tag);
        if (tag === 'a') el.setAttribute('href', n.getAttribute('href').trim());
        if (LAYOUT_BLOECKE.has(tag) && n.getAttribute('data-ausrichtung') === 'zentriert') el.setAttribute('data-ausrichtung', 'zentriert');
        layoutBereinige(n, el, mitFarbe);
        ziel.appendChild(el);
    });
}

function layoutHtmlLaden(editor, html, mitFarbe) {
    const geparst = new DOMParser().parseFromString('<!doctype html><body>' + (html || ''), 'text/html');
    const tmp = document.createElement('div');
    layoutBereinige(geparst.body, tmp, mitFarbe);
    editor.textContent = '';
    while (tmp.firstChild) editor.appendChild(tmp.firstChild);
}

function layoutHtmlLesen(editor, mitFarbe) {
    const tmp = document.createElement('div');
    layoutBereinige(editor, tmp, mitFarbe);
    let lauf = null;
    Array.from(tmp.childNodes).forEach(n => {
        const inline = n.nodeType === 3 || (n.nodeType === 1 && LAYOUT_INLINE.has(n.tagName.toLowerCase()));
        if (!inline) { lauf = null; return; }
        if (!lauf) {
            if (n.nodeType === 3 && !n.nodeValue.trim()) { tmp.removeChild(n); return; }
            lauf = document.createElement('p');
            tmp.insertBefore(lauf, n);
        }
        lauf.appendChild(n);
    });
    return {html: tmp.innerHTML, text: tmp.textContent.trim()};
}

function baueLayoutEditor(m, entwurf, holeBetreff) {
    const wurzel = document.createElement('div');
    wurzel.id = 'layout-gruppe';
    let bilderListe = [];

    const feldFehler = (feld) => {
        const d = document.createElement('div');
        d.className = 'field-error hidden';
        d.dataset.feld = feld;
        return d;
    };
    const gruppe = (beschriftung, eingabe, feld, hinweis) => {
        const g = document.createElement('div');
        g.className = 'form-group';
        const l = document.createElement('label');
        l.textContent = beschriftung;
        g.appendChild(l);
        g.appendChild(eingabe);
        if (hinweis) {
            const h = document.createElement('small');
            h.textContent = hinweis;
            g.appendChild(h);
        }
        if (feld) g.appendChild(feldFehler(feld));
        return g;
    };
    const textfeld = (id, max, platzhalter) => {
        const i = document.createElement('input');
        i.type = 'text';
        if (id) i.id = id;
        i.maxLength = max;
        if (platzhalter) i.placeholder = platzhalter;
        return i;
    };
    const knopf = (text, klick, klasse) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = klasse || 'btn btn-secondary';
        b.textContent = text;
        b.addEventListener('click', klick);
        return b;
    };

    const kopf = document.createElement('h4');
    kopf.textContent = 'Layout';
    wurzel.appendChild(kopf);

    // Balken
    const balkenText = textfeld('layout-balken-text', 60);
    balkenText.value = entwurf && entwurf.blocks ? entwurf.blocks.balken.text : '';
    wurzel.appendChild(gruppe('Balken: Text (optional)', balkenText, 'balken.text', '0-60 Zeichen'));
    const balkenUrl = textfeld('layout-balken-url', 300, 'https://...');
    balkenUrl.value = entwurf && entwurf.blocks && entwurf.blocks.balken.url ? entwurf.blocks.balken.url : '';
    wurzel.appendChild(gruppe('Balken: Link (optional)', balkenUrl, 'balken.url', 'nur https://'));

    // Text mit Formatleiste
    const editor = document.createElement('div');
    editor.id = 'layout-text';
    editor.setAttribute('contenteditable', 'true');
    editor.setAttribute('role', 'textbox');
    editor.setAttribute('aria-multiline', 'true');
    editor.setAttribute('aria-label', 'Text');
    editor.style.minHeight = '12rem';
    editor.style.padding = '0.5rem';
    editor.style.border = '1px solid var(--color-border)';
    editor.style.borderRadius = '4px';
    editor.style.background = '#fff';
    layoutHtmlLaden(editor, entwurf && entwurf.blocks ? entwurf.blocks.text_html : '');

    const fokussieren = () => {
        const sel = document.getSelection();
        if (!(sel && sel.anchorNode && editor.contains(sel.anchorNode))) editor.focus();
    };
    const befehl = (name, arg) => {
        fokussieren();
        if (typeof document.execCommand === 'function') document.execCommand(name, false, arg);
    };
    const blockVon = (knoten) => {
        while (knoten && knoten !== editor && !(knoten.nodeType === 1 && LAYOUT_BLOECKE.has(knoten.tagName.toLowerCase()))) knoten = knoten.parentNode;
        return knoten && knoten !== editor ? knoten : null;
    };
    const zentrieren = () => {
        const sel = document.getSelection();
        const anker = sel && sel.anchorNode && editor.contains(sel.anchorNode) ? sel.anchorNode : null;
        let block = blockVon(anker);
        fokussieren();
        if (!block) {
            befehl('formatBlock', 'p');
            const danach = document.getSelection();
            block = blockVon(danach && danach.anchorNode && editor.contains(danach.anchorNode) ? danach.anchorNode : null);
        }
        if (!block) return;
        if (block.getAttribute('data-ausrichtung') === 'zentriert') block.removeAttribute('data-ausrichtung');
        else block.setAttribute('data-ausrichtung', 'zentriert');
    };

    const leiste = document.createElement('div');
    leiste.id = 'layout-leiste';
    leiste.setAttribute('role', 'toolbar');
    leiste.style.display = 'flex';
    leiste.style.flexWrap = 'wrap';
    leiste.style.gap = '0.25rem';
    leiste.style.marginBottom = '0.5rem';
    const linkEingabe = textfeld('layout-link-url', 500, 'https://... oder mailto:...');
    const linkFehler = feldFehler('text_html');
    [
        ['Fett', () => befehl('bold')],
        ['Kursiv', () => befehl('italic')],
        ['Absatz', () => befehl('formatBlock', 'p')],
        ['Überschrift 2', () => befehl('formatBlock', 'h2')],
        ['Überschrift 3', () => befehl('formatBlock', 'h3')],
        ['Liste', () => befehl('insertUnorderedList')],
        ['Nummerierte Liste', () => befehl('insertOrderedList')],
        ['Zentriert', zentrieren],
        ['Link setzen', () => {
            if (!layoutHrefOk(linkEingabe.value)) {
                linkFehler.textContent = 'Link: nur https:// oder mailto: erlaubt';
                linkFehler.classList.remove('hidden');
                return;
            }
            linkFehler.classList.add('hidden');
            befehl('createLink', linkEingabe.value.trim());
        }],
        ['Link entfernen', () => befehl('unlink')],
    ].forEach(([text, aktion]) => {
        const b = knopf(text, aktion, 'btn btn-secondary btn-small');
        b.addEventListener('mousedown', e => e.preventDefault());
        leiste.appendChild(b);
    });
    leiste.appendChild(linkEingabe);

    const textGruppe = document.createElement('div');
    textGruppe.className = 'form-group';
    const textLabel = document.createElement('label');
    textLabel.textContent = 'Text *';
    textGruppe.appendChild(textLabel);
    textGruppe.appendChild(leiste);
    textGruppe.appendChild(linkFehler);
    textGruppe.appendChild(editor);
    const textHinweis = document.createElement('small');
    textHinweis.textContent = 'Erlaubt: Fett, Kursiv, Überschriften, Listen, Links (https/mailto), Zentrierung. Keine Bilder, Farben oder Stile im Text.';
    textGruppe.appendChild(textHinweis);
    textGruppe.appendChild(feldFehler('text_html'));
    wurzel.appendChild(textGruppe);

    // Bilder
    const bilderTitel = document.createElement('h4');
    bilderTitel.textContent = 'Bilder (rechts neben dem Text)';
    wurzel.appendChild(bilderTitel);
    const platzListe = document.createElement('div');
    platzListe.id = 'layout-bilder';
    wurzel.appendChild(platzListe);
    const bilderFehler = feldFehler('bilder');
    wurzel.appendChild(bilderFehler);
    const zaehler = document.createElement('small');
    zaehler.id = 'layout-bilder-zaehler';
    const hinzu = knopf('Bild hinzufügen', () => neuerPlatz({}), 'btn btn-secondary');
    hinzu.id = 'layout-bild-hinzufuegen';
    const bilderZeile = document.createElement('div');
    bilderZeile.style.margin = '0.5rem 0 1rem';
    bilderZeile.appendChild(hinzu);
    bilderZeile.appendChild(document.createTextNode(' '));
    bilderZeile.appendChild(zaehler);
    wurzel.appendChild(bilderZeile);

    const optionenFuellen = (select, gewaehlt) => {
        select.textContent = '';
        const leer = document.createElement('option');
        leer.value = '';
        leer.textContent = 'Bild wählen...';
        select.appendChild(leer);
        let gefunden = gewaehlt === null || gewaehlt === undefined;
        bilderListe.forEach(b => {
            const o = document.createElement('option');
            o.value = String(b.id);
            o.textContent = b.alt + ' (#' + b.id + ')';
            if (b.id === gewaehlt) { o.selected = true; gefunden = true; }
            select.appendChild(o);
        });
        if (!gefunden) {
            const o = document.createElement('option');
            o.value = String(gewaehlt);
            o.textContent = 'Bild #' + gewaehlt;
            o.selected = true;
            select.appendChild(o);
        }
    };
    const platzAktualisieren = () => {
        const plaetze = platzListe.querySelectorAll('.layout-bild');
        plaetze.forEach((p, i) => {
            p.querySelector('.layout-bild-titel').textContent = 'Bild ' + (i + 1);
            p.querySelectorAll('[data-teil]').forEach(d => { d.dataset.feld = 'bilder[' + i + ']' + (d.dataset.teil ? '.' + d.dataset.teil : ''); });
        });
        hinzu.disabled = plaetze.length >= LAYOUT_MAX_BILDER;
        zaehler.textContent = 'Bilder: ' + plaetze.length + ' von ' + LAYOUT_MAX_BILDER;
    };
    function neuerPlatz(daten) {
        if (platzListe.querySelectorAll('.layout-bild').length >= LAYOUT_MAX_BILDER) return null;
        const p = document.createElement('div');
        p.className = 'layout-bild';
        p.style.border = '1px solid var(--color-border)';
        p.style.borderRadius = '6px';
        p.style.padding = '0.75rem';
        p.style.marginBottom = '0.75rem';
        const titel = document.createElement('strong');
        titel.className = 'layout-bild-titel';
        p.appendChild(titel);

        const teilFehler = (teil) => { const d = feldFehler(''); d.dataset.teil = teil; return d; };
        const select = document.createElement('select');
        select.className = 'layout-bild-auswahl';
        optionenFuellen(select, daten.bild_id);
        const vorschau = document.createElement('img');
        vorschau.className = 'layout-bild-vorschau';
        vorschau.style.maxWidth = '120px';
        vorschau.style.display = 'block';
        vorschau.style.marginTop = '0.5rem';
        const bildZeigen = () => {
            const b = bilderListe.find(x => String(x.id) === select.value);
            if (b) { vorschau.src = b.url; vorschau.alt = b.alt; vorschau.style.display = 'block'; }
            else { vorschau.removeAttribute('src'); vorschau.style.display = 'none'; }
        };
        const alt = textfeld(null, 150);
        alt.className = 'layout-bild-alt';
        alt.required = true;
        alt.value = daten.alt || '';
        select.addEventListener('change', () => {
            bildZeigen();
            const b = bilderListe.find(x => String(x.id) === select.value);
            if (b && !alt.value.trim()) alt.value = b.alt;
        });
        const unterschrift = textfeld(null, 200);
        unterschrift.className = 'layout-bild-unterschrift';
        unterschrift.value = daten.bildunterschrift || '';
        const url = textfeld(null, 300, 'https://...');
        url.className = 'layout-bild-url';
        url.value = daten.url || '';

        const gSelect = gruppe('Bild *', select, null);
        gSelect.appendChild(vorschau);
        gSelect.appendChild(teilFehler('bild_id'));
        p.appendChild(gSelect);
        const gAlt = gruppe('Alternativtext * (1-150 Zeichen)', alt, null);
        gAlt.appendChild(teilFehler('alt'));
        p.appendChild(gAlt);
        const gUnter = gruppe('Bildunterschrift (optional, 0-200 Zeichen)', unterschrift, null);
        gUnter.appendChild(teilFehler('bildunterschrift'));
        p.appendChild(gUnter);
        const gUrl = gruppe('Link (optional, nur https://)', url, null);
        gUrl.appendChild(teilFehler('url'));
        p.appendChild(gUrl);
        const entfernen = knopf('Bild entfernen', () => { p.remove(); platzAktualisieren(); });
        entfernen.className = 'btn btn-secondary layout-bild-entfernen';
        p.appendChild(entfernen);
        p.appendChild(teilFehler(''));

        platzListe.appendChild(p);
        bildZeigen();
        platzAktualisieren();
        return p;
    }
    const gespeicherteBilder = entwurf && entwurf.blocks ? entwurf.blocks.bilder : [];
    gespeicherteBilder.forEach(b => neuerPlatz(b));
    platzAktualisieren();

    // Fehleranzeige am Feld
    const fehlerLoeschen = () => {
        wurzel.querySelectorAll('[data-feld]').forEach(d => { d.textContent = ''; d.classList.add('hidden'); });
        wurzel.querySelectorAll('[aria-invalid]').forEach(e => e.removeAttribute('aria-invalid'));
    };
    const fehlerZeigen = (feld, meldung) => {
        const alle = Array.from(wurzel.querySelectorAll('[data-feld]'));
        const kandidaten = [feld, (feld || '').replace(/\.[a-z_]+$/, ''), (feld || '').replace(/\[\d+\].*$/, '')];
        for (const k of kandidaten) {
            const d = alle.find(x => x.dataset.feld === k);
            if (d) {
                d.textContent = meldung;
                d.classList.remove('hidden');
                const eingabe = d.previousElementSibling;
                if (eingabe && /^(INPUT|SELECT)$/.test(eingabe.tagName)) eingabe.setAttribute('aria-invalid', 'true');
                return true;
            }
        }
        return false;
    };

    // Blöcke einsammeln und clientseitig prüfen
    const blocksLesen = () => {
        const fehler = [];
        const bt = balkenText.value.trim();
        const bu = balkenUrl.value.trim();
        if (bu && !layoutHttpsOk(bu)) fehler.push({feld: 'balken.url', meldung: 'Der Link muss eine https-Adresse sein'});
        const gelesen = layoutHtmlLesen(editor);
        if (!gelesen.text) fehler.push({feld: 'text_html', meldung: 'Der Text darf nicht leer sein'});
        if (gelesen.html.length > LAYOUT_MAX_TEXT_HTML) fehler.push({feld: 'text_html', meldung: 'Der Text ist zu lang (höchstens ' + LAYOUT_MAX_TEXT_HTML + ' Zeichen)'});
        const bilder = [];
        platzListe.querySelectorAll('.layout-bild').forEach((p, i) => {
            const id = parseInt(p.querySelector('.layout-bild-auswahl').value, 10);
            const a = p.querySelector('.layout-bild-alt').value.trim();
            const u = p.querySelector('.layout-bild-unterschrift').value.trim();
            const l = p.querySelector('.layout-bild-url').value.trim();
            if (Number.isNaN(id)) fehler.push({feld: 'bilder[' + i + '].bild_id', meldung: 'Bitte ein Bild wählen'});
            if (!a || a.length > 150) fehler.push({feld: 'bilder[' + i + '].alt', meldung: 'Alternativtext fehlt (1-150 Zeichen)'});
            if (u.length > 200) fehler.push({feld: 'bilder[' + i + '].bildunterschrift', meldung: 'Bildunterschrift: höchstens 200 Zeichen'});
            if (l && !layoutHttpsOk(l)) fehler.push({feld: 'bilder[' + i + '].url', meldung: 'Der Link muss eine https-Adresse sein'});
            bilder.push({bild_id: Number.isNaN(id) ? null : id, alt: a, bildunterschrift: u, url: l || null});
        });
        return {
            blocks: {version: 1, balken: {text: bt, url: bu || null}, text_html: gelesen.html, bilder},
            fehler,
        };
    };

    // Vorschau (Etappe 3)
    const zeigeClientFehler = (liste) => {
        liste.forEach(f => fehlerZeigen(f.feld, f.meldung));
    };
    wurzel.appendChild(layoutVorschauBauen(m, holeBetreff, {
        lesen: () => blocksLesen(),
        loeschen: () => fehlerLoeschen(),
        clientFehler: (liste) => zeigeClientFehler(liste),
        serverFehler: (feld, meldung) => fehlerZeigen(feld, meldung),
    }));

    return {
        el: wurzel,
        blocksLesen,
        fehlerLoeschen,
        fehlerZeigen,
        zeigeClientFehler,
        setzeBilderListe(liste) {
            bilderListe = liste || [];
            platzListe.querySelectorAll('.layout-bild').forEach(p => {
                const s = p.querySelector('.layout-bild-auswahl');
                const gewaehlt = parseInt(s.value, 10);
                optionenFuellen(s, Number.isNaN(gewaehlt) ? null : gewaehlt);
                const b = bilderListe.find(x => x.id === gewaehlt);
                const v = p.querySelector('.layout-bild-vorschau');
                if (b) { v.src = b.url; v.alt = b.alt; v.style.display = 'block'; }
            });
        },
        async ladeBilder() {
            this.setzeBilderListe(await apiCall(`/mandanten/${m.id}/bilder`));
        },
    };
}

// Vorschau (Etappe 3), von v1 und v2 gemeinsam benutzt: iframe sandbox="" mit srcdoc, Warnungen, Text-Fassung.
// cb: {lesen() -> {blocks, fehler}, loeschen(), clientFehler(liste), serverFehler(feld, meldung) -> bool}
function layoutVorschauBauen(m, holeBetreff, cb) {
    const bereich = document.createElement('div');
    bereich.id = 'layout-vorschau';
    bereich.style.marginTop = '1rem';
    const kopf = document.createElement('h4');
    kopf.textContent = 'Vorschau';
    bereich.appendChild(kopf);
    const aktion = document.createElement('div');
    const knopf = (text, klick) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn btn-secondary';
        b.textContent = text;
        b.addEventListener('click', klick);
        return b;
    };
    const vorschauKnopf = knopf('Vorschau aktualisieren', () => laden());
    vorschauKnopf.id = 'layout-vorschau-btn';
    aktion.appendChild(vorschauKnopf);
    const textKnopf = knopf('Text-Fassung anzeigen', () => {
        textAnsicht.classList.toggle('hidden');
        textKnopf.textContent = textAnsicht.classList.contains('hidden') ? 'Text-Fassung anzeigen' : 'Text-Fassung ausblenden';
    });
    textKnopf.id = 'layout-vorschau-text-btn';
    textKnopf.classList.add('hidden');
    aktion.appendChild(document.createTextNode(' '));
    aktion.appendChild(textKnopf);
    bereich.appendChild(aktion);
    const fehlerDiv = document.createElement('div');
    fehlerDiv.id = 'layout-vorschau-fehler';
    fehlerDiv.className = 'error hidden';
    bereich.appendChild(fehlerDiv);
    const warnungen = document.createElement('ul');
    warnungen.id = 'layout-vorschau-warnungen';
    bereich.appendChild(warnungen);
    const rahmenHalter = document.createElement('div');
    rahmenHalter.id = 'layout-vorschau-halter';
    bereich.appendChild(rahmenHalter);
    const textAnsicht = document.createElement('pre');
    textAnsicht.id = 'layout-vorschau-text';
    textAnsicht.className = 'hidden';
    textAnsicht.style.whiteSpace = 'pre-wrap';
    bereich.appendChild(textAnsicht);

    async function laden() {
        cb.loeschen();
        fehlerDiv.classList.add('hidden');
        const gelesen = cb.lesen();
        if (gelesen.fehler.length) {
            cb.clientFehler(gelesen.fehler);
            return;
        }
        const body = {blocks: gelesen.blocks};
        const betreff = (holeBetreff() || '').trim();
        if (betreff) body.betreff = betreff;
        try {
            const erg = await apiCall(`/mandanten/${m.id}/entwuerfe/vorschau`, {method: 'POST', body: JSON.stringify(body)});
            let rahmen = document.getElementById('layout-vorschau-frame');
            if (!rahmen) {
                rahmen = document.createElement('iframe');
                rahmen.id = 'layout-vorschau-frame';
                rahmen.setAttribute('sandbox', '');
                rahmen.title = 'Vorschau des Newsletters';
                rahmen.style.width = '100%';
                rahmen.style.height = '600px';
                rahmen.style.border = '1px solid var(--color-border)';
                rahmenHalter.appendChild(rahmen);
            }
            rahmen.srcdoc = erg.html;
            warnungen.textContent = '';
            (erg.warnungen || []).forEach(w => {
                const li = document.createElement('li');
                li.textContent = typeof w === 'string' ? w : (w.meldung || JSON.stringify(w));
                warnungen.appendChild(li);
            });
            textAnsicht.textContent = erg.text || '';
            textKnopf.classList.remove('hidden');
        } catch (err) {
            if (!err.feld || !cb.serverFehler(err.feld, err.message)) {
                fehlerDiv.textContent = err.message;
                fehlerDiv.classList.remove('hidden');
            }
        }
    }
    return bereich;
}

// ===== Layout v2: zwei Spalten mit freien Blöcken (catrin #19220, Variante A) =====
const LAYOUT2_MAX_BLOECKE = 20;
const LAYOUT2_MAX_BILDER = 12;
const LAYOUT2_MAX_TEXT_BLOCK = 20000;
const LAYOUT2_MAX_TEXT_GESAMT = 60000;
const LAYOUT2_SPALTEN = [['links', 'Linke Spalte'], ['rechts', 'Rechte Spalte']];
const LAYOUT2_AUSRICHTUNGEN = [['links', 'Links'], ['blocksatz', 'Blocksatz'], ['zentriert', 'Zentriert']];

function layoutFarbeOk(farbe) {
    return typeof farbe === 'string' && /^#[0-9a-f]{6}$/i.test(farbe);
}

function layoutFeldFehler(feld) {
    const d = document.createElement('div');
    d.className = 'field-error hidden';
    d.dataset.feld = feld;
    return d;
}

function layoutTextfeld(id, max, platzhalter) {
    const i = document.createElement('input');
    i.type = 'text';
    if (id) i.id = id;
    i.maxLength = max;
    if (platzhalter) i.placeholder = platzhalter;
    return i;
}

function layoutKnopf(text, klick, klasse) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = klasse || 'btn btn-secondary';
    b.textContent = text;
    b.addEventListener('click', klick);
    return b;
}

function layoutGruppe(beschriftung, inhalt, hinweis) {
    const g = document.createElement('div');
    g.className = 'form-group';
    const l = document.createElement('label');
    l.textContent = beschriftung;
    g.appendChild(l);
    g.appendChild(inhalt);
    if (hinweis) {
        const h = document.createElement('small');
        h.textContent = hinweis;
        g.appendChild(h);
    }
    return g;
}

// Farbfeld mit "Standardfarbe": solange kein Wert gewählt ist, bleibt die Farbe null (= Standard des Layouts)
function layoutFarbWahl(beschriftung, startwert, klasse) {
    const huelle = document.createElement('div');
    huelle.className = 'layout-farbe ' + (klasse || '');
    const label = document.createElement('label');
    label.textContent = beschriftung + ' ';
    const eingabe = document.createElement('input');
    eingabe.type = 'color';
    eingabe.className = 'layout-farbe-eingabe';
    let standard = !layoutFarbeOk(startwert);
    eingabe.value = standard ? '#000000' : startwert.toLowerCase();
    const stand = document.createElement('small');
    stand.className = 'layout-farbe-stand';
    const zeigen = () => { stand.textContent = standard ? ' Standardfarbe' : ' ' + eingabe.value.toLowerCase(); };
    const gewaehlt = () => { standard = false; zeigen(); };
    eingabe.addEventListener('input', gewaehlt);
    eingabe.addEventListener('change', gewaehlt);
    const zuruecksetzen = layoutKnopf('Standardfarbe', () => { standard = true; zeigen(); }, 'btn btn-secondary btn-small layout-farbe-standard');
    label.appendChild(eingabe);
    huelle.appendChild(label);
    huelle.appendChild(stand);
    huelle.appendChild(document.createTextNode(' '));
    huelle.appendChild(zuruecksetzen);
    zeigen();
    return {
        el: huelle,
        lesen: () => (standard ? null : eingabe.value.toLowerCase()),
        gueltig: () => standard || layoutFarbeOk(eingabe.value),
    };
}

// Formatleiste eines Textblocks: nur erlaubte Tags; Farbe für markierte Stellen als span data-farbe (nie style)
function layoutFormatleisteV2(editor, meldeFehler) {
    const leiste = document.createElement('div');
    leiste.className = 'layout-leiste';
    leiste.setAttribute('role', 'toolbar');
    leiste.style.display = 'flex';
    leiste.style.flexWrap = 'wrap';
    leiste.style.gap = '0.25rem';
    leiste.style.marginBottom = '0.5rem';

    const imEditor = (knoten) => !!knoten && editor.contains(knoten);
    const fokussieren = () => {
        const sel = document.getSelection();
        if (!(sel && imEditor(sel.anchorNode))) editor.focus();
    };
    const befehl = (name, arg) => {
        fokussieren();
        if (typeof document.execCommand === 'function') document.execCommand(name, false, arg);
    };
    const blockVon = (knoten) => {
        while (knoten && knoten !== editor && !(knoten.nodeType === 1 && LAYOUT_BLOECKE.has(knoten.tagName.toLowerCase()))) knoten = knoten.parentNode;
        return knoten && knoten !== editor ? knoten : null;
    };
    const zentrieren = () => {
        const sel = document.getSelection();
        let block = blockVon(sel && imEditor(sel.anchorNode) ? sel.anchorNode : null);
        fokussieren();
        if (!block) {
            befehl('formatBlock', 'p');
            const danach = document.getSelection();
            block = blockVon(danach && imEditor(danach.anchorNode) ? danach.anchorNode : null);
        }
        if (!block) return;
        if (block.getAttribute('data-ausrichtung') === 'zentriert') block.removeAttribute('data-ausrichtung');
        else block.setAttribute('data-ausrichtung', 'zentriert');
    };
    const markierung = () => {
        const sel = document.getSelection();
        return sel && sel.rangeCount > 0 && !sel.isCollapsed && imEditor(sel.anchorNode) && imEditor(sel.focusNode) ? sel : null;
    };

    const linkEingabe = layoutTextfeld(null, 500, 'https://... oder mailto:...');
    linkEingabe.className = 'layout-link-url';
    const farbeEingabe = document.createElement('input');
    farbeEingabe.type = 'color';
    farbeEingabe.className = 'layout-markierung-farbe';
    farbeEingabe.value = '#b91c1c';

    [
        ['Fett', () => befehl('bold')],
        ['Kursiv', () => befehl('italic')],
        ['Absatz', () => befehl('formatBlock', 'p')],
        ['Überschrift 2', () => befehl('formatBlock', 'h2')],
        ['Überschrift 3', () => befehl('formatBlock', 'h3')],
        ['Liste', () => befehl('insertUnorderedList')],
        ['Nummerierte Liste', () => befehl('insertOrderedList')],
        ['Zentriert', zentrieren],
        ['Link setzen', () => {
            if (!layoutHrefOk(linkEingabe.value)) {
                meldeFehler('Link: nur https:// oder mailto: erlaubt');
                return;
            }
            meldeFehler('');
            befehl('createLink', linkEingabe.value.trim());
        }],
        ['Link entfernen', () => befehl('unlink')],
        ['Markierung färben', () => {
            const sel = markierung();
            if (!sel) { meldeFehler('Bitte zuerst eine Textstelle markieren.'); return; }
            const farbe = (farbeEingabe.value || '').toLowerCase();
            if (!layoutFarbeOk(farbe)) { meldeFehler('Farbe ungültig (nur #rrggbb).'); return; }
            meldeFehler('');
            const bereich = sel.getRangeAt(0);
            const span = document.createElement('span');
            span.setAttribute('data-farbe', farbe);
            span.appendChild(bereich.extractContents());
            bereich.insertNode(span);
            sel.removeAllRanges();
            const neu = document.createRange();
            neu.selectNodeContents(span);
            sel.addRange(neu);
        }],
        ['Markierungsfarbe entfernen', () => {
            const sel = markierung();
            if (!sel) { meldeFehler('Bitte zuerst eine Textstelle markieren.'); return; }
            meldeFehler('');
            const bereich = sel.getRangeAt(0);
            Array.from(editor.querySelectorAll('span[data-farbe]')).forEach(sp => {
                if (!bereich.intersectsNode(sp)) return;
                while (sp.firstChild) sp.parentNode.insertBefore(sp.firstChild, sp);
                sp.remove();
            });
        }],
    ].forEach(([text, aktion]) => {
        const b = layoutKnopf(text, aktion, 'btn btn-secondary btn-small');
        b.addEventListener('mousedown', e => e.preventDefault());
        leiste.appendChild(b);
    });
    leiste.appendChild(linkEingabe);
    leiste.appendChild(farbeEingabe);
    return leiste;
}

function baueLayoutEditorV2(m, entwurf, holeBetreff) {
    const wurzel = document.createElement('div');
    wurzel.id = 'layout-gruppe';
    wurzel.dataset.version = '2';
    let bilderListe = [];
    const daten = entwurf && entwurf.blocks && entwurf.blocks.version === 2 ? entwurf.blocks : null;
    const balkenDaten = (daten && daten.balken) || {};

    const kopf = document.createElement('h4');
    kopf.textContent = 'Layout (zwei Spalten)';
    wurzel.appendChild(kopf);

    // Balken: Text, Link, Farbe des Titels
    const balkenText = layoutTextfeld('layout-balken-text', 60);
    balkenText.value = balkenDaten.text || '';
    const balkenGruppeText = layoutGruppe('Balken: Text (optional)', balkenText, '0-60 Zeichen');
    balkenGruppeText.appendChild(layoutFeldFehler('balken.text'));
    wurzel.appendChild(balkenGruppeText);
    const balkenUrl = layoutTextfeld('layout-balken-url', 300, 'https://...');
    balkenUrl.value = balkenDaten.url || '';
    const balkenGruppeUrl = layoutGruppe('Balken: Link (optional)', balkenUrl, 'nur https://');
    balkenGruppeUrl.appendChild(layoutFeldFehler('balken.url'));
    wurzel.appendChild(balkenGruppeUrl);
    const balkenFarbe = layoutFarbWahl('Balken: Farbe des Titels', balkenDaten.farbe, 'layout-balken-farbe');
    const balkenGruppeFarbe = document.createElement('div');
    balkenGruppeFarbe.className = 'form-group';
    balkenGruppeFarbe.appendChild(balkenFarbe.el);
    balkenGruppeFarbe.appendChild(layoutFeldFehler('balken.farbe'));
    wurzel.appendChild(balkenGruppeFarbe);

    // Zwei Spalten
    const spaltenBox = document.createElement('div');
    spaltenBox.style.display = 'grid';
    spaltenBox.style.gridTemplateColumns = 'repeat(auto-fit, minmax(320px, 1fr))';
    spaltenBox.style.gap = '1rem';
    const spalten = {};
    LAYOUT2_SPALTEN.forEach(([seite, titel]) => {
        const box = document.createElement('div');
        box.id = 'spalte-' + seite;
        box.className = 'layout-spalte';
        box.style.border = '1px solid var(--color-border)';
        box.style.borderRadius = '6px';
        box.style.padding = '0.75rem';
        const ueberschrift = document.createElement('h4');
        ueberschrift.textContent = titel;
        box.appendChild(ueberschrift);
        const liste = document.createElement('div');
        liste.className = 'layout-spalte-liste';
        box.appendChild(liste);
        box.appendChild(layoutFeldFehler('spalten.' + seite));
        const zeile = document.createElement('div');
        zeile.style.margin = '0.5rem 0';
        const addText = layoutKnopf('+ Text', () => neuerBlock(seite, 'text', {}), 'btn btn-secondary layout-add-text');
        const addBild = layoutKnopf('+ Bild', () => neuerBlock(seite, 'bild', {}), 'btn btn-secondary layout-add-bild');
        const zaehler = document.createElement('small');
        zaehler.className = 'layout-spalte-zaehler';
        zeile.appendChild(addText);
        zeile.appendChild(document.createTextNode(' '));
        zeile.appendChild(addBild);
        zeile.appendChild(document.createTextNode(' '));
        zeile.appendChild(zaehler);
        box.appendChild(zeile);
        spaltenBox.appendChild(box);
        spalten[seite] = {box, liste, addText, addBild, zaehler};
    });
    wurzel.appendChild(spaltenBox);
    const bilderZaehler = document.createElement('small');
    bilderZaehler.id = 'layout-bilder-zaehler';
    bilderZaehler.style.display = 'block';
    bilderZaehler.style.marginTop = '0.5rem';
    wurzel.appendChild(bilderZaehler);
    wurzel.appendChild(layoutFeldFehler('spalten'));

    const bloecke = (seite) => Array.from(spalten[seite].liste.children).filter(c => c.classList.contains('layout-block'));
    const bilderGesamt = () => LAYOUT2_SPALTEN.reduce((n, [s]) => n + bloecke(s).filter(b => b.dataset.typ === 'bild').length, 0);

    const aktualisieren = () => {
        const bilder = bilderGesamt();
        LAYOUT2_SPALTEN.forEach(([seite]) => {
            const alle = bloecke(seite);
            alle.forEach((b, i) => {
                b.querySelector('.layout-block-titel').textContent = (b.dataset.typ === 'text' ? 'Text ' : 'Bild ') + (i + 1);
                b.querySelectorAll('[data-teil]').forEach(d => { d.dataset.feld = `spalten.${seite}[${i}]` + (d.dataset.teil ? '.' + d.dataset.teil : ''); });
                b.querySelector('.layout-block-hoch').disabled = i === 0;
                b.querySelector('.layout-block-runter').disabled = i === alle.length - 1;
            });
            const s = spalten[seite];
            s.addText.disabled = alle.length >= LAYOUT2_MAX_BLOECKE;
            s.addBild.disabled = alle.length >= LAYOUT2_MAX_BLOECKE || bilder >= LAYOUT2_MAX_BILDER;
            s.zaehler.textContent = `Blöcke: ${alle.length} von ${LAYOUT2_MAX_BLOECKE}`;
        });
        bilderZaehler.textContent = `Bilder: ${bilder} von ${LAYOUT2_MAX_BILDER}`;
    };

    const teilFehler = (teil) => {
        const d = layoutFeldFehler('');
        d.dataset.teil = teil;
        return d;
    };
    const blockHuelle = (seite, typ) => {
        const el = document.createElement('div');
        el.className = 'layout-block';
        el.dataset.typ = typ;
        el.style.border = '1px solid var(--color-border)';
        el.style.borderRadius = '6px';
        el.style.padding = '0.5rem';
        el.style.margin = '0.5rem 0';
        el.style.background = '#fff';
        const kopfzeile = document.createElement('div');
        kopfzeile.style.display = 'flex';
        kopfzeile.style.gap = '0.25rem';
        kopfzeile.style.alignItems = 'center';
        const titel = document.createElement('strong');
        titel.className = 'layout-block-titel';
        titel.style.flex = '1';
        kopfzeile.appendChild(titel);
        const hoch = layoutKnopf('Hoch', () => {
            const davor = el.previousElementSibling;
            if (davor) spalten[seite].liste.insertBefore(el, davor);
            aktualisieren();
        }, 'btn btn-secondary btn-small layout-block-hoch');
        const runter = layoutKnopf('Runter', () => {
            const danach = el.nextElementSibling;
            if (danach) spalten[seite].liste.insertBefore(danach, el);
            aktualisieren();
        }, 'btn btn-secondary btn-small layout-block-runter');
        const loeschen = layoutKnopf('Löschen', () => { el.remove(); aktualisieren(); }, 'btn btn-secondary btn-small layout-block-loeschen');
        kopfzeile.appendChild(hoch);
        kopfzeile.appendChild(runter);
        kopfzeile.appendChild(loeschen);
        el.appendChild(kopfzeile);
        el.appendChild(teilFehler(''));
        return el;
    };

    const optionenFuellen = (select, gewaehlt) => {
        select.textContent = '';
        const leer = document.createElement('option');
        leer.value = '';
        leer.textContent = 'Bild wählen...';
        select.appendChild(leer);
        let gefunden = gewaehlt === null || gewaehlt === undefined;
        bilderListe.forEach(b => {
            const o = document.createElement('option');
            o.value = String(b.id);
            o.textContent = b.alt + ' (#' + b.id + ')';
            if (b.id === gewaehlt) { o.selected = true; gefunden = true; }
            select.appendChild(o);
        });
        if (!gefunden) {
            const o = document.createElement('option');
            o.value = String(gewaehlt);
            o.textContent = 'Bild #' + gewaehlt;
            o.selected = true;
            select.appendChild(o);
        }
    };

    function textBlock(seite, d) {
        const el = blockHuelle(seite, 'text');
        const editor = document.createElement('div');
        editor.className = 'layout-block-text';
        editor.setAttribute('contenteditable', 'true');
        editor.setAttribute('role', 'textbox');
        editor.setAttribute('aria-multiline', 'true');
        editor.setAttribute('aria-label', 'Text');
        editor.style.minHeight = '6rem';
        editor.style.padding = '0.5rem';
        editor.style.border = '1px solid var(--color-border)';
        editor.style.borderRadius = '4px';
        editor.style.background = '#fff';
        layoutHtmlLaden(editor, d.text_html || '', true);
        const fehlerText = teilFehler('text_html');
        const melde = (t) => { fehlerText.textContent = t || ''; fehlerText.classList.toggle('hidden', !t); };
        el.appendChild(layoutFormatleisteV2(editor, melde));
        el.appendChild(editor);
        el.appendChild(fehlerText);

        const ausrichtung = document.createElement('select');
        ausrichtung.className = 'layout-block-ausrichtung';
        LAYOUT2_AUSRICHTUNGEN.forEach(([wert, text]) => {
            const o = document.createElement('option');
            o.value = wert;
            o.textContent = text;
            ausrichtung.appendChild(o);
        });
        ausrichtung.value = LAYOUT2_AUSRICHTUNGEN.some(([w]) => w === d.ausrichtung) ? d.ausrichtung : 'links';
        const gAusr = layoutGruppe('Ausrichtung', ausrichtung);
        gAusr.appendChild(teilFehler('ausrichtung'));
        el.appendChild(gAusr);
        const farbe = layoutFarbWahl('Textfarbe', d.farbe, 'layout-block-farbe');
        const gFarbe = document.createElement('div');
        gFarbe.className = 'form-group';
        gFarbe.appendChild(farbe.el);
        gFarbe.appendChild(teilFehler('farbe'));
        el.appendChild(gFarbe);

        el._lesen = (pfad, fehler) => {
            const gelesen = layoutHtmlLesen(editor, true);
            if (!gelesen.text) fehler.push({feld: pfad + '.text_html', meldung: 'Der Text darf nicht leer sein'});
            if (gelesen.html.length > LAYOUT2_MAX_TEXT_BLOCK) fehler.push({feld: pfad + '.text_html', meldung: `Der Text ist zu lang (höchstens ${LAYOUT2_MAX_TEXT_BLOCK} Zeichen)`});
            if (!farbe.gueltig()) fehler.push({feld: pfad + '.farbe', meldung: 'Farbe ungültig (nur #rrggbb)'});
            return {block: {typ: 'text', text_html: gelesen.html, ausrichtung: ausrichtung.value, farbe: farbe.gueltig() ? farbe.lesen() : null}, textLaenge: gelesen.html.length};
        };
        return el;
    }

    function bildBlock(seite, d) {
        const el = blockHuelle(seite, 'bild');
        const select = document.createElement('select');
        select.className = 'layout-bild-auswahl';
        optionenFuellen(select, d.bild_id);
        const vorschau = document.createElement('img');
        vorschau.className = 'layout-bild-vorschau';
        vorschau.style.maxWidth = '120px';
        vorschau.style.display = 'block';
        vorschau.style.marginTop = '0.5rem';
        const alt = layoutTextfeld(null, 150);
        alt.className = 'layout-bild-alt';
        alt.value = d.alt || '';
        const bildZeigen = () => {
            const b = bilderListe.find(x => String(x.id) === select.value);
            if (b) { vorschau.src = b.url; vorschau.alt = b.alt; vorschau.style.display = 'block'; alt.placeholder = 'leer = ' + b.alt; }
            else { vorschau.removeAttribute('src'); vorschau.style.display = 'none'; alt.placeholder = 'leer = Alternativtext des Bildes'; }
        };
        select.addEventListener('change', bildZeigen);
        const unterschrift = layoutTextfeld(null, 200);
        unterschrift.className = 'layout-bild-unterschrift';
        unterschrift.value = d.bildunterschrift || '';
        const url = layoutTextfeld(null, 300, 'https://...');
        url.className = 'layout-bild-url';
        url.value = d.url || '';
        const farbe = layoutFarbWahl('Untertitelfarbe', d.bildunterschrift_farbe, 'layout-bild-farbe');

        const gSelect = layoutGruppe('Bild *', select);
        gSelect.appendChild(vorschau);
        gSelect.appendChild(teilFehler('bild_id'));
        el.appendChild(gSelect);
        const gAlt = layoutGruppe('Alternativtext (optional, leer = Text des Bildes)', alt);
        gAlt.appendChild(teilFehler('alt'));
        el.appendChild(gAlt);
        const gUnter = layoutGruppe('Bildunterschrift (optional, 0-200 Zeichen)', unterschrift);
        gUnter.appendChild(teilFehler('bildunterschrift'));
        el.appendChild(gUnter);
        const gFarbe = document.createElement('div');
        gFarbe.className = 'form-group';
        gFarbe.appendChild(farbe.el);
        gFarbe.appendChild(teilFehler('bildunterschrift_farbe'));
        el.appendChild(gFarbe);
        const gUrl = layoutGruppe('Link (optional, nur https://)', url);
        gUrl.appendChild(teilFehler('url'));
        el.appendChild(gUrl);
        bildZeigen();

        el._lesen = (pfad, fehler) => {
            const id = parseInt(select.value, 10);
            const a = alt.value.trim();
            const u = unterschrift.value.trim();
            const l = url.value.trim();
            if (Number.isNaN(id)) fehler.push({feld: pfad + '.bild_id', meldung: 'Bitte ein Bild wählen'});
            if (a.length > 150) fehler.push({feld: pfad + '.alt', meldung: 'Alternativtext: höchstens 150 Zeichen'});
            if (u.length > 200) fehler.push({feld: pfad + '.bildunterschrift', meldung: 'Bildunterschrift: höchstens 200 Zeichen'});
            if (!farbe.gueltig()) fehler.push({feld: pfad + '.bildunterschrift_farbe', meldung: 'Farbe ungültig (nur #rrggbb)'});
            if (l && !layoutHttpsOk(l)) fehler.push({feld: pfad + '.url', meldung: 'Der Link muss eine https-Adresse sein'});
            return {block: {typ: 'bild', bild_id: Number.isNaN(id) ? null : id, alt: a, bildunterschrift: u, bildunterschrift_farbe: farbe.gueltig() ? farbe.lesen() : null, url: l || null}, textLaenge: 0};
        };
        return el;
    }

    function neuerBlock(seite, typ, d) {
        if (bloecke(seite).length >= LAYOUT2_MAX_BLOECKE) return null;
        if (typ === 'bild' && bilderGesamt() >= LAYOUT2_MAX_BILDER) return null;
        const el = typ === 'bild' ? bildBlock(seite, d) : textBlock(seite, d);
        spalten[seite].liste.appendChild(el);
        aktualisieren();
        return el;
    }
    if (daten && daten.spalten) {
        LAYOUT2_SPALTEN.forEach(([seite]) => {
            (daten.spalten[seite] || []).forEach(b => {
                if (b && (b.typ === 'text' || b.typ === 'bild')) neuerBlock(seite, b.typ, b);
            });
        });
    }
    aktualisieren();

    // Fehleranzeige am Feld; ohne genauen Treffer wird von hinten gekürzt (…[i].teil, …[i], Spalte, spalten)
    const fehlerLoeschen = () => {
        wurzel.querySelectorAll('[data-feld]').forEach(d => { d.textContent = ''; d.classList.add('hidden'); });
        wurzel.querySelectorAll('[aria-invalid]').forEach(e => e.removeAttribute('aria-invalid'));
    };
    const fehlerZeigen = (feld, meldung) => {
        const alle = Array.from(wurzel.querySelectorAll('[data-feld]'));
        let f = (feld || '').replace(/^blocks\./, '');
        while (f) {
            const d = alle.find(x => x.dataset.feld === f);
            if (d) {
                d.textContent = meldung;
                d.classList.remove('hidden');
                const eingabe = d.previousElementSibling;
                if (eingabe && /^(INPUT|SELECT)$/.test(eingabe.tagName)) eingabe.setAttribute('aria-invalid', 'true');
                return true;
            }
            const kuerzer = f.replace(/(\.[A-Za-z_0-9]+|\[\d+\])$/, '');
            if (kuerzer === f) break;
            f = kuerzer;
        }
        return false;
    };
    const zeigeClientFehler = (liste) => { liste.forEach(f => fehlerZeigen(f.feld, f.meldung)); };

    const blocksLesen = () => {
        const fehler = [];
        const bt = balkenText.value.trim();
        const bu = balkenUrl.value.trim();
        if (bt.length > 60) fehler.push({feld: 'balken.text', meldung: 'Der Balkentext darf höchstens 60 Zeichen haben'});
        if (bu && !layoutHttpsOk(bu)) fehler.push({feld: 'balken.url', meldung: 'Der Link muss eine https-Adresse sein'});
        if (!balkenFarbe.gueltig()) fehler.push({feld: 'balken.farbe', meldung: 'Farbe ungültig (nur #rrggbb)'});
        const ergebnis = {links: [], rechts: []};
        let gesamt = 0;
        let textGesamt = 0;
        LAYOUT2_SPALTEN.forEach(([seite]) => {
            bloecke(seite).forEach((b, i) => {
                const gelesen = b._lesen(`spalten.${seite}[${i}]`, fehler);
                ergebnis[seite].push(gelesen.block);
                textGesamt += gelesen.textLaenge;
                gesamt++;
            });
        });
        if (gesamt === 0) fehler.push({feld: 'spalten', meldung: 'Bitte mindestens einen Block anlegen'});
        if (textGesamt > LAYOUT2_MAX_TEXT_GESAMT) fehler.push({feld: 'spalten', meldung: `Alle Texte zusammen sind zu lang (höchstens ${LAYOUT2_MAX_TEXT_GESAMT} Zeichen)`});
        return {
            blocks: {version: 2, balken: {text: bt, url: bu || null, farbe: balkenFarbe.gueltig() ? balkenFarbe.lesen() : null}, spalten: ergebnis},
            fehler,
        };
    };

    wurzel.appendChild(layoutVorschauBauen(m, holeBetreff, {
        lesen: () => blocksLesen(),
        loeschen: () => fehlerLoeschen(),
        clientFehler: (liste) => zeigeClientFehler(liste),
        serverFehler: (feld, meldung) => fehlerZeigen(feld, meldung),
    }));

    return {
        el: wurzel,
        blocksLesen,
        fehlerLoeschen,
        fehlerZeigen,
        zeigeClientFehler,
        setzeBilderListe(liste) {
            bilderListe = liste || [];
            wurzel.querySelectorAll('.layout-bild-auswahl').forEach(s => {
                const gewaehlt = parseInt(s.value, 10);
                optionenFuellen(s, Number.isNaN(gewaehlt) ? null : gewaehlt);
                s.dispatchEvent(new Event('change'));
            });
        },
        async ladeBilder() {
            this.setzeBilderListe(await apiCall(`/mandanten/${m.id}/bilder`));
        },
    };
}

// Initialisierung
document.addEventListener('DOMContentLoaded', () => {
    renderNav();
    loadMandanten();
});
