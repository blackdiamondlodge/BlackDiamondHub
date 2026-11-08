# Copilot Instructions for BlackDiamondHub

## Project Overview

BlackDiamondHub is a Django-based home automation and management hub for a vacation property at Sun Peaks, BC. It runs on Django 5.1 with Python 3.11, uses PostgreSQL for data storage, and integrates with Home Assistant for device control. The app is served via Daphne/Channels (ASGI) to support WebSockets.

## Django Apps

- **feedback** — User feedback submission and admin review (django-tables2)

Installed from their own repos via `sites/sunpeaks/apps.txt`:

- **wifi** (`blackdiamondlodge/bdh-app-wifi`) — WiFi QR code generator with password display
- **sunpeaks_webcams** (`bdh-app-sunpeaks-webcams`) — Sun Peaks resort webcam viewer
- **lift_status** (`bdh-app-lift-status`) — Sun Peaks lift and trail status
- **snow_report** (`bdh-app-snow-report`) — Mountain Conditions: seasonal snow/weather report + Open-Meteo forecast
- **radiant** (`bdh-app-radiant`) — Radiant heating / heat-pump plant dashboard
- **device_control** (`bdh-app-device-control`) — the "Controls" tile: scenes (first tab and homepage quick actions), lights, blinds, fireplaces and Gemstone Lights via Home Assistant (`BDH_DEVICE_CONTROL_SCENES_FILTER`, legacy `BDH_SCENES_FILTER`/`SCENE_FILTER`; `BDH_DEVICE_CONTROL_GEMSTONE_EMAIL`/`_PASSWORD`, legacy `GEMSTONE_*`)
- **cameras** (`bdh-app-cameras`) — Live camera feeds via go2rtc + UniFi Protect Integration API (`BDH_CAMERAS_GO2RTC_URL`, `BDH_CAMERAS_PROTECT_{HOST,API_KEY,NAME}_n`; legacy `GO2RTC_URL`, `UNIFI_PROTECT_*_n`)
- **vacation_mode** (`bdh-app-vacation-mode`) — Automates switching between vacation and home modes via Home Assistant REST API (thermostats, water heater, hot tub, TVs, fridge/freezer eco modes). Includes post-action state verification since HA silently drops commands to offline devices (`BDH_VACATION_MODE_MODES_URL`/`_MODES_API_KEY`/`_PREHEAT`, legacy `BDL_MODES_*`)
- **sonos_control** (`bdh-app-sonos-control`) — Sonos speaker control with Spotify integration (`BDH_SONOS_CONTROL_INTERFACE`, legacy `SONOS_INTERFACE`; Spotify OAuth/social-auth settings stay in core)
- **stays** (`bdh-app-stays`) — no pages; its `stay` hook reads `sensor.bdl_stay_current` from the Stays AppDaemon app to put the homepage in guest (or owner-visit) mode, and its `card` hook provides the lodge card (`BDH_STAYS_ENTITY` and friends, see its README)
- **inventory** (`bdh-app-inventory`) — kitchen inventory with item photos and QR code labels at `/inventory/` (sign-in, no homepage tile). Its tests use pyzbar, so keep `pyzbar`/`libzbar0` in the hub requirements and CI

## Tech Stack

- **Backend**: Django 5.1, Python 3.11, PostgreSQL, Daphne/Channels (ASGI)
- **Frontend**: Bootstrap 5 (crispy-bootstrap5), Font Awesome 6 icons
- **Auth**: Django auth + social-auth-app-django (Spotify OAuth)
- **Home Assistant**: REST API at `192.168.10.212:8123`, token stored in `.env` as `HA_TOKEN`
- **Containerization**: Docker + docker-compose (see Deployment section)
- **Environment**: `.env` file for secrets (not committed)

## Deployment & Infrastructure

### Production Host
- **Server**: Ubuntu host `homehub` at `~/bdl/BlackDiamondHub`
- **Network**: Dual-subnet — Sun Peaks (`192.168.10.x`) and Mercer Island (`192.168.1.x`)
- **Docker Compose V2** (`docker compose`, not the old `docker-compose` v1)

