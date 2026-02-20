import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
import re
from datetime import datetime, timedelta

st.set_page_config(page_title="Lanier Navigator", layout="centered", page_icon="⚓")

# --- Bulletproof State Management ---
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = True 
if "is_metric" not in st.session_state:
    st.session_state.is_metric = False

# --- Top Header & Controls ---
col_title, col_controls = st.columns([2.2, 1.8])
with col_title:
    st.markdown('<h1 class="main-title">⚓ Lanier Navigator</h1>', unsafe_allow_html=True)

with col_controls:
    st.markdown('<div class="control-panel">', unsafe_allow_html=True)
    theme_lbl = "🌙 Dark Theme" if st.session_state.dark_mode else "☀️ Light Theme"
    new_theme = st.toggle(theme_lbl, value=st.session_state.dark_mode)
    if new_theme != st.session_state.dark_mode:
        st.session_state.dark_mode = new_theme
        st.rerun()
        
    unit_lbl = "📏 Metric Units" if st.session_state.is_metric else "📏 Imperial Units"
    new_unit = st.toggle(unit_lbl, value=st.session_state.is_metric)
    if new_unit != st.session_state.is_metric:
        st.session_state.is_metric = new_unit
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# --- Theme Definitions ---
theme = {
    "bg": "#0e1117" if st.session_state.dark_mode else "#f0f2f6",
    "card_bg": "#1e2130" if st.session_state.dark_mode else "#ffffff",
    "text": "#fafafa" if st.session_state.dark_mode else "#2c3e50",
    "sub_text": "#a0aab5" if st.session_state.dark_mode else "#6c757d",
    "border": "#333847" if st.session_state.dark_mode else "#d1d8e0",
    "map_tiles": "CartoDB dark_matter" if st.session_state.dark_mode else "CartoDB positron"
}

