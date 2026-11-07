# Copilot Instructions for BlackDiamondHub

## Project Overview

BlackDiamondHub is a Django-based home automation and management hub for a vacation property at Sun Peaks, BC. It runs on Django 5.1 with Python 3.11, uses PostgreSQL for data storage, and integrates with Home Assistant for device control. The app is served via Daphne/Channels (ASGI) to support WebSockets.

## Django Apps

- **inventory** — Property inventory management with item tracking, images, and QR code labels (uses pyzbar for scanning)
- **vacation_mode** — Automates switching between vacation and home modes via Home Assistant REST API (thermostats, water heater, hot tub, TVs, fridge/freezer eco modes). Includes post-action state verification since HA silently drops commands to offline devices
- **sonos_control** — Sonos speaker control with Spotify integration via OAuth (social-auth)
- **cameras** — Live camera feeds via go2rtc + UniFi Protect Integration API
- **sunpeaks_webcams** — Sun Peaks resort webcam viewer
- **snow_report** — Snow/weather report display
- **scenes** — Home Assistant scene control
- **wifi** — WiFi QR code generator with password display
- **feedback** — User feedback submission and admin review (django-tables2)

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
   - Pushes to GHCR: `ghcr.io/sslivins/blackdiamondhub/blackdiamondhub:latest`
3. **Watchtower** on production polls GHCR every 300s, pulls new images, and recreates the `BlackDiamondHub` container automatically
   - Watchtower only watches the `BlackDiamondHub` container (not go2rtc)

### What auto-deploys vs. what doesn't
- **Auto-deploys** (via Watchtower): Any code change inside the Docker image — Django code, templates, static files, Python dependencies
- **Does NOT auto-deploy**: Changes to `docker-compose.yml`, `.env`, or `go2rtc/go2rtc.yaml` on the server — these require manual SSH + `git pull` + `docker compose up -d --force-recreate`
- `go2rtc/go2rtc.yaml` is **not tracked** (go2rtc writes stream URLs with RTSPS access tokens into it). Copy `go2rtc/go2rtc.example.yaml` to create it; never commit stream URLs.

### Docker Services (docker-compose.yml)
- **djangoapp** (`BlackDiamondHub`) — Django app on port 8000, image from GHCR
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
  - Two jobs: `unit-tests` (excludes selenium tag) and `selenium-tests` (selenium tag only, with retry via nick-fields/retry)
  - Both jobs run on `ubuntu-22.04` with PostgreSQL 13 service container
  - Selenium tests use headless Chrome with shared helpers in `tests/selenium_helpers.py`
- **Docker publish workflow** (`docker-publish.yml`): Runs on push to `main`
  - Builds Docker image and pushes to GHCR (`ghcr.io/sslivins/blackdiamondhub/blackdiamondhub:latest`)
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

- Run unit tests: `venv\Scripts\python.exe manage.py test --exclude-tag=selenium --verbosity 2`
- Run vacation_mode tests only: `venv\Scripts\python.exe manage.py test vacation_mode --verbosity 2`
- Run all tests: `$env:PGPASSWORD='postgres'; venv\Scripts\python.exe manage.py test --verbosity 2`
- Selenium tests extend `StaticLiveServerTestCase` and use shared `get_chrome_options()` from `tests/selenium_helpers.py`
- Always run relevant tests after making changes

## Communication Preferences

- **Do NOT use the ask_questions tool with selectable options** — if you have questions, just ask them directly in the chat as plain text
- Keep explanations concise and direct
- When making changes, implement them rather than just suggesting

## Key Files

- `BlackDiamondHub/settings.py` — Django settings, installed apps, database config
- `BlackDiamondHub/urls.py` — URL routing for all apps
- `vacation_mode/executor.py` — HA service call execution engine with state verification
- `vacation_mode/steps.py` — Step definitions for vacation and home mode sequences
- `cameras/protect_api.py` — UniFi Protect API client (camera discovery, RTSPS streams, PTZ control)
- `cameras/views.py` — Camera feed views, go2rtc stream registration
- `tests/selenium_helpers.py` — Shared Selenium test utilities (login, Chrome options, network waits)
- `.env` — Environment variables (HA_TOKEN, DB credentials, etc.)
- `requirements.txt` — Python dependencies

## Base Template & Navbar (`templates/base.html`)

All pages extend `base.html`, which provides:
- **Navbar**: Bootstrap 5 `navbar-dark bg-dark fixed-top` with brand "Black Diamond Hub" on the left, icon buttons (feedback, notifications, login/logout) on the right
- **Touch targets**: All navbar buttons/links have 48×48px minimum tap targets for touchscreen use
- **Navbar colour**: `.nav-link` elements inside the navbar have explicit `color: rgba(255,255,255,0.85)` because they sit outside a `.navbar-nav` wrapper — Bootstrap's `navbar-dark` rules don't reach them otherwise
- **Content wrapper**: `<div class="container-fluid content-wrapper">` with `margin-top: 62px` to clear the fixed navbar

### `{% block navbar_extras %}`

A template block in the navbar between the brand and the right-side icon group. Pages that need unit-conversion toggles (or other page-specific navbar controls) fill this block:

- **Landing page** (`index.html`): `°C/°F` button — client-side JS `toggleUnits()` converts temperature/elevation in-place via `data-metric` attributes
- **Snow report** (`snow_report.html`): `°C, m` / `°F, ft` buttons — server-side reload via `?units=metric` / `?units=imperial` query param
- **All other pages**: Block is empty, no toggle shown

Use the `.navbar-toggle-btn` class for toggle buttons in this block. When adding a new page that needs a unit toggle or similar control, fill `{% block navbar_extras %}` with the appropriate buttons — don't add inline toggles to the page body.
