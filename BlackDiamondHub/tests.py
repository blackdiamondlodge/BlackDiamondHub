from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.contrib.auth.models import User
from django.test import TestCase, Client, tag
from django.urls import reverse
from tests.selenium_helpers import get_chrome_options, login_via_browser, wait_for_network_idle

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
class LandingPageNoScrollTest(StaticLiveServerTestCase):
    """Ensure the landing page fits within the viewport on a 1920×1080 display."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.browser = webdriver.Chrome(options=get_chrome_options())
        # Use CDP to set exact viewport dimensions (1920×1080)
        # set_window_size sets the outer window, not the viewport
        cls.browser.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
            'width': 1920,
            'height': 1080,
            'deviceScaleFactor': 1,
            'mobile': False,
        })

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        super().tearDownClass()

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
class WeatherUnitToggleTest(StaticLiveServerTestCase):
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
        # Reset browser state between tests
        self.browser.get('about:blank')
        self.browser.delete_all_cookies()

    def test_temperature_non_number(self):
        self.browser.get(self.live_server_url)
        
        toggle_button = WebDriverWait(self.browser, 20).until(
            EC.visibility_of_element_located((By.CLASS_NAME, 'toggle-button'))
        )
        WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.CLASS_NAME, 'toggle-button'))
        )        
        
        self.browser.execute_script('''
            document.querySelector(".temperature").setAttribute("data-metric", "N/A");
            document.querySelector(".temperature").textContent = "N/A°C";
        ''')
        
        #self.browser.save_screenshot('screenshot.png')
        
        toggle_button.click()
        
        temperature_text = self.browser.find_element(By.CLASS_NAME, "temperature").text
        self.assertEqual(temperature_text, "N/A°C")
        toggle_button.click()
        temperature_text = self.browser.find_element(By.CLASS_NAME, "temperature").text
        self.assertEqual(temperature_text, "N/A°C")

    def test_temperature_missing(self):
        self.browser.get(self.live_server_url)
        WebDriverWait(self.browser, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'temperature'))
        )
        self.browser.execute_script('''
            document.querySelector(".temperature").setAttribute("data-metric", "");
            document.querySelector(".temperature").textContent = "°C";
        ''')
        toggle_button = self.browser.find_element(By.CLASS_NAME, "toggle-button")
        toggle_button.click()
        temperature_text = self.browser.find_element(By.CLASS_NAME, "temperature").text
        self.assertEqual(temperature_text, "°C")
        toggle_button.click()
        temperature_text = self.browser.find_element(By.CLASS_NAME, "temperature").text
        self.assertEqual(temperature_text, "°C")

    def test_temperature_conversion_c_to_f(self):
        self.browser.get(self.live_server_url)
        WebDriverWait(self.browser, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'temperature'))
        )
        self.browser.execute_script('''
            document.querySelector(".temperature").setAttribute("data-metric", "25");
            document.querySelector(".temperature").textContent = "25°C";
        ''')
        toggle_button = self.browser.find_element(By.CLASS_NAME, "toggle-button")
        toggle_button.click()
        temperature_text = self.browser.find_element(By.CLASS_NAME, "temperature").text
        self.assertEqual(temperature_text, "77°F")  # 25°C -> 77°F
        toggle_button.click()
        temperature_text = self.browser.find_element(By.CLASS_NAME, "temperature").text
        self.assertEqual(temperature_text, "25°C")

    def test_elevation_conversion_m_to_ft(self):
        self.browser.get(self.live_server_url)
        WebDriverWait(self.browser, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'elevation'))
        )
        self.browser.execute_script('''
            document.querySelector(".elevation").setAttribute("data-metric", "1000");
            document.querySelector(".elevation").textContent = "1000 m";
        ''')
        toggle_button = self.browser.find_element(By.CLASS_NAME, "toggle-button")
        toggle_button.click()
        elevation_text = self.browser.find_element(By.CLASS_NAME, "elevation").text
        self.assertEqual(elevation_text, "3281 ft")  # 1000 meters -> 3281 feet
        toggle_button.click()
        elevation_text = self.browser.find_element(By.CLASS_NAME, "elevation").text
        self.assertEqual(elevation_text, "1000 m")

@tag('selenium')
class NavbarLoginButtonTest(StaticLiveServerTestCase):
    """Test that the login button is visible to unauthenticated users."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.browser = webdriver.Chrome(options=get_chrome_options())
        cls.browser.set_window_size(1920, 1080)

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        super().tearDownClass()

    def test_login_button_visible_when_not_authenticated(self):
        """Login icon should be visible in the navbar for anonymous visitors.

        Checks both DOM visibility and that the icon's computed colour
        is light enough to be seen on the dark navbar (luminance > 128).
        Without an explicit colour rule, .nav-link inherits the body
        text colour which is near-black on pages that don't override it.
        """
        self.browser.get(self.live_server_url)
        login_btn = WebDriverWait(self.browser, 10).until(
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
class FeedbackModalTest(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.browser = webdriver.Chrome(options=get_chrome_options())
        cls.browser.set_window_size(1920, 1080)
        
        # Create a test user
        cls.test_user = User.objects.create_user(username='testuser', password='testpassword', is_staff=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        super().tearDownClass()

    def setUp(self):
        # Reset browser state between tests
        self.browser.get('about:blank')
        self.browser.delete_all_cookies()

    def test_feedback_modal_submission_and_unread_count(self):
        # Log in using shared helper
        login_via_browser(self.browser, self.live_server_url)

        # Wait for the login to complete and redirect to the home page
        WebDriverWait(self.browser, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "feedback-button"))
        )
        
        # Capture the current unread message count
        try:
            unread_count_element = self.browser.find_element(By.CLASS_NAME, "badge")
            initial_unread_count = int(unread_count_element.text)
        except Exception:
            initial_unread_count = 0

        # Open the feedback modal
        feedback_button = WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "feedback-button"))
        )
        feedback_button.click()

        # Wait for the modal to be visible
        WebDriverWait(self.browser, 20).until(
            EC.visibility_of_element_located((By.ID, "feedback-modal"))
        )

        # Wait for the form elements to be interactive
        name_input = WebDriverWait(self.browser, 20).until(
            EC.element_to_be_clickable((By.ID, "name"))
        )
        email_input = self.browser.find_element(By.ID, "email")
        message_input = self.browser.find_element(By.ID, "message")

        name_input.send_keys("Test User")
        email_input.send_keys("testuser@example.com")
        message_input.send_keys("This is a test feedback message.")

        # Submit the feedback form via JavaScript to ensure the submit event fires
        self.browser.execute_script("""
            var form = document.getElementById('feedback-form');
            form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        """)

        # Wait for network requests to complete
        wait_for_network_idle(self.browser)

        # Wait for the success message to be visible
        WebDriverWait(self.browser, 30).until(
            EC.visibility_of_element_located((By.ID, "feedback-success"))
        )

        # Check that the success message is displayed
        success_message = self.browser.find_element(By.ID, "feedback-success").text
        self.assertIn("Thank you for your feedback!", success_message)

        # Wait for the modal to close after a delay (JS has 2s setTimeout)
        WebDriverWait(self.browser, 30).until(
            EC.invisibility_of_element((By.ID, "feedback-modal"))
        )

        # Check if the unread message count increased
        WebDriverWait(self.browser, 30).until(
            EC.text_to_be_present_in_element((By.CLASS_NAME, "badge"), str(initial_unread_count + 1))
        )

        # Verify the unread count increased by 1
        new_unread_count_element = self.browser.find_element(By.CLASS_NAME, "badge")
        new_unread_count = int(new_unread_count_element.text)
        self.assertEqual(new_unread_count, initial_unread_count + 1)