import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
import re
from datetime import datetime

st.set_page_config(page_title="Lanier Navigator", layout="centered", page_icon="⚓")

# --- State Management ---
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = True 
if "is_metric" not in st.session_state:
    st.session_state.is_metric = False

# --- Top Header & Controls ---
col_title, col_controls = st.columns([2.5, 1.5])
with col_title:
    st.markdown('<h1 class="main-title">⚓ Lanier Navigator</h1>', unsafe_allow_html=True)
with col_controls:
    st.write("") # Spacing
    # Placing toggles inside a container ensures they never blend into the background
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    st.session_state.dark_mode = st.toggle("🌙 Dark Theme", value=st.session_state.dark_mode)
    st.session_state.is_metric = st.toggle("📏 Metric Units", value=st.session_state.is_metric)
    st.markdown('</div>', unsafe_allow_html=True)

# --- Theme Definitions ---
theme = {
    "bg": "#0e1117" if st.session_state.dark_mode else "#f8f9fa",
    "card_bg": "#1e2130" if st.session_state.dark_mode else "#ffffff",
    "text": "#fafafa" if st.session_state.dark_mode else "#2c3e50",
    "sub_text": "#a0aab5" if st.session_state.dark_mode else "#6c757d",
    "border": "#333847" if st.session_state.dark_mode else "#cccccc",
    "map_tiles": "CartoDB dark_matter" if st.session_state.dark_mode else "CartoDB positron"
}

st.markdown(f"""
    <style>
    /* Global App Background */
    .stApp {{ background-color: {theme['bg']} !important; }}
    
    /* Force Streamlit Labels and Text to use Theme Color */
    .main-title, h3, div[data-testid="stWidgetLabel"] p, .st-toggle p, p {{ 
        color: {theme['text']} !important; 
    }}
    
    /* Control Panel for Toggles (Fixes Light Mode Visibility) */
    .control-panel {{
        background-color: {theme['card_bg']};
        padding: 10px 15px;
        border-radius: 12px;
        border: 2px solid {theme['border']};
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 20px;
    }}
    
    /* Beautiful Metric Cards */
    .metric-card {{
        background: {theme['card_bg']};
        border-radius: 15px;
        padding: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        text-align: center;
        margin-bottom: 15px;
        border: 1px solid {theme['border']};
        transition: all 0.3s ease;
    }}
    .metric-title {{
        color: {theme['sub_text']};
        font-size: 0.95rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 8px;
    }}
    .metric-value {{ color: {theme['text']}; font-size: 2.2rem; font-weight: 900; }}
    .metric-sub {{ font-size: 0.9rem; font-weight: 600; margin-top: 5px; color: {theme['sub_text']}; }}
    .text-red {{ color: #e74c3c; }}
    .text-blue {{ color: #3498db; }}
    
    /* Chop Conditions */
    .chop-safe {{ color: #2ecc71; font-weight: 800; }}
    .chop-warn {{ color: #f1c40f; font-weight: 800; }}
    .chop-danger {{ color: #e74c3c; font-weight: 800; }}
    
    /* Small Info Pills */
    .info-pill {{
        background: {theme['card_bg']};
        border: 1px solid {theme['border']};
        border-radius: 30px;
        padding: 8px 10px;
        color: {theme['text']};
        font-size: 0.85rem;
        font-weight: 600;
        text-align: center;
        display: inline-block;
        width: 100%;
        margin-bottom: 10px;
        white-space: nowrap;
    }}
    
    /* Wind Animation */
    @keyframes wind-pulse {{
        0% {{ transform: scale(1) translateY(0px); opacity: 0.8; }}
        50% {{ transform: scale(1.1) translateY(-5px); opacity: 1; filter: drop-shadow(0px 0px 8px rgba(255, 255, 255, 0.8)); }}
        100% {{ transform: scale(1) translateY(0px); opacity: 0.8; }}
    }}
    .animated-wind {{
        display: inline-block;
        animation: wind-pulse 2s infinite ease-in-out;
        transition: transform 0.5s ease;
    }}
    
    .wind-container {{
        background: linear-gradient(135deg, #2c3e50, #3498db);
        border-radius: 20px;
        padding: 25px;
        color: white;
        text-align: center;
        box-shadow: 0 10px 20px rgba(0,0,0,0.15);
        margin-bottom: 20px;
        height: 100%;
    }}
    </style>
    """, unsafe_allow_html=True)