st.markdown(f"""
    <style>
    /* Global App Background */
    .stApp {{ background-color: {theme['bg']} !important; }}
    
    h3, div[data-testid="stWidgetLabel"] p, p {{ color: {theme['text']} !important; font-weight: 600; }}
    
    .main-title {{
        color: {theme['text']} !important; font-weight: 800; font-size: clamp(1.8rem, 5vw, 2.5rem);
        white-space: nowrap; margin-bottom: 0px; margin-top: 15px;
    }}
    
    div[data-testid="stToggle"] label div[role="switch"] {{ background-color: #a0aab5 !important; }}
    div[data-testid="stToggle"] label div[role="switch"][aria-checked="true"] {{ background-color: #3498db !important; }}
    
    .control-panel {{
        background-color: {theme['card_bg']}; padding: 5px 15px; border-radius: 12px;
        border: 2px solid {theme['border']}; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px;
    }}
    
    .metrics-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 15px; }}
    .wind-grid {{ display: grid; grid-template-columns: 1fr 2fr; gap: 15px; margin-bottom: 25px; }}
    
    .metric-card {{
        background: {theme['card_bg']}; border-radius: 15px; padding: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05); text-align: center; border: 1px solid {theme['border']};
        display: flex; flex-direction: column; justify-content: center;
    }}
    .metric-title {{ color: {theme['sub_text']}; font-size: 0.85rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
    .metric-value {{ color: {theme['text']}; font-size: 2.2rem; font-weight: 900; line-height: 1.1; }}
    .metric-sub {{ font-size: 0.8rem; font-weight: 600; margin-top: 5px; color: {theme['sub_text']}; line-height: 1.3; }}
    .text-red {{ color: #e74c3c; }}
    .text-blue {{ color: #3498db; }}
    
    .chop-safe {{ color: #2ecc71; font-weight: 800; }}
    .chop-warn {{ color: #f1c40f; font-weight: 800; }}
    .chop-danger {{ color: #e74c3c; font-weight: 800; }}
    
    .pill-container {{ display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-bottom: 25px; margin-top: 5px; }}
    .info-pill {{
        background: {theme['card_bg']}; border: 1px solid {theme['border']}; border-radius: 30px; padding: 8px 15px;
        color: {theme['text']}; font-size: 0.85rem; font-weight: 600; text-align: center;
        flex: 1 1 calc(33% - 10px); min-width: 130px; box-shadow: 0 2px 5px rgba(0,0,0,0.02);
    }}
    
    .wind-container {{
        background: linear-gradient(135deg, #2c3e50, #3498db); border-radius: 20px; padding: 20px; color: white;
        text-align: center; box-shadow: 0 10px 20px rgba(0,0,0,0.15); height: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center;
    }}
    @keyframes wind-pulse {{
        0% {{ transform: scale(1) translateY(0px); opacity: 0.8; }}
        50% {{ transform: scale(1.1) translateY(-5px); opacity: 1; filter: drop-shadow(0px 0px 8px rgba(255, 255, 255, 0.8)); }}
        100% {{ transform: scale(1) translateY(0px); opacity: 0.8; }}
    }}
    .animated-wind {{ display: inline-block; animation: wind-pulse 2s infinite ease-in-out; transition: transform 0.5s ease; }}
    .wind-stats-flex {{ margin-top: 15px; display: flex; justify-content: space-around; }}

    /* NEW: Dynamic Wave Animation CSS */
    .sim-wave-box {{
        position: relative;
        background: linear-gradient(to bottom, transparent 0%, rgba(52, 152, 219, 0.1) 100%);
        height: 100px;
        border-radius: 10px;
        overflow: hidden;
        margin-top: 15px;
        width: 100%;
        border-bottom: 3px solid #3498db;
    }}
    .sim-wave-back {{
        position: absolute; bottom: 0; left: 0; width: 200%; height: 60px;
        background: url('data:image/svg+xml;utf8,<svg viewBox="0 0 1200 60" xmlns="http://www.w3.org/2000/svg"><path d="M0,30 C150,60 350,0 600,30 C850,60 1050,0 1200,30 L1200,60 L0,60 Z" fill="%232980b9" opacity="0.5"/></svg>') repeat-x;
        background-size: 50% 100%;
        transform-origin: bottom;
        animation: wave-move var(--wave-speed-back, 3s) linear infinite reverse;
    }}
    .sim-wave-front {{
        position: absolute; bottom: 0; left: 0; width: 200%; height: 50px;
        background: url('data:image/svg+xml;utf8,<svg viewBox="0 0 1200 60" xmlns="http://www.w3.org/2000/svg"><path d="M0,30 C150,0 350,60 600,30 C850,0 1050,60 1200,30 L1200,60 L0,60 Z" fill="%233498db" opacity="0.8"/></svg>') repeat-x;
        background-size: 50% 100%;
        transform-origin: bottom;
        animation: wave-move var(--wave-speed-front, 2.5s) linear infinite;
    }}
    @keyframes wave-move {{
        0% {{ transform: translateX(0) scaleY(var(--wave-scale, 1)); }}
        100% {{ transform: translateX(-50%) scaleY(var(--wave-scale, 1)); }}
    }}

    /* MOBILE OVERRIDES */
    @media (max-width: 600px) {{
        .main-title {{ text-align: center; margin-bottom: 10px; }}
        .control-panel {{ padding: 10px; display: flex; flex-direction: column; align-items: center; gap: 5px; }}
        .metrics-grid {{ grid-template-columns: 1fr 1fr; gap: 10px; }}
        .metrics-grid .metric-card:nth-child(3) {{ grid-column: span 2; }}
        .wind-grid {{ grid-template-columns: 1fr 1fr; gap: 10px; }}
        .wind-container, .metric-card {{ padding: 15px 10px; }}
        .metric-value {{ font-size: 1.6rem !important; }}
        .wind-stats-flex {{ flex-direction: column; gap: 8px; margin-top: 10px; }}
    }}
    </style>
    """, unsafe_allow_html=True)

