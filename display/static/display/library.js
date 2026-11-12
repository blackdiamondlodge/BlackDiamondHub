(() => {
    const lib = document.getElementById('dsp-lib');
    if (!lib) return;
    const grid = document.getElementById('dsp-lib-grid');
    const addTile = document.getElementById('dsp-add');
    const count = document.getElementById('dsp-lib-count');
    const seasons = JSON.parse(document.getElementById('dsp-seasons').textContent);
    const csrf = document.querySelector('#dsp-form [name=csrfmiddlewaretoken]').value;
    const tiles = new Map();
    const known = new Map();

    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text != null) e.textContent = text;
        return e;
    }

    function btn(cls, text) {
        const b = el('button', cls, text);
        b.type = 'button';
        return b;
    }

    async function post(url, data) {
        const body = data instanceof FormData ? data : new URLSearchParams(data);
        const r = await fetch(url, { method: 'POST', body, headers: { 'X-CSRFToken': csrf }, credentials: 'same-origin' });
        const json = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(json.error || 'Something went wrong.');
        return json;
    }

    const photoUrl = (id, tail = '') => `${lib.dataset.base}${id}/${tail}`;

    function closeOverlay(tile) { tile.querySelector('.over')?.remove(); }

    function editSeasons(tile, photo) {
        closeOverlay(tile);
        const picked = new Set(photo.seasons);
        const over = el('div', 'over seasons');
        const row = el('div', 'grid');
        seasons.forEach(([id, label]) => {
            const chip = btn('chip' + (picked.has(id) || !picked.size ? ' on' : ''), label);
            chip.addEventListener('click', () => {
                if (!picked.size) seasons.forEach(([s]) => picked.add(s));
                picked.has(id) ? picked.delete(id) : picked.add(id);
                chip.classList.toggle('on', picked.has(id));
            });
            row.append(chip);
        });
        const acts = el('div', 'row');
        const cancel = btn('', 'Cancel');
        const save = btn('ok', 'Save');
        cancel.addEventListener('click', () => closeOverlay(tile));
        save.addEventListener('click', async () => {
            if (!picked.size) return;
            try { render(await post(photoUrl(photo.id), { seasons: [...picked].join(',') })); }
            catch (e) { alert(e.message); }
        });
        acts.append(cancel, save);
        over.append(row, acts);
        tile.append(over);
    }

    function confirmDelete(tile, photo) {
        closeOverlay(tile);
        const over = el('div', 'over');
        over.append(el('b', '', 'Delete this photo?'));
        const row = el('div', 'row');
        const no = btn('', 'Keep');
        const yes = btn('del', 'Delete');
        no.addEventListener('click', () => closeOverlay(tile));
        yes.addEventListener('click', async () => {
            try {
                await post(photoUrl(photo.id, 'delete/'), {});
                tile.remove();
                tiles.delete(photo.id);
                known.delete(photo.id);
                updateCount();
            } catch (e) { alert(e.message); }
        });
        row.append(no, yes);
        over.append(row);
        tile.append(over);
    }

    function render(photo, fresh) {
        known.set(photo.id, photo);
        let tile = tiles.get(photo.id);
        if (!tile) {
            tile = el('div', 'dsp-ph');
            tiles.set(photo.id, tile);
            addTile.after(tile);
        }
        tile.replaceChildren();
        tile.classList.toggle('off', !photo.enabled);
        if (fresh) tile.classList.add('new');
        const img = el('img');
        img.src = photo.thumb;
        img.alt = photo.name || 'Photo';
        img.loading = 'lazy';
        const tog = el('span', 'hst-tog');
        const box = el('input');
        box.type = 'checkbox';
        box.setAttribute('role', 'switch');
        box.setAttribute('aria-label', 'Show in screensaver');
        box.checked = photo.enabled;
        box.addEventListener('change', async () => {
            try { render(await post(photoUrl(photo.id), { enabled: box.checked ? '1' : '0' })); }
            catch (e) { box.checked = !box.checked; alert(e.message); }
        });
        tog.append(box, el('span'));
        const tag = btn('tagbtn', photo.tag);
        tag.addEventListener('click', () => editSeasons(tile, photo));
        const trash = btn('trash');
        trash.setAttribute('aria-label', 'Delete photo');
        trash.innerHTML = '<i class="fas fa-trash" aria-hidden="true"></i>';
        trash.addEventListener('click', () => confirmDelete(tile, photo));
        tile.append(img, tog, tag, trash);
        if (!photo.enabled) tile.append(el('span', 'hid', 'Hidden'));
        updateCount();
        return tile;
    }

    function updateCount() {
        count.textContent = tiles.size ? `${tiles.size} photo${tiles.size === 1 ? '' : 's'}` : '';
        // The per-season counts under each "My photos" source choice.
        document.querySelectorAll('[data-photo-count]').forEach(n => {
            const season = n.dataset.photoCount;
            const k = [...known.values()].filter(p => p.enabled && (!p.seasons.length || p.seasons.includes(season))).length;
            n.textContent = `${k} photo${k === 1 ? '' : 's'} for ${n.dataset.label}`;
        });
    }

    function sync(photos, markNew) {
        let added = [];
        photos.slice().reverse().forEach(p => {
            const known = tiles.has(p.id);
            if (!known) added.push(p);
            if (!known || !markNew) render(p, markNew && !known);
        });
        updateCount();
        return added;
    }

    sync(JSON.parse(document.getElementById('dsp-photos').textContent), false);

    // Upload modal: QR for a phone, or pick files here.
    const dlg = document.getElementById('dsp-qr');
    const code = document.getElementById('dsp-qr-code');
    const time = document.getElementById('dsp-qr-time');
    const status = document.getElementById('dsp-qr-status');
    const fresh = document.getElementById('dsp-qr-new');
    const local = document.getElementById('dsp-local');
    let link = null, poll = null, tick = null, left = 0;

    function setStatus(text, ok) {
        status.className = 'dsp-qr-status' + (ok ? ' ok' : '');
        status.replaceChildren(el('span', 'dot'), document.createTextNode(text));
    }

    function showTime() {
        if (left <= 0) {
            time.textContent = 'This code has expired.';
            code.classList.add('dead');
            stop();
            const again = btn('hst-btn ghost', 'New code');
            again.addEventListener('click', open);
            time.append(' ', again);
            return;
        }
        const m = Math.floor(left / 60), s = String(left % 60).padStart(2, '0');
        time.textContent = `Code expires in ${m}:${s} · one phone`;
    }

    function stop() {
        clearInterval(poll);
        clearInterval(tick);
        poll = tick = null;
    }

    function arrived(photos) {
        photos.forEach(p => {
            const img = el('img');
            img.src = p.thumb;
            img.alt = '';
            fresh.prepend(img);
        });
    }

    async function check() {
        if (!link) return;
        try {
            const r = await fetch(`${lib.dataset.list}?link=${encodeURIComponent(link)}`, { credentials: 'same-origin' });
            if (!r.ok) return;
            const data = await r.json();
            arrived(sync(data.photos, true));
            if (data.link) {
                left = data.link.seconds;
                const n = data.link.arrived;
                if (n) setStatus(`${n} photo${n === 1 ? '' : 's'} added`, true);
                else if (data.link.claimed) setStatus('Phone connected. Waiting for photos…');
            }
        } catch (e) { /* next poll */ }
    }

    async function open() {
        stop();
        code.replaceChildren();
        code.classList.remove('dead');
        fresh.replaceChildren();
        time.textContent = '';
        setStatus('Waiting for your phone…');
        if (!dlg.open) dlg.showModal();
        try {
            const data = await post(lib.dataset.link, {});
            link = data.key;
            left = data.seconds;
            code.innerHTML = data.qr;
            showTime();
            tick = setInterval(() => { left -= 1; showTime(); }, 1000);
            poll = setInterval(check, 3000);
        } catch (e) {
            setStatus(e.message);
        }
    }

    addTile.addEventListener('click', open);
    dlg.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => dlg.close()));
    dlg.addEventListener('close', () => {
        stop();
        link = null;
        grid.querySelectorAll('.dsp-ph.new').forEach(t => setTimeout(() => t.classList.remove('new'), 4000));
    });

    local.addEventListener('change', async () => {
        const files = [...local.files];
        local.value = '';
        let done = 0;
        for (const f of files) {
            setStatus(`Uploading ${done + 1} of ${files.length}…`);
            const fd = new FormData();
            fd.append('photo', f);
            try {
                const data = await post(lib.dataset.add, fd);
                data.photos.forEach(p => render(p, true));
                arrived(data.photos);
                done += 1;
            } catch (e) {
                setStatus(`${f.name}: ${e.message}`);
                return;
            }
        }
        updateCount();
        setStatus(`${done} photo${done === 1 ? '' : 's'} added`, true);
    });
})();
