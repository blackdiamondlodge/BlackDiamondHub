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
    const SHIFT = 3;
    function shift() {
        const r = () => Math.round(Math.random() * SHIFT * 2 - SHIFT) + 'px';
        document.documentElement.style.setProperty('--bx', r());
        document.documentElement.style.setProperty('--by', r());
    }
    if (cfg.burn_in) {
        shift();
        setInterval(shift, 3 * 60 * 1000);
    }

    /* ---------- the overlay ---------- */
    let root = null, data = null, season = null, timers = [];
    const $ = sel => root.querySelector(sel);
    const esc = s => String(s).replace(/[&<>"']/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[ch]);
    const timeText = iso => new Date(iso).toLocaleTimeString('en-US', {hour: 'numeric', minute: '2-digit'});

    function build() {
        root = document.createElement('div');
        root.className = 'bdh-saver';
        root.innerHTML = '<div class="layer stock"></div><div class="layer cam"></div><div class="shade"></div>'
            + '<div class="info"><div class="clock"></div><div class="date"></div><div class="row"></div></div>'
            + '<div class="cam-name"></div><div class="season"></div><div class="hint">Tap anywhere</div>';
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

    let showing = 'stock';
    function showLayer(name) {
        showing = name;
        $('.layer.stock').classList.toggle('on', name === 'stock');
        $('.layer.cam').classList.toggle('on', name === 'cam');
        $('.cam-name').classList.toggle('on', name === 'cam');
    }

    function render(d) {
        data = d;
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
            if (!current || current.dataset.src !== d.cam.url) {
                const img = new Image();
                img.alt = '';
                img.dataset.src = d.cam.url;
                img.onload = () => camLayer.replaceChildren(img);
                img.src = d.cam.url;
            }
        } else {
            camLayer.replaceChildren();
        }
        const sources = d.sources || ['stock'];
        if (!sources.includes(showing) || (showing === 'cam' && !camLayer.firstChild)) showLayer(sources[0]);
    }

    function load() {
        const forced = params.get('saver_season');
        const url = cfg.api + (forced ? `?season=${encodeURIComponent(forced)}` : '');
        return fetch(url, {cache: 'no-store'}).then(r => r.ok ? r.json() : Promise.reject(r.status)).then(render)
            .catch(() => { if (!data) render({season: 'winter', label: 'Winter', sources: ['stock'], stats: []}); });
    }

    function rotate() {
        const sources = (data && data.sources) || ['stock'];
        if (sources.length < 2) return;
        const next = sources[(sources.indexOf(showing) + 1) % sources.length];
        if (next === 'cam' && !$('.layer.cam').firstChild) return;
        showLayer(next);
    }

    function show() {
        if (root && root.classList.contains('on')) return;
        if (!root) build();
        root.style.display = '';
        root.style.pointerEvents = '';
        tick();
        showLayer(showing);
        load().then(() => {
            if (!root.classList.contains('on')) return;
            const every = Math.max(60, (data && data.rotate_seconds) || 180) * 1000;
            timers.push(setInterval(rotate, every));
        });
        timers.push(setInterval(tick, 10 * 1000), setInterval(drift, 60 * 1000), setInterval(load, 5 * 60 * 1000));
        requestAnimationFrame(() => root.classList.add('on'));
    }

    function hide() {
        if (!root) return;
        timers.forEach(clearInterval);
        timers = [];
        root.classList.remove('on');
        root.style.pointerEvents = 'none';
        swallowNextClick();
        setTimeout(() => { if (!root.classList.contains('on')) root.style.display = 'none'; }, 1300);
        arm();
    }

    /* ---------- idle detection ---------- */
    const idleMs = Math.max(1, cfg.idle_minutes || 10) * 60 * 1000;
    let idleTimer = null;
    const isDisplay = () => window.innerWidth >= 1280;
    function arm() {
        clearTimeout(idleTimer);
        if (isDisplay()) idleTimer = setTimeout(show, idleMs);
    }
    ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart'].forEach(type =>
        document.addEventListener(type, () => { if (!root || !root.classList.contains('on')) arm(); },
            {passive: true, capture: true}));
    document.addEventListener('keydown', e => { if (e.key === 'Escape') hide(); });
    window.addEventListener('resize', arm);

    window.BDHSaver = {show, hide, scene};
    if (params.get('saver') === '1') show(); else arm();
})();
