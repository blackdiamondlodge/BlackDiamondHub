"""
Shared Selenium test helpers for BlackDiamondHub.

Provides reusable utilities for Selenium-based tests including:
- Browser login helper with proper WebDriverWait
- Network idle wait for AJAX-heavy pages
- Common Chrome options setup
- SeleniumTestCase base class that dumps browser state when a test fails
"""

import json

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from selenium import webdriver

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


def get_chrome_options():
    """Return standard headless Chrome options used across all Selenium tests.

    Google Chrome pulls field-trial configs, component updates and other
    background downloads at runtime, so its behaviour can change between CI
    runs with no version change. These flags (the ones Puppeteer and
    Playwright use) keep the browser the same from run to run.
    """
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-background-networking')
    options.add_argument('--disable-component-update')
    options.add_argument('--disable-field-trial-config')
    options.add_argument('--disable-default-apps')
    options.add_argument('--disable-sync')
    options.add_argument('--no-first-run')
    options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    return options


_STATE_JS = """
    function box(e) {
        var cs = getComputedStyle(e), r = e.getBoundingClientRect();
        return {display: cs.display, visibility: cs.visibility, opacity: cs.opacity,
                rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]};
    }
    var ids = {};
    document.querySelectorAll('[id]').forEach(function (e) {
        if (e.offsetParent !== null || getComputedStyle(e).position === 'fixed') ids[e.id] = box(e);
    });
    return {
        url: location.href,
        readyState: document.readyState,
        bodyClass: document.body ? document.body.className : null,
        visibleIds: ids,
        requests: performance.getEntriesByType('resource').slice(-30).map(function (r) {
            return r.name.replace(location.origin, '') + ' ' + Math.round(r.duration) + 'ms ' + (r.responseStatus || '');
        }),
    };
"""


def dump_browser_state(driver, label=''):
    """Print the browser console, page state and recent requests."""
    print(f'\n===== browser state after failure: {label}')
    try:
        for entry in driver.get_log('browser'):
            print(f"console {entry.get('level')}: {entry.get('message')}")
    except Exception as exc:
        print(f'(no console log: {exc})')
    try:
        print(json.dumps(driver.execute_script(_STATE_JS), indent=1))
    except Exception as exc:
        print(f'(no page state: {exc})')
    print('===== end browser state')


class SeleniumTestCase(StaticLiveServerTestCase):
    """Live-server test with one shared 1920x1080 headless Chrome per class.

    When a test fails, the browser console and page state are printed so a
    CI-only failure can be diagnosed from the log instead of re-run.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.browser = webdriver.Chrome(options=get_chrome_options())
        cls.browser.set_window_size(1920, 1080)

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.addCleanup(self._dump_if_failed)

    def _dump_if_failed(self):
        # Python 3.11+ reports a test's errors to the result as they happen,
        # so they are already visible when cleanups run.
        result = getattr(getattr(self, '_outcome', None), 'result', None)
        if result is None:
            return
        if any(test is self for test, _ in result.errors + result.failures):
            dump_browser_state(self.browser, self.id())


def login_via_browser(driver, live_server_url, username="testuser", password="testpassword"):
    """
    Log in via the Django login page using Selenium.

    Uses WebDriverWait for all element interactions to avoid race conditions.
    Waits for the login to complete by checking for the feedback-button element
    on the redirected page.

    Args:
        driver: Selenium WebDriver instance.
        live_server_url: The base URL of the live test server.
        username: Username to log in with (default: "testuser").
        password: Password to log in with (default: "testpassword").
    """
    driver.get(f'{live_server_url}/accounts/login/')

    username_input = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.ID, "id_username"))
    )
    password_input = driver.find_element(By.ID, "id_password")

    username_input.send_keys(username)
    password_input.send_keys(password)

    login_button = driver.find_element(By.ID, 'login-submit')
    login_button.click()

    # The login page shares base.html elements (e.g. feedback-button) with the
    # destination, so wait for the redirect to avoid grabbing stale elements.
    WebDriverWait(driver, 20).until(
        lambda d: '/accounts/login/' not in d.current_url
    )


def login_from_page(driver, live_server_url, username="testuser", password="testpassword"):
    """
    Click the login button on the current page, fill credentials, and submit.

    Used when navigating to a page that has a login-button element that
    redirects to the login form, then back to the original page.
    If already on the login page (e.g. after a redirect), skips clicking
    the login button and fills in credentials directly.

    Args:
        driver: Selenium WebDriver instance.
        live_server_url: The base URL of the live test server.
        username: Username to log in with (default: "testuser").
        password: Password to log in with (default: "testpassword").
    """
    # If we're already on the login page (e.g. redirected by @login_required),
    # skip clicking the navbar login button — just fill in credentials directly.
    if '/accounts/login/' not in driver.current_url:
        login_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.ID, 'login-button'))
        )
        login_button.click()

    # Wait for login page to load
    username_input = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.ID, "id_username"))
    )
    password_input = driver.find_element(By.ID, "id_password")

    username_input.send_keys(username)
    password_input.send_keys(password)

    # Wait for submit button to be clickable before clicking
    login_button = WebDriverWait(driver, 20).until(
        EC.element_to_be_clickable((By.ID, 'login-submit'))
    )
    login_button.click()

    # Wait for navigation away from the login page
    WebDriverWait(driver, 20).until(
        lambda d: '/accounts/login/' not in d.current_url
    )


def wait_for_network_idle(driver, timeout=10):
    """
    Wait for the page to reach a network-idle state.

    Checks that:
    1. document.readyState is 'complete'
    2. No active XMLHttpRequest or fetch requests are pending

    This uses a JavaScript performance observer approach that tracks
    in-flight fetch/XHR requests via monkey-patching.

    Args:
        driver: Selenium WebDriver instance.
        timeout: Maximum seconds to wait (default: 10).
    """
    # First ensure document is fully loaded
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )

    # Inject a network activity tracker if not already present
    driver.execute_script("""
        if (!window.__networkIdleTracker) {
            window.__networkIdleTracker = { pending: 0 };

            // Monkey-patch fetch
            const originalFetch = window.fetch;
            window.fetch = function() {
                window.__networkIdleTracker.pending++;
                return originalFetch.apply(this, arguments)
                    .then(response => {
                        window.__networkIdleTracker.pending--;
                        return response;
                    })
                    .catch(error => {
                        window.__networkIdleTracker.pending--;
                        throw error;
                    });
            };

            // Monkey-patch XMLHttpRequest
            const originalOpen = XMLHttpRequest.prototype.open;
            const originalSend = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = function() {
                this.__tracked = true;
                return originalOpen.apply(this, arguments);
            };
            XMLHttpRequest.prototype.send = function() {
                if (this.__tracked) {
                    window.__networkIdleTracker.pending++;
                    this.addEventListener('loadend', function() {
                        window.__networkIdleTracker.pending--;
                    });
                }
                return originalSend.apply(this, arguments);
            };
        }
    """)

    # Wait for all pending requests to complete
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script(
            "return window.__networkIdleTracker ? window.__networkIdleTracker.pending === 0 : true"
        )
    )
