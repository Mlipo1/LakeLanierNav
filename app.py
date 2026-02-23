import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
import re
import json
from datetime import datetime, timedelta

st.set_page_config(page_title="Lanier Navigator", layout="centered", page_icon="⚓")

# --- Persistent State Management (URL Query Params) ---
# 1. Initialize state from saved URL parameters (Acts like cookies)
if "dark_mode" not in st.session_state:
    # Default to dark mode if no saved preference exists
    saved_theme = st.query_params.get("theme", "dark") 
    st.session_state.dark_mode = (saved_theme == "dark")
    
if "is_metric" not in st.session_state:
    # Default to imperial if no saved preference exists
    saved_unit = st.query_params.get("units", "imperial") 
    st.session_state.is_metric = (saved_unit == "metric")

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

def calculate_boat_score(d, wave):
    score = 100
    reasons = []

    # 1. Wind & Gusts (Safety & Comfort)
    wind_penalty = d["wind_mph"] * 1.5
    gust_penalty = (d["gusts"] - d["wind_mph"]) * 1.0 if d["gusts"] > d["wind_mph"] else 0
    score -= (wind_penalty + gust_penalty)
    if d["wind_mph"] > 12: reasons.append("Significant wind/gusts")

    # 2. Rain & Clouds (Comfort)
    score -= (d["rain_chance"] * 0.6)
    if d["rain_chance"] > 40: reasons.append(f"{d['rain_chance']}% Rain chance")

    # 3. Wave Height (Safety)
    score -= (wave * 10)
    if wave > 1.5: reasons.append("High surface chop")

    # 4. Water Temp (Safety - Hypothermia Risk)
    if d["water_temp"] < 60:
        score -= 15
        reasons.append("Dangerously cold water")
    elif d["water_temp"] < 70:
        score -= 5
        reasons.append("Chilly water")

    # 5. Visibility (Safety)
    if d["visibility"] != "N/A" and d["visibility"] < 4:
        score -= 10
        reasons.append("Low visibility/Fog")

    # 6. Lake Level (Hazard)
    if d['level'] != "N/A":
        level_diff = abs(FULL_POOL_FT - d['level'])
        if level_diff > 3:
            score -= (level_diff * 2)
            reasons.append("Off-pool hazards")

    final_score = max(0, min(100, round(score)))
    return final_score, reasons

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

# --- INITIALIZE DATA SO ALERTS CAN BE SHOWN AT TOP ---
d = fetch_data()
trend_24h = fetch_level_trend()
wave_height = round(0.016 * (d["wind_mph"] ** 1.5), 1)
alerts = get_safety_alert(d, wave_height)

# Metric Conversions
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

# --- UI Theme Definitions ---
theme = {
    "bg": "#0e1117" if st.session_state.dark_mode else "#f0f2f6",
    "card_bg": "#1e2130" if st.session_state.dark_mode else "#ffffff",
    "text": "#fafafa" if st.session_state.dark_mode else "#2c3e50",
    "sub_text": "#a0aab5" if st.session_state.dark_mode else "#6c757d",
    "border": "#333847" if st.session_state.dark_mode else "#d1d8e0",
    "map_tiles": "CartoDB dark_matter" if st.session_state.dark_mode else "CartoDB positron"
}

# --- Dynamic Color & Animation Variables ---
# Determine Dynamic Backgrounds for Temperatures
temp_bg = theme['card_bg']
if d['air_temp'] != "N/A":
    if d['air_temp'] >= 80: temp_bg = "linear-gradient(135deg, #2c1a1a, #3a2020)" if st.session_state.dark_mode else "linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)"
    elif d['air_temp'] <= 55: temp_bg = "linear-gradient(135deg, #1a252c, #1f303a)" if st.session_state.dark_mode else "linear-gradient(135deg, #e0c3fc 0%, #8ec5fc 100%)"

water_temp_bg = theme['card_bg']
if d['water_temp'] >= 80: water_temp_bg = "linear-gradient(135deg, #2c1a1a, #3a2020)" if st.session_state.dark_mode else "linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)"
elif d['water_temp'] <= 60: water_temp_bg = "linear-gradient(135deg, #1a252c, #1f303a)" if st.session_state.dark_mode else "linear-gradient(135deg, #e0c3fc 0%, #8ec5fc 100%)"

