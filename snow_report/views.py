from django.shortcuts import render
from bs4 import BeautifulSoup
import requests
import re

# Conversion Functions
def sanitize_number(value):
    """Clean malformed numeric strings from the source website (e.g. '--7' → '-7', 'N/A' → None)."""
    if not value:
        return None
    # Keep only digits, minus sign, and decimal point
    cleaned = re.sub(r'[^\d.\-]', '', str(value))
    # Collapse multiple minus signs into one (e.g. '--7' → '-7')
    cleaned = re.sub(r'-+', '-', cleaned)
    if not cleaned or cleaned == '-':
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None

def convert_celsius_to_fahrenheit(celsius):
    """Convert Celsius to Fahrenheit."""
    val = sanitize_number(celsius)
    return round((val * 9/5) + 32) if val is not None else None

def convert_meters_to_feet(meters):
    """Convert meters to feet."""
    val = sanitize_number(meters)
    return round(val * 3.28084) if val is not None else None

def convert_cm_to_inches(cm):
    """Convert cm to inches."""
    val = sanitize_number(cm)
    return round(val * 0.393701) if val is not None else None

def convert_kph_to_mph(kph):
    """Convert kilometers per hour to miles per hour."""
    val = sanitize_number(kph)
    return round(val * 0.621371) if val is not None else None

# Main View
SNOW_REPORT_URL = "https://www.sunpeaksresort.com/ski-ride/weather-conditions-cams/weather-snow-report"


def fetch_weather_html():
    response = requests.get(SNOW_REPORT_URL, timeout=15)
    return response.content


def snow_report(request):
    """Handles the snow report and allows unit switching via query parameter."""
    units = request.GET.get("units", "metric")  # Default to metric

    html_content = fetch_weather_html()

    weather_data = parse_weather_html(html_content, units)

    return render(request, "snow_report/snow_report.html", weather_data)

