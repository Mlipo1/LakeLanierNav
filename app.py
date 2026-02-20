import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
import re
import json
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
    st.write("") 
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
    /* Prevent Mobile Horizontal Scrolling & Bouncing */
    html, body, [data-testid="stAppViewContainer"], .stApp {{
        overflow-x: hidden !important; max-width: 100vw !important;
    }}
    * {{ box-sizing: border-box !important; }}

    .stApp {{ background-color: {theme['bg']} !important; }}
    h3, div[data-testid="stWidgetLabel"] p, p {{ color: {theme['text']} !important; font-weight: 600; }}
    
    .main-title {{
        color: {theme['text']} !important; font-weight: 800; font-size: clamp(1.8rem, 5vw, 2.5rem);
        white-space: nowrap; margin-bottom: 0px; margin-top: 15px;
    }}
    
    div[data-testid="stToggle"] {{
        background-color: {theme['card_bg']}; padding: 8px 15px; border-radius: 20px;
        border: 1px solid {theme['border']}; margin-bottom: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }}
    div[data-testid="stToggle"] label div[role="switch"] {{ background-color: #a0aab5 !important; }}
    div[data-testid="stToggle"] label div[role="switch"][aria-checked="true"] {{ background-color: #3498db !important; }}
    
    .metrics-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 15px; }}
    
    .metric-card {{
        background: {theme['card_bg']}; border-radius: 15px; padding: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05); text-align: center; border: 1px solid {theme['border']};
        display: flex; flex-direction: column; justify-content: center;
    }}
    .metric-title {{ color: {theme['sub_text']}; font-size: 0.85rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
    .metric-value {{ color: {theme['text']}; font-size: 2.2rem; font-weight: 900; line-height: 1.1; }}
    .metric-sub {{ font-size: 0.8rem; font-weight: 600; margin-top: 5px; color: {theme['sub_text']}; line-height: 1.3; }}
    .text-red {{ color: #e74c3c; }}
    
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
        box-shadow: 0 10px 20px rgba(0,0,0,0.15); margin-bottom: 25px;
    }}
    .wind-merged {{ display: flex; flex-direction: row; align-items: center; justify-content: space-around; gap: 20px; width: 100%; }}
    .wind-stats-box {{ background: rgba(0,0,0,0.25); padding: 15px 25px; border-radius: 15px; min-width: 50%; text-align: center; }}
    
    @keyframes wind-pulse {{
        0% {{ transform: translateY(0px); opacity: 0.8; }}
        50% {{ transform: translateY(-8px); opacity: 1; filter: drop-shadow(0px 0px 8px rgba(255, 255, 255, 0.8)); }}
        100% {{ transform: translateY(0px); opacity: 0.8; }}
    }}
    .animated-wind {{ display: inline-block; animation: wind-pulse 2s infinite ease-in-out; }}

    .sim-wave-box {{
        position: relative; background: linear-gradient(to bottom, transparent 0%, rgba(52, 152, 219, 0.1) 100%);
        height: 100px; border-radius: 10px; overflow: hidden; margin-top: 15px; width: 100%; border-bottom: 3px solid #3498db;
    }}
    .sim-wave-back {{
        position: absolute; bottom: 0; left: 0; width: 200%; height: 60px;
        background: url('data:image/svg+xml;utf8,<svg viewBox="0 0 1200 60" xmlns="http://www.w3.org/2000/svg"><path d="M0,30 C150,60 350,0 600,30 C850,60 1050,0 1200,30 L1200,60 L0,60 Z" fill="%232980b9" opacity="0.5"/></svg>') repeat-x;
        background-size: 50% 100%; transform-origin: bottom; animation: wave-move var(--wave-speed-back, 3s) linear infinite reverse;
    }}
    .sim-wave-front {{
        position: absolute; bottom: 0; left: 0; width: 200%; height: 50px;
        background: url('data:image/svg+xml;utf8,<svg viewBox="0 0 1200 60" xmlns="http://www.w3.org/2000/svg"><path d="M0,30 C150,0 350,60 600,30 C850,0 1050,60 1200,30 L1200,60 L0,60 Z" fill="%233498db" opacity="0.8"/></svg>') repeat-x;
        background-size: 50% 100%; transform-origin: bottom; animation: wave-move var(--wave-speed-front, 2.5s) linear infinite;
    }}
    @keyframes wave-move {{
        0% {{ transform: translateX(0) scaleY(var(--wave-scale, 1)); }}
        100% {{ transform: translateX(-50%) scaleY(var(--wave-scale, 1)); }}
    }}

    /* Collapsible Alert System CSS */
    .alert-expander {{
        background: #e74c3c; border-radius: 12px; color: white;
        margin-top: 15px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.2);
    }}
    .alert-summary {{
        padding: 15px; font-weight: 800; cursor: pointer; display: flex;
        align-items: center; justify-content: space-between; list-style: none;
    }}
    .alert-summary::-webkit-details-marker {{ display: none; }}
    .alert-content {{ padding: 0 15px 15px 15px; font-weight: 600; font-size: 0.95rem; line-height: 1.4; }}

    @media (max-width: 600px) {{
        .main-title {{ text-align: center; margin-bottom: 10px; }}
        .metrics-grid {{ grid-template-columns: 1fr 1fr; gap: 10px; }}
        .metrics-grid .metric-card:nth-child(3) {{ grid-column: span 2; }}
        .metric-value {{ font-size: 1.6rem !important; }}
        div[data-testid="stToggle"] {{ width: 100%; display: flex; justify-content: center; }}
        .wind-merged {{ flex-direction: column; text-align: center; }}
        .wind-stats-box {{ width: 100%; padding: 15px; }}
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
    if avg_force < 5: return "Glassy", "#a2de96" 
    elif avg_force < 12: return "Light Chop", "#a2de96"
    elif avg_force < 20: return "Choppy (Small Boat Caution)", "#fde047" 
    else: return "Rough / Whitecaps", "#fca5a5" 

FULL_POOL_FT = 1071.0

# UPDATED: Score now actively deducts points for low water levels
def calculate_boat_score(d, wave):
    score = 100 - (d["wind_mph"] * 1.5) - (d["rain_chance"] * 0.5) - (wave * 8)
    if d['level'] != "N/A":
        level_diff = FULL_POOL_FT - d['level']
        if level_diff > 0:
            # Deduct 3 points for every foot the lake is down
            score -= (level_diff * 3)
    return max(0, min(100, round(score)))

# UPDATED: Dynamic text alerts including severe water level warnings
def get_safety_alert(d, wave):
    alerts = []
    if d["wind_mph"] >= 20 or d["gusts"] >= 30: 
        alerts.append("🌬️ <strong>High Wind Advisory:</strong> Dangerous gusts detected. Small craft caution.")
    if d["rain_chance"] >= 70: 
        alerts.append("⛈️ <strong>Heavy Rain:</strong> High probability of storms/rain today.")
    if d["visibility"] != "N/A" and d["visibility"] < 2: 
        alerts.append("🌫️ <strong>Low Visibility:</strong> Fog or haze is severely limiting sight distance.")
    if wave >= 3: 
        alerts.append("🌊 <strong>Rough Chop:</strong> Estimated wave heights exceed 3 feet.")
    
    if d['level'] != "N/A":
        if d['level'] < 1066:
            alerts.append("📉 <strong>Low Water Hazard:</strong> Lake is >5ft down. Watch for newly exposed shoals. Fixed docks and ramps may be unusable.")
        elif d['level'] > 1072:
            alerts.append("🪵 <strong>High Water Warning:</strong> Lake is above full pool. Watch for floating debris and submerged dock structures.")
    return alerts

# --- Execute Data Logic ---
d = fetch_data()
trend_24h = fetch_level_trend()
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
chop_text, chop_color = calculate_chop(d['wind_mph'], d['gusts'])
wind_rotation = d['wind_dir']

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
    <div class="metric-sub" style="font-size: 1rem;">{score_label} (Based on level, wind, rain & waves)</div>
</div>
""", unsafe_allow_html=True)

# NEW: Collapsible Interactive Alert Banner
if alerts:
    alert_items = "".join([f"<div style='margin-bottom: 8px;'>{a}</div>" for a in alerts])
    alert_count = len(alerts)
    st.markdown(f"""
    <details class="alert-expander" open>
        <summary class="alert-summary">
            <span>⚠️ IMPORTANT SAFETY ALERTS ({alert_count})</span>
            <span style="font-size: 0.8rem; opacity: 0.9; text-transform: uppercase;">Tap to toggle</span>
        </summary>
        <div class="alert-content">
            {alert_items}
        </div>
    </details>
    """, unsafe_allow_html=True)

# --- Live Camera & Wave Simulator Section ---
st.markdown("### 📷 Live Camera & Wave Simulator")

cam_col, sim_col = st.columns([1, 1])
with cam_col:
    st.markdown('<div class="metric-title" style="margin-bottom:10px;">🔴 LLSC Live Stream</div>', unsafe_allow_html=True)
    st.video("https://www.youtube.com/watch?v=QjJC9ORyOMQ")

with sim_col:
    st.markdown('<div class="metric-title" style="margin-bottom:10px;">🌊 Wave Height Simulation</div>', unsafe_allow_html=True)
    
    css_wave_scale = max(0.15, min(wave_height * 0.6 + 0.15, 2.5))
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

# --- Consolidated Wind Section ---
st.markdown("### 💨 Live Wind Details")

wind_html = f"""
<div class="wind-container">
<div class="wind-merged">
<div style="text-align: center;">
<div style="font-size: 0.8rem; font-weight: bold; letter-spacing: 1px; margin-bottom: 8px; opacity: 0.9;">WIND DIR</div>
<div style="transform: rotate({wind_rotation}deg); display: inline-block;">
<div class="animated-wind">
<svg width="45" height="45" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
<line x1="12" y1="19" x2="12" y2="5"></line>
<polyline points="5 12 12 5 19 12"></polyline>
</svg>
</div>
</div>
<div style="font-size: 1.5rem; font-weight: 900; margin-top: 8px;">{direction_text}</div>
<div style="font-size: 0.9rem; opacity: 0.8;">{d['wind_dir']}°</div>
</div>
<div class="wind-stats-box">
<div style="font-size: 0.8rem; font-weight: bold; letter-spacing: 1px; margin-bottom: 5px; opacity: 0.9;">SURFACE CONDITION</div>
<div style="color: {chop_color}; font-weight: 800; font-size: 1.25rem; margin-bottom: 15px;">{chop_text}</div>
<div style="display: flex; justify-content: space-around; gap: 15px;">
<div>
<div style="font-size: 0.75rem; text-transform: uppercase; opacity: 0.8;">Sustained</div>
<div style="font-size: 1.3rem; font-weight: bold;">{disp_wind} <span style="font-size:0.75rem;">{unit_speed}</span></div>
</div>
<div>
<div style="font-size: 0.75rem; text-transform: uppercase; opacity: 0.8;">Gusts</div>
<div style="font-size: 1.3rem; font-weight: bold; color: #ff7675;">{disp_gusts} <span style="font-size:0.75rem;">{unit_speed}</span></div>
</div>
</div>
</div>
</div>
</div>
"""
st.markdown(wind_html, unsafe_allow_html=True)


# ---------------------------------------------------------
# MAP & NAVIGATION DASHBOARD
# ---------------------------------------------------------
st.markdown("### 📍 Dock & Dine Navigation")

nav_html = f"""
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body {{ margin: 0; padding: 0; font-family: -apple-system, sans-serif; background: transparent; }}
        
        /* Flexbox Layout Fix: Dashboard pushes map down instead of overlaying */
        #map-container {{ 
            display: flex; flex-direction: column; position: relative; 
            height: 550px; width: 100%; border-radius: 12px; overflow: hidden; 
            border: 1px solid {theme['border']}; 
        }}
        #map {{ flex: 1; width: 100%; z-index: 1; }}
        
        /* Navigation Dashboard (Now sits IN the flexbox, no absolute positioning) */
        #nav-dashboard {{
            display: none; width: 100%; z-index: 1001;
            background: {theme['card_bg']}; color: {theme['text']}; padding: 15px;
            border-bottom: 3px solid #3498db; box-sizing: border-box;
        }}
        
        /* Search Bar Setup */
        #search-container {{
            position: absolute; top: 10px; left: 10px; z-index: 1000; width: 65%; max-width: 320px;
        }}
        #poi-search {{
            width: 100%; padding: 12px 15px; border-radius: 25px; border: 2px solid #3498db;
            background: {theme['card_bg']}; color: {theme['text']}; font-weight: bold; font-size: 1rem;
            outline: none; box-shadow: 0 4px 10px rgba(0,0,0,0.3); box-sizing: border-box;
        }}
        #search-results {{
            display: none; background: {theme['card_bg']}; margin-top: 5px; border-radius: 12px;
            border: 1px solid {theme['border']}; box-shadow: 0 4px 15px rgba(0,0,0,0.4); overflow: hidden;
            max-height: 250px; overflow-y: auto;
        }}
        .search-item {{ padding: 12px 15px; cursor: pointer; border-bottom: 1px solid {theme['border']}; color: {theme['text']}; }}
        .search-item:last-child {{ border-bottom: none; }}
        .search-item:hover {{ background: rgba(52, 152, 219, 0.15); }}

        /* Floating Map Filters */
        #filter-panel {{
            position: absolute; top: 10px; right: 10px; z-index: 1000;
            background: {theme['card_bg']}; color: {theme['text']};
            padding: 10px 15px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.3);
            border: 1px solid {theme['border']}; font-size: 0.9rem; font-weight: bold;
        }}
        .filter-cb {{ margin-right: 8px; transform: scale(1.2); cursor: pointer; }}
        .filter-row {{ margin-bottom: 8px; display: flex; align-items: center; cursor: pointer; }}
        
        .stats-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); text-align: center; margin-top: 15px; }}
        .stat-val {{ font-size: 1.4rem; font-weight: 900; }}
        .stat-lbl {{ font-size: 0.7rem; opacity: 0.8; font-weight: bold; text-transform: uppercase; }}
        .eta-box {{ margin-top: 15px; background: rgba(52, 152, 219, 0.1); padding: 8px; border-radius: 8px; font-weight: bold; text-align: center; color: #3498db; }}
        
        /* Custom Map Markers */
        .map-marker {{
            width: 34px; height: 34px; background: white; border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            box-shadow: 0 3px 8px rgba(0,0,0,0.4); font-size: 18px; border: 2px solid white;
        }}
        .marker-dining {{ border-color: #e74c3c; background: #ffeaa7; }}
        .marker-fuel {{ border-color: #f39c12; background: #ffeaa7; }}
        .marker-marina {{ border-color: #3498db; background: #81ecec; }}
        
        /* Smart Zoom Labels (Using !important to override Leaflet default inline opacity) */
        .poi-label {{
            background: transparent !important; border: none !important; box-shadow: none !important; 
            color: {theme['text']} !important; font-weight: 900 !important; font-size: 0.9rem !important;
            text-shadow: 2px 2px 0 {theme['bg']}, -2px -2px 0 {theme['bg']}, 2px -2px 0 {theme['bg']}, -2px 2px 0 {theme['bg']} !important;
            opacity: 0 !important; pointer-events: none !important; transition: opacity 0.3s ease !important;
        }}
        #map.show-labels .poi-label {{ opacity: 1 !important; }}

        /* Navigation Arrow Icon */
        .nav-arrow-marker {{
            display: flex; align-items: center; justify-content: center;
            transition: transform 0.1s linear; transform-origin: center center;
        }}

        /* Buttons */
        .start-btn {{ background: #3498db; color: white; border: none; padding: 10px 15px; border-radius: 6px; font-weight: bold; cursor: pointer; margin-top: 10px; width: 100%; }}
        .stop-btn {{ background: #e74c3c; color: white; border: none; padding: 6px 12px; border-radius: 6px; font-weight: bold; cursor: pointer; font-size: 0.8rem; float: right; }}
        
        #recenter-btn {{
            display: none; position: absolute; bottom: 20px; right: 20px; z-index: 1000;
            background: {theme['card_bg']}; color: #3498db; border: 2px solid #3498db;
            width: 48px; height: 48px; border-radius: 50%; padding: 0;
            box-shadow: 0 4px 10px rgba(0,0,0,0.3); cursor: pointer;
            align-items: center; justify-content: center;
        }}

        /* Steering Compass */
        .steer-compass {{
            margin: 10px auto 0 auto; width: 50px; height: 50px; border-radius: 50%;
            background: {theme['bg']}; border: 2px solid #3498db; display: flex;
            align-items: center; justify-content: center; box-shadow: inset 0 0 10px rgba(0,0,0,0.2);
        }}
        
        /* MOBILE OVERRIDES */
        @media (max-width: 600px) {{
            #search-container {{ width: 90%; max-width: none; left: 5%; }}
            #filter-panel {{ top: 70px; right: 5%; }}
        }}
    </style>
</head>
<body>
    <div id="map-container">
        
        <div id="nav-dashboard">
            <div style="font-size: 1.1rem; font-weight: 800; display: flex; justify-content: space-between; align-items: center;">
                <span id="nav-title" style="color:#3498db;">Navigating...</span>
                <button class="stop-btn" onclick="stopNav()">🛑 Stop</button>
            </div>
            
            <div style="display: flex; justify-content: center; align-items: center; gap: 20px;">
                <div class="steer-compass">
                    <svg id="steer-arrow" style="transition: transform 0.1s ease-out;" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#3498db" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="12" y1="19" x2="12" y2="5"></line>
                        <polyline points="5 12 12 5 19 12"></polyline>
                    </svg>
                </div>
                <div style="font-size: 0.8rem; opacity: 0.8; font-weight: bold; width: 80px;">TURN TO <br>TARGET</div>
            </div>

            <div class="stats-grid">
                <div><div class="stat-lbl">Speed</div><div class="stat-val" id="gps-speed">--</div><div style="font-size:0.6rem" id="lbl-speed">mph</div></div>
                <div><div class="stat-lbl">Distance</div><div class="stat-val" id="gps-dist" style="color:#e74c3c">--</div><div style="font-size:0.6rem" id="lbl-dist">miles</div></div>
                <div><div class="stat-lbl">Heading</div><div class="stat-val" id="gps-heading">--</div><div style="font-size:0.6rem">deg</div></div>
            </div>
            <div class="eta-box">⏱️ ETA: <span id="gps-eta">Waiting for GPS lock...</span></div>
        </div>

        <div id="search-container">
            <input type="text" id="poi-search" placeholder="🔍 Search lake destinations..." oninput="filterSearch()">
            <div id="search-results"></div>
        </div>

        <div id="filter-panel">
            <label class="filter-row"><input type="checkbox" class="filter-cb" value="Dining" checked onchange="renderMarkers()"> 🍽️ Dining</label>
            <label class="filter-row"><input type="checkbox" class="filter-cb" value="Fuel" checked onchange="renderMarkers()"> ⛽ Fuel</label>
            <label class="filter-row" style="margin-bottom:0;"><input type="checkbox" class="filter-cb" value="Marina" checked onchange="renderMarkers()"> ⚓ Marinas</label>
        </div>

        <button id="recenter-btn" onclick="recenterMap()">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#3498db" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="22" y1="12" x2="18" y2="12"></line>
                <line x1="6" y1="12" x2="2" y2="12"></line>
                <line x1="12" y1="6" x2="12" y2="2"></line>
                <line x1="12" y1="22" x2="12" y2="18"></line>
            </svg>
        </button>
        
        <div id="map"></div>
    </div>

    <script>
    var isMetric = {js_metric_flag};
    var map = L.map('map', {{ zoomControl: false }}).setView([34.18, -83.98], 11);
    L.tileLayer('{map_tile_url}', {{ attribution: '&copy; Carto' }}).addTo(map);

    var places = {places_json};
    var markersLayer = L.layerGroup().addTo(map);
    
    // Custom Icons
    var iconMap = {{
        "Dining": L.divIcon({{className: '', html: '<div class="map-marker marker-dining">🍔</div>', iconSize: [34,34], iconAnchor: [17,17], popupAnchor: [0,-17]}}),
        "Fuel": L.divIcon({{className: '', html: '<div class="map-marker marker-fuel">⛽</div>', iconSize: [34,34], iconAnchor: [17,17], popupAnchor: [0,-17]}}),
        "Marina": L.divIcon({{className: '', html: '<div class="map-marker marker-marina">⚓</div>', iconSize: [34,34], iconAnchor: [17,17], popupAnchor: [0,-17]}})
    }};

    var targetIcon = L.icon({{
        iconUrl: 'https://cdn.rawgit.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
        iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34]
    }});

    // Render Markers & Bind Enhanced Tooltips/Popups
    window.renderMarkers = function() {{
        markersLayer.clearLayers();
        var checkboxes = document.querySelectorAll('.filter-cb');
        var activeFilters = Array.from(checkboxes).filter(cb => cb.checked).map(cb => cb.value);

        places.forEach((p, index) => {{
            if (activeFilters.includes(p.type)) {{
                var marker = L.marker([p.lat, p.lon], {{icon: iconMap[p.type] || iconMap["Dining"]}}).addTo(markersLayer);
                
                var tooltip = L.tooltip({{permanent: true, direction: 'bottom', className: 'poi-label', offset: [0, 5]}}).setContent(p.name);
                marker.bindTooltip(tooltip);

                var popupHTML = `
                    <div style="text-align: center; min-width: 140px; font-family: sans-serif;">
                        <b style="font-size: 1.1rem; color: #2c3e50;">${{p.name}}</b><br/>
                        <span style="font-size: 0.8rem; color: #7f8c8d;">${{p.type}}</span><br/>
                        <div style="font-size: 0.8rem; margin: 8px 0; color: #333;">🕒 ${{p.hours}}</div>
                        <a href="${{p.web}}" target="_blank" style="font-size: 0.85rem; color: #3498db; text-decoration: none; font-weight: bold;">🌐 Visit Website</a><br/>
                        <button class="start-btn" onclick="startNav(${{index}})">Start Navigating</button>
                    </div>
                `;
                marker.bindPopup(popupHTML);
            }}
        }});
    }};
    renderMarkers();

    // Smart Zoom Label Logic - Runs immediately to hide them initially
    function handleZoom() {{
        if (map.getZoom() >= 13) {{ document.getElementById('map').classList.add('show-labels'); }} 
        else {{ document.getElementById('map').classList.remove('show-labels'); }}
    }}
    map.on('zoomend', handleZoom);
    handleZoom();

    // Search Engine
    window.filterSearch = function() {{
        let query = document.getElementById('poi-search').value.toLowerCase();
        let resultsDiv = document.getElementById('search-results');
        resultsDiv.innerHTML = "";
        
        if (query.length === 0) {{ resultsDiv.style.display = "none"; return; }}
        
        let matches = places.filter(p => p.name.toLowerCase().includes(query) || p.type.toLowerCase().includes(query));
        
        if (matches.length > 0) {{
            resultsDiv.style.display = "block";
            matches.forEach(m => {{
                let idx = places.indexOf(m);
                let div = document.createElement('div');
                div.className = "search-item";
                div.innerHTML = `<b>${{m.name}}</b> <span style="font-size:0.75rem; opacity:0.7;">(${{m.type}})</span>`;
                div.onclick = function() {{
                    document.getElementById('poi-search').value = "";
                    resultsDiv.style.display = "none";
                    map.setView([m.lat, m.lon], 14, {{animate: true}}); 
                    startNav(idx);
                }};
                resultsDiv.appendChild(div);
            }});
        }} else {{
            resultsDiv.style.display = "none";
        }}
    }};

    // Global Nav Variables
    var watchId = null;
    var userMarker = null;
    var routeLine = null;
    var targetMarker = null;
    var currentTarget = null;
    var isNavigating = false;
    var mapLocked = true;
    var lastLat = null;
    var lastLon = null;
    var currentHeading = 0;

    map.on('dragstart', function() {{
        if (isNavigating) {{
            mapLocked = false;
            document.getElementById('recenter-btn').style.display = 'flex';
        }}
    }});

    window.recenterMap = function() {{
        mapLocked = true;
        document.getElementById('recenter-btn').style.display = 'none';
        if (lastLat != null && lastLon != null) {{ map.setView([lastLat, lastLon], 15, {{animate: true}}); }}
    }};

    // Orientation Logic
    function handleOrientation(event) {{
        if(!isNavigating) return;
        let newHeading = 0;
        if (event.webkitCompassHeading) {{ newHeading = event.webkitCompassHeading; }} 
        else if (event.alpha != null) {{ newHeading = 360 - event.alpha; }}
        currentHeading = newHeading;
        updateCompassUI();
    }}

    function updateCompassUI() {{
        if (!isNavigating) return;
        
        // Update Nav Chevron Rotation
        let navArrow = document.getElementById('map-nav-arrow');
        if (navArrow) navArrow.style.transform = `rotate(${{currentHeading}}deg)`;

        if (lastLat != null && currentTarget) {{
            const targetBearing = getBearing(lastLat, lastLon, currentTarget.lat, currentTarget.lon);
            let relativeBearing = targetBearing - currentHeading;
            let steerArrow = document.getElementById('steer-arrow');
            if (steerArrow) steerArrow.style.transform = `rotate(${{relativeBearing}}deg)`;
        }}
        document.getElementById("gps-heading").innerText = Math.round(currentHeading) + "°";
    }}

    function getDistance(lat1, lon1, lat2, lon2) {{
        const R = isMetric ? 6371 : 3958.8; 
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat/2) * Math.sin(dLat/2) + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon/2) * Math.sin(dLon/2);
        return R * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a)));
    }}

    function getBearing(lat1, lon1, lat2, lon2) {{
        var dLon = (lon2 - lon1) * Math.PI / 180;
        var y = Math.sin(dLon) * Math.cos(lat2 * Math.PI / 180);
        var x = Math.cos(lat1 * Math.PI / 180) * Math.sin(lat2 * Math.PI / 180) - Math.sin(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.cos(dLon);
        return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
    }}

    window.startNav = function(index) {{
        currentTarget = places[index];
        map.closePopup();
        isNavigating = true;
        mapLocked = true;
        
        document.getElementById('nav-dashboard').style.display = 'block';
        document.getElementById('search-container').style.display = 'none';
        document.getElementById('filter-panel').style.display = 'none';
        document.getElementById('recenter-btn').style.display = 'none';
        document.getElementById('nav-title').innerText = "To: " + currentTarget.name;
        document.getElementById('lbl-speed').innerText = isMetric ? "km/h" : "mph";
        document.getElementById('lbl-dist').innerText = isMetric ? "km" : "miles";
        
        // Let CSS push the map down, then recalculate map center physically
        setTimeout(function() {{ map.invalidateSize(); }}, 50);

        if(targetMarker) map.removeLayer(targetMarker);
        targetMarker = L.marker([currentTarget.lat, currentTarget.lon], {{icon: targetIcon}}).addTo(map);

        if (typeof DeviceOrientationEvent !== 'undefined' && typeof DeviceOrientationEvent.requestPermission === 'function') {{
            DeviceOrientationEvent.requestPermission().then(permissionState => {{
                if (permissionState === 'granted') {{ window.addEventListener('deviceorientation', handleOrientation, true); }}
            }}).catch(console.error);
        }} else {{
            window.addEventListener('deviceorientationabsolute', handleOrientation, true);
            window.addEventListener('deviceorientation', handleOrientation, true);
        }}

        if (navigator.geolocation) {{
            watchId = navigator.geolocation.watchPosition(updateNav, handleError, {{ enableHighAccuracy: true, maximumAge: 1000, timeout: 5000 }});
        }}
    }};

    window.stopNav = function() {{
        isNavigating = false;
        mapLocked = false;
        if(watchId) navigator.geolocation.clearWatch(watchId);
        
        window.removeEventListener('deviceorientation', handleOrientation, true);
        window.removeEventListener('deviceorientationabsolute', handleOrientation, true);

        document.getElementById('nav-dashboard').style.display = 'none';
        document.getElementById('search-container').style.display = 'block';
        document.getElementById('filter-panel').style.display = 'block';
        document.getElementById('recenter-btn').style.display = 'none';
        
        // Resize map back up when dashboard closes
        setTimeout(function() {{ map.invalidateSize(); }}, 50);
        
        if(routeLine) map.removeLayer(routeLine);
        if(targetMarker) map.removeLayer(targetMarker);
        if(userMarker) map.removeLayer(userMarker);
        routeLine = null; targetMarker = null; userMarker = null;
        map.setView([34.18, -83.98], 11);
    }};

    function updateNav(position) {{
        if(!isNavigating || !currentTarget) return;
        
        lastLat = position.coords.latitude;
        lastLon = position.coords.longitude;
        var userLatLng = [lastLat, lastLon];
        var targetLatLng = [currentTarget.lat, currentTarget.lon];

        // Draw/Update the Precision Arrow Icon
        if (!userMarker) {{
            let arrowHtml = `
            <div id="map-nav-arrow" class="nav-arrow-marker" style="transform: rotate(${{currentHeading}}deg);">
                <svg viewBox="0 0 24 24" width="40" height="40" style="filter: drop-shadow(0px 3px 5px rgba(0,0,0,0.5));">
                    <path d="M12 2L22 22L12 18L2 22L12 2Z" fill="#3498db" stroke="#ffffff" stroke-width="2"/>
                </svg>
            </div>`;
            var icon = L.divIcon({{className: '', html: arrowHtml, iconSize: [40, 40], iconAnchor: [20, 20]}});
            userMarker = L.marker(userLatLng, {{icon: icon, zIndexOffset: 1000}}).addTo(map);
        }} else {{
            userMarker.setLatLng(userLatLng);
        }}

        if (mapLocked) {{ map.setView(userLatLng, 15, {{animate: true}}); }}

        if (!routeLine) {{
            routeLine = L.polyline([userLatLng, targetLatLng], {{color: '#3498db', weight: 4, dashArray: '8, 8'}}).addTo(map);
        }} else {{
            routeLine.setLatLngs([userLatLng, targetLatLng]);
        }}

        const dist = getDistance(lastLat, lastLon, currentTarget.lat, currentTarget.lon);
        document.getElementById("gps-dist").innerText = dist.toFixed(2);

        let speed_val = 0;
        if (position.coords.speed != null) {{
            speed_val = isMetric ? (position.coords.speed * 3.6) : (position.coords.speed * 2.23694); 
            document.getElementById("gps-speed").innerText = speed_val.toFixed(1);
        }} else {{
            document.getElementById("gps-speed").innerText = "0.0";
        }}

        if (speed_val > 2) {{
            const hours = dist / speed_val;
            const mins = Math.round(hours * 60);
            document.getElementById("gps-eta").innerText = mins + " mins";
        }} else {{
            document.getElementById("gps-eta").innerText = "Start moving...";
        }}
        
        updateCompassUI();
    }}

    function handleError(error) {{
        console.warn(error);
        document.getElementById("gps-eta").innerText = "GPS Access Denied";
    }}
    </script>
</body>
</html>
"""
st.components.v1.html(nav_html, height=570)

# --- Utilities ---
st.markdown("---")
with st.expander("✅ Pre-Departure Checklist"):
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

with st.expander("🌉 Bridge Clearance Calculator"):
    st.markdown("Calculate clearance based on the live water level.")
    boat_height = st.number_input("Boat Height Above Waterline (ft)", min_value=1.0, step=0.5, value=12.0)
    if d['level'] != "N/A":
        browns_clearance_full = 53.0
        boling_clearance_full = 54.0
        current_browns = browns_clearance_full + (FULL_POOL_FT - d['level'])
        current_boling = boling_clearance_full + (FULL_POOL_FT - d['level'])
        
        st.markdown(f"**Browns Bridge Clearance:** {round(current_browns, 1)} ft")
        if current_browns > boat_height: st.success("🟢 Safe to pass Browns Bridge")
        else: st.error("🔴 DO NOT PASS Browns Bridge")
            
        st.markdown(f"**Boling Bridge Clearance:** {round(current_boling, 1)} ft")
        if current_boling > boat_height: st.success("🟢 Safe to pass Boling Bridge")
        else: st.error("🔴 DO NOT PASS Boling Bridge")
    else:
        st.warning("Lake level data currently unavailable.")