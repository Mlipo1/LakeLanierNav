import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
import re

st.set_page_config(page_title="Lanier Navigator", layout="centered", page_icon="⚓")

# Custom UI Tweaks for a sleek, modern mobile app look
st.markdown("""
    <style>
    /* Global App Background */
    .stApp { background-color: #f8f9fa; }
    
    /* Beautiful Metric Cards */
    .metric-card {
        background: #ffffff;
        border-radius: 15px;
        padding: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        text-align: center;
        margin-bottom: 15px;
        border: 1px solid #e9ecef;
    }
    .metric-title {
        color: #6c757d;
        font-size: 0.95rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 8px;
    }
    .metric-value { color: #2c3e50; font-size: 2.2rem; font-weight: 900; }
    .metric-sub { font-size: 0.9rem; font-weight: 600; margin-top: 5px; }
    .text-red { color: #e74c3c; }
    .text-blue { color: #3498db; }
    
    /* Chop Conditions */
    .chop-safe { color: #2ecc71; font-weight: 800; }
    .chop-warn { color: #f1c40f; font-weight: 800; }
    .chop-danger { color: #e74c3c; font-weight: 800; }
    
    /* Wind Animation */
    @keyframes wind-pulse {
        0% { transform: scale(1) translateY(0px); opacity: 0.8; }
        50% { transform: scale(1.1) translateY(-5px); opacity: 1; filter: drop-shadow(0px 0px 8px rgba(255, 255, 255, 0.8)); }
        100% { transform: scale(1) translateY(0px); opacity: 0.8; }
    }
    .animated-wind {
        display: inline-block;
        animation: wind-pulse 2s infinite ease-in-out;
        transition: transform 0.5s ease;
    }
    
    /* Wind Container */
    .wind-container {
        background: linear-gradient(135deg, #2c3e50, #3498db);
        border-radius: 20px;
        padding: 25px;
        color: white;
        text-align: center;
        box-shadow: 0 10px 20px rgba(0,0,0,0.15);
        margin-bottom: 20px;
        height: 100%;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("⚓ Lanier Navigator")

@st.cache_data(ttl=300) 
def fetch_data():
    data = {
        "level": "N/A", "air_temp": "N/A", "water_temp": "N/A",
        "wind_mph": 0, "wind_dir": 0, "gusts": 0
    }
    
    # 1. Lake Level (USGS Buford Dam Elevation)
    try:
        usgs_url = "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=02334400&parameterCd=00062"
        usgs_res = requests.get(usgs_url).json()
        val = usgs_res['value']['timeSeries'][0]['values'][0]['value'][0]['value']
        data["level"] = float(val)
    except Exception:
        pass

    # 2. Weather & Wind (Open-Meteo for Flowery Branch)
    try:
        meteo_url = "https://api.open-meteo.com/v1/forecast?latitude=34.18&longitude=-83.98&current=temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m&temperature_unit=fahrenheit&wind_speed_unit=mph"
        meteo_res = requests.get(meteo_url).json()['current']
        data["air_temp"] = round(meteo_res['temperature_2m'], 1)
        data["wind_mph"] = round(meteo_res['wind_speed_10m'], 1)
        data["wind_dir"] = meteo_res['wind_direction_10m']
        data["gusts"] = round(meteo_res['wind_gusts_10m'], 1)
    except Exception:
        pass

    # 3. Water Temp (Web Scrape)
    try:
        lm_url = "https://lakemonster.com/lake/GA/Lake-Lanier-234"
        headers = {'User-Agent': 'Mozilla/5.0'}
        lm_res = requests.get(lm_url, headers=headers, timeout=5)
        match = re.search(r'(\d+)°F\s*water', lm_res.text, re.IGNORECASE)
        if match:
            data["water_temp"] = int(match.group(1))
    except Exception:
        pass

    return data

def get_compass_dir(degrees):
    dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    ix = int(round(degrees / (360. / len(dirs))))
    return dirs[ix % len(dirs)]

def calculate_chop(wind, gusts):
    avg_force = (wind + gusts) / 2
    if avg_force < 5:
        return "Glassy (Perfect for wakeboarding)", "chop-safe"
    elif avg_force < 12:
        return "Light Chop", "chop-safe"
    elif avg_force < 20:
        return "Choppy (Caution for smaller boats)", "chop-warn"
    else:
        return "Rough / Whitecaps", "chop-danger"

# --- App Execution ---
d = fetch_data()
direction_text = get_compass_dir(d['wind_dir'])
chop_text, chop_class = calculate_chop(d['wind_mph'], d['gusts'])

FULL_POOL = 1071.0

# --- UI Rendering ---

# Row 1: Primary Stats 
c1, c2, c3 = st.columns(3)

with c1:
    level_diff = f"<span class='text-red'>↓ {abs(round(d['level'] - FULL_POOL, 2))} ft (Full Pool)</span>" if d['level'] != "N/A" else ""
    level_val = f"{d['level']:.2f}'" if d['level'] != "N/A" else "N/A"
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Lake Level</div>
        <div class="metric-value">{level_val}</div>
        <div class="metric-sub">{level_diff}</div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Water Temp</div>
        <div class="metric-value text-blue">{d['water_temp']}°</div>
        <div class="metric-sub" style="color:#7f8c8d;">Avg: 46°F (Feb)</div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Air Temp</div>
        <div class="metric-value">{d['air_temp']}°</div>
        <div class="metric-sub" style="color:#7f8c8d;">Flowery Branch</div>
    </div>
    """, unsafe_allow_html=True)

# Row 2: Animated Wind & Surface Conditions
st.markdown("### 💨 Live Wind & Surface Simulation")
cc1, cc2 = st.columns([1, 2])

with cc1:
    # Wind blows FROM the direction, so we rotate a standard UP arrow by (degrees + 180) to show where it's blowing
    wind_rotation = (d['wind_dir'] + 180) % 360
    
    st.markdown(f"""
    <div class="wind-container">
        <div style="font-size: 0.9rem; font-weight: bold; letter-spacing: 1px; margin-bottom: 10px; opacity: 0.9;">WIND DIRECTION</div>
        <div style="transform: rotate({wind_rotation}deg);" class="animated-wind">
            <svg width="60" height="60" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="19" x2="12" y2="5"></line>
                <polyline points="5 12 12 5 19 12"></polyline>
            </svg>
        </div>
        <div style="font-size: 1.8rem; font-weight: 900; margin-top: 10px;">{direction_text}</div>
        <div style="font-size: 1rem; opacity: 0.8;">{d['wind_dir']}°</div>
    </div>
    """, unsafe_allow_html=True)

with cc2:
    st.markdown(f"""
    <div class="metric-card" style="height: 83%; display: flex; flex-direction: column; justify-content: center;">
        <div class="metric-title">Surface Condition</div>
        <div class="metric-value {chop_class}" style="font-size: 1.4rem; margin-top: 10px;">{chop_text}</div>
        <div style="margin-top: 20px; display: flex; justify-content: space-around;">
            <div>
                <div class="metric-title">Sustained</div>
                <div style="font-size: 1.4rem; font-weight: bold; color: #2c3e50;">{d['wind_mph']} <span style="font-size:0.8rem;">mph</span></div>
            </div>
            <div>
                <div class="metric-title">Gusts</div>
                <div style="font-size: 1.4rem; font-weight: bold; color: #e74c3c;">{d['gusts']} <span style="font-size:0.8rem;">mph</span></div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# Row 3: Interactive Map
st.markdown("### 📍 Dock & Dine GPS")
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