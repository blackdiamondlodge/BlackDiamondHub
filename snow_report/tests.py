import os
from unittest.mock import patch
import requests
from django.test import TestCase, tag
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from snow_report.views import parse_weather_html, sanitize_number, convert_celsius_to_fahrenheit, convert_cm_to_inches, convert_meters_to_feet, convert_kph_to_mph


class SanitizeNumberTests(TestCase):
    """Tests for sanitize_number and conversion functions handling malformed input."""

    def test_double_dash_negative(self):
        """'--7' from the website should be treated as -7."""
        self.assertEqual(sanitize_number('--7'), -7.0)

    def test_normal_negative(self):
        self.assertEqual(sanitize_number('-7'), -7.0)

    def test_normal_positive(self):
        self.assertEqual(sanitize_number('15'), 15.0)

    def test_empty_string(self):
        self.assertIsNone(sanitize_number(''))

    def test_none(self):
        self.assertIsNone(sanitize_number(None))

    def test_na_string(self):
        self.assertIsNone(sanitize_number('N/A'))

    def test_dash_only(self):
        self.assertIsNone(sanitize_number('-'))

    def test_double_dash_only(self):
        self.assertIsNone(sanitize_number('--'))

    def test_decimal(self):
        self.assertEqual(sanitize_number('3.5'), 3.5)

    def test_celsius_to_fahrenheit_double_dash(self):
        """'--7' should convert as -7°C → 19°F."""
        self.assertEqual(convert_celsius_to_fahrenheit('--7'), 19)

    def test_celsius_to_fahrenheit_normal(self):
        self.assertEqual(convert_celsius_to_fahrenheit('-7'), 19)

    def test_celsius_to_fahrenheit_none(self):
        self.assertIsNone(convert_celsius_to_fahrenheit(None))

    def test_celsius_to_fahrenheit_na(self):
        self.assertIsNone(convert_celsius_to_fahrenheit('N/A'))

    def test_cm_to_inches_double_dash(self):
        self.assertEqual(convert_cm_to_inches('--10'), -4)

    def test_meters_to_feet_normal(self):
        self.assertEqual(convert_meters_to_feet('1000'), 3281)

    def test_kph_to_mph_normal(self):
        self.assertEqual(convert_kph_to_mph('100'), 62)
from tests.selenium_helpers import get_chrome_options

