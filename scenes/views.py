from django.shortcuts import render, redirect
from django.conf import settings
import requests
from urllib.parse import urljoin

# Home Assistant Configuration
HEADERS = {
    "Authorization": f"Bearer {settings.HOMEASSISTANT_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}

def get_scenes():
    """Fetch the list of scenes from Home Assistant."""
    
    base_url = settings.HOMEASSISTANT_URL
    api_endpoint = "/api/states"
    url = urljoin(base_url, api_endpoint)

    response = requests.get(url, headers=HEADERS, timeout=10)
    scenes = []
    if response.status_code == 200:
        entities = response.json()
        scene_filter = [name.lower() for name in settings.SCENE_FILTER]  # Convert SCENE_FILTER to lowercase
        for entity in entities:
            if entity['entity_id'].startswith('scene.'):
                friendly_name = entity['attributes'].get('friendly_name', entity['entity_id'])
                if not scene_filter or friendly_name.lower() in scene_filter:
                    icon = entity['attributes'].get('icon')
                    scenes.append({
                        "id": entity['entity_id'],
                        "name": friendly_name,
                        "icon": homeassistant_icon_mapping(icon),
                    })
    else:
        print(f"Error fetching scenes: {response.status_code} - {response.text}")
    return scenes

def activate_scene(scene_id):
    """Activate a scene using Home Assistant API."""
    url = f"{settings.HOMEASSISTANT_URL}/api/services/scene/turn_on"
    data = {"entity_id": scene_id}
    response = requests.post(url, headers=HEADERS, json=data, timeout=10)
    response.raise_for_status()

def scenes(request):
    """View to display and activate scenes."""
    if request.method == "POST":
        scene_id = request.POST.get("scene_id")
        if scene_id:
            activate_scene(scene_id)
        return redirect("scenes")  # Refresh page after activating scene

    scenes_list = get_scenes()
    return render(request, "scenes/scene_control.html", {"scenes": scenes_list})

def homeassistant_icon_mapping(hass_icon):
    """Map Home Assistant icons to Font Awesome icons."""
    
    HA_TO_FA_ICON_MAPPING = {
        # ⚡ Power & Energy
        "mdi:lightbulb": "fa-solid fa-lightbulb",  # Light
        "mdi:power-plug": "fa-solid fa-plug",  # Power plug
        "mdi:flash": "fa-solid fa-bolt",  # Electricity
        "mdi:solar-power": "fa-solid fa-solar-panel",  # Solar power

        # 🏠 Home & Rooms
        "mdi:home": "fa-solid fa-house",  # Home
        "mdi:sofa": "fa-solid fa-couch",  # Living room
        "mdi:bed": "fa-solid fa-bed",  # Bedroom
        "mdi:toilet": "fa-solid fa-toilet",  # Bathroom
        "mdi:silverware-fork-knife": "fa-solid fa-utensils",  # Dining room

        # 💡 Lights & Devices
        "mdi:lamp": "fa-solid fa-lightbulb",  # Lamp
        "mdi:ceiling-light": "fa-solid fa-lightbulb",  # Ceiling light
        "mdi:led-strip": "fa-solid fa-grip-lines",  # LED strip
        "mdi:television": "fa-solid fa-tv",  # TV
        "mdi:remote": "fa-solid fa-gamepad",  # Remote control

        # 🔥 Heating & Cooling
        "mdi:thermometer": "fa-solid fa-temperature-high",  # Thermometer
        "mdi:fire": "fa-solid fa-fire",  # Fireplace
        "mdi:snowflake": "fa-solid fa-snowflake",  # Air conditioning

        # 🚗 Garage & Doors
        "mdi:garage": "fa-solid fa-warehouse",  # Garage
        "mdi:garage-open": "fa-solid fa-warehouse",  # Garage (open)
        "mdi:door": "fa-solid fa-door-open",  # Door open
        "mdi:lock": "fa-solid fa-lock",  # Lock
        "mdi:lock-open": "fa-solid fa-unlock",  # Unlock

        # 🍳 Cooking & Kitchen
        "mdi:stove": "fa-solid fa-fire-burner",  # Stove
        "mdi:fridge": "fa-solid fa-icicles",  # Refrigerator
        "mdi:coffee": "fa-solid fa-mug-hot",  # Coffee machine
        "mdi:microwave": "fa-solid fa-wave-square",  # Microwave

        # 🎬 Entertainment & Media
        "mdi:movie": "fa-solid fa-film",  # Movies
        "mdi:popcorn": "fa-solid fa-popcorn",  # Movie night
        "mdi:speaker": "fa-solid fa-volume-up",  # Speaker
        "mdi:headphones": "fa-solid fa-headphones",  # Music
        "mdi:radio": "fa-solid fa-radio",  # Radio
        "mdi:gamepad": "fa-solid fa-gamepad",  # Gaming console

        # 🚗 Vehicles & Travel
        "mdi:car": "fa-solid fa-car",  # Car
        "mdi:bicycle": "fa-solid fa-bicycle",  # Bicycle
        "mdi:train": "fa-solid fa-train",  # Train
        "mdi:bus": "fa-solid fa-bus",  # Bus
        "mdi:airplane": "fa-solid fa-plane",  # Airplane

        # 🌡 Weather
        "mdi:weather-sunny": "fa-solid fa-sun",  # Sunny
        "mdi:weather-partly-cloudy": "fa-solid fa-cloud-sun",  # Partly cloudy
        "mdi:weather-cloudy": "fa-solid fa-cloud",  # Cloudy
        "mdi:weather-rainy": "fa-solid fa-cloud-showers-heavy",  # Rain
        "mdi:weather-snowy": "fa-solid fa-snowflake",  # Snow
        "mdi:weather-lightning": "fa-solid fa-bolt",  # Thunderstorm

        # 🔔 Alerts & Security
        "mdi:bell": "fa-solid fa-bell",  # Notifications
        "mdi:security": "fa-solid fa-shield-halved",  # Security system
        "mdi:alarm-light": "fa-solid fa-exclamation-triangle",  # Alarm
        "mdi:cctv": "fa-solid fa-video",  # Security camera

        # 📦 Sensors & Smart Devices
        "mdi:motion-sensor": "fa-solid fa-running",  # Motion sensor
        "mdi:water": "fa-solid fa-tint",  # Water sensor
        "mdi:smoke-detector": "fa-solid fa-smoking-ban",  # Smoke detector
        "mdi:gas-cylinder": "fa-solid fa-gas-pump",  # Gas sensor
        "mdi:battery": "fa-solid fa-battery-half",  # Battery

        # 🚪 Doors & Windows
        "mdi:window-closed": "fa-solid fa-window-close",  # Window closed
        "mdi:window-open": "fa-solid fa-window-maximize",  # Window open

        # 🌱 Outdoor & Gardening
        "mdi:flower": "fa-solid fa-seedling",  # Gardening
        "mdi:tree": "fa-solid fa-tree",  # Tree
        "mdi:grass": "fa-solid fa-leaf",  # Lawn
        "mdi:pool": "fa-solid fa-swimmer",  # Pool
        "mdi:sprinkler": "fa-solid fa-tint",  # Sprinkler system

        # 🔋 Power & Electricity
        "mdi:car-battery": "fa-solid fa-car-battery",  # Car battery
        "mdi:solar-panel": "fa-solid fa-solar-panel",  # Solar panel
        
        "mdi:theater": "fas fa-tv",
        "mdi:chef-hat": "fas fa-blender",
        "mdi:briefcase": "fas fa-briefcase",
        "mdi:food": "fas fa-utensils",
        "mdi:account-voice": "fas fa-glass-cheers",        
    }
    
    
    fa_icon =  HA_TO_FA_ICON_MAPPING.get(hass_icon, "fas fa-question-circle")  # Default icon if not found
    
    if fa_icon == "fas fa-question-circle":
        print(f"Unsupported HomeAssistant icon: {hass_icon}")
        
    return fa_icon