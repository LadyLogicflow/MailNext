// MailNext Betreiber-Oberfläche - CSP 'self' konform (keine Inline-Scripts)

const API_BASE = '/api/v1/betreiber';
let state = {
    mandanten: [],
    currentView: 'liste'
};

// Hilfsfunktionen
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast show';
    if (type === 'error') toast.classList.add('error');
    if (type === 'success') toast.classList.add('success');

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

    const data = await response.json();

    if (!response.ok) {
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
        nameCell.textContent = m.name;
        row.appendChild(nameCell);

        const statusCell = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = m.aktiv ? 'badge badge-success' : 'badge badge-warning';
        badge.textContent = m.aktiv ? 'Aktiv' : 'Inaktiv';
        statusCell.appendChild(badge);
        row.appendChild(statusCell);

        const aboCell = document.createElement('td');
        const abo = m.abonnenten || {};
        aboCell.textContent = `${abo.aktiv || 0} / ${abo.gesamt || 0}`;
        row.appendChild(aboCell);

        // TODO: Click-Handler für Details (Schritt 2)

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

// Initialisierung
document.addEventListener('DOMContentLoaded', () => {
    renderNav();
    loadMandanten();
});
