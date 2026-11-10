"""
Shared Selenium test helpers for BlackDiamondHub.

Provides reusable utilities for Selenium-based tests including:
- Browser login helper with proper WebDriverWait
- Network idle wait for AJAX-heavy pages
- Common Chrome options setup
- SeleniumTestCase base class that dumps browser state when a test fails
- wait_for_paint / click_until / type_into for input that Chrome may drop

Why the last group exists: WebDriver reports a click or keystroke as sent
even when the page never receives it. The main cause, Chrome's password
manager taking focus after login, is switched off in get_chrome_options();
these helpers also confirm every interaction had its effect and repeat it
if not, so a test fails on a real bug rather than on lost input.
"""

import json

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException, StaleElementReferenceException, TimeoutException,
)

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
    # After the tests log in, Chrome's password manager can open a "Save
    # password?" bubble or a leaked-password warning ("testpassword" is in
    # breach lists). Either takes focus from the page, and the clicks and
    # keystrokes that follow are silently lost.
    options.add_argument('--disable-features=PasswordLeakDetection,PasswordManagerOnboarding')
    options.add_experimental_option('prefs', {
        'credentials_enable_service': False,
        'profile.password_manager_enabled': False,
        'profile.password_manager_leak_detection': False,
    })
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


def wait_for_paint(driver, timeout=20):
    """Wait until the page has loaded and painted at least one frame.

    Call after a navigation and before the first click or keystroke.
    """
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script('return document.readyState') == 'complete'
    )
    driver.set_script_timeout(timeout)
    driver.execute_async_script(
        'var done = arguments[arguments.length - 1];'
        'requestAnimationFrame(function () { requestAnimationFrame(function () { done(true); }); });'
    )


def click_until(driver, locator, done, attempts=3, settle=3, timeout=20):
    """Click the element at ``locator`` until ``done(driver)`` is truthy.

    The element is looked up again before every click, so a re-render
    between attempts doesn't leave a stale reference. Only use this where
    ``done`` turns true as soon as the click lands; a slow server reply
    could otherwise trigger a second click.

    Returns the value ``done`` returned.
    """
    for attempt in range(attempts):
        WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator)).click()
        try:
            return WebDriverWait(driver, settle).until(done)
        except TimeoutException:
            # A poll can block on a page load until after the deadline, so
            # look once more before clicking again.
            try:
                value = done(driver)
            except (NoSuchElementException, StaleElementReferenceException):
                value = None
            if value:
                return value
            if attempt == attempts - 1:
                raise


def type_into(driver, locator, text, attempts=3, timeout=20):
    """Replace the value of the input at ``locator`` with ``text`` and check it stuck."""
    def typed(d):
        return d.find_element(*locator).get_attribute('value') == text

    for attempt in range(attempts):
        field = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator))
        field.click()
        field.clear()
        field.send_keys(text)
        try:
            WebDriverWait(driver, 2).until(typed)
            return
        except TimeoutException:
            if attempt == attempts - 1:
                raise


def _submit_login(driver, username, password):
    """Fill in and submit the login form on the current page."""
    wait_for_paint(driver)
    type_into(driver, (By.ID, 'id_username'), username)
    type_into(driver, (By.ID, 'id_password'), password)
    # Note the form's submit so a click that is still navigating isn't repeated.
    driver.execute_script(
        "document.getElementById('login-submit').form.addEventListener("
        "'submit', function () { window.__loginSubmitted = true; });"
    )
    click_until(
        driver, (By.ID, 'login-submit'),
        lambda d: '/accounts/login/' not in d.current_url
        or d.execute_script('return window.__loginSubmitted === true'),
        settle=10,
    )
    # The login page shares base.html elements (e.g. feedback-button) with the
    # destination, so wait for the redirect to avoid grabbing stale elements.
    WebDriverWait(driver, 30).until(lambda d: '/accounts/login/' not in d.current_url)
    wait_for_paint(driver)


def login_via_browser(driver, live_server_url, username="testuser", password="testpassword"):
    """
    Log in via the Django login page using Selenium.

    Every keystroke and the submit click are confirmed, and the helper
    returns once the redirected page has painted.

    Args:
        driver: Selenium WebDriver instance.
        live_server_url: The base URL of the live test server.
        username: Username to log in with (default: "testuser").
        password: Password to log in with (default: "testpassword").
    """
    driver.get(f'{live_server_url}/accounts/login/')
    _submit_login(driver, username, password)


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
    if '/accounts/login/' not in driver.current_url:
        wait_for_paint(driver)
        click_until(driver, (By.ID, 'login-button'),
                    lambda d: '/accounts/login/' in d.current_url, settle=10)
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, 'id_username')))
    _submit_login(driver, username, password)


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