### CI/CD Pipeline
1. **Code changes** go through feature branches → PRs → merge to `main`
2. **GitHub Actions** (`docker-publish.yml`) triggers on push to `main`:
   - Builds the Docker image from the Dockerfile
   - Pushes to GHCR: `ghcr.io/blackdiamondlodge/blackdiamondhub/blackdiamondhub:latest`
3. **Watchtower** on production polls GHCR every 300s, pulls new images, and recreates the `BlackDiamondHub` container automatically
   - Watchtower only watches the `BlackDiamondHub` container (not go2rtc)

### What auto-deploys vs. what doesn't
- **Auto-deploys** (via Watchtower): Any code change inside the Docker image — Django code, templates, static files, Python dependencies
- **Does NOT auto-deploy**: Changes to `docker-compose.yml`, `.env`, or `go2rtc/go2rtc.yaml` on the server — these require manual SSH + `git pull` + `docker compose up -d --force-recreate`
- `go2rtc/go2rtc.yaml` is **not tracked** (go2rtc writes stream URLs with RTSPS access tokens into it). Copy `go2rtc/go2rtc.example.yaml` to create it; never commit stream URLs.

### Docker Services (docker-compose.yml)
- **djangoapp** (`BlackDiamondHub`) — Django app on port 8000, image from GHCR
  - Runs `docker/entrypoint.sh`: waits for the DB; if migrations are pending, `pg_dump`s to `./backups` (host volume, last 10 kept) and runs `migrate`; then serves with **Daphne** (not `runserver`). Static files are collected at image build and served by **WhiteNoise**.
  - Requires `DJANGO_SECRET_KEY` in `.env`; `DJANGO_DEBUG` defaults to off (set `DJANGO_DEBUG=true` in a local `.env` for development).
  - `/healthz` (DB check, exempt from ALLOWED_HOSTS) backs the image's Docker `HEALTHCHECK`.
  - Rollback: images are also tagged `:sha-<commit>`; pin `image:` in compose to a previous sha and `docker compose up -d`. Watchtower does not roll back on its own, and an image rollback does not undo migrations (restore from `./backups` if needed).
- **go2rtc** (`alexxit/go2rtc`) — RTSPS-to-WebRTC proxy on port 1984 (API/WebUI) and 8555 (WebRTC)
- **watchtower** (`containrrr/watchtower`) — Auto-updates the Django container from GHCR

### go2rtc Browser URL Strategy
- Django uses host networking, so it calls go2rtc at `GO2RTC_URL=http://localhost:1984` and registers each camera's RTSPS stream via `PUT /api/streams` (re-registering if the URL changed)
- The **browser** needs to reach go2rtc directly — the template uses `window.location.hostname` + port 1984 so it works from any subnet without hardcoding an IP

## UniFi Protect Integration API

