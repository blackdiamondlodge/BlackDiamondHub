from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from django.contrib.auth.models import User
from django.test import TestCase, Client, tag
from django.urls import reverse
from feedback.models import Feedback
from tests.selenium_helpers import (
    SeleniumTestCase, click_until, login_via_browser, type_into, wait_for_paint,
)

class LandingPageLiveTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_landing_page_live_data(self):
        response = self.client.get(reverse('landing_page'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('sunpeaks_weather', response.context)
        weather_data = response.context['sunpeaks_weather']

        # Verify that there are 4 entries.
        self.assertEqual(len(weather_data), 4, "Expected exactly 4 weather entries.")

        # Expected values for location and elevation (elevation as integer)
        expected_entries = [
            {'location': 'Top of the World', 'elevation': 2080},
            {'location': 'Mid-mountain', 'elevation': 1855},
            {'location': 'Top of Morrisey', 'elevation': 1675},
            {'location': 'Valley', 'elevation': 1255}
        ]
        
        for expected in expected_entries:
            found = any(
                entry['location'] == expected['location'] and entry['elevation'] == expected['elevation']
                for entry in weather_data
            )
            self.assertTrue(found, f"Did not find expected entry: {expected}")

        # Verify that each weather entry has a temperature value.
        # Temperature can be "N/A" (indicating live data issues) or a valid number.
        for entry in weather_data:
            temp = entry.get('temperature')
            self.assertIsNotNone(temp, f"No temperature value found for entry: {entry}")

            if temp != "N/A":
                try:
                    temp_val = float(temp)
                    # Check that the temperature falls within a reasonable range.
                    self.assertTrue(
                        -50 <= temp_val <= 150,
                        f"Temperature {temp_val} out of expected range for entry: {entry}"
                    )
                except ValueError:
                    self.fail(f"Temperature value is not a valid number: {temp}")

@tag('selenium')
class LandingPageNoScrollTest(SeleniumTestCase):
    """Ensure the landing page fits within the viewport on a 1920×1080 display."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Use CDP to set exact viewport dimensions (1920×1080)
        # set_window_size sets the outer window, not the viewport
        cls.browser.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
            'width': 1920,
            'height': 1080,
            'deviceScaleFactor': 1,
            'mobile': False,
        })

    def test_no_vertical_scroll_on_1080p(self):
        """The landing page should not scroll vertically on a 1920×1080 display."""
        self.browser.get(self.live_server_url)

        # Wait for the page to fully load
        WebDriverWait(self.browser, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "hub-sections"))
        )

        # Wait for all tile icons to finish loading
        WebDriverWait(self.browser, 20).until(
            lambda d: d.execute_script("""
                var imgs = document.querySelectorAll('.hub-tile img');
                return imgs.length > 0 && Array.from(imgs).every(
                    function(img) { return img.complete && img.naturalHeight > 0; }
                );
            """)
        )

        # Check that body content does not exceed viewport height.
        # Note: we check document.body.scrollHeight, NOT
        # document.documentElement.scrollHeight — the landing page sets
        # overflow-x:hidden on body which (per CSS spec) computes
        # overflow-y to 'auto', making body the scroll container.
        body_scroll_height = self.browser.execute_script("return document.body.scrollHeight")
        viewport_height = self.browser.execute_script("return window.innerHeight")

        self.assertLessEqual(
            body_scroll_height, viewport_height,
            f"Page scrolls vertically: body scrollHeight ({body_scroll_height}px) > "
            f"viewport height ({viewport_height}px). "
            f"Content overflows by {body_scroll_height - viewport_height}px."
        )


@tag('selenium')
class LandingPageSectionNavTest(SeleniumTestCase):
    """The section selector only shows when the sections don't all fit on screen."""

    def _nav_state(self, width):
        self.browser.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
            'width': width, 'height': 1080, 'deviceScaleFactor': 1, 'mobile': False,
        })
        self.browser.get(self.live_server_url)
        WebDriverWait(self.browser, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "hub-sections"))
        )
        return self.browser.execute_script("""
            var view = document.getElementById('hub-view');
            return [document.getElementById('hub-nav').hidden,
                    view.scrollWidth > view.clientWidth + 4,
                    document.querySelectorAll('.hub-pane').length];
        """)

    def tearDown(self):
        self.browser.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
        super().tearDown()

    def test_selector_hidden_when_everything_fits(self):
        hidden, overflows, panes = self._nav_state(12000)
        self.assertGreater(panes, 1)
        self.assertFalse(overflows)
        self.assertTrue(hidden)

    def test_selector_shown_when_sections_scroll(self):
        # Narrowest panorama layout; at <=1100px the sections stack vertically.
        hidden, overflows, _ = self._nav_state(1200)
        self.assertTrue(overflows)
        self.assertFalse(hidden)