# --- Data Fetching Functions ---
@st.cache_data(ttl=300) 
def fetch_data():
    data = {
        "level": "N/A", "air_temp": "N/A", "water_temp": 47, 
        "wind_mph": 0, "wind_dir": 0, "gusts": 0, "uv": 0, 
        "sunrise": "N/A", "sunset": "N/A", "rain_chance": 0, "visibility": "N/A", "pressure": "N/A", "clouds": 0
    }
    
    try:
        usgs_url = "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=02334400&parameterCd=00062"
        usgs_res = requests.get(usgs_url, timeout=5).json()
        val = usgs_res['value']['timeSeries'][0]['values'][0]['value'][0]['value']
        data["level"] = float(val)
    except Exception: pass

    try:
        meteo_url = "https://api.open-meteo.com/v1/forecast?latitude=34.18&longitude=-83.98&current=temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,uv_index,visibility,surface_pressure,cloud_cover&daily=sunrise,sunset,precipitation_probability_max&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=America%2FNew_York"
        meteo_res = requests.get(meteo_url, timeout=5).json()
        current, daily = meteo_res['current'], meteo_res['daily']
        
        data["air_temp"] = current['temperature_2m']
        data["wind_mph"] = current['wind_speed_10m']
        data["wind_dir"] = current['wind_direction_10m']
        data["gusts"] = current['wind_gusts_10m']
        data["uv"] = current['uv_index']
        data["visibility"] = current['visibility'] / 1609.34
        data["pressure"] = current['surface_pressure']
        data["clouds"] = current['cloud_cover']
        data["rain_chance"] = daily['precipitation_probability_max'][0]
        data["sunrise"] = datetime.strptime(daily['sunrise'][0], "%Y-%m-%dT%H:%M").strftime("%I:%M %p")
        data["sunset"] = datetime.strptime(daily['sunset'][0], "%Y-%m-%dT%H:%M").strftime("%I:%M %p")
    except Exception: pass

    try:
        lm_url = "https://lakemonster.com/lake/GA/Lake-Lanier-234"
        headers = {'User-Agent': 'Mozilla/5.0'}
        lm_res = requests.get(lm_url, headers=headers, timeout=5)
        match = re.search(r'(\d{2,3})(?:\s*°|\s*&deg;|\s*deg)?\s*F', lm_res.text, re.IGNORECASE)
        if match:
            scraped_temp = int(match.group(1))
            if 35 <= scraped_temp <= 95: data["water_temp"] = scraped_temp
    except Exception: pass 
    return data

@st.cache_data(ttl=300)
def fetch_level_trend():
    try:
        end = datetime.utcnow()
        start = end - timedelta(hours=24)
        url = f"https://waterservices.usgs.gov/nwis/iv/?format=json&sites=02334400&parameterCd=00062&startDT={start.isoformat()}&endDT={end.isoformat()}"
        res = requests.get(url, timeout=5).json()
        values = res['value']['timeSeries'][0]['values'][0]['value']
        first, last = float(values[0]['value']), float(values[-1]['value'])
        return round(last - first, 2)
    except: return 0

def get_compass_dir(degrees):
    dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    return dirs[int(round(degrees / (360. / len(dirs)))) % len(dirs)]

def calculate_chop(wind, gusts):
    avg_force = (wind + gusts) / 2
    if avg_force < 5: return "Glassy", "chop-safe"
    elif avg_force < 12: return "Light Chop", "chop-safe"
    elif avg_force < 20: return "Choppy (Small Boat Caution)", "chop-warn"
    else: return "Rough / Whitecaps", "chop-danger"

def calculate_boat_score(d, wave):
    score = 100 - (d["wind_mph"] * 1.5) - (d["rain_chance"] * 0.5) - (wave * 8)
    return max(0, min(100, round(score)))

def get_safety_alert(d, wave):
    alerts = []
    if d["wind_mph"] >= 20 or d["gusts"] >= 30: alerts.append("High Wind")
    if d["rain_chance"] >= 70: alerts.append("Heavy Rain")
    if d["visibility"] != "N/A" and d["visibility"] < 2: alerts.append("Low Visibility")
    if wave >= 3: alerts.append("High Waves")
    return alerts