class LiveParseWeatherHtmlTests(TestCase):
    def parse_weather_html_live_data_and_test(self, units=""):
        url = "https://www.sunpeaksresort.com/ski-ride/weather-conditions-cams/weather-snow-report"
        response = requests.get(url)
        html_content = response.content

        weather_data_metric = parse_weather_html(html_content, units)
        self.assertIsNotNone(weather_data_metric)

        # Ensure today_icon is mapped correctly (may be empty when
        # Sun Peaks removes the current-condition section seasonally)
        today_icon = weather_data_metric["today_icon"]
        if today_icon:
            self.assertNotEqual(today_icon, "fas fa-question-circle", f"today_icon is set to unknown value {today_icon}")

        # today_description may be empty when the current-condition
        # section is absent from the page (e.g. off-season)
        today_description = weather_data_metric["today_description"]

        ##########################
        ## Temperatures
        ##########################
        temperatures = weather_data_metric["temperatures"]
        self.assertEqual(len(temperatures), 4, f"Expected 4 temperature readings but found {len(temperatures)}")

        for temp in temperatures:
            self.assertNotEqual(temp["location"], "", f"Temperature location for {temp['location']} is empty")
            self.assertNotEqual(temp["elevation"], "", f"Temperature elevation for {temp['location']} is empty")

            try:
                temp_value = int(temp["elevation"])
                self.assertGreaterEqual(temp_value, 1000, f"Elevation of {temp['elevation']} for {temp['location']} is less than 1000")
                self.assertLessEqual(temp_value, 10000, f"Elevation of {temp['elevation']} for {temp['location']} is greater than 10000")
            except ValueError:
                self.fail(f"Elevation value for {temp['location']} is not a valid integer: {temp['elevation']}")

        expected_unit = "ft" if units == "imperial" else "m"
        for temp in temperatures:
            self.assertEqual(temp["elevation_unit"], expected_unit, f"Elevation unit for {temp['location']} is {temp['elevation_unit']} - expected: {expected_unit}")

        for temp in temperatures:
            self.assertNotEqual(temp["value"], "", f"Temperature value for {temp['location']} is empty")

            try:
                temp_value = int(temp["value"])
                self.assertGreaterEqual(temp_value, -50, f"Temperature of {temp['value']} for {temp['location']} is less than -50")
                self.assertLessEqual(temp_value, 110, f"Temperature of {temp['value']} for {temp['location']} is greater than 110")
            except ValueError:
                self.fail(f"Temperature value for {temp['location']} is not a valid integer: {temp['value']}")

        expected_unit = "°F" if units == "imperial" else "°C"
        for temp in temperatures:
            self.assertEqual(temp["unit"], expected_unit, f"Temperature unit for {temp['location']} is {temp['unit']} - expected: {expected_unit}")

        ##########################
        ## Snow Conditions
        ## (may be empty off-season when Sun Peaks removes the
        ## snow-conditions section from the page)
        ##########################
        snow_conditions = weather_data_metric["snow_conditions"]
        if len(snow_conditions) > 0:
            self.assertEqual(len(snow_conditions), 4, f"Expected 4 snow conditions but found: {len(snow_conditions)}")

            for snow in snow_conditions:
                self.assertNotEqual(snow["period"], "", f"Snow condition period for {snow['period']} is empty")
                self.assertNotEqual(snow["value"], "", f"Snow condition value for {snow['period']} is empty")

            expected_unit = "in" if units == "imperial" else "cm"
            for snow in snow_conditions:
                self.assertEqual(snow["unit"], expected_unit, f"Snow condition unit for {snow['period']} is {snow['unit']} - expected: {expected_unit}")

        ##########################
        ## Wind Speeds
        ## (may be empty off-season)
        ##########################
        wind_speeds = weather_data_metric["wind_speeds"]
        if len(wind_speeds) > 0:
            self.assertEqual(len(wind_speeds), 3, f"Expected 3 wind speeds but found {len(wind_speeds)}")

            for wind in wind_speeds:
                self.assertNotEqual(wind["location"], "", f"Wind speed location for {wind['location']} is empty")
                self.assertNotEqual(wind["elevation"], "", f"Wind speed elevation for {wind['location']} is empty")

                try:
                    temp_value = int(wind["elevation"])
                    self.assertGreaterEqual(temp_value, 1000, f"Elevation of {wind['elevation']} for {wind['location']} is less than 1000")
                    self.assertLessEqual(temp_value, 10000, f"Elevation of {wind['elevation']} for {wind['location']} is greater than 10000")
                except ValueError:
                    self.fail(f"Elevation value for {wind['location']} is not a valid integer: {wind['elevation']}")

            for wind in wind_speeds:
                self.assertNotEqual(wind["speed_direction"], "", f"Wind speed direction for {wind['location']} is empty")
                self.assertNotEqual(wind["speed_average"], "", f"Wind speed average for {wind['location']} is empty")

                try:
                    temp_value = int(wind["speed_average"])
                    self.assertGreaterEqual(temp_value, 0, f"Wind speed of {wind['speed_average']} for {wind['location']} is less than 0")
                    self.assertLessEqual(temp_value, 150, f"Wind speed of {wind['speed_average']} for {wind['location']} is greater than 150")
                except ValueError:
                    self.fail(f"Wind speed value for {wind['location']} is not a valid integer: {wind['speed_average']}")

            expected_unit = "mph" if units == "imperial" else "kph"
            for wind in wind_speeds:
                self.assertEqual(wind["speed_unit"], expected_unit, f"Wind speed unit for {wind['location']} is {wind['speed_unit']} - expected: {expected_unit}")

        ##########################
        ## Forecast
        ## (may be empty off-season)
        ##########################
        forecast = weather_data_metric["forecast"]
        if len(forecast) > 0:
            self.assertEqual(len(forecast), 6, f"Expected 6 forecast items but found {len(forecast)}")

            for day in forecast:
                self.assertNotEqual(day["day_name"], "", f"Forecast day name for {day['day_name']} is empty")
                self.assertTrue(day["day_name"].startswith(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")), f"Forecast day name for {day['day_name']} is not a valid day of the week")
                self.assertNotEqual(day["icon"], "", f"Forecast icon for {day['day_name']} is empty")
                self.assertNotEqual(day["icon"], "fas fa-question-circle", f"Forecast icon for {day['day_name']} is set to an unknown icon (check mapping)")
                self.assertNotEqual(day["description"], "", f"Forecast description for {day['day_name']} is empty")

            expected_unit = "°F" if units == "imperial" else "°C"
            for day in forecast:
                self.assertEqual(day["temp_unit"], expected_unit, f"Forecast temp unit for {day['day_name']} is {day['temp_unit']} - expected: {expected_unit}")

    def test_parse_weather_html_live_data_imperial(self):
        self.parse_weather_html_live_data_and_test("imperial")

    def test_parse_weather_html_live_data_metric(self):
        self.parse_weather_html_live_data_and_test("metric")

    def test_parse_weather_html_live_data_empty(self):
        self.parse_weather_html_live_data_and_test("")

    def test_parse_weather_html_live_data_invalid_unit(self):
        self.parse_weather_html_live_data_and_test("invalid_unit")

                    
class OfflineParseWeatherHtmlTests(TestCase):
    def test_parse_weather_html_bad_data(self):
        # Load the sample bad data HTML file
        file_path = os.path.join(os.path.dirname(__file__), 'tests', 'weather_bad_data.html')
        with open(file_path, 'r', encoding='utf-8') as file:
            html_content = file.read()

        weather_data_metric = parse_weather_html(html_content, "metric")        
        #the 24hr value for snow_conditions should be empty
        #loop through the snow_conditions list and find where period == "24 hr"
        found = False
        for snow in weather_data_metric["snow_conditions"]:
          print(snow)
          if snow["period"] == "24 Hr":
              self.assertEqual(snow["value"], "N/A", f"24 hr snow condition should be empty but found: {snow['value']}")
              found = True
              break
              
        self.assertTrue(found, "Did not find 24 hr snow condition in the list")

    def test_parse_weather_html_ignores_air_quality(self):
        """Ensure the parser only returns temperature entries and ignores
        the air-quality ul.list-temps section added to the page."""
        file_path = os.path.join(os.path.dirname(__file__), 'tests', 'weather_current.html')
        with open(file_path, 'r', encoding='utf-8') as file:
            html_content = file.read()

        weather_data = parse_weather_html(html_content, "metric")
        self.assertIsNotNone(weather_data)

        temperatures = weather_data["temperatures"]
        self.assertEqual(len(temperatures), 4,
                         f"Expected 4 temperature entries (air quality should be excluded), got {len(temperatures)}")

        expected_locations = {"Top of the World", "Mid-mountain", "Top of Morrisey", "Valley"}
        actual_locations = {t["location"] for t in temperatures}
        self.assertEqual(actual_locations, expected_locations,
                         f"Unexpected locations: {actual_locations}")

        # Air quality stations should NOT appear in temperatures
        for temp in temperatures:
            self.assertNotIn("AQHI", str(temp),
                             f"Air quality data leaked into temperatures: {temp}")


@tag('selenium')
class SnowReportScrollHintTest(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.browser = webdriver.Chrome(options=get_chrome_options())
        cls.browser.set_window_size(1920, 1080)

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        super().tearDownClass()

    def test_scroll_hint_hides_at_bottom(self):
        """Scroll hint should disappear when the user scrolls to the bottom."""
        self.browser.get(f'{self.live_server_url}/snow_report/')

        # Wait for scroll hint to be visible
        scroll_hint = WebDriverWait(self.browser, 10).until(
            EC.visibility_of_element_located((By.ID, 'scroll-hint'))
        )
        self.assertTrue(scroll_hint.is_displayed(), "Scroll hint should be visible initially")

        # Scroll the sentinel element into view to trigger IntersectionObserver
        self.browser.execute_script(
            "document.getElementById('scroll-sentinel').scrollIntoView();"
        )

        # Wait for the 'hidden' class to appear on the scroll hint
        WebDriverWait(self.browser, 5).until(
            lambda driver: 'hidden' in driver.find_element(By.ID, 'scroll-hint').get_attribute('class'),
            "Scroll hint should have 'hidden' class after scrolling to bottom"
        )

class HomepageHookTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    @patch("snow_report.homepage.fetch_weather_html", return_value=b"")
    @patch("snow_report.homepage.parse_weather_html")
    def test_status_uses_first_snow_amount(self, mock_parse, _fetch):
        mock_parse.return_value = {"today_description": "Sunny", "snow_conditions": [
            {"period": "New Snow", "value": "N/A"}, {"period": "24 Hr", "value": "14"},
        ]}
        from snow_report.homepage import status
        result = status()
        self.assertEqual((result.text, result.level), ("14 cm in 24 hr", "on"))