# Determine Wind & UV Animations
is_windy = d['wind_mph'] >= 15 or d['gusts'] >= 20
wind_anim_class = "wind-shake" if is_windy else "animated-wind"
wind_icon_color = "#ff7675" if is_windy else "#ffffff"

is_high_uv = d['uv'] > 6
uv_anim_class = "uv-pulse" if is_high_uv else ""

st.markdown(f"""
    <style>
    html, body, [data-testid="stAppViewContainer"], .stApp {{ overflow-x: hidden !important; max-width: 100vw !important; }}
    * {{ box-sizing: border-box !important; }}
    .stApp {{ background-color: {theme['bg']} !important; }}
    h3, div[data-testid="stWidgetLabel"] p, p {{ color: {theme['text']} !important; font-weight: 600; }}
    
    .main-title {{ color: {theme['text']} !important; font-weight: 800; font-size: clamp(1.8rem, 5vw, 2.5rem); white-space: nowrap; margin-bottom: 0px; margin-top: 15px; }}
    
    div[data-testid="stToggle"] {{ background-color: {theme['card_bg']}; padding: 8px 15px; border-radius: 20px; border: 1px solid {theme['border']}; margin-bottom: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }}
    div[data-testid="stToggle"] label div[role="switch"] {{ background-color: #a0aab5 !important; }}
    div[data-testid="stToggle"] label div[role="switch"][aria-checked="true"] {{ background-color: #3498db !important; }}
    
    .alert-expander {{ background: #e74c3c; border-radius: 12px; color: white; margin-top: 5px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.2); }}
    .alert-summary {{ padding: 15px; font-weight: 800; cursor: pointer; display: flex; align-items: center; justify-content: space-between; list-style: none; }}
    .alert-summary::-webkit-details-marker {{ display: none; }}
    .alert-content {{ padding: 0 15px 15px 15px; font-weight: 600; font-size: 0.95rem; line-height: 1.4; }}
    
    .metrics-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 15px; }}
    .metric-card {{ background: {theme['card_bg']}; border-radius: 15px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); text-align: center; border: 1px solid {theme['border']}; display: flex; flex-direction: column; justify-content: center; transition: background 0.5s ease; }}
    .metric-title {{ color: {theme['sub_text']}; font-size: 0.85rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
    .metric-value {{ color: {theme['text']}; font-size: 2.2rem; font-weight: 900; line-height: 1.1; }}
    .metric-sub {{ font-size: 0.8rem; font-weight: 600; margin-top: 5px; color: {theme['sub_text']}; line-height: 1.3; }}
    .text-red {{ color: #e74c3c; }}
    
    .pill-container {{ display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-bottom: 25px; margin-top: 5px; }}
    .info-pill {{ background: {theme['card_bg']}; border: 1px solid {theme['border']}; border-radius: 30px; padding: 8px 15px; color: {theme['text']}; font-size: 0.85rem; font-weight: 600; text-align: center; flex: 1 1 calc(33% - 10px); min-width: 130px; box-shadow: 0 2px 5px rgba(0,0,0,0.02); transition: all 0.3s; }}
    
    /* NEW: Score Reasoning Pills */
    .reason-pill {{ display: inline-block; background: rgba(0,0,0,0.1); padding: 4px 12px; border-radius: 15px; font-size: 0.8rem; margin: 3px; font-weight: 700; border: 1px solid rgba(128,128,128,0.3); color: {theme['text']}; }}

    .wind-container {{ background: linear-gradient(135deg, #2c3e50, #3498db); border-radius: 20px; padding: 20px; color: white; box-shadow: 0 10px 20px rgba(0,0,0,0.15); margin-bottom: 25px; }}
    .wind-merged {{ display: flex; flex-direction: row; align-items: center; justify-content: space-around; gap: 20px; width: 100%; }}
    .wind-stats-box {{ background: rgba(0,0,0,0.25); padding: 15px 25px; border-radius: 15px; min-width: 50%; text-align: center; }}
    
    /* Wind Animations */
    @keyframes wind-pulse {{ 0% {{ transform: translateY(0px); opacity: 0.8; }} 50% {{ transform: translateY(-8px); opacity: 1; filter: drop-shadow(0px 0px 8px rgba(255, 255, 255, 0.8)); }} 100% {{ transform: translateY(0px); opacity: 0.8; }} }}
    .animated-wind {{ display: inline-block; animation: wind-pulse 2s infinite ease-in-out; }}
    
    @keyframes wind-shake-anim {{ 0% {{ transform: translateY(0px) rotate(0deg); }} 25% {{ transform: translateY(-3px) rotate(15deg); }} 50% {{ transform: translateY(-6px) rotate(0deg); }} 75% {{ transform: translateY(-3px) rotate(-15deg); }} 100% {{ transform: translateY(0px) rotate(0deg); }} }}
    .wind-shake {{ display: inline-block; animation: wind-shake-anim 0.4s infinite ease-in-out; filter: drop-shadow(0px 0px 10px rgba(255, 118, 117, 0.9)); }}

    /* UV Animation */
    @keyframes uv-pulse-anim {{ 0% {{ box-shadow: 0 0 0 0 rgba(241, 196, 15, 0.7); }} 70% {{ box-shadow: 0 0 0 10px rgba(241, 196, 15, 0); }} 100% {{ box-shadow: 0 0 0 0 rgba(241, 196, 15, 0); }} }}
    .uv-pulse {{ animation: uv-pulse-anim 2s infinite; border-color: #f1c40f !important; color: #f1c40f !important; }}

    .sim-wave-box {{ position: relative; background: linear-gradient(to bottom, transparent 0%, rgba(52, 152, 219, 0.1) 100%); height: 100px; border-radius: 10px; overflow: hidden; margin-top: 15px; width: 100%; border-bottom: 3px solid #3498db; }}
    .sim-wave-back {{ position: absolute; bottom: 0; left: 0; width: 200%; height: 60px; background: url('data:image/svg+xml;utf8,<svg viewBox="0 0 1200 60" xmlns="http://www.w3.org/2000/svg"><path d="M0,30 C150,60 350,0 600,30 C850,60 1050,0 1200,30 L1200,60 L0,60 Z" fill="%232980b9" opacity="0.5"/></svg>') repeat-x; background-size: 50% 100%; transform-origin: bottom; animation: wave-move var(--wave-speed-back, 3s) linear infinite reverse; }}
    .sim-wave-front {{ position: absolute; bottom: 0; left: 0; width: 200%; height: 50px; background: url('data:image/svg+xml;utf8,<svg viewBox="0 0 1200 60" xmlns="http://www.w3.org/2000/svg"><path d="M0,30 C150,0 350,60 600,30 C850,0 1050,60 1200,30 L1200,60 L0,60 Z" fill="%233498db" opacity="0.8"/></svg>') repeat-x; background-size: 50% 100%; transform-origin: bottom; animation: wave-move var(--wave-speed-front, 2.5s) linear infinite; }}
    @keyframes wave-move {{ 0% {{ transform: translateX(0) scaleY(var(--wave-scale, 1)); }} 100% {{ transform: translateX(-50%) scaleY(var(--wave-scale, 1)); }} }}

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

# --- Top Header & Controls ---
col_title, col_controls = st.columns([2.2, 1.8])
with col_title:
    st.markdown('<h1 class="main-title">⚓ Lanier Navigator</h1>', unsafe_allow_html=True)

with col_controls:
    st.write("") 
    
    # Theme Toggle
    theme_lbl = "🌙 Dark Theme" if st.session_state.dark_mode else "☀️ Light Theme"
    new_theme = st.toggle(theme_lbl, value=st.session_state.dark_mode)
    if new_theme != st.session_state.dark_mode:
        st.session_state.dark_mode = new_theme
        # Silently update the URL so the browser remembers this choice
        st.query_params["theme"] = "dark" if new_theme else "light" 
        st.rerun()
        
    # Units Toggle
    unit_lbl = "📏 Metric Units" if st.session_state.is_metric else "📏 Imperial Units"
    new_unit = st.toggle(unit_lbl, value=st.session_state.is_metric)
    if new_unit != st.session_state.is_metric:
        st.session_state.is_metric = new_unit
        # Silently update the URL so the browser remembers this choice
        st.query_params["units"] = "metric" if new_unit else "imperial" 
        st.rerun()

# --- TOP PRIORITY: SAFETY BANNER ---
if alerts:
    alert_items = "".join([f"<div style='margin-bottom: 8px;'>{a}</div>" for a in alerts])
    alert_count = len(alerts)
    st.markdown(f"""
    <details class="alert-expander" open>
        <summary class="alert-summary">
            <span>⚠️ IMPORTANT SAFETY ALERTS ({alert_count})</span>
            <span style="font-size: 0.8rem; opacity: 0.9; text-transform: uppercase;">Tap to toggle</span>
        </summary>
        <div class="alert-content">{alert_items}</div>
    </details>
    """, unsafe_allow_html=True)

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
    <div class="metric-card" style="background: {water_temp_bg};">
        <div class="metric-title">Water Temp</div>
        <div class="metric-value" style="color:{temp_color};">{disp_water_temp}{unit_temp}</div>
        <div class="metric-sub">Surface</div>
    </div>
    <div class="metric-card" style="background: {temp_bg};">
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
    <div class="info-pill {uv_anim_class}">☀️ UV: {round(d["uv"],1)}</div>
</div>
""", unsafe_allow_html=True)