@st.cache_data(ttl=300) 
def fetch_data():
    # We fetch base data in Imperial/Standard, then convert later if needed
    data = {
        "level": "N/A", "air_temp": "N/A", "water_temp": 47, 
        "wind_mph": 0, "wind_dir": 0, "gusts": 0, "uv": 0, 
        "sunrise": "N/A", "sunset": "N/A", "rain_chance": 0, "visibility": "N/A",
        "pressure": "N/A", "clouds": 0
    }
    
    try:
        usgs_url = "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=02334400&parameterCd=00062"
        usgs_res = requests.get(usgs_url, timeout=5).json()
        val = usgs_res['value']['timeSeries'][0]['values'][0]['value'][0]['value']
        data["level"] = float(val)
    except Exception:
        pass

    try:
        meteo_url = "https://api.open-meteo.com/v1/forecast?latitude=34.18&longitude=-83.98&current=temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index,visibility,surface_pressure,cloud_cover&daily=sunrise,sunset,precipitation_probability_max&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=America%2FNew_York"
        meteo_res = requests.get(meteo_url, timeout=5).json()
        
        current = meteo_res['current']
        daily = meteo_res['daily']
        
        data["air_temp"] = current['temperature_2m']
        data["wind_mph"] = current['wind_speed_10m']
        data["wind_dir"] = current['wind_direction_10m']
        data["gusts"] = current['wind_gusts_10m']
        data["uv"] = current['uv_index']
        data["visibility"] = current['visibility'] / 1609.34 # meters to miles
        data["pressure"] = current['surface_pressure'] # Open-meteo defaults to hPa
        data["clouds"] = current['cloud_cover']
        data["rain_chance"] = daily['precipitation_probability_max'][0]
        
        data["sunrise"] = datetime.strptime(daily['sunrise'][0], "%Y-%m-%dT%H:%M").strftime("%I:%M %p")
        data["sunset"] = datetime.strptime(daily['sunset'][0], "%Y-%m-%dT%H:%M").strftime("%I:%M %p")
    except Exception:
        pass

    try:
        lm_url = "https://lakemonster.com/lake/GA/Lake-Lanier-234"
        headers = {'User-Agent': 'Mozilla/5.0'}
        lm_res = requests.get(lm_url, headers=headers, timeout=5)
        match = re.search(r'(\d{2,3})(?:\s*°|\s*&deg;|\s*deg)?\s*F', lm_res.text, re.IGNORECASE)
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

d = fetch_data()

# --- Unit Conversions & Formatting ---
FULL_POOL_FT = 1071.0

if st.session_state.is_metric:
    unit_dist = "m"
    unit_temp = "°C"
    unit_speed = "km/h"
    unit_vis = "km"
    unit_press = "hPa"
    
    # Math logic
    disp_level = round(d['level'] * 0.3048, 2) if d['level'] != "N/A" else "N/A"
    disp_pool_diff = round(abs((d['level'] - FULL_POOL_FT) * 0.3048), 2) if d['level'] != "N/A" else "N/A"
    disp_water_temp = round((d['water_temp'] - 32) * 5/9, 1)
    disp_air_temp = round((d['air_temp'] - 32) * 5/9, 1) if d['air_temp'] != "N/A" else "N/A"
    disp_wind = round(d['wind_mph'] * 1.60934, 1)
    disp_gusts = round(d['gusts'] * 1.60934, 1)
    disp_vis = round(d['visibility'] * 1.60934, 1) if d['visibility'] != "N/A" else "N/A"
    disp_press = round(d['pressure'], 1) if d['pressure'] != "N/A" else "N/A"
else:
    unit_dist = "'" # using ' for feet to look cleaner
    unit_temp = "°F"
    unit_speed = "mph"
    unit_vis = "mi"
    unit_press = "inHg"
    
    # Standard Imperial logic
    disp_level = round(d['level'], 2) if d['level'] != "N/A" else "N/A"
    disp_pool_diff = round(abs(d['level'] - FULL_POOL_FT), 2) if d['level'] != "N/A" else "N/A"
    disp_water_temp = d['water_temp']
    disp_air_temp = round(d['air_temp'], 1) if d['air_temp'] != "N/A" else "N/A"
    disp_wind = round(d['wind_mph'], 1)
    disp_gusts = round(d['gusts'], 1)
    disp_vis = round(d['visibility'], 1) if d['visibility'] != "N/A" else "N/A"
    disp_press = round(d['pressure'] * 0.02953, 2) if d['pressure'] != "N/A" else "N/A" # hPa to inHg

