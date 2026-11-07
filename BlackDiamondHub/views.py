from django.shortcuts import render
import requests
from requests.exceptions import RequestException
from django.http import HttpResponse
from bs4 import BeautifulSoup
import re
from social_django.utils import load_strategy
from social_core.backends.spotify import SpotifyOAuth2

from hub.modes import resolve_mode, tiles_for_mode

def landing_page(request):
    url = 'https://www.sunpeaksresort.com/bike-hike/weather-webcams/weather'  # Replace with the URL you want to fetch
    current_weather = None
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # Parse the HTML content
        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract the current weather
        current_weather = soup.find('div', {'class': 'weather current-conditions'})  # Adjust as needed        
    except RequestException as e:
        print(f"Failed to fetch content from {url}")
        
    soup = BeautifulSoup(str(current_weather), 'html.parser')
    
    weather_data = []

    # Find all list items under current-temps (not air-quality or other sections)
    list_temps = soup.select('div.current-temps ul.list-temps li')

    # Iterate over each item and extract the relevant data
    for item in list_temps:
        location = item.find('h3').text
        
        # Extract the elevation, remove non-numeric characters, and convert to an integer
        elevation_str = item.find('p').text.split(': ')[1]
        elevation = int(re.sub(r'[^\d]', '', elevation_str))
        
        # Extract the temperature and convert it to an integer
        temperature = item.find('div', class_='weather-value').text.strip()

        # Create a dictionary for each weather entry
        weather_entry = {
            'location': location,
            'elevation': elevation,
            'temperature': temperature
        }
        
        # Append the entry to the weather_data list
        weather_data.append(weather_entry)    
    
    mode = resolve_mode(request)
    context = {
        'sunpeaks_weather': weather_data,
        'hub_mode': mode,
        'hub_sections': tiles_for_mode(mode),
    }
    return render(request, 'index.html', context)

def refresh_spotify_token(user):
    social_auth = user.social_auth.get(provider='spotify')
    strategy = load_strategy()
    spotify_backend = SpotifyOAuth2(strategy=strategy)

    # Check if the token has expired
    if spotify_backend.access_token_expired(social_auth):
        new_token = spotify_backend.refresh_token(social_auth.extra_data['refresh_token'])
        social_auth.extra_data['access_token'] = new_token['access_token']
        social_auth.save()
        return new_token['access_token']
    return social_auth.extra_data['access_token']