# --- Execute Data Logic ---
d = fetch_data()
trend_24h = fetch_level_trend()
FULL_POOL_FT = 1071.0

# Base wave calculation without vessel multiplier
wave_height = round(0.016 * (d["wind_mph"] ** 1.5), 1)

if st.session_state.is_metric:
    unit_dist, unit_temp, unit_speed, unit_vis, unit_press = "m", "°C", "km/h", "km", "hPa"
    disp_level = round(d['level'] * 0.3048, 2) if d['level'] != "N/A" else "N/A"
    disp_pool_diff = round(abs((d['level'] - FULL_POOL_FT) * 0.3048), 2) if d['level'] != "N/A" else "N/A"
    disp_water_temp = round((d['water_temp'] - 32) * 5/9, 1)
    disp_air_temp = round((d['air_temp'] - 32) * 5/9, 1) if d['air_temp'] != "N/A" else "N/A"
    disp_wind = round(d['wind_mph'] * 1.60934, 1)
    disp_gusts = round(d['gusts'] * 1.60934, 1)
    disp_vis = round(d['visibility'] * 1.60934, 1) if d['visibility'] != "N/A" else "N/A"
    disp_press = round(d['pressure'], 1) if d['pressure'] != "N/A" else "N/A"
    disp_wave = round(wave_height * 0.3048, 1)
else:
    unit_dist, unit_temp, unit_speed, unit_vis, unit_press = "'", "°F", "mph", "mi", "inHg"
    disp_level = round(d['level'], 2) if d['level'] != "N/A" else "N/A"
    disp_pool_diff = round(abs(d['level'] - FULL_POOL_FT), 2) if d['level'] != "N/A" else "N/A"
    disp_water_temp = d['water_temp']
    disp_air_temp = round(d['air_temp'], 1) if d['air_temp'] != "N/A" else "N/A"
    disp_wind = round(d['wind_mph'], 1)
    disp_gusts = round(d['gusts'], 1)
    disp_vis = round(d['visibility'], 1) if d['visibility'] != "N/A" else "N/A"
    disp_press = round(d['pressure'] * 0.02953, 2) if d['pressure'] != "N/A" else "N/A"
    disp_wave = wave_height

direction_text = get_compass_dir(d['wind_dir'])
chop_text, chop_class = calculate_chop(d['wind_mph'], d['gusts'])
wind_rotation = (d['wind_dir'] + 180) % 360

# --- Top Level HTML Formatting ---
trend_arrow = "↑" if trend_24h >= 0 else "↓"
trend_color = "#2ecc71" if trend_24h >= 0 else "#e74c3c"
trend_html = f"<span style='color:{trend_color}; font-weight:700;'>{trend_arrow} {abs(trend_24h)} ft (24h)</span>"

level_diff_html = f"{trend_html}<br><span class='text-red'>↓ {disp_pool_diff}{unit_dist}</span>" if disp_level != "N/A" else ""
level_val = f"{disp_level}{unit_dist}" if disp_level != "N/A" else "N/A"
temp_color = "#3498db" if disp_water_temp < 60 else "#f39c12" if disp_water_temp < 80 else "#e74c3c"

st.markdown(f"""
<div class="metrics-grid">
    <div class="metric-card">
        <div class="metric-title">Lake Level</div>
        <div class="metric-value">{level_val}</div>
        <div class="metric-sub">{level_diff_html} (Full)</div>
    </div>
    <div class="metric-card">
        <div class="metric-title">Water Temp</div>
        <div class="metric-value" style="color:{temp_color};">{disp_water_temp}{unit_temp}</div>
        <div class="metric-sub">Surface</div>
    </div>
    <div class="metric-card">
        <div class="metric-title">Air Temp</div>
        <div class="metric-value">{disp_air_temp}{unit_temp}</div>
        <div class="metric-sub">Flowery Branch</div>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="pill-container">
    <div class="info-pill">🌅 Sun: {d["sunrise"]} / {d["sunset"]}</div>
    <div class="info-pill">🌧️ Rain: {d["rain_chance"]}%</div>
    <div class="info-pill">🌫️ Vis: {disp_vis} {unit_vis}</div>
    <div class="info-pill">🌡️ Pres: {disp_press} {unit_press}</div>
    <div class="info-pill">☁️ Clouds: {d["clouds"]}%</div>
    <div class="info-pill">☀️ UV: {round(d["uv"],1)}</div>
</div>
""", unsafe_allow_html=True)

