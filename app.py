import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests

st.set_page_config(page_title="Lanier Navigator", layout="centered")

# Custom UI Tweaks
st.markdown("""
    <style>
    div[data-testid="stMetricValue"] { font-size: 1.8rem; color: #1f77b4; }
    .chop-safe { color: #28a745; font-weight: bold; }
    .chop-warn { color: #ffc107; font-weight: bold; }
    .chop-danger { color: #dc3545; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

st.title("⚓ Lanier Navigator")

@st.cache_data(ttl=300) # 5 min cache
def fetch_data():
    data = {
        "level": "N/A", "air_temp": "N/A", 
        "wind_mph": 0, "wind_dir": 0, "gusts": 0
    }
    
    # 1. Get Lake Level (USGS Buford Dam)
    # Using 00062 for Reservoir Elevation instead of river gage height
    try:
        usgs_url = "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=02334400&parameterCd=00062"
        usgs_res = requests.get(usgs_url).json()
        val = usgs_res['value']['timeSeries'][0]['values'][0]['value'][0]['value']
        data["level"] = float(val)
    except Exception:
        pass

    # 2. Get Weather & Wind (Open-Meteo for Flowery Branch / Lanier Area)
    try:
        meteo_url = "https://api.open-meteo.com/v1/forecast?latitude=34.18&longitude=-83.98&current=temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m&temperature_unit=fahrenheit&wind_speed_unit=mph"
        meteo_res = requests.get(meteo_url).json()['current']
        data["air_temp"] = round(meteo_res['temperature_2m'], 1)
        data["wind_mph"] = round(meteo_res['wind_speed_10m'], 1)
        data["wind_dir"] = meteo_res['wind_direction_10m']
        data["gusts"] = round(meteo_res['wind_gusts_10m'], 1)
    except Exception:
        pass

    return data

def get_compass_dir(degrees):
    dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    ix = int(round(degrees / (360. / len(dirs))))
    return dirs[ix % len(dirs)]

def calculate_chop(wind, gusts):
    # Simulated wave/chop factor based on wind speeds
    avg_force = (wind + gusts) / 2
    if avg_force < 5:
        return "Glassy (Perfect for wakeboarding)", "chop-safe"
    elif avg_force < 12:
        return "Light Chop", "chop-safe"
    elif avg_force < 20:
        return "Choppy (Caution for smaller boats)", "chop-warn"
    else:
        return "Rough / Whitecaps", "chop-danger"

# --- Main App Execution ---
d = fetch_data()
direction_text = get_compass_dir(d['wind_dir'])
chop_text, chop_class = calculate_chop(d['wind_mph'], d['gusts'])

# Constants
FULL_POOL = 1071.0

# Top Row: Primary Stats
c1, c2, c3 = st.columns(3)

# Calculate +/- from Full Pool and use Streamlit's native delta display
if d['level'] != "N/A":
    diff = round(d['level'] - FULL_POOL, 2)
    # The 'delta' argument automatically shows a red down-arrow for negative numbers
    c1.metric(label="Lake Level", value=f"{d['level']:.2f} ft", delta=f"{diff} ft (Full Pool)")
else:
    c1.metric("Lake Level", "N/A ft")

c2.metric("Air Temp", f"{d['air_temp']} °F")
c3.metric("Wind Speed", f"{d['wind_mph']} mph")

# Second Row: Wind Details
st.markdown("### 💨 Wind & Water Simulation")
cc1, cc2, cc3 = st.columns(3)
cc1.metric("Wind Direction", f"{direction_text} ({d['wind_dir']}°)")
cc2.metric("Gusts", f"{d['gusts']} mph")
cc3.markdown(f"**Surface Condition:**<br><span class='{chop_class}'>{chop_text}</span>", unsafe_allow_html=True)

# Third Row: Map
st.markdown("### 📍 Dock & Dine")
restaurants = [
    {"name": "Pig Tales (Aqualand)", "lat": 34.148, "lon": -83.991},
    {"name": "Fish Tales (Hideaway)", "lat": 34.175, "lon": -83.961},
    {"name": "Pelican Pete's", "lat": 34.225, "lon": -84.001},
    {"name": "Twisted Oar", "lat": 34.188, "lon": -84.008},
    {"name": "LandShark Bar & Grill", "lat": 34.1852, "lon": -83.9854}
]

m = folium.Map(location=[34.18, -83.98], zoom_start=11, tiles="CartoDB positron")
for res in restaurants:
    folium.Marker([res['lat'], res['lon']], popup=res['name'], icon=folium.Icon(color='blue', icon='anchor', prefix='fa')).add_to(m)

st_folium(m, width="100%", height=400)