@tag('selenium')
class LandingPageTileFitTest(SeleniumTestCase):
    """Tile icons and titles stay inside their tiles on kiosk and laptop sizes."""

    SIZES = [(1920, 1080), (1440, 900), (1366, 768), (1280, 720)]

    def _overflows(self):
        return self.browser.execute_script("""
            var bad = [];
            document.querySelectorAll('.hub-tile').forEach(function (tile) {
                var t = tile.getBoundingClientRect();
                var name = tile.querySelector('.hub-tile-title').textContent.trim();
                tile.querySelectorAll('img, .hub-tile-title, .hub-tile-sub').forEach(function (el) {
                    if (getComputedStyle(el).display === 'none') return;
                    var r = el.getBoundingClientRect();
                    if (r.left < t.left - 1 || r.right > t.right + 1 ||
                        r.top < t.top - 1 || r.bottom > t.bottom + 1) {
                        bad.push(name + ': ' + el.className + ' outside tile');
                    }
                });
                var title = tile.querySelector('.hub-tile-title');
                if (title.scrollWidth > title.clientWidth + 1) bad.push(name + ': title too wide');
            });
            return bad;
        """)

    def test_tiles_fit(self):
        for width, height in self.SIZES:
            with self.subTest(size=f'{width}x{height}'):
                self.browser.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
                    'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False,
                })
                self.browser.get(self.live_server_url)
                WebDriverWait(self.browser, 20).until(
                    EC.presence_of_element_located((By.CLASS_NAME, 'hub-tile'))
                )
                wait_for_paint(self.browser)
                self.assertEqual(self._overflows(), [])
                self.assertLessEqual(
                    self.browser.execute_script('return document.body.scrollHeight'),
                    self.browser.execute_script('return window.innerHeight'),
                )


@tag('selenium')
class WeatherUnitToggleTest(SeleniumTestCase):
    TOGGLE = (By.CLASS_NAME, 'toggle-button')

    def setUp(self):
        super().setUp()
        self.browser.get('about:blank')
        self.browser.delete_all_cookies()
        self.browser.get(self.live_server_url)
        WebDriverWait(self.browser, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'temperature'))
        )
        wait_for_paint(self.browser)

    def _set(self, cls, metric, text):
        """Give the first reading of class ``cls`` a known metric value."""
        self.browser.execute_script(
            'var e = document.querySelector("." + arguments[0]);'
            'e.setAttribute("data-metric", arguments[1]);'
            'e.textContent = arguments[2];',
            cls, metric, text,
        )

    def _toggle(self, unit):
        """Click the unit toggle until it reports ``unit`` (C or F)."""
        click_until(
            self.browser, self.TOGGLE,
            lambda d: d.find_element(*self.TOGGLE).get_attribute('data-unit') == unit,
        )

    def _text(self, cls):
        return self.browser.find_element(By.CLASS_NAME, cls).text

    def test_temperature_non_number(self):
        self._set('temperature', 'N/A', 'N/A°C')
        self._toggle('F')
        self.assertEqual(self._text('temperature'), 'N/A°C')
        self._toggle('C')
        self.assertEqual(self._text('temperature'), 'N/A°C')

    def test_temperature_missing(self):
        self._set('temperature', '', '°C')
        self._toggle('F')
        self.assertEqual(self._text('temperature'), '°C')
        self._toggle('C')
        self.assertEqual(self._text('temperature'), '°C')

    def test_temperature_conversion_c_to_f(self):
        self._set('temperature', '25', '25°C')
        self._toggle('F')
        self.assertEqual(self._text('temperature'), '77°F')  # 25°C -> 77°F
        self._toggle('C')
        self.assertEqual(self._text('temperature'), '25°C')

    def test_elevation_conversion_m_to_ft(self):
        self._set('elevation', '1000', '1000 m')
        self._toggle('F')
        self.assertEqual(self._text('elevation'), '3,281 ft')  # 1000 meters -> 3281 feet
        self._toggle('C')
        self.assertEqual(self._text('elevation'), '1,000 m')

