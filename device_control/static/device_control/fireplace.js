/* Fireplace tab: hosts the napoleon-fireplace-card Lovelace card from the
   hass-napoleon Home Assistant integration.

     GET  api/fireplace/states/  -> { entities, devices, config, states }
     POST api/fireplace/action/  body { domain, service, data }
     GET  api/fireplace/card.js  -> the card JS, proxied from HA

   The card expects a Home Assistant ``hass`` object; this file builds a
   minimal one (states + registries + callService), defines a tiny <ha-icon>
   for the MDI icons the card uses, and keeps the pill selector so one
   fireplace is shown at a time. */
(function () {
    const ROOT = document.getElementById('panel-fireplace');
    if (!ROOT) return;  // fireplace tab not present

    const STATES_URL = ROOT.dataset.statesUrl;
    const ACTION_URL = ROOT.dataset.actionUrl;
    const CARD_URL = ROOT.dataset.cardUrl;
    const CSRF = ROOT.dataset.csrf;
    const SEL = document.getElementById('fpSelect');
    const HOST = document.getElementById('fpCard');
    const MSG = document.getElementById('fpMsg');
    const STORE_KEY = 'fpSelectedDevice';
    const POLL_MS = 5000;

    const MDI = {"mdi:fireplace":"M22,22H2V20H22V22M22,6H2V3H22V6M20,7V19H17V11C17,11 14.5,10 12,10C9.5,10 7,11 7,11V19H4V7H20M14.5,14.67H14.47L14.81,15.22L14.87,15.34C15.29,16.35 15,17.5 14.21,18.24C13.5,18.9 12.5,19.07 11.58,18.95C10.71,18.84 9.9,18.29 9.45,17.53C9.3,17.3 9.19,17.03 9.13,16.77L9,16.11C8.96,15.15 9.34,14.14 10.06,13.54C9.73,14.26 9.81,15.16 10.3,15.79L10.36,15.87C10.44,15.94 10.55,15.97 10.64,15.92C10.73,15.89 10.8,15.8 10.8,15.7L10.76,15.56C10.23,14.17 10.68,12.55 11.79,11.63C12.1,11.38 12.5,11.15 12.87,11.05C12.46,11.87 12.61,12.93 13.25,13.57L14.14,14.3L14.5,14.67M13.11,17.44V17.44C13.37,17.2 13.53,16.8 13.5,16.44V16.25C13.38,15.65 12.85,15.46 12.5,15L12.26,14.55C12.13,14.85 12.12,15.13 12.17,15.46C12.23,15.8 12.37,16.09 12.29,16.44C12.2,16.83 11.9,17.22 11.37,17.35C11.67,17.64 12.15,17.87 12.64,17.71L13.11,17.44Z","mdi:fireplace-off":"M22,22H2V20H22V22M22,6H2V3H22V6M20,7V19H17V11C17,11 14.5,10 12,10C9.5,10 7,11 7,11V19H4V7H20Z","mdi:power":"M16.56,5.44L15.11,6.89C16.84,7.94 18,9.83 18,12A6,6 0 0,1 12,18A6,6 0 0,1 6,12C6,9.83 7.16,7.94 8.88,6.88L7.44,5.44C5.36,6.88 4,9.28 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12C20,9.28 18.64,6.88 16.56,5.44M13,3H11V13H13","mdi:thermometer":"M15 13V5A3 3 0 0 0 9 5V13A5 5 0 1 0 15 13M12 4A1 1 0 0 1 13 5V8H11V5A1 1 0 0 1 12 4Z","mdi:lightbulb-on-outline":"M20,11H23V13H20V11M1,11H4V13H1V11M13,1V4H11V1H13M4.92,3.5L7.05,5.64L5.63,7.05L3.5,4.93L4.92,3.5M16.95,5.63L19.07,3.5L20.5,4.93L18.37,7.05L16.95,5.63M12,6A6,6 0 0,1 18,12C18,14.22 16.79,16.16 15,17.2V19A1,1 0 0,1 14,20H10A1,1 0 0,1 9,19V17.2C7.21,16.16 6,14.22 6,12A6,6 0 0,1 12,6M14,21V22A1,1 0 0,1 13,23H11A1,1 0 0,1 10,22V21H14M11,18H13V15.87C14.73,15.43 16,13.86 16,12A4,4 0 0,0 12,8A4,4 0 0,0 8,12C8,13.86 9.27,15.43 11,15.87V18Z","mdi:fire":"M17.66 11.2C17.43 10.9 17.15 10.64 16.89 10.38C16.22 9.78 15.46 9.35 14.82 8.72C13.33 7.26 13 4.85 13.95 3C13 3.23 12.17 3.75 11.46 4.32C8.87 6.4 7.85 10.07 9.07 13.22C9.11 13.32 9.15 13.42 9.15 13.55C9.15 13.77 9 13.97 8.8 14.05C8.57 14.15 8.33 14.09 8.14 13.93C8.08 13.88 8.04 13.83 8 13.76C6.87 12.33 6.69 10.28 7.45 8.64C5.78 10 4.87 12.3 5 14.47C5.06 14.97 5.12 15.47 5.29 15.97C5.43 16.57 5.7 17.17 6 17.7C7.08 19.43 8.95 20.67 10.96 20.92C13.1 21.19 15.39 20.8 17.03 19.32C18.86 17.66 19.5 15 18.56 12.72L18.43 12.46C18.22 12 17.66 11.2 17.66 11.2M14.5 17.5C14.22 17.74 13.76 18 13.4 18.1C12.28 18.5 11.16 17.94 10.5 17.28C11.69 17 12.4 16.12 12.61 15.23C12.78 14.43 12.46 13.77 12.33 13C12.21 12.26 12.23 11.63 12.5 10.94C12.69 11.32 12.89 11.7 13.13 12C13.9 13 15.11 13.44 15.37 14.8C15.41 14.94 15.43 15.08 15.43 15.23C15.46 16.05 15.1 16.95 14.5 17.5H14.5Z","mdi:dots-hexagon":"M16 12C16 10.9 16.9 10 18 10S20 10.9 20 12 19.1 14 18 14 16 13.1 16 12M10 12C10 10.9 10.9 10 12 10S14 10.9 14 12 13.1 14 12 14 10 13.1 10 12M4 12C4 10.9 4.9 10 6 10S8 10.9 8 12 7.1 14 6 14 4 13.1 4 12M13 18C13 16.9 13.9 16 15 16S17 16.9 17 18 16.1 20 15 20 13 19.1 13 18M7 18C7 16.9 7.9 16 9 16S11 16.9 11 18 10.1 20 9 20 7 19.1 7 18M13 6C13 4.9 13.9 4 15 4S17 4.9 17 6 16.1 8 15 8 13 7.1 13 6M7 6C7 4.9 7.9 4 9 4S11 4.9 11 6 10.1 8 9 8 7 7.1 7 6","mdi:party-popper":"M14.53 1.45L13.45 2.53L15.05 4.13C15.27 4.38 15.38 4.67 15.38 5S15.27 5.64 15.05 5.86L11.5 9.47L12.5 10.55L16.13 6.94C16.66 6.35 16.92 5.7 16.92 5C16.92 4.3 16.66 3.64 16.13 3.05L14.53 1.45M10.55 3.47L9.47 4.55L10.08 5.11C10.3 5.33 10.41 5.63 10.41 6S10.3 6.67 10.08 6.89L9.47 7.45L10.55 8.53L11.11 7.92C11.64 7.33 11.91 6.69 11.91 6C11.91 5.28 11.64 4.63 11.11 4.03L10.55 3.47M21 5.06C20.31 5.06 19.67 5.33 19.08 5.86L13.45 11.5L14.53 12.5L20.11 6.94C20.36 6.69 20.66 6.56 21 6.56S21.64 6.69 21.89 6.94L22.5 7.55L23.53 6.47L22.97 5.86C22.38 5.33 21.72 5.06 21 5.06M7 8L2 22L16 17L7 8M19 11.06C18.3 11.06 17.66 11.33 17.06 11.86L15.47 13.45L16.55 14.53L18.14 12.94C18.39 12.69 18.67 12.56 19 12.56C19.33 12.56 19.63 12.69 19.88 12.94L21.5 14.53L22.55 13.5L20.95 11.86C20.36 11.33 19.7 11.06 19 11.06Z","mdi:campfire":"M15.9,18.5L21.9,20.1L21.5,22L12.1,19.5L2.7,22L2.2,20.1L8.2,18.5L2.1,16.9L2.6,15L12,17.5L21.4,15L21.9,16.9L15.9,18.5M16.07,7.92C15.91,7.7 15.71,7.5 15.5,7.33C15.05,6.9 14.5,6.59 14.06,6.13C13,5.08 12.79,3.34 13.44,2C12.79,2.17 12.18,2.54 11.67,2.95C9.84,4.46 9.11,7.1 10,9.38C10,9.45 10.04,9.53 10.04,9.62C10.04,9.78 9.93,9.92 9.79,10C9.63,10.05 9.46,10 9.33,9.9C9.28,9.86 9.25,9.82 9.22,9.77C8.42,8.74 8.29,7.26 8.84,6.07C7.65,7.06 7,8.72 7.11,10.29C7.13,10.65 7.18,11 7.3,11.36C7.41,11.8 7.59,12.23 7.82,12.61C8.57,13.86 9.9,14.76 11.32,14.94C12.84,15.14 14.46,14.85 15.63,13.79C16.93,12.59 17.4,10.67 16.71,9L16.61,8.83C16.47,8.5 16.28,8.2 16.04,7.93L16.07,7.92M13.83,12.47C13.63,12.65 13.31,12.83 13.05,12.91C12.26,13.19 11.46,12.79 11,12.31C11.84,12.11 12.34,11.47 12.5,10.83C12.61,10.25 12.39,9.78 12.29,9.22C12.21,8.69 12.22,8.23 12.42,7.73C12.55,8 12.69,8.28 12.86,8.5C13.41,9.22 14.27,9.54 14.45,10.5C14.47,10.63 14.5,10.72 14.5,10.83C14.5,11.43 14.26,12.07 13.82,12.47","mdi:weather-sunny":"M12,7A5,5 0 0,1 17,12A5,5 0 0,1 12,17A5,5 0 0,1 7,12A5,5 0 0,1 12,7M12,9A3,3 0 0,0 9,12A3,3 0 0,0 12,15A3,3 0 0,0 15,12A3,3 0 0,0 12,9M12,2L14.39,5.42C13.65,5.15 12.84,5 12,5C11.16,5 10.35,5.15 9.61,5.42L12,2M3.34,7L7.5,6.65C6.9,7.16 6.36,7.78 5.94,8.5C5.5,9.24 5.25,10 5.11,10.79L3.34,7M3.36,17L5.12,13.23C5.26,14 5.53,14.78 5.95,15.5C6.37,16.24 6.91,16.86 7.5,17.37L3.36,17M20.65,7L18.88,10.79C18.74,10 18.47,9.23 18.05,8.5C17.63,7.78 17.1,7.15 16.5,6.64L20.65,7M20.64,17L16.5,17.36C17.09,16.85 17.62,16.22 18.04,15.5C18.46,14.77 18.73,14 18.87,13.21L20.64,17M12,22L9.59,18.56C10.33,18.83 11.14,19 12,19C12.82,19 13.63,18.83 14.37,18.56L12,22Z","mdi:weather-sunset":"M3,12H7A5,5 0 0,1 12,7A5,5 0 0,1 17,12H21A1,1 0 0,1 22,13A1,1 0 0,1 21,14H3A1,1 0 0,1 2,13A1,1 0 0,1 3,12M5,16H19A1,1 0 0,1 20,17A1,1 0 0,1 19,18H5A1,1 0 0,1 4,17A1,1 0 0,1 5,16M17,20A1,1 0 0,1 18,21A1,1 0 0,1 17,22H7A1,1 0 0,1 6,21A1,1 0 0,1 7,20H17M15,12A3,3 0 0,0 12,9A3,3 0 0,0 9,12H15M12,2L14.39,5.42C13.65,5.15 12.84,5 12,5C11.16,5 10.35,5.15 9.61,5.42L12,2M3.34,7L7.5,6.65C6.9,7.16 6.36,7.78 5.94,8.5C5.5,9.24 5.25,10 5.11,10.79L3.34,7M20.65,7L18.88,10.79C18.74,10 18.47,9.23 18.05,8.5C17.63,7.78 17.1,7.15 16.5,6.64L20.65,7Z"};

    if (!customElements.get('ha-icon')) {
        customElements.define('ha-icon', class extends HTMLElement {
            static get observedAttributes() { return ['icon']; }
            connectedCallback() { this._r(); }
            attributeChangedCallback() { this._r(); }
            _r() {
                const d = MDI[this.getAttribute('icon')] || '';
                this.style.display = 'inline-flex';
                this.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor" style="width:var(--mdc-icon-size,24px);height:var(--mdc-icon-size,24px)"><path d="' + d + '"></path></svg>';
            }
        });
    }

    let data = null;
    let selected = localStorage.getItem(STORE_KEY);
    let card = null;
    let cardLoad = null;
    let pollTimer = null;
    let inflight = false;

    function showMessage(text) {
        MSG.textContent = text || '';
        MSG.hidden = !text;
    }

    function loadCard() {
        if (customElements.get('napoleon-fireplace-card')) return Promise.resolve();
        if (!cardLoad) {
            cardLoad = new Promise((resolve, reject) => {
                const s = document.createElement('script');
                s.src = CARD_URL;
                s.onload = () => customElements.whenDefined('napoleon-fireplace-card').then(resolve);
                s.onerror = () => { cardLoad = null; s.remove(); reject(new Error('card load failed')); };
                document.head.appendChild(s);
            });
        }
        return cardLoad;
    }

    function callService(domain, service, serviceData) {
        return fetch(ACTION_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: JSON.stringify({ domain, service, data: serviceData }),
        }).then(async (r) => {
            const body = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(body.error || ('HTTP ' + r.status));
            return body;
        }).finally(() => {
            setTimeout(poll, 600);
            setTimeout(poll, 2500);
        });
    }

    function buildHass() {
        return {
            states: data.states,
            entities: data.entities,
            devices: data.devices,
            config: data.config,
            callService,
        };
    }

    function deviceName(d) { return d.name_by_user || d.name || 'Fireplace'; }

    function powerState(deviceId) {
        const e = Object.values(data.entities).find(
            (x) => x.device_id === deviceId && x.translation_key === 'fireplace_power');
        const s = e && data.states[e.entity_id];
        if (!s || s.state === 'unavailable' || s.state === 'unknown') return 'offline';
        return s.state === 'on' ? 'on' : 'off';
    }

    function renderPills(ids) {
        if (ids.length < 2) { SEL.innerHTML = ''; return; }
        SEL.innerHTML = ids.map((id) => {
            const p = powerState(id);
            const label = p === 'on' ? 'On' : (p === 'off' ? 'Standby' : 'Offline');
            return '<div class="fp-pill ' + (p === 'on' ? 'on ' : '') + (id === selected ? 'active' : '') + '" data-id="' + id + '">'
                + '<div class="pill-ic"><i class="fa-solid fa-fire"></i></div>'
                + '<div class="pill-txt"><b></b><span><i class="fa-solid fa-circle dot ' + (p === 'offline' ? 'offline' : 'online') + '"></i>' + label + '</span></div></div>';
        }).join('');
        SEL.querySelectorAll('.fp-pill').forEach((el) => {
            el.querySelector('b').textContent = deviceName(data.devices[el.dataset.id]);
            el.addEventListener('click', () => select(el.dataset.id));
        });
    }

    function select(id) {
        if (id === selected && card) return;
        selected = id;
        localStorage.setItem(STORE_KEY, id);
        render();
    }

    function render() {
        const ids = Object.keys(data.devices).sort((a, b) =>
            deviceName(data.devices[a]).localeCompare(deviceName(data.devices[b])));
        if (!ids.length) {
            showMessage('No Napoleon fireplaces found in Home Assistant.');
            SEL.innerHTML = '';
            return;
        }
        if (!ids.includes(selected)) selected = ids[0];
        renderPills(ids);
        if (!card || card.dataset.deviceId !== selected) {
            if (card) card.remove();
            card = document.createElement('napoleon-fireplace-card');
            card.dataset.deviceId = selected;
            card.setConfig({ device_id: selected, fill: true });
            card.addEventListener('hass-notification', (ev) => {
                showMessage((ev.detail && ev.detail.message) || 'Fireplace command failed');
                setTimeout(() => showMessage(''), 6000);
            });
            HOST.appendChild(card);
        }
        card.hass = buildHass();
    }

    async function poll() {
        if (inflight) return;
        inflight = true;
        try {
            const r = await fetch(STATES_URL, { cache: 'no-store' });
            const body = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(body.error || ('HTTP ' + r.status));
            data = body;
            await loadCard();
            if (MSG.dataset.sticky) { delete MSG.dataset.sticky; showMessage(''); }
            render();
        } catch (err) {
            console.error('Fireplace:', err);
            MSG.dataset.sticky = '1';
            showMessage('Home Assistant is unreachable — retrying…');
        } finally {
            inflight = false;
        }
    }

    function isActive() { return ROOT.classList.contains('active') && !document.hidden; }

    function sync() {
        if (isActive()) {
            if (!pollTimer) { poll(); pollTimer = setInterval(poll, POLL_MS); }
        } else if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    new MutationObserver(sync).observe(ROOT, { attributes: true, attributeFilter: ['class'] });
    document.addEventListener('visibilitychange', sync);
    sync();
})();