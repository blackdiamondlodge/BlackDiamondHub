/* Screensaver and burn-in protection for the lodge display. */
(function () {
    'use strict';
    const cfgEl = document.getElementById('bdh-saver-cfg');
    if (!cfgEl) return;
    const cfg = JSON.parse(cfgEl.textContent);
    const params = new URLSearchParams(location.search);

    /* ---------- stock scenes ---------- */
    const PALETTES = {
        winter: {sky: ['#1b2b4d', '#5a6f9a', '#e9a77a', '#f5cf9a'], sun: '#ffe3b0', m1: ['#f4f6fa', '#aab4cc', '#5d6a8a'],
            m2: ['#e8eef7', '#7d8aa8'], ground: '#eef2f8', cap: .62, cap2: .55, tree: '#1d2b3a', treeSnow: true, flakes: true},
        spring: {sky: ['#3d6fae', '#7fb0e0', '#cfe4f5', '#eaf4fb'], sun: '#fff6d8', m1: ['#f6f8fb', '#9fb2c8', '#5f7690'],
            m2: ['#dfe9f2', '#7f97a8'], ground: '#9fbf7a', cap: .42, cap2: .22, patches: true, tree: '#24433a'},
        summer: {sky: ['#2b6cc4', '#5fa2e6', '#a9d3f4', '#dff0fb'], sun: '#fff3c0', sunHigh: true, m1: ['#c7d3c9', '#7f9a86', '#4d6a58'],
            m2: ['#7fa36e', '#4f7552'], ground: '#7aa95a', cap: .12, cap2: 0, flowers: true, tree: '#1f3d2c'},
        fall: {sky: ['#33406b', '#8a7aa0', '#e8a06a', '#f6c98a'], sun: '#ffd28a', m1: ['#e9e6ea', '#9a8f9e', '#5c5470'],
            m2: ['#b58a4e', '#7a5a36'], ground: '#a8874e', cap: .22, cap2: .05, tree: '#2a3a2a', larch: true},
    };
    const R1 = [[0, 760], [240, 560], [380, 640], [620, 380], [820, 560], [980, 470], [1200, 640], [1420, 500], [1640, 620], [1860, 520], [2000, 590]];
    const R2 = [[0, 900], [300, 720], [520, 820], [760, 640], [1000, 830], [1260, 700], [1540, 860], [1800, 740], [2000, 820]];
    const TREES = [[1650, 990, 130, 34], [1710, 1000, 100, 26], [1760, 1010, 80, 22], [1880, 990, 120, 30], [1560, 1005, 90, 24]];

    const ridge = (pts, fill, op) =>
        `<path d="M${pts.map(p => p.join(' ')).join(' L')} L2000 1160 L0 1160Z" fill="${fill}" opacity="${op}"/>`;

    // Snow cap: walks down both flanks of each peak by fraction f, with a jagged lower edge.
    function caps(pts, f, tall) {
        if (f <= 0) return '';
        let d = '';
        for (let i = 1; i < pts.length - 1; i++) {
            const [px, py] = pts[i], [ax, ay] = pts[i - 1], [bx, by] = pts[i + 1];
            if (py > ay || py > by) continue;
            const ff = f * (tall ? 1 - (py - 380) / 400 : 1);
            if (ff <= 0.02) continue;
            const L = [px + (ax - px) * ff, py + (ay - py) * ff], R = [px + (bx - px) * ff, py + (by - py) * ff];
            const drop = Math.abs(R[1] - py);
            d += `M${px} ${py} L${R[0]} ${R[1]}`;
            for (let j = 1; j < 6; j++) {
                const t = j / 6;
                d += ` L${R[0] + (L[0] - R[0]) * t} ${R[1] + (L[1] - R[1]) * t + (j % 2 ? -drop * .28 : drop * .08)}`;
            }
            d += ` L${L[0]} ${L[1]}Z`;
        }
        return `<path d="${d}" fill="#fbfcfe" opacity=".93"/>`;
    }

    function scene(season) {
        const c = PALETTES[season] || PALETTES.winter;
        let h = `<svg viewBox="0 0 2000 1160" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg"><defs>`
            + `<linearGradient id="bdh-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c.sky[0]}"/>`
            + `<stop offset=".45" stop-color="${c.sky[1]}"/><stop offset=".72" stop-color="${c.sky[2]}"/><stop offset="1" stop-color="${c.sky[3]}"/></linearGradient>`
            + `<linearGradient id="bdh-m1" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c.m1[0]}"/>`
            + `<stop offset=".5" stop-color="${c.m1[1]}"/><stop offset="1" stop-color="${c.m1[2]}"/></linearGradient>`
            + `<linearGradient id="bdh-m2" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${c.m2[0]}"/>`
            + `<stop offset="1" stop-color="${c.m2[1]}"/></linearGradient></defs>`
            + `<rect width="2000" height="1160" fill="url(#bdh-sky)"/>`
            + `<circle cx="1480" cy="${c.sunHigh ? 300 : 560}" r="70" fill="${c.sun}" opacity=".75"/>`;
        h += ridge(R1, 'url(#bdh-m1)', .92) + caps(R1, c.cap, true) + ridge(R2, 'url(#bdh-m2)', 1) + caps(R2, c.cap2, false);
        h += `<path d="M0 1000 Q500 900 1000 960 T2000 940 L2000 1160 L0 1160Z" fill="${c.ground}"/>`;
        if (c.patches) {
            h += '<g fill="#f2f6fa" opacity=".85"><ellipse cx="420" cy="1010" rx="160" ry="16"/>'
                + '<ellipse cx="1180" cy="985" rx="120" ry="12"/><ellipse cx="1500" cy="1030" rx="90" ry="10"/></g>';
        }
        if (c.flowers) {
            const colors = ['#f4d35e', '#e86a92', '#f7f7f7', '#b28dff'];
            for (let i = 0; i < 90; i++) h += `<circle cx="${(i * 137) % 2000}" cy="${975 + (i * 53) % 170}" r="4" fill="${colors[i % 4]}"/>`;
        }
        TREES.forEach(([x, y, ht, w], i) => {
            h += `<path d="M${x} ${y} l${w} ${-ht} l${w} ${ht}z" fill="${c.larch && i % 2 ? '#d89a2e' : c.tree}"/>`;
            if (c.treeSnow) {
                h += `<path d="M${x + w * .55} ${y - ht * .55} l${w * .45} ${-ht * .45} l${w * .45} ${ht * .45} `
                    + `q-${w * .45} -10 -${w * .9} 0z" fill="#f4f7fb" opacity=".9"/>`;
            }
        });
        if (c.flakes) {
            for (let i = 0; i < 140; i++) {
                h += `<circle cx="${(i * 263) % 2000}" cy="${(i * 149) % 1100}" r="${1.5 + i % 3}" fill="#fff" opacity="${.35 + (i % 4) * .12}"/>`;
            }
        }
        return h + '</svg>';
    }

    /* ---------- burn-in: shift every screen by a few pixels ---------- */
    const SHIFT = 6;
    function shift() {
        // Up/left only: a positive offset would push the page past the viewport and make it scroll.
        const r = () => -Math.round(Math.random() * SHIFT) + 'px';
        document.documentElement.style.setProperty('--bx', r());
        document.documentElement.style.setProperty('--by', r());
    }
    if (cfg.burn_in) {
        shift();
        setInterval(shift, 3 * 60 * 1000);
    }

    /* ---------- the overlay ---------- */
    let root = null, data = null, season = null, timers = [];
    let night = cfg.night || null;
    const $ = sel => root.querySelector(sel);
    const esc = s => String(s).replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[ch]);
    const timeText = iso => new Date(iso).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'});

    function build() {
        root = document.createElement('div');
        root.className = 'bdh-saver';
        root.innerHTML = '<div class="layer stock"></div><div class="layer photos"></div><div class="layer cam"></div><div class="shade"></div>'
            + '<div class="info"><div class="clock"></div><div class="date"></div><div class="row"></div></div>'
            + '<div class="cam-name"></div><div class="caption"></div><div class="season"></div><div class="hint">Tap anywhere</div>';
        // Swallow the tap that wakes the display so it doesn't land on what's underneath.
        ['pointerdown', 'touchstart', 'mousedown'].forEach(type => root.addEventListener(type, e => {
            e.preventDefault();
            e.stopPropagation();
        }, {passive: false}));
        root.addEventListener('pointerup', e => {
            e.preventDefault();
            e.stopPropagation();
            hide();
        });
        root.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); });
        document.body.appendChild(root);
    }

    // After the saver closes, eat the click that the same tap may still produce.
    function swallowNextClick() {
        const eat = e => { e.preventDefault(); e.stopPropagation(); };
        window.addEventListener('click', eat, {capture: true, once: true});
        setTimeout(() => window.removeEventListener('click', eat, {capture: true}), 500);
    }

    function tick() {
        const now = new Date();
        const [hm, ampm] = now.toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'}).split(' ');
        $('.clock').innerHTML = `${esc(hm)}<small>${esc(ampm || '')}</small>`;
        $('.date').textContent = now.toLocaleDateString('en-US', {weekday: 'long', month: 'long', day: 'numeric'});
    }

    function drift() {
        const r = n => Math.round(Math.random() * n * 2 - n) + 'px';
        $('.info').style.translate = `${r(40)} ${r(24)}`;
        $('.season').style.translate = `${r(20)} ${r(12)}`;
    }

    // Night mode, in lodge time (the display's own clock may be on another zone).
    function isNight() {
        if (params.get('saver_night') === '1') return true;
        if (!night || night.from === night.until) return false;
        const now = new Date();
        const m = ((now.getUTCHours() * 60 + now.getUTCMinutes() + (night.offset || 0)) % 1440 + 1440) % 1440;
        return night.from < night.until ? m >= night.from && m < night.until : m >= night.from || m < night.until;
    }
    function applyNight() { if (root) root.classList.toggle('night', isNight()); }

    let showing = 'stock';
    let order = [], orderKey = '', pos = 0;
    // Photos that failed to load are skipped for a while, so one bad file can't leave the screen black.
    const broken = new Map();
    const BROKEN_MS = 10 * 60 * 1000;
    const isBroken = url => broken.has(url) && Date.now() - broken.get(url) < BROKEN_MS;
    function photoList() { return ((data && data.photos) || []).filter(p => !isBroken(p.url)); }
    const byUrl = url => photoList().find(p => p.url === url);
    const rand = (lo, hi) => lo + Math.random() * (hi - lo);

    function shuffle(urls, avoidFirst) {
        const a = urls.slice();
        for (let i = a.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [a[i], a[j]] = [a[j], a[i]];
        }
        // Don't show the same photo twice in a row across a reshuffle.
        if (a.length > 1 && a[0] === avoidFirst) [a[0], a[1]] = [a[1], a[0]];
        return a;
    }

    // Reshuffles only when the set of photos changes, so a refresh doesn't restart the cycle.
    function syncOrder() {
        const urls = photoList().map(p => p.url);
        const key = urls.slice().sort().join('\n');
        if (key !== orderKey) {
            orderKey = key;
            order = shuffle(urls);
            pos = 0;
        }
    }

    function currentFrame() { return $('.layer.photos').lastElementChild; }

    function showCaption() {
        const frame = currentFrame();
        const photo = frame && byUrl(frame.dataset.src);
        const text = (photo && photo.caption) || '';
        $('.caption').textContent = text;
        $('.caption').classList.toggle('on', showing === 'photos' && !!text);
    }

    // Slow random pan and zoom; it lasts as long as the photo stays up.
    function kenBurns(frame) {
        const every = Math.max(60, (data && data.rotate_seconds) || 180);
        const zoomIn = Math.random() < 0.5;
        const [s0, s1] = zoomIn ? [rand(1.04, 1.07), rand(1.12, 1.16)] : [rand(1.12, 1.16), rand(1.04, 1.07)];
        // Small enough that the zoom always hides the frame's edges.
        const p = () => rand(-1.5, 1.5).toFixed(2) + '%';
        frame.style.setProperty('--s0', s0.toFixed(3));
        frame.style.setProperty('--s1', s1.toFixed(3));
        [['--x0', p()], ['--y0', p()], ['--x1', p()], ['--y1', p()]].forEach(([k, v]) => frame.style.setProperty(k, v));
        frame.style.animationDuration = (every + 4) + 's';
    }

    function restartKenBurns(frame) {
        if (!frame) return;
        kenBurns(frame);
        frame.style.animationName = 'none';
        void frame.offsetWidth;
        frame.style.animationName = '';
    }

    // Brings in the next library photo, crossfading over the current one if it's on screen.
    function nextPhoto(fade) {
        const list = photoList();
        const layer = $('.layer.photos');
        if (!list.length) { layer.replaceChildren(); showCaption(); return; }
        syncOrder();
        const current = currentFrame();
        if (pos >= order.length) {
            order = shuffle(order, current && current.dataset.src);
            pos = 0;
        }
        let url = order[pos++];
        if (current && current.dataset.src === url) {
            if (order.length < 2) return;
            url = order[pos++ % order.length];
        }
        const frame = document.createElement('div');
        frame.className = 'frame';
        frame.dataset.src = url;
        const bg = new Image(), fg = new Image();
        bg.alt = fg.alt = '';
        bg.className = 'bg';
        fg.className = 'fg';
        fg.onload = () => {
            // Close to the screen's shape: fill it. Otherwise (portraits) show it whole over a blurred copy.
            const ratio = (fg.naturalWidth / fg.naturalHeight) / (window.innerWidth / window.innerHeight);
            frame.classList.toggle('fill', ratio > 0.8 && ratio < 1.25);
            kenBurns(frame);
            if (!fade) {
                frame.classList.add('in');
                layer.replaceChildren(frame);
            } else {
                layer.append(frame);
                requestAnimationFrame(() => requestAnimationFrame(() => frame.classList.add('in')));
                setTimeout(() => { while (layer.firstElementChild && layer.firstElementChild !== frame) layer.firstElementChild.remove(); }, 3200);
            }
            showCaption();
        };
        fg.onerror = () => {
            broken.set(url, Date.now());
            // Try another photo, or switch to another source if none are left.
            if (data) render(data);
        };
        frame.append(bg, fg);
        bg.src = url;
        fg.src = url;
    }

    function showLayer(name) {
        const leaving = showing === 'photos' && name !== 'photos';
        const entering = showing !== 'photos' && name === 'photos';
        showing = name;
        $('.layer.stock').classList.toggle('on', name === 'stock');
        $('.layer.photos').classList.toggle('on', name === 'photos');
        if (leaving) setTimeout(() => nextPhoto(false), 3500);
        if (entering) restartKenBurns(currentFrame());
        $('.layer.cam').classList.toggle('on', name === 'cam');
        $('.cam-name').classList.toggle('on', name === 'cam');
        showCaption();
    }

    let camTimer = null, camEvery = 0;

    // Live images change behind the same URL: refetch with a cache-buster, swap in once loaded.
    function loadCam(url, fresh) {
        const img = new Image();
        img.alt = '';
        img.dataset.src = url;
        img.onload = () => {
            if (data && data.cam && data.cam.url === url) $('.layer.cam').replaceChildren(img);
        };
        img.src = fresh ? url + (url.includes('?') ? '&' : '?') + 't=' + Date.now() : url;
    }

    function render(d) {
        data = d;
        if ('night' in d) night = d.night;
        applyNight();
        if (d.season !== season) {
            season = d.season;
            $('.layer.stock').innerHTML = scene(season);
        }
        $('.season').textContent = d.label || season;
        $('.row').innerHTML = (d.stats || []).map(s =>
            `<div><b>${esc(s.time ? timeText(s.time) : s.value)}</b>${esc(s.label)}</div>`).join('');
        const camLayer = $('.layer.cam');
        if (d.cam && d.cam.url) {
            $('.cam-name').textContent = d.cam.name || '';
            const current = camLayer.querySelector('img');
            if (!current || current.dataset.src !== d.cam.url) loadCam(d.cam.url, false);
            const every = Math.max(10, d.cam.refresh_seconds || 0) * 1000;
            if (!d.cam.refresh_seconds) { clearInterval(camTimer); camTimer = null; camEvery = 0; }
            else if (every !== camEvery || camTimer === null) {
                clearInterval(camTimer);
                camEvery = every;
                camTimer = setInterval(() => data && data.cam && loadCam(data.cam.url, true), every);
            }
        } else {
            clearInterval(camTimer); camTimer = null; camEvery = 0;
            camLayer.replaceChildren();
        }
        const photosLayer = $('.layer.photos');
        const loaded = currentFrame();
        syncOrder();
        if (!photoList().length) photosLayer.replaceChildren();
        else if (!loaded || !byUrl(loaded.dataset.src)) nextPhoto(false);
        showCaption();
        const sources = d.sources || ['stock'];
        const empty = name => (name === 'cam' && !camLayer.firstChild) || (name === 'photos' && !photoList().length);
        if (!sources.includes(showing) || empty(showing)) showLayer(sources.find(s => !empty(s)) || 'stock');
    }

    function load() {
        // The settings page's Preview passes its unsaved values (the API only honours them for staff).
        const q = new URLSearchParams();
        [['saver_season', 'season'], ['saver_source', 'source'], ['saver_cam', 'cam'],
         ['saver_rotate', 'rotate'], ['saver_caption', 'caption']].forEach(([from, to]) => {
            if (params.has(from)) q.set(to, params.get(from));
        });
        const url = cfg.api + (q.toString() ? '?' + q : '');
        return fetch(url, {cache: 'no-store'}).then(r => r.ok ? r.json() : Promise.reject(r.status)).then(render)
            .catch(() => { if (!data) render({season: 'winter', label: 'Winter', sources: ['stock'], stats: []}); });
    }

    function rotate() {
        const sources = (data && data.sources) || ['stock'];
        if (sources.length < 2) {
            if (showing === 'photos' && photoList().length > 1) nextPhoto(true);
            return;
        }
        const next = sources[(sources.indexOf(showing) + 1) % sources.length];
        if (next === 'cam' && !$('.layer.cam').firstChild) return;
        if (next === 'photos' && !$('.layer.photos').firstChild) return;
        showLayer(next);
    }

    function show() {
        if (root && root.classList.contains('on')) return;
        if (!root) build();
        root.style.display = '';
        root.style.pointerEvents = '';
        applyNight();
        tick();
        showLayer(showing);
        load().then(() => {
            if (!root.classList.contains('on')) return;
            const every = Math.max(60, (data && data.rotate_seconds) || 180) * 1000;
            timers.push(setInterval(rotate, every));
        });
        timers.push(setInterval(tick, 10 * 1000), setInterval(drift, 60 * 1000), setInterval(load, 5 * 60 * 1000),
            setInterval(applyNight, 30 * 1000));
        requestAnimationFrame(() => root.classList.add('on'));
    }

    function hide(swallow = true) {
        if (!root) return;
        timers.forEach(clearInterval);
        timers = [];
        root.classList.remove('on');
        root.style.pointerEvents = 'none';
        if (swallow) swallowNextClick();
        setTimeout(() => { if (!root.classList.contains('on')) root.style.display = 'none'; }, 1300);
        arm();
    }

    /* ---------- idle detection ---------- */
    const idleMs = Math.max(1, cfg.idle_minutes || 10) * 60 * 1000;
    let idleTimer = null;
    let paused = false;
    // A page that must stay on screen (e.g. live cameras) opts out with
    // <meta name="bdh-screensaver" content="off">; alerts' resume() can't undo it.
    const held = !!document.querySelector('meta[name="bdh-screensaver"][content="off"]');
    const isDisplay = () => window.innerWidth >= 1280;
    function arm() {
        clearTimeout(idleTimer);
        if (!paused && !held && isDisplay()) idleTimer = setTimeout(show, idleMs);
    }
    ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart'].forEach(type =>
        document.addEventListener(type, () => { if (!root || !root.classList.contains('on')) arm(); },
            {passive: true, capture: true}));
    document.addEventListener('keydown', e => { if (e.key === 'Escape') hide(); });
    window.addEventListener('resize', arm);

    /* Something else (an alert) owns the screen: keep the saver away until resume(). */
    function pause() {
        paused = true;
        clearTimeout(idleTimer);
    }
    function resume() {
        paused = false;
        arm();
    }
    const wake = () => hide(false);

    window.BDHSaver = {show, hide, wake, pause, resume, scene};
    if (params.get('saver') === '1') show(); else arm();
})();