@tag('selenium')
class NavbarLoginButtonTest(SeleniumTestCase):
    """Test that the login button is visible to unauthenticated users."""

    def test_login_button_visible_when_not_authenticated(self):
        """Login icon should be visible in the navbar for anonymous visitors.

        Checks both DOM visibility and that the icon's computed colour
        is light enough to be seen on the dark navbar (luminance > 128).
        Without an explicit colour rule, .nav-link inherits the body
        text colour which is near-black on pages that don't override it.
        """
        self.browser.get(self.live_server_url)
        login_btn = WebDriverWait(self.browser, 20).until(
            EC.visibility_of_element_located((By.ID, 'login-button'))
        )
        self.assertTrue(login_btn.is_displayed())

        # The icon inside the link must render with a light colour
        # so it's actually visible on the dark navbar background.
        icon = login_btn.find_element(By.TAG_NAME, 'i')
        rgba = self.browser.execute_script(
            "return window.getComputedStyle(arguments[0]).color;", icon
        )
        # Parse "rgb(r, g, b)" or "rgba(r, g, b, a)"
        parts = [int(x) for x in rgba.replace('rgba', '').replace('rgb', '')
                 .strip('() ').split(',')[:3]]
        luminance = 0.299 * parts[0] + 0.587 * parts[1] + 0.114 * parts[2]
        self.assertGreater(
            luminance, 128,
            f"Login icon colour {rgba} is too dark to see on the navbar"
        )


@tag('selenium')
class FeedbackModalTest(SeleniumTestCase):
    BADGE = (By.CSS_SELECTOR, '#user-menu-button .badge')

    def setUp(self):
        super().setUp()
        # Per test: TransactionTestCase flushes the database after each one.
        User.objects.create_user(username='testuser', password='testpassword', is_staff=True)
        self.browser.get('about:blank')
        self.browser.delete_all_cookies()

    def test_feedback_modal_submission_and_unread_count(self):
        browser = self.browser
        wait = WebDriverWait(browser, 20)
        login_via_browser(browser, self.live_server_url)
        # No feedback yet, so the server renders no unread badge.
        self.assertFalse(browser.find_elements(*self.BADGE))

        browser.execute_script("""
            window.__fb = {opening: false, shown: false, sent: false};
            var modal = document.getElementById('feedback-modal');
            modal.addEventListener('show.bs.modal', function () { window.__fb.opening = true; });
            modal.addEventListener('shown.bs.modal', function () { window.__fb.shown = true; });
            document.getElementById('feedback-form').addEventListener(
                'submit', function () { window.__fb.sent = true; });
        """)
        click_until(browser, (By.ID, 'feedback-button'),
                    lambda d: d.execute_script('return window.__fb.opening'))
        wait.until(lambda d: d.execute_script('return window.__fb.shown'))

        message = 'This is a test feedback message.'
        type_into(browser, (By.ID, 'message'), message)
        click_until(browser, (By.CSS_SELECTOR, '#feedback-form .fb-send'),
                    lambda d: d.execute_script('return window.__fb.sent'))

        wait.until(EC.visibility_of_element_located((By.ID, 'feedback-success')))
        self.assertIn('Thank you for your feedback!',
                      browser.find_element(By.ID, 'feedback-success').text)
        feedback = Feedback.objects.get()
        self.assertEqual(feedback.message, message)
        self.assertFalse(feedback.is_read)

        # The modal closes itself 2s after a successful send.
        wait.until(EC.invisibility_of_element_located((By.ID, 'feedback-modal')))
        # A successful send refreshes the badge without waiting for the poll.
        wait.until(lambda d: [b.text for b in d.find_elements(*self.BADGE)] == ['1'])