# Data Extraction & Parsing
def parse_weather_html(html, units):
    """Parses HTML and converts values based on the selected unit system."""
    soup = BeautifulSoup(html, "html.parser")

    # Extract today's weather
    today_weather = soup.find("div", class_="current-condition")
    sunpeaks_today_icon = today_weather.find("span", class_="icon")["class"][1] if today_weather else ""
    today_icon = map_weather_icon(sunpeaks_today_icon) if sunpeaks_today_icon else ""
    today_description = today_weather.find("p", class_="today-description").text.strip() if today_weather else ""

    # Extract temperatures
    temperatures = []
    current_temps_section = soup.find("div", class_="half current-temps")
    if current_temps_section:
        for temp in current_temps_section.select("ul.list-temps li"):
            location = temp.find("h3").text.strip() if temp.find("h3") else ""
            elevation_text = temp.find("p").text.strip() if temp.find("p") else ""
            elevation = re.sub(r"[^\d]", "", elevation_text) if elevation_text else ""
            value_span = temp.select_one("span.value_switch.value_deg")
            value = value_span.text.strip() if value_span else ""

            if units == "imperial":
                value = convert_celsius_to_fahrenheit(value) if value else ""
                elevation = convert_meters_to_feet(elevation) if elevation else ""
                temp_unit = "°F"
                elevation_unit = "ft"
            else:
                temp_unit = "°C"
                elevation_unit = "m"

            temperatures.append({
                "location": location,
                "elevation": elevation,
                "elevation_unit": elevation_unit,
                "value": value,
                "unit": temp_unit,
            })

    # Extract snow conditions
    snow_conditions = []
    for snow in soup.select("div#snow-conditions ul.list-snow:not(.snow-base) li"):
        period = snow.find("h4").text.strip() if snow.find("h4") else ""
        period = period.replace(" *", "")
        value_span = snow.find("span", class_="value_switch")
        value = value_span.text.strip() if value_span else "N/A"

        if units == "imperial":
            value = convert_cm_to_inches(value) if value != "N/A" else "N/A"
            snow_unit = "in"
        else:
            snow_unit = "cm"

        snow_conditions.append({
            "period": period,
            "value": value,
            "unit": snow_unit,
        })

    # Extract base snow conditions
    base_snow_conditions = []
    for base_snow in soup.select("ul.list-snow.snow-base li"):
        h4_element = base_snow.find("h4")
        if not h4_element or not h4_element.text.strip():
            continue
        period = h4_element.text.strip()
        value_span = base_snow.find("span", class_="value_switch")
        value = value_span.text.strip() if value_span else ""

        if units == "imperial":
            value = convert_cm_to_inches(value) if value else ""
            unit = "in"
        else:
            unit = "cm"

        base_snow_conditions.append({
            "period": period,
            "value": value,
            "unit": unit,
        })

    # Extract wind speeds
    wind_speeds = []
    for wind in soup.find_all("div", class_="wind"):
        location = wind.find("h3").text.strip() if wind.find("h3") else ""
        elevation_text = wind.find("p").text.strip() if wind.find("p") else ""
        elevation = re.sub(r"[^\d]", "", elevation_text) if elevation_text else ""
        speed_direction = wind.select_one("div.weather-value").text.strip() if wind.select_one("div.weather-value") else ""
        average_span = wind.select_one("span.value_switch.value_kph")
        speed_average = average_span.text.strip() if average_span else ""

        if units == "imperial":
            elevation = convert_meters_to_feet(elevation) if elevation else ""
            speed_average = convert_kph_to_mph(speed_average) if speed_average else ""
            elevation_unit = "ft"
            speed_unit = "mph"
        else:
            elevation_unit = "m"
            speed_unit = "kph"

        wind_speeds.append({
            "location": location,
            "elevation": elevation,
            "elevation_unit": elevation_unit,
            "speed_direction": speed_direction,
            "speed_average": speed_average,
            "speed_unit": speed_unit,
        })

    # Extract 5-day forecast
    forecast = []
    for day in soup.select("div#forecast div.third"):
        day_name = day.find("h4").text.strip().capitalize() if day.find("h4") else ""
        icon_span = day.find("div", class_="day_conditions").find("span") if day.find("div", class_="day_conditions") else None
        sunpeaks_icon_class = next((cls for cls in icon_span.get("class", []) if cls.startswith("icon-")), None) if icon_span else ""
        icon_class = map_weather_icon(sunpeaks_icon_class) if sunpeaks_icon_class else ""

        description_div = day.find("div", class_="day_description")
        description = description_div.get_text(strip=True) if description_div else ""

        low_temp_span = day.find("span", class_="day_low")
        low_temp_value = low_temp_span.find("span", class_="value_switch").get_text(strip=True) if low_temp_span else ""
        high_temp_span = day.find("span", class_="day_high")
        high_temp_value = high_temp_span.find("span", class_="value_switch").get_text(strip=True) if high_temp_span else ""

        if units == "imperial":
            low_temp_value = convert_celsius_to_fahrenheit(low_temp_value) if low_temp_value else ""
            high_temp_value = convert_celsius_to_fahrenheit(high_temp_value) if high_temp_value else ""
            temp_unit = "°F"
        else:
            temp_unit = "°C"

        forecast.append({
            "day_name": day_name,
            "icon": icon_class,
            "description": description,
            "low_temp_value": low_temp_value,
            "high_temp_value": high_temp_value,
            "temp_unit": temp_unit,
        })

    return {
        "today_icon": today_icon,
        "today_description": today_description,
        "temperatures": temperatures,
        "snow_conditions": snow_conditions,
        "base_snow_conditions": base_snow_conditions,
        "wind_speeds": wind_speeds,
        "forecast": forecast,
        "units": units,  # Pass units to template
    }

# Weather Icon Mapping
def map_weather_icon(sunpeaks_icon):
    """Maps Sun Peaks weather icon classes to FontAwesome or Weather Icons."""
    icon_mapping = {
        "icon-sunny_clear_skies": "fas fa-sun",
        "icon-partly_cloudy": "fas fa-cloud-sun",
        "icon-mainly_cloudy": "fas fa-cloud",
        "icon-cloudy": "fas fa-cloud",
        "icon-overcast": "fas fa-smog",
        "icon-light_rain_showers": "fas fa-cloud-showers-light",
        "icon-rain_showers": "fas fa-cloud-rain",
        "icon-snow_showers": "fas fa-snowflake",
        "icon-light_snow": "fas fa-snowflake",
        "icon-snow_flurries": "fas fa-snowflake",
        "icon-mixed_snow": "fas fa-snowflake",
        "icon-snow": "fas fa-snowflake",
        "icon-heavy_snow": "fas fa-snowflake",
        "icon-thunderstorm": "fas fa-bolt",
        "icon-fog": "fas fa-smog",
        "icon-clear_skies_night": "fas fa-moon",
        "icon-partly_cloudy_night": "fas fa-cloud-moon",
        "icon-mainly_cloudy_night": "fas fa-cloud-moon",
        "icon-cloudy_night": "fas fa-cloud-moon",
        "icon-snow_flurries_night": "fas fa-snowflake",
        "icon-mixed_snow_night": "fas fa-snowflake",
    }
    
    icon = icon_mapping.get(sunpeaks_icon, "fas fa-question-circle")
    if icon == "fas fa-question-circle":
        print(f"Unknown icon class: {sunpeaks_icon}")
    
    return icon