# --- Boating Score & Safety Banner ---
st.markdown("### 🚦 Boating Conditions & Safety")

boat_score = calculate_boat_score(d, wave_height)
alerts = get_safety_alert(d, wave_height)

if boat_score >= 85: score_label, score_color = "🟢 Excellent", "#2ecc71"
elif boat_score >= 65: score_label, score_color = "🟡 Good", "#f1c40f"
elif boat_score >= 40: score_label, score_color = "🟠 Marginal", "#e67e22"
else: score_label, score_color = "🔴 Stay Home", "#e74c3c"

st.markdown(f"""
<div class="metric-card" style="padding: 15px; margin-bottom: 15px;">
    <div class="metric-title" style="margin-bottom: 5px;">Overall Boating Score</div>
    <div style="font-size: 2.5rem; font-weight: 900; color: {score_color}; line-height: 1; margin: 10px 0;">{boat_score}<span style="font-size: 1.2rem; color: {theme['sub_text']}">/100</span></div>
    <div class="metric-sub" style="font-size: 1rem;">{score_label} (Based on wind, rain & waves)</div>
</div>
""", unsafe_allow_html=True)

if alerts:
    st.markdown(f"""
    <div style="background:#e74c3c; padding:12px; border-radius:12px; color:white; font-weight:700; text-align:center; margin-top: 15px; margin-bottom:20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        ⚠️ {" | ".join(alerts)}
    </div>
    """, unsafe_allow_html=True)

# --- NEW: Live Camera & Wave Simulator Section ---
st.markdown("### 📷 Live Camera & Wave Simulator")

# Streamlit columns automatically stack perfectly on mobile phones
cam_col, sim_col = st.columns([1, 1])

with cam_col:
    st.markdown('<div class="metric-title" style="margin-bottom:10px;">🔴 Lake Lanier Sailing Club Live</div>', unsafe_allow_html=True)
    # Streamlit natively handles YouTube embeds and makes them responsive
    st.video("https://www.youtube.com/watch?v=QjJC9ORyOMQ")

with sim_col:
    st.markdown('<div class="metric-title" style="margin-bottom:10px;">🌊 Wave Height Simulation</div>', unsafe_allow_html=True)
    
    # Mathematical variables to control the CSS animation dynamically
    # Wave Scale: Flattens out near 0 wind, scales up to 2.5x height on high wind
    css_wave_scale = max(0.15, min(wave_height * 0.6 + 0.15, 2.5))
    
    # Animation Speed: Glassy water moves slow (8s), high wind moves extremely fast (1.5s)
    css_speed_front = max(1.5, 8.0 - (d["wind_mph"] * 0.25))
    css_speed_back = max(1.2, 6.0 - (d["wind_mph"] * 0.25))

    wave_sim_html = f"""
    <div class="metric-card" style="padding: 15px; height: 100%; display: flex; flex-direction: column; justify-content: space-between; margin-bottom: 0px;">
        <div style="text-align: center; margin-bottom: 10px;">
            <div style="font-size: 2.5rem; font-weight: 900; color: {theme['text']}; line-height: 1;">{disp_wave} {unit_dist}</div>
            <div style="font-size: 0.9rem; font-weight: 600; color: {theme['sub_text']}; margin-top: 5px;">Estimated Surface Chop</div>
        </div>
        <div class="sim-wave-box" style="--wave-scale: {css_wave_scale}; --wave-speed-front: {css_speed_front}s; --wave-speed-back: {css_speed_back}s;">
            <div class="sim-wave-back"></div>
            <div class="sim-wave-front"></div>
        </div>
    </div>
    """
    st.markdown(wave_sim_html, unsafe_allow_html=True)