- **API Docs**: https://developer.ui.com/protect/v6.2.88/get-v1metainfo (sidebar has all endpoints)
- **Auth**: API key via `X-API-KEY` header, key generated at unifi.ui.com → Settings → API Keys
- **Base URL**: `https://{UNIFI_PROTECT_HOST}/proxy/protect/integration/v1`
- **Camera list**: `GET /v1/cameras` — returns id, name, state, featureFlags (note: PTZ flags NOT exposed)
- **RTSPS streams**: `GET /v1/cameras/{id}/rtsps-stream` and `POST /v1/cameras/{id}/rtsps-stream` with `{"qualities": ["high"]}`
- **PTZ endpoints** (for PTZ cameras only, non-PTZ returns 400 "Camera is not a type of PTZ"):
  - `POST /v1/cameras/{id}/ptz/goto/{slot}` — Move to preset (slots 0-4, 204 on success, 404 if preset doesn't exist)
  - `POST /v1/cameras/{id}/ptz/patrol/start/{slot}` — Start patrol
  - `POST /v1/cameras/{id}/ptz/patrol/stop` — Stop patrol
- **go2rtc**: Proxies RTSPS streams to browser via WebRTC/MSE. `video-stream.js` web component (set src/mode/background as JS properties, NOT HTML attributes). Docker image: `alexxit/go2rtc`

## CI/CD

- **Test workflow** (`tests.yml`): Runs on every push/PR
  - Three jobs: `unit-tests` (excludes selenium tag), `selenium-tests` (selenium tag only, with retry via nick-fields/retry), and `image-smoke-test` (builds the Docker image, boots it against Postgres 16 and checks backup, migrate, health, pages and static files)
  - Test jobs run on `ubuntu-22.04` with a PostgreSQL service container
  - Selenium tests use headless Chrome with shared helpers in `tests/selenium_helpers.py`
- **Docker publish workflow** (`docker-publish.yml`): Runs on push to `main`
  - Builds Docker image and pushes to GHCR (`ghcr.io/blackdiamondlodge/blackdiamondhub/blackdiamondhub:latest` and `:sha-<commit>`)
  - Watchtower on production auto-pulls the new image (see Deployment section)

## Branch & Git Workflow

- **All changes must go into a feature branch** — never commit directly to `main`
- **Only I (the user) merge PRs to main** — Copilot should push branches and may suggest creating a PR, but should not merge
- Branch naming: `feature/description`, `fix/description`
- `main` branch has protection rules: require PR, require status checks (unit-tests, selenium-tests), no force push, no deletion

## Pull Requests

- **Always use the GitHub CLI (`gh`) for PR operations** — do not use MCP tools, API calls, or browser-based approaches
- Create PRs: `gh pr create --title "..." --body "..." --base main`
- View PR status: `gh pr view`
- List PRs: `gh pr list`
- Check CI status: `gh pr checks`
- The `gh` CLI is already authenticated on this machine

## Testing

- Install the site's extracted apps into the venv first (once, and after each `apps.txt` bump): `venv\Scripts\python.exe -m pip install --require-hashes --no-deps -r sites\sunpeaks\apps.txt`. Their own tests run in each app repo's CI, not here.
- Run unit tests: `venv\Scripts\python.exe manage.py test --exclude-tag=selenium --verbosity 2`
- Run one app's tests only: `venv\Scripts\python.exe manage.py test hub --verbosity 2` (installed apps need a module label, e.g. `vacation_mode.tests`)
- Run all tests: `$env:PGPASSWORD='postgres'; venv\Scripts\python.exe manage.py test --verbosity 2`
- Selenium tests extend `StaticLiveServerTestCase` and use shared `get_chrome_options()` from `tests/selenium_helpers.py`
- Always run relevant tests after making changes

## Communication Preferences

- **Do NOT use the ask_questions tool with selectable options** — if you have questions, just ask them directly in the chat as plain text
- Keep explanations concise and direct
- When making changes, implement them rather than just suggesting

## Key Files

- `BlackDiamondHub/settings.py` — Django settings, database config, and the `HUB_PLUGINS` list of hub apps
- `BlackDiamondHub/urls.py` — core URLs; hub app URLs are mounted automatically from their `PluginSpec`
- `hub/plugins.py` — plugin contract (`PluginSpec`, `Tile`, modes, sections) that every hub app implements
- `hub/loader.py` / `hub/modes.py` — plugin discovery/validation, websocket route collection and homepage mode (guest / dashboard / owner) + tile lookup
- `hub/spotify_auth.py` — platform-owned Spotify social-auth hooks (`spotify_token` context processor, disconnect-pipeline steps) referenced from core settings
- `bdh_sdk.ha` — shared Home Assistant client (`get_entity_states`, `get_history`, `call_service`, `ws_commands`…), in bdh-sdk so extracted apps can use it. Apps import it from `bdh_sdk.ha`, never from another app (`hub/ha_client.py` and `device_control.ha_client` are compatibility re-exports)
- `tests/selenium_helpers.py` — Shared Selenium test utilities (login, Chrome options, network waits)
- `.env` — Environment variables (HA_TOKEN, DB credentials, etc.)
- `requirements.txt` — Python dependencies

## Base Template & Navbar (`templates/base.html`)

`templates/base.html` is the public shell contract for hub apps: every app page does `{% extends 'base.html' %}` and fills its blocks (`content`, `navbar_extras`, `extra_head`, `body_class`). Keep those block names stable — apps in other repos depend on them. Core templates (`base.html`, `index.html`, `registration/login.html`) stay in the project `templates/` folder.

All pages extend `base.html`, which provides:
- **Navbar**: Bootstrap 5 `navbar-dark bg-dark fixed-top` with brand "Black Diamond Hub" on the left, icon buttons (feedback, notifications, login/logout) on the right
- **Touch targets**: All navbar buttons/links have 48×48px minimum tap targets for touchscreen use
- **Navbar colour**: `.nav-link` elements inside the navbar have explicit `color: rgba(255,255,255,0.85)` because they sit outside a `.navbar-nav` wrapper — Bootstrap's `navbar-dark` rules don't reach them otherwise
- **Content wrapper**: `<div class="container-fluid content-wrapper">` with `margin-top: 62px` to clear the fixed navbar

### `{% block navbar_extras %}`

A template block in the navbar between the brand and the right-side icon group. Pages that need unit-conversion toggles (or other page-specific navbar controls) fill this block:

- **Landing page** (`index.html`): `°C/°F` button — client-side JS `toggleUnits()` converts temperature/elevation in-place via `data-metric` attributes
- **Mountain Conditions** (`snow_report/snow_report.html`): `°C, m` / `°F, ft` buttons — server-side reload via `?units=metric` / `?units=imperial` query param
- **All other pages**: Block is empty, no toggle shown

Use the `.navbar-toggle-btn` class for toggle buttons in this block. When adding a new page that needs a unit toggle or similar control, fill `{% block navbar_extras %}` with the appropriate buttons — don't add inline toggles to the page body.

`base.html` also has `{% block extra_head %}` (page styles in `<head>`) and `{% block body_class %}` (classes on `<body>`).

## Hub Apps (plugins)

The hub is a platform; each feature is an app that describes itself in `<app>/plugin.py` with a `PluginSpec` (`hub/plugins.py`). The hub uses the specs to add apps to `INSTALLED_APPS`, mount their URLs at `<id>/`, and build the homepage tiles. Apps in their own repos register a `blackdiamondhub.plugins` entry point instead of being listed in `settings.HUB_PLUGINS`.

To add an app: create `<app>/plugin.py` with `spec = PluginSpec(...)`, add `'<app>.plugin.spec'` to `HUB_PLUGINS`, and put its tile icon at `<app>/static/<app>/hub/icon.svg` (64×64 rounded tile, tinted gradient, white 2.6-stroke glyph — match the existing icons).

Homepage modes: `owner` when signed in, `guest` while an app's `stay` hook reports a stay, otherwise `dashboard`. `Tile.modes` only hides tiles — owner-only views must still enforce `@login_required` themselves. During an owner visit (`Stay.owner`), `hub.owner_visit.OwnerVisitMiddleware` makes `request.user` the `HUB_OWNER_VISIT_USER` account (blank = off); nothing is stored in the session, so it ends with the visit. In guest mode the homepage never mentions owner features beyond the navbar login icon; the page reloads itself when the polled mode changes.

Homepage hooks (optional, dotted paths in the spec, conventionally in `<app>/homepage.py`):
- `status` → `Status(text, level)` (levels `info`/`on`/`warn`) replaces the tile subtitle. Hooks run in a thread pool with a 6 s deadline and are cached 60 s; on failure the last good value is shown faded as stale. A hook that takes a `mode` argument is called with the homepage mode and cached per mode (e.g. cameras counts every site only for owners).
- `shortcuts` → list of `Shortcut` for the Quick actions row, run via `run_shortcut(id)` from `POST /hub/api/shortcut/<plugin>/<id>/` (CSRF). Shortcuts are owner-only unless they set `modes` explicitly; the hub rejects shortcuts not offered in the caller's mode.
- The homepage polls `GET /hub/api/status/` every minute.
- `stay` → `Stay(guest, arrival, checkout, owner)` or None (`hub.status.current_stay`). Run like `status` but with a 3 s deadline since every homepage request needs it; a stale last-good stay is dropped once its checkout passes. Never put door PINs in a `Stay`.
- `card` → `Card(title, detail, readings, alerts, url_name, level)` or None (`hub.status.lodge_card`): the lodge card at the top of the homepage in every mode, from the first app with the hook. Same 3 s deadline; also returned by the status API and re-rendered on each poll. Guests get it without alerts or the link. Without a card app, guests get the plain welcome line.
- `websocket_routes` → dotted path to a list of Channels URL patterns (e.g. `"sonos_control.routing.websocket_urlpatterns"`). `BlackDiamondHub/asgi.py` collects them from every installed plugin with `hub.loader.websocket_urlpatterns()` after Django is set up, and serves them behind `AllowedHostsOriginValidator(AuthMiddlewareStack(...))`. Never import an app's routing from core code.

### Rules that keep apps extractable into their own repos

- **Namespaced templates.** An app's templates live in `<app>/templates/<app_label>/` and are always referenced with the prefix — `render(request, "wifi/wifi_qr.html")`, `{% include "sonos_control/partials/spotify.html" %}`, `assertTemplateUsed(r, "vacation_mode/vacation_mode.html")`. Never add un-prefixed templates to an app; they collide across apps.
- **Side-effect-free `plugin.py`.** `<app>/plugin.py` may import only `hub.plugins` (and the stdlib). It must not import the app's models, views or homepage, `requests`, or anything that calls Home Assistant/HTTP or starts threads — specs are loaded while settings are still being built. Point hooks at code with dotted strings. `hub/tests/test_plugin_entrypoints.py` enforces this in a fresh interpreter.
- **No cross-app imports.** Apps import from `bdh_sdk` (e.g. `bdh_sdk.ha`, `bdh_sdk.settings`), `hub` and Django, not from each other. Shared helpers belong in `hub`.

### SDK, per-site apps and acceptance smoke test

- The contract (`PluginSpec`, `Tile`, `Status`, `Shortcut`, modes, sections) lives in **`bdh-sdk`** (github.com/blackdiamondlodge/bdh-sdk), pinned in `requirements.txt` by GitHub release wheel URL. `hub/plugins.py` only re-exports it — change the contract in bdh-sdk, release it, then bump the pin. bdh-sdk also provides `bdh_sdk.settings.app_setting(app_id, key, legacy=...)` (reads `BDH_<ID>_<KEY>`, then legacy env names, then Django settings), the Home Assistant client `bdh_sdk.ha` and the reusable app CI workflow `app-ci.yml`.
- Apps from their own repos (`blackdiamondlodge/bdh-app-<id>`) are installed per site from `sites/<site>/apps.txt` (hashed wheel URLs, `pip install --require-hashes --no-deps`); the image is built with `--build-arg HUB_SITE=<site>` and tagged `:<site>` (`:sunpeaks` and `:latest` today). An app's third-party deps must be in the hub's `requirements.txt`. When an app is extracted, remove it from `HUB_PLUGINS` in the same PR that adds it to the site's `apps.txt`. Hub CI installs `sites/sunpeaks/apps.txt` and runs `hub_smoke` before the unit tests; the app's CI (bdh-sdk `app-ci.yml`) deletes any in-tree copy from the hub checkout so it can be tested before the hub drops it.
- `python manage.py hub_smoke [--app <id>]` is the acceptance check: hook paths import, tile icons resolve via static finders, and every tile page renders (<500) for a signed-in superuser against a throwaway test DB. The reusable app CI runs it after installing the app's wheel next to the hub.