direction_text = get_compass_dir(d['wind_dir'])
chop_text, chop_class = calculate_chop(d['wind_mph'], d['gusts'])

# --- UI Rendering ---

# Row 1: Primary Stats 
c1, c2, c3 = st.columns(3)
with c1:
    level_diff_html = f"<span class='text-red'>↓ {disp_pool_diff} {unit_dist}</span>" if disp_level != "N/A" else ""
    level_val = f"{disp_level}{unit_dist}" if disp_level != "N/A" else "N/A"
    st.markdown(f'<div class="metric-card"><div class="metric-title">Lake Level</div><div class="metric-value">{level_val}</div><div class="metric-sub">{level_diff_html} (Full)</div></div>', unsafe_allow_html=True)

with c2:
    st.markdown(f'<div class="metric-card"><div class="metric-title">Water Temp</div><div class="metric-value text-blue">{disp_water_temp}{unit_temp}</div><div class="metric-sub">Surface</div></div>', unsafe_allow_html=True)

with c3:
    st.markdown(f'<div class="metric-card"><div class="metric-title">Air Temp</div><div class="metric-value">{disp_air_temp}{unit_temp}</div><div class="metric-sub">Flowery Branch</div></div>', unsafe_allow_html=True)

# Row 1.5: Quick Boating Info
qc1, qc2, qc3 = st.columns(3)
with qc1: st.markdown(f'<div class="info-pill">🌅 Sun: {d["sunrise"]} / {d["sunset"]}</div>', unsafe_allow_html=True)
with qc2: st.markdown(f'<div class="info-pill">🌧️ Rain Chance: {d["rain_chance"]}%</div>', unsafe_allow_html=True)
with qc3: st.markdown(f'<div class="info-pill">🌫️ Vis: {disp_vis} {unit_vis}</div>', unsafe_allow_html=True)

qc4, qc5, qc6 = st.columns(3)
with qc4: st.markdown(f'<div class="info-pill">🌡️ Pressure: {disp_press} {unit_press}</div>', unsafe_allow_html=True)
with qc5: st.markdown(f'<div class="info-pill">☁️ Clouds: {d["clouds"]}%</div>', unsafe_allow_html=True)
with qc6: st.markdown(f'<div class="info-pill">☀️ UV Index: {round(d["uv"],1)}</div>', unsafe_allow_html=True)

# Row 2: Animated Wind & Surface Conditions
st.markdown("### 💨 Live Wind & Surface Simulation")
cc1, cc2 = st.columns([1, 2])
with cc1:
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
                <div style="font-size: 1.4rem; font-weight: bold; color: {theme['text']};">{disp_wind} <span style="font-size:0.8rem;">{unit_speed}</span></div>
            </div>
            <div>
                <div class="metric-title">Gusts</div>
                <div style="font-size: 1.4rem; font-weight: bold; color: #e74c3c;">{disp_gusts} <span style="font-size:0.8rem;">{unit_speed}</span></div>
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
    {"name": "LandShark / Margaritaville", "lat": 34.1852, "lon": -83.9854},
    {"name": "Holiday Marina (Gas)", "lat": 34.173, "lon": -84.017}
]

m = folium.Map(location=[34.18, -83.98], zoom_start=11, tiles=theme['map_tiles'])
for res in restaurants:
    folium.Marker([res['lat'], res['lon']], popup=res['name'], icon=folium.Icon(color='blue', icon='anchor', prefix='fa')).add_to(m)
st_folium(m, width="100%", height=400)

# Row 4: Pre-Departure Checklist
st.markdown("---")
with st.expander("✅ Pre-Departure Checklist (Don't sink the boat!)"):
    st.checkbox("Hull drain plug securely installed")
    st.checkbox("Battery switch set to ON (or ALL/1+2)")
    st.checkbox("Engine blower run for 4 minutes before starting")
    st.checkbox("Life jackets counted & readily accessible")
    st.checkbox("Anchor and dock lines ready")
    st.checkbox("Sufficient fuel for the trip")