# --- Wind & Surface Stats ---
st.markdown("### 💨 Live Wind Details")
st.markdown(f"""
<div class="wind-grid">
    <div class="wind-container">
        <div style="font-size: 0.8rem; font-weight: bold; letter-spacing: 1px; margin-bottom: 8px; opacity: 0.9;">WIND DIR</div>
        <div style="transform: rotate({wind_rotation}deg);" class="animated-wind">
            <svg width="45" height="45" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="19" x2="12" y2="5"></line>
                <polyline points="5 12 12 5 19 12"></polyline>
            </svg>
        </div>
        <div style="font-size: 1.5rem; font-weight: 900; margin-top: 8px;">{direction_text}</div>
        <div style="font-size: 0.9rem; opacity: 0.8;">{d['wind_dir']}°</div>
    </div>
    <div class="metric-card" style="margin-bottom: 0;">
        <div class="metric-title">Wind Condition</div>
        <div class="metric-value {chop_class}" style="font-size: 1.15rem; margin-top: 5px;">{chop_text}</div>
        <div class="wind-stats-flex">
            <div>
                <div class="metric-title" style="font-size: 0.75rem;">Sustained</div>
                <div style="font-size: 1.1rem; font-weight: bold; color: {theme['text']};">{disp_wind} <span style="font-size:0.75rem;">{unit_speed}</span></div>
            </div>
            <div>
                <div class="metric-title" style="font-size: 0.75rem;">Gusts</div>
                <div style="font-size: 1.1rem; font-weight: bold; color: #e74c3c;">{disp_gusts} <span style="font-size:0.75rem;">{unit_speed}</span></div>
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# --- Map ---
st.markdown("### 📍 Dock & Dine GPS")
category = st.multiselect("Show on Map", ["Restaurant","Fuel"], default=["Restaurant","Fuel"])

places = [
    {"name":"Pig Tales (Aqualand)","lat":34.148,"lon":-83.991,"type":"Restaurant"},
    {"name":"Fish Tales (Hideaway)","lat":34.175,"lon":-83.961,"type":"Restaurant"},
    {"name":"Pelican Pete's","lat":34.225,"lon":-84.001,"type":"Restaurant"},
    {"name":"Twisted Oar","lat":34.188,"lon":-84.008,"type":"Restaurant"},
    {"name":"LandShark / Margaritaville","lat":34.1852,"lon":-83.9854,"type":"Restaurant"},
    {"name":"Holiday Marina (Gas)","lat":34.173,"lon":-84.017,"type":"Fuel"}
]

m = folium.Map(location=[34.18, -83.98], zoom_start=11, tiles=theme['map_tiles'])
for p in places:
    if p["type"] in category:
        color = "blue" if p["type"]=="Restaurant" else "green"
        folium.Marker(
            [p['lat'], p['lon']], popup=f"{p['name']} ({p['type']})", icon=folium.Icon(color=color, icon='anchor', prefix='fa')
        ).add_to(m)
st_folium(m, width="100%", height=400)

# --- Pre-Departure & Utilities ---
st.markdown("---")
with st.expander("✅ Pre-Departure Checklist (Don't sink the boat!)"):
    st.checkbox("Hull drain plug securely installed")
    st.checkbox("Battery switch set to ON (or ALL/1+2)")
    st.checkbox("Engine blower run for 4 minutes before starting")
    st.checkbox("Life jackets counted & readily accessible")
    st.checkbox("Anchor and dock lines ready")
    st.checkbox("Sufficient fuel for the trip")

with st.expander("⛽ Fuel Range Estimator"):
    fuel = st.number_input("Fuel Onboard (Gallons)", min_value=0.0, step=1.0)
    mpg = st.number_input("Boat MPG", min_value=0.1, step=0.1)
    if fuel and mpg:
        safe_range = fuel * mpg * 0.7
        if st.session_state.is_metric:
            st.success(f"Safe Range (30% reserve): {round(safe_range * 1.60934, 1)} kilometers")
        else:
            st.success(f"Safe Range (30% reserve): {round(safe_range, 1)} miles")