# --- Boating Score ---
st.markdown("### 🚦 Boating Conditions")
boat_score, score_reasons = calculate_boat_score(d, wave_height)

if boat_score >= 85: score_label, score_color = "🟢 Excellent", "#2ecc71"
elif boat_score >= 65: score_label, score_color = "🟡 Good", "#f1c40f"
elif boat_score >= 40: score_label, score_color = "🟠 Marginal", "#e67e22"
else: score_label, score_color = "🔴 Stay Home", "#e74c3c"

# Convert reasons into display pills
reasons_html = "".join([f'<span class="reason-pill">{r}</span>' for r in score_reasons])
if not reasons_html: reasons_html = '<span class="reason-pill">Ideal Conditions</span>'

st.markdown(f"""
<div class="metric-card" style="padding: 15px; margin-bottom: 15px;">
    <div class="metric-title" style="margin-bottom: 5px;">Overall Boating Score</div>
    <div style="font-size: 2.5rem; font-weight: 900; color: {score_color}; line-height: 1; margin: 10px 0;">{boat_score}<span style="font-size: 1.2rem; color: {theme['sub_text']}">/100</span></div>
    <div class="metric-sub" style="font-size: 1rem; margin-bottom: 10px;">{score_label} (Based on level, wind, rain & waves)</div>
    <div style="margin-top: 5px;">{reasons_html}</div>
</div>
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
<div class="{wind_anim_class}">
<svg width="45" height="45" viewBox="0 0 24 24" fill="none" stroke="{wind_icon_color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
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

places = [
    {"name":"Pig Tales (Aqualand)","lat":34.1805,"lon":-83.9515,"type":"Dining","hours":"Daily 11am - 10pm","web":"https://www.pigtaleslakelanier.com/"},
    {"name":"Fish Tales (Hideaway)","lat":34.1833,"lon":-83.9392,"type":"Dining","hours":"Daily 11am - 10pm","web":"https://www.fishtaleslakelanier.com/"},
    {"name":"Pelican Pete's","lat":34.2432,"lon":-83.9617,"type":"Dining","hours":"Fri-Sun 11am - 9pm","web":"https://www.pelicanpetes.com/"},
    {"name":"Twisted Oar","lat":34.1692,"lon":-84.0047,"type":"Dining","hours":"Daily 11am - 10pm","web":"https://www.twistedoar.com/"},
    {"name":"LandShark (Margaritaville)","lat":34.1852,"lon":-84.0150,"type":"Dining","hours":"Daily 11am - 10pm","web":"https://www.margaritavilleresorts.com/"},
    {"name":"Holiday Marina (Gas)","lat":34.1712,"lon":-84.0047,"type":"Fuel","hours":"Daily 9am - 6pm","web":"https://holidaylakelanier.com/"},
    {"name":"Sunset Cove (Gas)","lat":34.1830,"lon":-84.0180,"type":"Fuel","hours":"Daily 9am - 6pm","web":"https://www.margaritavilleresorts.com/"},
    {"name":"Aqualand Marina","lat":34.1793,"lon":-83.9538,"type":"Marina","hours":"Daily 9am - 5pm","web":"https://shmarinas.com/"},
    {"name":"Port Royale Marina","lat":34.2450,"lon":-83.9620,"type":"Marina","hours":"Daily 8am - 5pm","web":"https://www.bestinboating.com/"}
]

places_json = json.dumps(places)
map_tile_url = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png" if st.session_state.dark_mode else "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
js_metric_flag = "true" if st.session_state.is_metric else "false"
dash_bg = "rgba(30, 33, 48, 0.95)" if st.session_state.dark_mode else "rgba(255, 255, 255, 0.95)"

nav_html = f"""
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body {{ margin: 0; padding: 0; font-family: -apple-system, sans-serif; background: transparent; touch-action: none; }}
        
        #map-container {{ position: relative; height: 600px; width: 100%; border-radius: 12px; overflow: hidden; border: 1px solid {theme['border']}; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
        #map {{ height: 100%; width: 100%; z-index: 1; }}
        
        /* Ultra-Slim Navigation Dashboard Overlay */
        #nav-dashboard {{
            position: absolute; bottom: 0; left: 0; width: 100%; z-index: 1001;
            background: {dash_bg}; backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
            color: {theme['text']}; padding: 12px 15px 15px 15px; border-top: 3px solid #3498db;
            box-sizing: border-box; border-radius: 20px 20px 0 0;
            transform: translateY(110%); transition: transform 0.3s cubic-bezier(0.1, 0.8, 0.2, 1);
            box-shadow: 0 -5px 20px rgba(0,0,0,0.3);
        }}
        #nav-dashboard.active {{ transform: translateY(0); }}
        
        .stats-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); text-align: center; margin-top: 5px; }}
        .stat-val {{ font-size: 1.6rem; font-weight: 900; line-height: 1.2; }}
        .stat-lbl {{ font-size: 0.7rem; opacity: 0.8; font-weight: bold; text-transform: uppercase; }}
        
        #search-container {{ position: absolute; top: 10px; left: 10px; z-index: 1000; width: 65%; max-width: 320px; }}
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
        .search-item {{ padding: 12px 15px; cursor: pointer; border-bottom: 1px solid {theme['border']}; color: {theme['text']}; font-size: 0.9rem; }}
        .search-item:last-child {{ border-bottom: none; }}
        .search-item:hover {{ background: rgba(52, 152, 219, 0.15); }}

        #filter-panel {{
            position: absolute; top: 10px; right: 10px; z-index: 1000;
            background: {dash_bg}; backdrop-filter: blur(5px); color: {theme['text']};
            padding: 8px 12px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.3);
            border: 1px solid {theme['border']}; font-size: 0.9rem; font-weight: bold;
        }}
        .filter-cb {{ margin-right: 6px; transform: scale(1.2); cursor: pointer; }}
        .filter-row {{ margin-bottom: 6px; display: flex; align-items: center; cursor: pointer; }}
        
        .map-marker {{
            width: 36px; height: 36px; background: white; border-radius: 50%; display: flex;
            align-items: center; justify-content: center; box-shadow: 0 3px 8px rgba(0,0,0,0.4);
            font-size: 20px; border: 2px solid white; transition: transform 0.2s;
        }}
        .map-marker:hover {{ transform: scale(1.2); }}
        .marker-dining {{ border-color: #e74c3c; background: #ffeaa7; }}
        .marker-fuel {{ border-color: #f39c12; background: #ffeaa7; }}
        .marker-marina {{ border-color: #3498db; background: #81ecec; }}
        
        .poi-label {{
            background: transparent !important; border: none !important; box-shadow: none !important; 
            color: {theme['text']} !important; font-weight: 900 !important; font-size: 0.95rem !important;
            text-shadow: 2px 2px 0 {theme['bg']}, -2px -2px 0 {theme['bg']}, 2px -2px 0 {theme['bg']}, -2px 2px 0 {theme['bg']} !important;
            opacity: 0 !important; pointer-events: none !important; transition: opacity 0.3s ease !important;
        }}
        #map.show-labels .poi-label {{ opacity: 1 !important; }}

        .nav-arrow-marker {{ display: flex; align-items: center; justify-content: center; transition: transform 0.1s linear; transform-origin: center center; }}
        .start-btn {{ background: #3498db; color: white; border: none; padding: 10px 15px; border-radius: 8px; font-weight: bold; font-size: 0.9rem; cursor: pointer; margin-top: 10px; width: 100%; }}
        .stop-btn {{ background: #e74c3c; color: white; border: none; padding: 6px 12px; border-radius: 15px; font-weight: bold; cursor: pointer; font-size: 0.8rem; }}
        
        #recenter-btn {{
            display: none; position: absolute; bottom: 120px; right: 20px; z-index: 1000;
            background: {theme['card_bg']}; color: #3498db; border: 2px solid #3498db;
            width: 44px; height: 44px; border-radius: 50%; padding: 0;
            box-shadow: 0 4px 10px rgba(0,0,0,0.3); cursor: pointer;
            align-items: center; justify-content: center; transition: background 0.2s;
        }}
        #recenter-btn:active {{ background: #3498db; color: white; stroke: white; }}
        
        @media (max-width: 600px) {{
            #search-container {{ width: 90%; max-width: none; left: 5%; }}
            #filter-panel {{ top: 75px; right: 5%; display: flex; gap: 10px; padding: 8px 10px; }}
            .filter-row {{ margin-bottom: 0; font-size: 0.8rem; }}
        }}
    </style>
</head>
<body>
    <div id="map-container">
        
        <div id="search-container">
            <input type="text" id="poi-search" placeholder="🔍 Search destinations..." oninput="filterSearch()">
            <div id="search-results"></div>
        </div>

        <div id="filter-panel">
            <label class="filter-row"><input type="checkbox" class="filter-cb" value="Dining" checked onchange="renderMarkers()"> 🍔</label>
            <label class="filter-row"><input type="checkbox" class="filter-cb" value="Fuel" checked onchange="renderMarkers()"> ⛽</label>
            <label class="filter-row" style="margin-bottom:0;"><input type="checkbox" class="filter-cb" value="Marina" checked onchange="renderMarkers()"> ⚓</label>
        </div>

        <button id="recenter-btn" onclick="recenterMap()">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle><line x1="22" y1="12" x2="18" y2="12"></line><line x1="6" y1="12" x2="2" y2="12"></line><line x1="12" y1="6" x2="12" y2="2"></line><line x1="12" y1="22" x2="12" y2="18"></line>
            </svg>
        </button>

        <div id="nav-dashboard">
            <div style="font-size: 1.1rem; font-weight: 800; display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px;">
                <span id="nav-title" style="color:#3498db;">Navigating...</span>
                <button class="stop-btn" onclick="stopNav()">🛑 Stop</button>
            </div>
            
            <div class="stats-grid">
                <div><div class="stat-lbl">Speed</div><div class="stat-val" id="gps-speed">--</div><div style="font-size:0.6rem" id="lbl-speed">mph</div></div>
                <div><div class="stat-lbl">Distance</div><div class="stat-val" id="gps-dist" style="color:#e74c3c">--</div><div style="font-size:0.6rem" id="lbl-dist">miles</div></div>
                <div><div class="stat-lbl">ETA</div><div class="stat-val" id="gps-eta" style="color:#3498db">--</div><div style="font-size:0.6rem">mins</div></div>
            </div>
        </div>
        
        <div id="map"></div>
    </div>

    <script>
    var isMetric = {js_metric_flag};
    var map = L.map('map', {{ zoomControl: false }}).setView([34.18, -83.98], 11);
    L.tileLayer('{map_tile_url}', {{ attribution: '&copy; Carto' }}).addTo(map);

    var places = {places_json};
    var markersLayer = L.layerGroup().addTo(map);
    
    var iconMap = {{
        "Dining": L.divIcon({{className: '', html: '<div class="map-marker marker-dining">🍔</div>', iconSize: [36,36], iconAnchor: [18,18], popupAnchor: [0,-18]}}),
        "Fuel": L.divIcon({{className: '', html: '<div class="map-marker marker-fuel">⛽</div>', iconSize: [36,36], iconAnchor: [18,18], popupAnchor: [0,-18]}}),
        "Marina": L.divIcon({{className: '', html: '<div class="map-marker marker-marina">⚓</div>', iconSize: [36,36], iconAnchor: [18,18], popupAnchor: [0,-18]}})
    }};

    var targetIcon = L.divIcon({{
        className: '', html: '<div style="font-size: 32px; text-shadow: 0 4px 8px rgba(0,0,0,0.5);">📍</div>', iconSize: [32,32], iconAnchor: [16,32], popupAnchor: [0,-32]
    }});

    window.renderMarkers = function() {{
        markersLayer.clearLayers();
        var checkboxes = document.querySelectorAll('.filter-cb');
        var activeFilters = Array.from(checkboxes).filter(cb => cb.checked).map(cb => cb.value);

        places.forEach((p, index) => {{
            if (activeFilters.includes(p.type)) {{
                var marker = L.marker([p.lat, p.lon], {{icon: iconMap[p.type] || iconMap["Dining"]}}).addTo(markersLayer);
                
                var tooltip = L.tooltip({{permanent: true, direction: 'bottom', className: 'poi-label', offset: [0, 8]}}).setContent(p.name);
                marker.bindTooltip(tooltip);

                var popupHTML = `
                    <div style="text-align: center; min-width: 150px; font-family: sans-serif;">
                        <b style="font-size: 1.1rem; color: #2c3e50; display:block; margin-bottom: 2px;">${{p.name}}</b>
                        <span style="font-size: 0.8rem; color: #7f8c8d; text-transform: uppercase; font-weight: bold;">${{p.type}}</span>
                        <div style="font-size: 0.85rem; margin: 10px 0; color: #333; background: #f0f2f6; padding: 5px; border-radius: 5px;">🕒 ${{p.hours}}</div>
                        <a href="${{p.web}}" target="_blank" style="font-size: 0.9rem; color: #3498db; text-decoration: none; font-weight: bold;">🌐 Website</a><br/>
                        <button class="start-btn" onclick="startNav(${{index}})">Navigate</button>
                    </div>
                `;
                marker.bindPopup(popupHTML);
            }}
        }});
    }};
    renderMarkers();

    function handleZoom() {{
        if (map.getZoom() >= 13) {{ document.getElementById('map').classList.add('show-labels'); }} 
        else {{ document.getElementById('map').classList.remove('show-labels'); }}
    }}
    map.on('zoomend', handleZoom);
    handleZoom();

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
        }} else {{ resultsDiv.style.display = "none"; }}
    }};

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
    var lockedScrollY = 0; // Remembers page position for unlocking

    // AGGRESSIVE SCREEN LOCK SCRIPT
    function executeScreenLock() {{
        try {{
            let iframe = window.frameElement;
            if (iframe) {{
                // Auto-scroll exactly to the map window, bypassing YouTube feed
                iframe.scrollIntoView({{behavior: "auto", block: "start"}});
            }}
            
            // Give browser 50ms to finish scrolling, then freeze it
            setTimeout(() => {{
                let sy = window.parent.scrollY || 0;
                lockedScrollY = sy;
                
                let parentStyle = window.parent.document.getElementById('nav-lock-style');
                if (!parentStyle) {{
                    parentStyle = window.parent.document.createElement('style');
                    parentStyle.id = 'nav-lock-style';
                    window.parent.document.head.appendChild(parentStyle);
                }}
                
                // Physically disable scrolling & hide Streamlit header
                parentStyle.innerHTML = `
                    header[data-testid="stHeader"] {{ display: none !important; }}
                    .stApp, [data-testid="stAppViewContainer"] {{
                        overflow: hidden !important;
                        position: fixed !important;
                        width: 100vw !important;
                        top: -${{sy}}px !important;
                        touch-action: none !important;
                    }}
                `;
            }}, 50);
        }} catch(e) {{ console.warn("Lock bypassed due to browser security"); }}
    }}

    function executeScreenUnlock() {{
        try {{
            let parentStyle = window.parent.document.getElementById('nav-lock-style');
            if (parentStyle) {{ parentStyle.innerHTML = ""; }}
            // Return user to original scroll position
            window.parent.scrollTo(0, lockedScrollY);
        }} catch(e) {{}}
    }}

    map.on('dragstart', function() {{
        if (isNavigating) {{
            mapLocked = false;
            document.getElementById('recenter-btn').style.display = 'flex';
        }}
    }});

    window.recenterMap = function() {{
        mapLocked = true;
        document.getElementById('recenter-btn').style.display = 'none';
        if (lastLat != null && lastLon != null) {{ 
            map.setView([lastLat, lastLon], 15, {{animate: true}}); 
        }}
    }};

    function handleOrientation(event) {{
        if(!isNavigating) return;
        let newHeading = 0;
        if (event.webkitCompassHeading) {{ newHeading = event.webkitCompassHeading; }} 
        else if (event.alpha != null) {{ newHeading = 360 - event.alpha; }}
        currentHeading = newHeading;
        
        let navArrow = document.getElementById('map-nav-arrow');
        if (navArrow) navArrow.style.transform = `rotate(${{currentHeading}}deg)`;
    }}

    function getDistance(lat1, lon1, lat2, lon2) {{
        const R = isMetric ? 6371 : 3958.8; 
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat/2) * Math.sin(dLat/2) + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon/2) * Math.sin(dLon/2);
        return R * (2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a)));
    }}

    window.startNav = function(index) {{
        currentTarget = places[index];
        map.closePopup();
        isNavigating = true;
        mapLocked = true;
        
        // 1. FOCUS MODE: Hide all other POIs
        markersLayer.clearLayers();

        // 2. TRIGGER SCREEN LOCK
        executeScreenLock();
        
        // 3. Update UI
        document.getElementById('nav-dashboard').classList.add('active');
        document.getElementById('search-container').style.display = 'none';
        document.getElementById('filter-panel').style.display = 'none';
        document.getElementById('recenter-btn').style.display = 'none';
        document.getElementById('nav-title').innerText = "To: " + currentTarget.name;
        document.getElementById('lbl-speed').innerText = isMetric ? "km/h" : "mph";
        document.getElementById('lbl-dist').innerText = isMetric ? "km" : "miles";

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

        // 1. TRIGGER SCREEN UNLOCK
        executeScreenUnlock();

        // 2. Restore all POIs
        renderMarkers();

        // 3. Update UI
        document.getElementById('nav-dashboard').classList.remove('active');
        document.getElementById('search-container').style.display = 'block';
        document.getElementById('filter-panel').style.display = 'flex';
        document.getElementById('recenter-btn').style.display = 'none';
        
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

        if (!userMarker) {{
            let arrowHtml = `
            <div id="map-nav-arrow" class="nav-arrow-marker" style="transform: rotate(${{currentHeading}}deg);">
                <svg viewBox="0 0 24 24" width="45" height="45" style="filter: drop-shadow(0px 4px 6px rgba(0,0,0,0.6));">
                    <path d="M12 2L22 22L12 18L2 22L12 2Z" fill="#3498db" stroke="#ffffff" stroke-width="2"/>
                </svg>
            </div>`;
            var icon = L.divIcon({{className: '', html: arrowHtml, iconSize: [45, 45], iconAnchor: [22, 22]}});
            userMarker = L.marker(userLatLng, {{icon: icon, zIndexOffset: 1000}}).addTo(map);
        }} else {{
            userMarker.setLatLng(userLatLng);
        }}

        if (mapLocked) {{ 
            map.setView(userLatLng, 15, {{animate: true}}); 
        }}

        if (!routeLine) {{
            routeLine = L.polyline([userLatLng, targetLatLng], {{color: '#3498db', weight: 5, dashArray: '10, 10'}}).addTo(map);
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
            document.getElementById("gps-eta").innerText = mins;
        }} else {{
            document.getElementById("gps-eta").innerText = "--";
        }}
    }}

    function handleError(error) {{
        console.warn(error);
        document.getElementById("gps-eta").innerText = "Err";
    }}
    </script>
</body>
</html>
"""
st.components.v1.html(nav_html, height=620)

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