@tag('selenium')
class OnScreenKeyboardTest(SeleniumTestCase):
    """The hub-screen keyboard types into fields, moves on with Next and closes."""

    KB_OPEN = (By.CSS_SELECTOR, '.hub-kb.open')

    def load_login(self, kb):
        browser = self.browser
        browser.get(f'{self.live_server_url}/accounts/login/')
        if kb is None:
            browser.execute_script("localStorage.removeItem('hub-kb')")
        else:
            browser.execute_script("localStorage.setItem('hub-kb', arguments[0])", kb)
        self.addCleanup(browser.execute_script, "localStorage.removeItem('hub-kb')")
        browser.refresh()
        wait_for_paint(browser)

    def wait_open(self):
        # .open is visible to Selenium as soon as it's added, but the keyboard
        # is still sliding up from off-screen; wait until it's fully in view.
        WebDriverWait(self.browser, 10).until(lambda d: d.execute_script(
            "const k = document.querySelector('.hub-kb.open');"
            "return !!k && k.getBoundingClientRect().bottom <= window.innerHeight + 1;"))

    def tap(self, char):
        locator = (By.CSS_SELECTOR, f'.hub-kb-key[data-c="{char}"]')
        WebDriverWait(self.browser, 10).until(EC.element_to_be_clickable(locator)).click()

    def test_types_into_fields(self):
        browser = self.browser
        self.load_login('on')
        wait = WebDriverWait(browser, 10)
        browser.find_element(By.ID, 'id_username').click()
        self.wait_open()
        username = browser.find_element(By.ID, 'id_username')
        self.assertEqual(username.get_attribute('inputmode'), 'none')

        for ch in 'abc':
            self.tap(ch)
        self.assertEqual(username.get_attribute('value'), 'abc')
        self.assertEqual(browser.switch_to.active_element.get_attribute('id'), 'id_username')

        go = browser.find_element(By.CSS_SELECTOR, '.hub-kb-key.go')
        self.assertEqual(go.text, 'Next')
        go.click()
        wait.until(lambda d: d.switch_to.active_element.get_attribute('id') == 'id_password')
        wait.until(lambda d: d.find_element(By.CSS_SELECTOR, '.hub-kb-key.go').text == 'Sign in')
        self.assertTrue(browser.find_element(By.CSS_SELECTOR, '.hub-kb-show').is_displayed())

        self.tap('x')
        self.assertEqual(browser.find_element(By.ID, 'id_password').get_attribute('value'), 'x')

        # Tapping outside the field and keyboard closes it.
        browser.find_element(By.CSS_SELECTOR, '.login-sub').click()
        wait.until(EC.invisibility_of_element_located(self.KB_OPEN))

    def test_hide_button_closes(self):
        browser = self.browser
        self.load_login('on')
        browser.find_element(By.ID, 'id_username').click()
        wait = WebDriverWait(browser, 10)
        self.wait_open()
        kb_h = "return getComputedStyle(document.documentElement).getPropertyValue('--hub-kb-h')"
        wait.until(lambda d: d.execute_script(kb_h))
        self.assertEqual(browser.execute_script(kb_h),
                         browser.execute_script("return document.querySelector('.hub-kb').offsetHeight + 'px'"))
        browser.find_element(By.CSS_SELECTOR, '.hub-kb-hide').click()
        wait.until(EC.invisibility_of_element_located(self.KB_OPEN))
        self.assertEqual(browser.execute_script(kb_h), '')

    def test_off_on_desktop(self):
        # Headless Chrome has a mouse (hover), so it isn't treated as the hub screen.
        browser = self.browser
        self.load_login(None)
        browser.find_element(By.ID, 'id_username').click()
        self.assertEqual(browser.find_elements(By.CSS_SELECTOR, '.hub-kb'), [])
        self.assertNotEqual(browser.find_element(By.ID, 'id_username').get_attribute('inputmode'), 'none')