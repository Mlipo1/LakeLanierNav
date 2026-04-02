import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
import re
import json
from datetime import datetime, timedelta

def _eastern_offset(utc_dt=None):
    """Return correct US Eastern UTC offset as timedelta, DST-aware via date math (works on UTC servers)."""
    if utc_dt is None:
        utc_dt = datetime.utcnow()
    year = utc_dt.year
    mar1 = datetime(year, 3, 1)
    dst_start = (mar1 + timedelta(days=(6 - mar1.weekday()) % 7 + 7)).replace(hour=7)  # 2nd Sun Mar, 2am EST
    nov1 = datetime(year, 11, 1)
    dst_end = (nov1 + timedelta(days=(6 - nov1.weekday()) % 7)).replace(hour=6)         # 1st Sun Nov, 2am EDT
    return timedelta(hours=4 if dst_start <= utc_dt < dst_end else 5)

st.set_page_config(page_title="Lanier Navigator", layout="centered", page_icon="⚓")

# --- Persistent State Management (URL Query Params) ---
if "dark_mode" not in st.session_state:
    saved_theme = st.query_params.get("theme", "dark")
    st.session_state.dark_mode = (saved_theme == "dark")

if "is_metric" not in st.session_state:
    saved_unit = st.query_params.get("units", "imperial")
    st.session_state.is_metric = (saved_unit == "metric")

# --- Data Fetching Functions ---
@st.cache_data(ttl=300)
def fetch_data():
    data = {
        "level": "N/A", "air_temp": "N/A", "water_temp": "N/A",
        "wind_mph": 0, "wind_dir": 0, "gusts": 0, "uv": 0,
        "sunrise": "N/A", "sunset": "N/A", "rain_chance": 0, "visibility": "N/A", "pressure": "N/A", "clouds": 0
    }

    # USGS Data — Lake Level + Water Temperature (parameter 00010 = water temp in Celsius)
    usgs_base = "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=02334400"

    for attempt in range(3):
        try:
            usgs_res = requests.get(f"{usgs_base}&parameterCd=00062", timeout=5).json()
            val = usgs_res['value']['timeSeries'][0]['values'][0]['value'][0]['value']
            data["level"] = float(val)
            break
        except Exception:
            if attempt == 2:
                st.cache_data.clear()
            import time
            time.sleep(1)

    # Water temp is now fetched separately via fetch_water_temps()
    data["water_temp"] = "N/A"

    # Weather Data
    try:
        API_KEY = "Ctel2fkIkgMDlQPIx8rN7WDPjxCLRNDY"
        pw_url = f"https://api.pirateweather.net/forecast/{API_KEY}/34.18,-83.98?units=us"
        response = requests.get(pw_url, timeout=10)
        response.raise_for_status()
        pw_res = response.json()
        currently = pw_res.get('currently', {})
        daily_data = pw_res.get('daily', {}).get('data', [{}])[0]

        data["air_temp"] = currently.get('temperature', "N/A")
        data["wind_mph"] = currently.get('windSpeed', 0)
        data["wind_dir"] = currently.get('windBearing', 0)
        data["gusts"] = currently.get('windGust', 0)
        data["uv"] = currently.get('uvIndex', 0)
        data["visibility"] = currently.get('visibility', "N/A")
        data["pressure"] = currently.get('pressure', "N/A")

        clouds = currently.get('cloudCover', 0)
        data["clouds"] = int(clouds * 100) if clouds is not None else 0

        rain_prob = currently.get('precipProbability', daily_data.get('precipProbability', 0))
        data["rain_chance"] = int(rain_prob * 100) if rain_prob is not None else 0

        if 'sunriseTime' in daily_data:
            sr_utc = datetime.utcfromtimestamp(daily_data['sunriseTime'])
            data["sunrise"] = (sr_utc - _eastern_offset(sr_utc)).strftime("%I:%M %p")
        if 'sunsetTime' in daily_data:
            ss_utc = datetime.utcfromtimestamp(daily_data['sunsetTime'])
            data["sunset"] = (ss_utc - _eastern_offset(ss_utc)).strftime("%I:%M %p")

    except Exception as e:
        st.error(f"🚨 Pirate Weather Fetch Error: {str(e)}")

    now_est = datetime.utcnow() - _eastern_offset()
    data["last_updated"] = now_est.strftime("%I:%M %p")

    return data


@st.cache_data(ttl=300)
def fetch_water_temps():
    """
    Pulls water temperature from multiple sources for Lake Lanier.
    Sources:
      1. USGS Chattahoochee R. below Buford Dam (02334430) - param 00010 - outflow temp sensor, most reliable
      2. USGS Flowery Branch gauge (02334480) - param 00010
      3. Omnia Fishing - scrapes their Lake Lanier current conditions page
      4. Lake Monster scrape (fallback HTML)

    NOTE: Open-Meteo ERA5 lake surface temp has been removed - it lags reality by
    weeks and consistently reads 10-15°F too warm for Lake Lanier.
    USGS 02334400 (Buford Dam reservoir gauge) does NOT have a 00010 water temp
    sensor - it only reports elevation/level data.
    """
    import statistics

    readings = {}

    # ---- Source 1: USGS Chattahoochee R. Below Buford Dam (02334430) ----
    # This gauge is ON the outflow of Buford Dam — measures actual released water temp
    try:
        url = "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=02334430&parameterCd=00010"
        res = requests.get(url, timeout=6).json()
        ts = res['value']['timeSeries']
        if ts:
            val_raw = ts[0]['values'][0]['value'][0]['value']
            val_c = float(val_raw)
            # Sanity check: water temp in lake should be 35-85°F year-round
            val_f = round(val_c * 9 / 5 + 32, 1)
            if 35 <= val_f <= 85:
                readings["USGS Below Buford Dam"] = val_f
    except Exception:
        pass

    # ---- Source 2: USGS Flowery Branch (02334480) ----
    try:
        url = "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=02334480&parameterCd=00010"
        res = requests.get(url, timeout=6).json()
        ts = res['value']['timeSeries']
        if ts:
            val_c = float(ts[0]['values'][0]['value'][0]['value'])
            val_f = round(val_c * 9 / 5 + 32, 1)
            if 35 <= val_f <= 85:
                readings["USGS Flowery Branch"] = val_f
    except Exception:
        pass

    # ---- Source 3: Omnia Fishing scrape ----
    try:
        url = "https://www.omniafishing.com/w/lake-lanier-fishing-reports/current-conditions"
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; LanierNav/1.0)'}
        res = requests.get(url, headers=headers, timeout=7)
        # Look for temperature pattern like "47º" or "47°F" or "47 F"
        match = re.search(r'(\d{2,3})\s*[º°]\s*(?:F(?:ahrenheit)?)?', res.text)
        if match:
            val = int(match.group(1))
            if 35 <= val <= 85:
                readings["Omnia Fishing"] = float(val)
    except Exception:
        pass

    # ---- Source 4: Lake Monster scrape ----
    try:
        lm_url = "https://lakemonster.com/lake/GA/Lake-Lanier-234"
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; LanierNav/1.0)'}
        lm_res = requests.get(lm_url, headers=headers, timeout=6)
        match = re.search(r'(\d{2,3})(?:\s*°|\s*&deg;|\s*deg)?\s*F', lm_res.text, re.IGNORECASE)
        if match:
            scraped = int(match.group(1))
            if 35 <= scraped <= 85:
                readings["Lake Monster"] = float(scraped)
    except Exception:
        pass

    # ---- Compute stats ----
    if not readings:
        return {
            "sources": {},
            "median": "N/A",
            "high": "N/A",
            "low": "N/A",
            "confidence": "No data"
        }

    vals = list(readings.values())
    median_val = round(statistics.median(vals), 1)
    high_val = round(max(vals), 1)
    low_val = round(min(vals), 1)

    n = len(vals)
    confidence = "High" if n >= 3 else "Medium" if n == 2 else "Low (1 source)"

    return {
        "sources": readings,
        "median": median_val,
        "high": high_val,
        "low": low_val,
        "confidence": confidence
    }


@st.cache_data(ttl=300)
def fetch_water_temp_history():
    """Fetch 24h water temperature history from USGS Below Buford Dam (02334430) — has actual temp sensor."""
    try:
        end = datetime.utcnow()
        start = end - timedelta(hours=24)
        url = (
            f"https://waterservices.usgs.gov/nwis/iv/?format=json&sites=02334430"
            f"&parameterCd=00010"
            f"&startDT={start.isoformat()}&endDT={end.isoformat()}"
        )
        res = requests.get(url, timeout=6).json()
        values = res['value']['timeSeries'][0]['values'][0]['value']

        _et_offset = _eastern_offset()

        chart_points = []
        for v in values:
            try:
                dt_str = v['dateTime'][:16]
                dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M") - _et_offset
                temp_c = float(v['value'])
                temp_f = round(temp_c * 9 / 5 + 32, 1)
                chart_points.append((dt.strftime("%H:%M"), temp_f))
            except Exception:
                continue

        # Thin to ~24 points
        step = max(1, len(chart_points) // 24)
        return chart_points[::step]
    except Exception:
        return []


@st.cache_data(ttl=300)
def fetch_level_trend():
    """Returns (trend_24h_delta, list of (timestamp_str, level_ft)) for charting."""
    try:
        end = datetime.utcnow()
        start = end - timedelta(hours=24)
        url = (
            f"https://waterservices.usgs.gov/nwis/iv/?format=json&sites=02334400"
            f"&parameterCd=00062"
            f"&startDT={start.isoformat()}&endDT={end.isoformat()}"
        )
        res = requests.get(url, timeout=5).json()
        values = res['value']['timeSeries'][0]['values'][0]['value']

        chart_points = []
        for v in values:
            try:
                dt_str = v['dateTime'][:16]  # "2024-04-01T14:30"
                dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M") - _eastern_offset()
                level = float(v['value'])
                chart_points.append((dt.strftime("%H:%M"), level))
            except Exception:
                continue

        # Thin to ~24 points max for rendering
        step = max(1, len(chart_points) // 24)
        chart_points = chart_points[::step]

        first = float(values[0]['value'])
        last = float(values[-1]['value'])
        trend = round(last - first, 2)
        return trend, chart_points
    except Exception:
        return 0, []


def get_compass_dir(degrees):
    dirs = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    return dirs[int(round(degrees / (360. / len(dirs)))) % len(dirs)]


def calculate_chop(wind, gusts):
    avg_force = (wind + gusts) / 2
    if avg_force < 5:
        return "Glassy", "#a2de96"
    elif avg_force < 12:
        return "Light Chop", "#a2de96"
    elif avg_force < 20:
        return "Choppy (Small Boat Caution)", "#fde047"
    else:
        return "Rough / Whitecaps", "#fca5a5"


FULL_POOL_FT = 1071.0


def calculate_boat_score(d, wave):
    score = 100
    reasons = []
    weights = {}

    # 1. Wind & Gusts (max penalty ~45 pts at 25mph sustained)
    wind_penalty = min(d["wind_mph"] * 1.2, 30)
    gust_bonus_penalty = min(max(d["gusts"] - d["wind_mph"], 0) * 0.8, 15)
    score -= (wind_penalty + gust_bonus_penalty)
    weights["wind"] = wind_penalty + gust_bonus_penalty
    if d["wind_mph"] > 10:
        reasons.append(f"Wind {d['wind_mph']}mph")
    if d["gusts"] > 18:
        reasons.append(f"Gusts {d['gusts']}mph")

    # 2. Rain (max -30)
    rain_penalty = min(d["rain_chance"] * 0.45, 30)
    score -= rain_penalty
    weights["rain"] = rain_penalty
    if d["rain_chance"] > 35:
        reasons.append(f"{d['rain_chance']}% Rain chance")

    # 3. Wave Height (max -25)
    wave_penalty = min(wave * 8, 25)
    score -= wave_penalty
    weights["waves"] = wave_penalty
    if wave > 1.5:
        reasons.append("High surface chop")

    # 4. Water Temperature — cold water shock risk
    wt = d["water_temp"]
    if wt != "N/A":
        wt = float(wt)
        if wt < 40:
            score -= 30
            reasons.append("Dangerous Cold (<40°F): Shock risk")
        elif wt < 50:
            score -= 22
            reasons.append("Very Cold (<50°F): Rapid hypothermia risk")
        elif wt < 60:
            score -= 12
            reasons.append("Cold (50-60°F): Wetsuit recommended")
        elif wt < 70:
            score -= 4
            reasons.append("Cool (60-70°F): May be uncomfortable")

    # 5. Air temperature comfort
    if d["air_temp"] != "N/A":
        at = float(d["air_temp"])
        if at < 32:
            score -= 15
            reasons.append("Freezing air temp")
        elif at < 45:
            score -= 6
            reasons.append("Cold air (<45°F)")
        elif at > 95:
            score -= 5
            reasons.append("Extreme heat (>95°F)")

    # 6. Visibility
    if d["visibility"] != "N/A" and float(d["visibility"]) < 4:
        penalty = min((4 - float(d["visibility"])) * 4, 15)
        score -= penalty
        reasons.append("Low visibility/Fog")

    # 7. Lake Level — shallow hazards & debris
    if d['level'] != "N/A":
        pool_diff = d['level'] - FULL_POOL_FT
        if pool_diff < -5:
            penalty = min(abs(pool_diff) * 2.5, 20)
            score -= penalty
            reasons.append("Very Low Water: Shoal hazards")
        elif pool_diff < -3:
            penalty = min(abs(pool_diff) * 1.5, 12)
            score -= penalty
            reasons.append("Low Water: Watch for shoals")
        elif pool_diff > 5:
            penalty = min(pool_diff * 1.5, 12)
            score -= penalty
            reasons.append("High Water: Floating debris")
        elif pool_diff > 3:
            penalty = min(pool_diff * 1.0, 8)
            score -= penalty
            reasons.append("Above full pool: Debris risk")

    # 8. UV — sunburn risk flagging (informational, -5 max)
    if d["uv"] > 8:
        score -= 3
        reasons.append(f"High UV ({d['uv']}): Sun protection needed")

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

    wt = d["water_temp"]
    if wt != "N/A":
        wt = float(wt)
        if wt < 40:
            alerts.append("🥶 <strong>EXTREME Cold Water:</strong> Water is <40°F. Cold shock can cause immediate cardiac arrest. Do NOT enter water. Wear life jacket at all times.")
        elif wt < 50:
            alerts.append("🥶 <strong>Extreme Cold Water:</strong> Water is <50°F. Immediate life-threatening hypothermia risk if submerged. Wear life jackets.")

    if d["air_temp"] != "N/A" and d["air_temp"] <= 32:
        alerts.append("❄️ <strong>Freezing Conditions:</strong> Watch for black ice on boat ramps and slippery decks.")

    try:
        now_est = datetime.utcnow() - _eastern_offset()
        curr_mins = now_est.time().hour * 60 + now_est.time().minute
        ss_time = datetime.strptime(d["sunset"], "%I:%M %p").time()
        ss_mins = ss_time.hour * 60 + ss_time.minute

        if curr_mins >= ss_mins:
            alerts.append("🌙 <strong>Night Operations:</strong> Sun has set. Navigational lights are required by law.")
        elif (ss_mins - curr_mins) <= 45:
            alerts.append("🌇 <strong>Approaching Sunset:</strong> Less than 45 minutes of daylight. Prepare navigation lights.")
    except Exception:
        pass

    if d['level'] != "N/A":
        pool_diff = d['level'] - FULL_POOL_FT
        if pool_diff < -5:
            alerts.append("📉 <strong>Very Low Water:</strong> Lake is >5ft below full pool. Many ramps and docks unusable. Extreme shoal risk.")
        elif pool_diff < -3:
            alerts.append("📉 <strong>Low Water Hazard:</strong> Lake is >3ft down. Watch for newly exposed shoals. Fixed docks and ramps may be unusable.")
        elif pool_diff > 3:
            alerts.append("🪵 <strong>High Water Warning:</strong> Lake is above full pool. Watch for floating debris and submerged dock structures.")

    return alerts


# --- INITIALIZE DATA ---
d = fetch_data()
wt_data = fetch_water_temps()
wt_history = fetch_water_temp_history()

# Inject median water temp back into d so safety alerts / boating score still work
if wt_data["median"] != "N/A":
    d["water_temp"] = wt_data["median"]

trend_24h, chart_points = fetch_level_trend()
wave_height = round(0.016 * (d["wind_mph"] ** 1.5), 1)
alerts = get_safety_alert(d, wave_height)

now_est = datetime.utcnow() - _eastern_offset()

# Metric Conversions
if st.session_state.is_metric:
    unit_dist, unit_temp, unit_speed, unit_vis, unit_press = "m", "°C", "km/h", "km", "hPa"
    disp_level = round(d['level'] * 0.3048, 2) if d['level'] != "N/A" else "N/A"
    disp_pool_diff = round(abs((d['level'] - FULL_POOL_FT) * 0.3048), 2) if d['level'] != "N/A" else "N/A"
    disp_water_temp = round((float(wt_data['median']) - 32) * 5 / 9, 1) if wt_data['median'] != "N/A" else "N/A"
    disp_water_high = round((wt_data['high'] - 32) * 5 / 9, 1) if wt_data['high'] != "N/A" else "N/A"
    disp_water_low  = round((wt_data['low']  - 32) * 5 / 9, 1) if wt_data['low']  != "N/A" else "N/A"
    disp_air_temp = round((d['air_temp'] - 32) * 5 / 9, 1) if d['air_temp'] != "N/A" else "N/A"
    disp_wind = round(d['wind_mph'] * 1.60934, 1)
    disp_gusts = round(d['gusts'] * 1.60934, 1)
    disp_vis = round(d['visibility'] * 1.60934, 1) if d['visibility'] != "N/A" else "N/A"
    disp_press = round(d['pressure'], 1) if d['pressure'] != "N/A" else "N/A"
    disp_wave = round(wave_height * 0.3048, 1)
else:
    unit_dist, unit_temp, unit_speed, unit_vis, unit_press = "'", "°F", "mph", "mi", "inHg"
    disp_level = round(d['level'], 2) if d['level'] != "N/A" else "N/A"
    disp_pool_diff = round(abs(d['level'] - FULL_POOL_FT), 2) if d['level'] != "N/A" else "N/A"
    disp_water_temp = wt_data['median'] if wt_data['median'] != "N/A" else "N/A"
    disp_water_high = wt_data['high']   if wt_data['high']   != "N/A" else "N/A"
    disp_water_low  = wt_data['low']    if wt_data['low']    != "N/A" else "N/A"
    disp_air_temp = round(d['air_temp'], 1) if d['air_temp'] != "N/A" else "N/A"
    disp_wind = round(d['wind_mph'], 1)
    disp_gusts = round(d['gusts'], 1)
    disp_vis = round(d['visibility'], 1) if d['visibility'] != "N/A" else "N/A"
    disp_press = round(d['pressure'] * 0.02953, 2) if d['pressure'] != "N/A" else "N/A"
    disp_wave = wave_height

direction_text = get_compass_dir(d['wind_dir'])
chop_text, chop_color = calculate_chop(d['wind_mph'], d['gusts'])
wind_rotation = d['wind_dir']

# --- UI Theme ---
theme = {
    "bg": "#0e1117" if st.session_state.dark_mode else "#f0f2f6",
    "card_bg": "#1e2130" if st.session_state.dark_mode else "#ffffff",
    "text": "#fafafa" if st.session_state.dark_mode else "#2c3e50",
    "sub_text": "#a0aab5" if st.session_state.dark_mode else "#6c757d",
    "border": "#333847" if st.session_state.dark_mode else "#d1d8e0",
    "map_tiles": "CartoDB dark_matter" if st.session_state.dark_mode else "CartoDB positron"
}

is_windy = d['wind_mph'] >= 15 or d['gusts'] >= 20
wind_anim_class = "wind-shake" if is_windy else "animated-wind"
wind_icon_color = "#ff7675" if is_windy else "#ffffff"

st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;800;900&family=Barlow:wght@400;500;600;700&display=swap');

    html, body, [data-testid="stAppViewContainer"], .stApp {{ overflow-x: hidden !important; max-width: 100vw !important; box-sizing: border-box; }}
    * {{ box-sizing: border-box !important; }}
    .stApp {{ background-color: {theme['bg']} !important; font-family: 'Barlow', sans-serif !important; }}
    h3, div[data-testid="stWidgetLabel"] p, p {{ color: {theme['text']} !important; font-weight: 600; font-family: 'Barlow', sans-serif !important; }}

    .main-title {{ color: {theme['text']} !important; font-family: 'Barlow Condensed', sans-serif !important; font-weight: 900; font-size: clamp(1.6rem, 5vw, 2.4rem); white-space: nowrap; margin-bottom: 0px; margin-top: 15px; letter-spacing: -0.5px; }}
    .section-header {{ font-family: 'Barlow Condensed', sans-serif !important; font-weight: 800; font-size: 1.3rem; color: {theme['text']} !important; margin: 20px 0 10px 0; letter-spacing: 0.5px; text-transform: uppercase; }}

    div[data-testid="stToggle"] {{ background-color: {theme['card_bg']}; padding: 6px 12px; border-radius: 20px; border: 1px solid {theme['border']}; margin-bottom: 5px; }}
    div[data-testid="stToggle"] label div[role="switch"] {{ background-color: #a0aab5 !important; }}
    div[data-testid="stToggle"] label div[role="switch"][aria-checked="true"] {{ background-color: #3498db !important; }}

    .alert-expander {{ background: linear-gradient(135deg, #c0392b, #e74c3c); border-radius: 14px; color: white; margin-top: 5px; margin-bottom: 16px; box-shadow: 0 6px 20px rgba(231,76,60,0.35); }}
    .alert-summary {{ padding: 14px 16px; font-weight: 800; cursor: pointer; display: flex; align-items: center; justify-content: space-between; list-style: none; font-family: 'Barlow Condensed', sans-serif; font-size: 1.05rem; letter-spacing: 0.5px; }}
    .alert-summary::-webkit-details-marker {{ display: none; }}
    .alert-content {{ padding: 0 16px 14px 16px; font-weight: 500; font-size: 0.92rem; line-height: 1.5; }}

    /* ---- METRIC CARDS ---- */
    .metrics-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 12px; }}
    .metric-card {{ background: {theme['card_bg']}; border-radius: 16px; padding: 18px 14px; box-shadow: 0 2px 12px rgba(0,0,0,0.07); text-align: center; border: 1px solid {theme['border']}; display: flex; flex-direction: column; justify-content: center; transition: background 0.5s ease; }}
    .metric-title {{ color: {theme['sub_text']}; font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 6px; font-family: 'Barlow Condensed', sans-serif; }}
    .metric-value {{ color: {theme['text']}; font-size: 2rem; font-weight: 900; line-height: 1.1; font-family: 'Barlow Condensed', sans-serif; }}
    .metric-sub {{ font-size: 0.75rem; font-weight: 500; margin-top: 4px; color: {theme['sub_text']}; line-height: 1.4; }}
    .text-red {{ color: #e74c3c; }}

    /* ---- PILLS ---- */
    .pill-container {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-bottom: 20px; margin-top: 4px; }}
    .info-pill {{ background: {theme['card_bg']}; border: 1px solid {theme['border']}; border-radius: 28px; color: {theme['text']}; font-size: 0.8rem; font-weight: 600; text-align: center; flex: 1 1 calc(33% - 8px); min-width: 120px; min-height: 50px; height: auto; display: flex; flex-direction: column; align-items: center; justify-content: center; overflow: hidden; padding: 6px 10px; box-shadow: 0 1px 4px rgba(0,0,0,0.04); transition: all 0.3s; }}
    .reason-pill {{ display: inline-block; background: rgba(0,0,0,0.1); padding: 4px 10px; border-radius: 14px; font-size: 0.75rem; margin: 2px; font-weight: 700; border: 1px solid rgba(128,128,128,0.25); color: {theme['text']}; font-family: 'Barlow Condensed', sans-serif; letter-spacing: 0.3px; }}

    /* ---- WIND CARD ---- */
    .wind-container {{ background: linear-gradient(135deg, #1a2a3a, #2c4a6e, #3498db); border-radius: 18px; padding: 18px; color: white; box-shadow: 0 8px 24px rgba(52,152,219,0.25); margin-bottom: 20px; }}
    .wind-merged {{ display: flex; flex-direction: row; align-items: center; justify-content: space-around; gap: 16px; width: 100%; }}
    .wind-stats-box {{ background: rgba(0,0,0,0.22); padding: 14px 22px; border-radius: 14px; min-width: 50%; text-align: center; }}

    @keyframes wind-pulse {{ 0% {{ transform: translateY(0px); opacity: 0.8; }} 50% {{ transform: translateY(-8px); opacity: 1; filter: drop-shadow(0 0 8px rgba(255,255,255,0.8)); }} 100% {{ transform: translateY(0px); opacity: 0.8; }} }}
    .animated-wind {{ display: inline-block; animation: wind-pulse 2s infinite ease-in-out; }}
    @keyframes wind-shake-anim {{ 0% {{ transform: translateY(0) rotate(0deg); }} 25% {{ transform: translateY(-3px) rotate(15deg); }} 50% {{ transform: translateY(-6px) rotate(0deg); }} 75% {{ transform: translateY(-3px) rotate(-15deg); }} 100% {{ transform: translateY(0) rotate(0deg); }} }}
    .wind-shake {{ display: inline-block; animation: wind-shake-anim 0.4s infinite ease-in-out; filter: drop-shadow(0 0 10px rgba(255,118,117,0.9)); }}

    @keyframes uv-pulse-anim {{ 0% {{ box-shadow: 0 0 0 0 rgba(241,196,15,0.7); }} 70% {{ box-shadow: 0 0 0 10px rgba(241,196,15,0); }} 100% {{ box-shadow: 0 0 0 0 rgba(241,196,15,0); }} }}
    .uv-pulse {{ animation: uv-pulse-anim 2s infinite; border-color: #f1c40f !important; color: #f1c40f !important; }}
    @keyframes rain-drip {{ 0% {{ transform: translateY(-2px); box-shadow: 0 4px 10px rgba(116,185,255,0.4); }} 50% {{ transform: translateY(2px); box-shadow: 0 0 0 rgba(116,185,255,0); }} 100% {{ transform: translateY(-2px); box-shadow: 0 4px 10px rgba(116,185,255,0.4); }} }}
    .rain-anim {{ animation: rain-drip 1.5s infinite ease-in-out; border-color: #74b9ff !important; color: #74b9ff !important; }}
    @keyframes fog-fade {{ 0% {{ opacity: 0.5; filter: blur(1px); }} 50% {{ opacity: 1; filter: blur(0); }} 100% {{ opacity: 0.5; filter: blur(1px); }} }}
    .fog-anim {{ animation: fog-fade 3s infinite ease-in-out; border-color: #b2bec3 !important; color: #b2bec3 !important; }}

    /* ---- WAVE SIMULATOR ---- */
    .sim-wave-box {{ position: relative; background: linear-gradient(to bottom, transparent 0%, rgba(52,152,219,0.1) 100%); height: 90px; border-radius: 10px; overflow: hidden; margin-top: 12px; width: 100%; border-bottom: 3px solid #3498db; }}
    .sim-wave-back {{ position: absolute; bottom: 0; left: 0; width: 200%; height: 55px; background: url('data:image/svg+xml;utf8,<svg viewBox="0 0 1200 60" xmlns="http://www.w3.org/2000/svg"><path d="M0,30 C150,60 350,0 600,30 C850,60 1050,0 1200,30 L1200,60 L0,60 Z" fill="%232980b9" opacity="0.5"/></svg>') repeat-x; background-size: 50% 100%; transform-origin: bottom; animation: wave-move var(--wave-speed-back,3s) linear infinite reverse; }}
    .sim-wave-front {{ position: absolute; bottom: 0; left: 0; width: 200%; height: 45px; background: url('data:image/svg+xml;utf8,<svg viewBox="0 0 1200 60" xmlns="http://www.w3.org/2000/svg"><path d="M0,30 C150,0 350,60 600,30 C850,0 1050,60 1200,30 L1200,60 L0,60 Z" fill="%233498db" opacity="0.8"/></svg>') repeat-x; background-size: 50% 100%; transform-origin: bottom; animation: wave-move var(--wave-speed-front,2.5s) linear infinite; }}
    @keyframes wave-move {{ 0% {{ transform: translateX(0) scaleY(var(--wave-scale,1)); }} 100% {{ transform: translateX(-50%) scaleY(var(--wave-scale,1)); }} }}

    /* ---- CHART ---- */
    .chart-wrapper {{ background: {theme['card_bg']}; border: 1px solid {theme['border']}; border-radius: 16px; padding: 18px 18px 10px 18px; margin-bottom: 20px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }}
    .chart-title {{ font-family: 'Barlow Condensed', sans-serif; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; color: {theme['sub_text']}; margin-bottom: 12px; }}
    .chart-svg {{ width: 100%; overflow: visible; }}
    .chart-line {{ fill: none; stroke: #3498db; stroke-width: 2.5; stroke-linejoin: round; stroke-linecap: round; }}
    .chart-area {{ fill: url(#chartGrad); }}
    .chart-dot {{ fill: #3498db; }}

    /* ---- BOATING SCORE ---- */
    .score-card {{ background: {theme['card_bg']}; border: 1px solid {theme['border']}; border-radius: 16px; padding: 18px; margin-bottom: 14px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }}
    .score-bar-bg {{ background: {theme['border']}; border-radius: 10px; height: 10px; width: 100%; margin: 12px 0 10px 0; overflow: hidden; }}
    .score-bar-fill {{ height: 10px; border-radius: 10px; transition: width 1s ease; }}

    /* ---- MOBILE ---- */
    @media (max-width: 768px) {{
        /* More breathing room on all cards */
        .metric-card {{ padding: 16px 12px !important; border-radius: 14px !important; }}
        .metric-value {{ font-size: 1.8rem !important; }}
        .metric-title {{ font-size: 0.68rem !important; margin-bottom: 4px !important; }}
        .metric-sub {{ font-size: 0.72rem !important; }}
        .section-header {{ font-size: 1.1rem; margin: 16px 0 8px 0; }}
        .score-card {{ padding: 14px; }}
        .chart-wrapper {{ padding: 12px 8px 6px 8px; }}
        .wind-container {{ padding: 14px; border-radius: 14px; }}
        .wind-stats-box {{ padding: 12px 16px; }}
        .alert-content {{ font-size: 0.85rem; line-height: 1.5; }}
        .alert-summary {{ font-size: 0.95rem; padding: 12px 14px; }}
    }}

    @media (max-width: 640px) {{
        .main-title {{ text-align: center; margin-bottom: 6px; font-size: 1.5rem !important; }}
        /* 2-col grid, water temp spans full width for readability */
        .metrics-grid {{ grid-template-columns: 1fr 1fr; gap: 10px; }}
        .metrics-grid .metric-card:nth-child(3) {{ grid-column: span 2; }}
        .metric-value {{ font-size: 1.7rem !important; }}
        /* Pills: 2 per row on small screens */
        .pill-container {{ gap: 8px; }}
        .info-pill {{ flex: 1 1 calc(50% - 8px); min-width: 0; min-height: 52px; font-size: 0.8rem; padding: 8px 10px; }}
        div[data-testid="stToggle"] {{ width: 100%; display: flex; justify-content: center; }}
        .wind-merged {{ flex-direction: column; text-align: center; gap: 12px; }}
        .wind-stats-box {{ width: 100%; padding: 12px; min-width: unset; }}
    }}

    @media (max-width: 400px) {{
        .metric-value {{ font-size: 1.5rem !important; }}
        .info-pill {{ font-size: 0.75rem; min-height: 48px; }}
        .main-title {{ font-size: 1.35rem !important; }}
    }}
    </style>
""", unsafe_allow_html=True)

# --- Header ---
# now_est already set DST-aware above

col_title, col_controls = st.columns([2.2, 1.8])
with col_title:
    st.markdown(f'''
        <h1 class="main-title">⚓ Lanier Navigator</h1>
        <div id="live-clock-text" style="color:{theme['sub_text']}; font-size:0.88rem; font-weight:600; margin-top:2px; margin-bottom:12px; padding-left:2px; font-family:'Barlow',sans-serif;"></div>
    ''', unsafe_allow_html=True)

with col_controls:
    st.write("")
    c1, c2 = st.columns(2)
    with c1:
        new_theme = st.toggle("🌙 Dark", value=st.session_state.dark_mode)
        if new_theme != st.session_state.dark_mode:
            st.session_state.dark_mode = new_theme
            st.query_params["theme"] = "dark" if new_theme else "light"
            st.rerun()
    with c2:
        new_unit = st.toggle("📏 Metric", value=st.session_state.is_metric)
        if new_unit != st.session_state.is_metric:
            st.session_state.is_metric = new_unit
            st.query_params["units"] = "metric" if new_unit else "imperial"
            st.rerun()

# --- Safety Alerts ---
if alerts:
    alert_items = "".join([f"<div style='margin-bottom:8px;'>{a}</div>" for a in alerts])
    st.markdown(f"""
    <details class="alert-expander" open>
        <summary class="alert-summary">
            <span>⚠️ IMPORTANT SAFETY ALERTS ({len(alerts)})</span>
            <span style="font-size:0.78rem; opacity:0.9; text-transform:uppercase;">Tap to toggle</span>
        </summary>
        <div class="alert-content">{alert_items}</div>
    </details>
    """, unsafe_allow_html=True)

# --- Metric Cards ---
if d['level'] != "N/A":
    trend_arrow = "↑" if trend_24h >= 0 else "↓"
    trend_color = "#2ecc71" if trend_24h >= 0 else "#e74c3c"
    pool_diff_raw = d['level'] - FULL_POOL_FT
    pool_arrow = "↑" if pool_diff_raw >= 0 else "↓"
    pool_color = "#3498db" if pool_diff_raw >= 0 else "#e74c3c"
    level_sub_html = (
        f"<span style='color:{trend_color}; font-weight:700;'>{trend_arrow} {abs(trend_24h)} {unit_dist} (24h)</span>"
        f"<br><span style='color:{pool_color}; font-weight:700;'>{pool_arrow} {disp_pool_diff}{unit_dist} (Full)</span>"
    )
else:
    level_sub_html = "Data unavailable"

level_val = f"{disp_level}{unit_dist}" if disp_level != "N/A" else "N/A"

# Water temp color (always based on °F median for thresholds)
wt_median_f = wt_data['median']
if wt_median_f != "N/A":
    wt_f = float(wt_median_f)
    temp_color = "#74b9ff" if wt_f < 50 else "#3498db" if wt_f < 60 else "#f39c12" if wt_f < 80 else "#e74c3c"
    water_temp_display = f"{disp_water_temp}{unit_temp}"
else:
    temp_color = theme['sub_text']
    water_temp_display = "N/A"

# Build per-source rows for the water temp breakdown card
wt_source_rows = ""
src_icons = {
    "USGS Buford Dam":      "🏛️",
    "USGS Flowery Branch":  "📍",
    "Open-Meteo (ERA5)":    "🛰️",
    "Lake Monster":         "🐊",
}
for src_name, src_val in wt_data["sources"].items():
    icon = src_icons.get(src_name, "🌡️")
    if st.session_state.is_metric:
        disp_src_val = f"{round((src_val - 32) * 5/9, 1)}{unit_temp}"
    else:
        disp_src_val = f"{src_val}{unit_temp}"
    # Highlight if this source matches the median (within 0.5°)
    is_median = abs(src_val - float(wt_median_f)) <= 0.5 if wt_median_f != "N/A" else False
    badge = " ✓" if is_median else ""
    wt_source_rows += f"""
        <div style="display:flex; justify-content:space-between; align-items:center;
                    padding:5px 0; border-bottom:1px solid {theme['border']}; font-size:0.75rem;">
            <span style="color:{theme['sub_text']}; font-weight:600;">{icon} {src_name}{badge}</span>
            <span style="color:{theme['text']}; font-weight:800; font-family:'Barlow Condensed',sans-serif; font-size:0.88rem;">{disp_src_val}</span>
        </div>"""

conf_color = {"High": "#2ecc71", "Medium": "#f1c40f", "Low (1 source)": "#e67e22"}.get(wt_data["confidence"], theme['sub_text'])

# Spread display
if disp_water_high != "N/A" and disp_water_low != "N/A":
    spread_html = (
        f"<span style='color:#74b9ff;'>↓{disp_water_low}{unit_temp}</span>"
        f"&nbsp;–&nbsp;"
        f"<span style='color:#e74c3c;'>↑{disp_water_high}{unit_temp}</span>"
    )
else:
    spread_html = "N/A"

air_temp_color = theme['text']
if d['air_temp'] != "N/A":
    if d['air_temp'] >= 85: air_temp_color = "#ff7675"
    elif d['air_temp'] >= 75: air_temp_color = "#fdcb6e"
    elif d['air_temp'] <= 45: air_temp_color = "#74b9ff"
    elif d['air_temp'] <= 32: air_temp_color = "#81ecec"

# Build source rows for popup
_src_rows_html = ""
src_icon_map = {"USGS Below Buford Dam": "🏛️", "USGS Flowery Branch": "📍", "Omnia Fishing": "🎣", "Lake Monster": "🐊"}
for sn, sv in wt_data["sources"].items():
    ico = src_icon_map.get(sn, "🌡️")
    if st.session_state.is_metric:
        dsv = str(round((sv - 32) * 5 / 9, 1)) + unit_temp
    else:
        dsv = str(sv) + unit_temp
    near = wt_data["median"] != "N/A" and abs(sv - float(wt_data["median"])) <= 0.5
    check = '<span class="wt-check">median</span>' if near else ""
    _src_rows_html += (
        f'<div class="wt-source-row">'
        f'<div class="wt-source-name">{ico} {sn}{check}</div>'
        f'<div class="wt-source-val">{dsv}</div>'
        f'</div>'
    )
if not _src_rows_html:
    _src_rows_html = '<div style="text-align:center;padding:14px;opacity:0.4;font-size:0.82rem;">No sources available</div>'

# Build water temp 24h history chart SVG
def build_wt_chart_svg(pts, is_metric, unit_temp, card_bg, border, sub_text, text):
    if not pts or len(pts) < 3:
        return '<div style="text-align:center;padding:20px;opacity:0.5;font-size:0.82rem;">No history data available</div>'
    if is_metric:
        levels = [round((p[1] - 32) * 5 / 9, 1) for p in pts]
    else:
        levels = [p[1] for p in pts]
    labels = [p[0] for p in pts]
    n = len(pts)
    min_l, max_l = min(levels), max(levels)
    pad = max(0.3, (max_l - min_l) * 0.25)
    y_min, y_max = min_l - pad, max_l + pad
    W, H = 500, 110
    pl, pr, pt_p, pb = 46, 12, 10, 26
    pw, ph = W - pl - pr, H - pt_p - pb

    def cx(i): return pl + (i / (n - 1)) * pw
    def cy(v): return pt_p + ph - ((v - y_min) / (y_max - y_min)) * ph

    pts_str = " ".join(f"{cx(i):.1f},{cy(v):.1f}" for i, v in enumerate(levels))
    area_str = f"{cx(0):.1f},{pt_p + ph} " + pts_str + f" {cx(n-1):.1f},{pt_p + ph}"

    y_ticks = [y_min + (y_max - y_min) * k / 2 for k in range(3)]
    grid = "".join(
        f'<line x1="{pl}" y1="{cy(yv):.1f}" x2="{W-pr}" y2="{cy(yv):.1f}" stroke="{border}" stroke-width="1" stroke-dasharray="4,3"/>'
        f'<text x="{pl-4}" y="{cy(yv)+4:.1f}" text-anchor="end" font-size="9" fill="{sub_text}" font-family="Barlow Condensed,sans-serif" font-weight="600">{yv:.1f}</text>'
        for yv in y_ticks
    )
    x_idxs = [0, n // 4, n // 2, 3 * n // 4, n - 1]
    xlbls = "".join(
        f'<text x="{cx(i):.1f}" y="{H-4}" text-anchor="middle" font-size="9" fill="{sub_text}" font-family="Barlow Condensed,sans-serif" font-weight="600">{labels[i]}</text>'
        for i in x_idxs if 0 <= i < n
    )
    last_cx, last_cy = cx(n - 1), cy(levels[-1])
    dot_col = "#2ecc71" if levels[-1] >= levels[0] else "#e74c3c"

    return (
        f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="width:100%;overflow:visible;">'
        f'<defs><linearGradient id="wtGrad" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="#f39c12" stop-opacity="0.4"/>'
        f'<stop offset="100%" stop-color="#f39c12" stop-opacity="0.03"/>'
        f'</linearGradient></defs>'
        f'{grid}{xlbls}'
        f'<polyline points="{area_str}" fill="url(#wtGrad)"/>'
        f'<polyline points="{pts_str}" fill="none" stroke="#f39c12" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{last_cx:.1f}" cy="{last_cy:.1f}" r="4.5" fill="{dot_col}" stroke="{card_bg}" stroke-width="2"/>'
        f'</svg>'
    )

wt_chart_svg = build_wt_chart_svg(wt_history, st.session_state.is_metric, unit_temp,
                                   theme['card_bg'], theme['border'], theme['sub_text'], theme['text'])

# Render as a single self-contained HTML component (no split markdown calls)
wt_modal_html = f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800;900&family=Barlow:wght@400;500;600;700&display=swap');

  .wt-card {{
    background:{theme['card_bg']}; border:1px solid {theme['border']}; border-radius:16px;
    padding:18px 14px; box-shadow:0 2px 12px rgba(0,0,0,0.07); text-align:center;
    display:flex; flex-direction:column; justify-content:center; cursor:pointer;
    transition:border-color 0.25s, box-shadow 0.25s, transform 0.15s;
    font-family:'Barlow',sans-serif;
  }}
  .wt-card:hover {{
    border-color:#f39c12; box-shadow:0 4px 20px rgba(243,156,18,0.25); transform:translateY(-1px);
  }}
  .wt-card:active {{ transform:translateY(0); }}
  .wt-tap-hint {{
    font-size:0.58rem; opacity:0.4; margin-top:4px; font-weight:700;
    letter-spacing:0.8px; text-transform:uppercase; color:{theme['text']};
  }}

  /* ---- OVERLAY ---- */
  .wt-overlay {{
    display:none; position:fixed; inset:0;
    background:rgba(0,0,0,0.72);
    backdrop-filter:blur(4px); -webkit-backdrop-filter:blur(4px);
    z-index:99999; align-items:center; justify-content:center; padding:16px;
    animation:fadeIn 0.18s ease;
  }}
  @keyframes fadeIn {{ from{{opacity:0}} to{{opacity:1}} }}
  .wt-overlay.open {{ display:flex; }}

  /* ---- MODAL ---- */
  .wt-modal {{
    background:{theme['card_bg']}; border:1px solid {theme['border']}; border-radius:24px;
    width:100%; max-width:440px; max-height:88vh; overflow-y:auto;
    box-shadow:0 32px 80px rgba(0,0,0,0.6);
    animation:slideUp 0.22s cubic-bezier(0.34,1.56,0.64,1);
    font-family:'Barlow',sans-serif;
  }}
  @keyframes slideUp {{ from{{transform:translateY(30px);opacity:0}} to{{transform:translateY(0);opacity:1}} }}

  /* ---- MODAL HEADER ---- */
  .wt-modal-header {{
    background: linear-gradient(135deg, {theme['card_bg']}, {'#2a2d3e' if st.session_state.dark_mode else '#eef2f7'});
    border-radius:24px 24px 0 0; padding:20px 20px 16px;
    border-bottom:1px solid {theme['border']};
  }}
  .wt-modal-topbar {{
    display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;
  }}
  .wt-modal-label {{
    font-family:'Barlow Condensed',sans-serif; font-size:0.72rem; font-weight:700;
    text-transform:uppercase; letter-spacing:1.5px; color:{theme['sub_text']};
  }}
  .wt-close {{
    background:{'rgba(255,255,255,0.08)' if st.session_state.dark_mode else 'rgba(0,0,0,0.06)'};
    border:1px solid {theme['border']}; color:{theme['text']};
    border-radius:50%; width:32px; height:32px; cursor:pointer; font-size:0.9rem;
    display:flex; align-items:center; justify-content:center; transition:all 0.2s;
    font-family:sans-serif;
  }}
  .wt-close:hover {{
    background:{'rgba(255,255,255,0.15)' if st.session_state.dark_mode else 'rgba(0,0,0,0.12)'};
    transform:rotate(90deg);
  }}

  /* ---- BIG TEMP DISPLAY ---- */
  .wt-hero {{ text-align:center; }}
  .wt-hero-temp {{
    font-family:'Barlow Condensed',sans-serif; font-size:4rem; font-weight:900;
    color:{temp_color}; line-height:1; letter-spacing:-1px;
  }}
  .wt-hero-sub {{
    font-size:0.82rem; color:{theme['sub_text']}; margin-top:6px;
    display:flex; justify-content:center; align-items:center; gap:12px; flex-wrap:wrap;
  }}
  .wt-badge {{
    display:inline-flex; align-items:center; gap:4px; padding:3px 10px;
    border-radius:20px; font-size:0.72rem; font-weight:700;
    border:1px solid currentColor; opacity:0.85;
  }}

  /* ---- MODAL BODY ---- */
  .wt-modal-body {{ padding:18px 20px 22px; }}
  .wt-section-label {{
    font-family:'Barlow Condensed',sans-serif; font-size:0.68rem; font-weight:700;
    text-transform:uppercase; letter-spacing:1.5px; color:{theme['sub_text']};
    margin:18px 0 10px;
  }}
  .wt-section-label:first-child {{ margin-top:0; }}

  /* ---- SOURCE ROWS ---- */
  .wt-source-row {{
    display:flex; justify-content:space-between; align-items:center;
    padding:9px 12px; border-radius:10px; margin-bottom:6px;
    background:{'rgba(255,255,255,0.03)' if st.session_state.dark_mode else 'rgba(0,0,0,0.03)'};
    border:1px solid {theme['border']};
  }}
  .wt-source-name {{
    font-size:0.82rem; font-weight:600; color:{theme['sub_text']}; display:flex; align-items:center; gap:6px;
  }}
  .wt-source-val {{
    font-family:'Barlow Condensed',sans-serif; font-size:1.05rem; font-weight:800; color:{theme['text']};
  }}
  .wt-check {{
    background:rgba(46,204,113,0.15); color:#2ecc71; border:1px solid rgba(46,204,113,0.3);
    border-radius:12px; font-size:0.62rem; font-weight:800; padding:1px 6px; margin-left:4px;
    letter-spacing:0.3px;
  }}

  /* ---- CHART ---- */
  .wt-chart-wrap {{
    background:{'rgba(0,0,0,0.2)' if st.session_state.dark_mode else 'rgba(0,0,0,0.04)'};
    border:1px solid {theme['border']}; border-radius:12px; padding:14px 12px 8px;
  }}

  /* ---- FOOTER ---- */
  .wt-footer {{
    text-align:center; font-size:0.62rem; opacity:0.3; margin-top:16px;
    font-weight:500; line-height:1.5;
  }}
</style>

<!-- 3-col metrics grid including clickable water temp card -->
<div style="display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:12px;">

  <div style="background:{theme['card_bg']};border:1px solid {theme['border']};border-radius:16px;padding:18px 14px;box-shadow:0 2px 12px rgba(0,0,0,0.07);text-align:center;display:flex;flex-direction:column;justify-content:center;font-family:'Barlow',sans-serif;">
    <div style="color:{theme['sub_text']};font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;margin-bottom:6px;font-family:'Barlow Condensed',sans-serif;">Lake Level</div>
    <div style="color:{theme['text']};font-size:2rem;font-weight:900;line-height:1.1;font-family:'Barlow Condensed',sans-serif;">{level_val}</div>
    <div style="font-size:0.75rem;font-weight:500;margin-top:4px;color:{theme['sub_text']};line-height:1.4;">
      {level_sub_html}<br>
      <span style="font-size:0.62rem;opacity:0.4;display:inline-block;margin-top:4px;">Updated: {d['last_updated']}</span>
    </div>
  </div>

  <div style="background:{theme['card_bg']};border:1px solid {theme['border']};border-radius:16px;padding:18px 14px;box-shadow:0 2px 12px rgba(0,0,0,0.07);text-align:center;display:flex;flex-direction:column;justify-content:center;font-family:'Barlow',sans-serif;">
    <div style="color:{theme['sub_text']};font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;margin-bottom:6px;font-family:'Barlow Condensed',sans-serif;">Air Temp</div>
    <div style="color:{air_temp_color};font-size:2rem;font-weight:900;line-height:1.1;font-family:'Barlow Condensed',sans-serif;">{disp_air_temp}{unit_temp}</div>
    <div style="font-size:0.75rem;font-weight:500;margin-top:4px;color:{theme['sub_text']};line-height:1.4;">
      Flowery Branch<br>
      <span style="font-size:0.62rem;opacity:0.4;display:inline-block;margin-top:4px;">Updated: {d['last_updated']}</span>
    </div>
  </div>

  <div class="wt-card" onclick="document.getElementById('wtOverlay').classList.add('open')">
    <div style="color:{theme['sub_text']};font-size:0.72rem;font-weight:700;text-transform:uppercase;letter-spacing:1.2px;margin-bottom:6px;font-family:'Barlow Condensed',sans-serif;">Water Temp</div>
    <div style="color:{temp_color};font-size:2rem;font-weight:900;line-height:1.1;font-family:'Barlow Condensed',sans-serif;">{water_temp_display}</div>
    <div style="font-size:0.75rem;font-weight:500;margin-top:4px;color:{theme['sub_text']};line-height:1.4;">
      <span style="color:#74b9ff;">↓{disp_water_low}{unit_temp}</span> · <span style="color:#e74c3c;">↑{disp_water_high}{unit_temp}</span>
      <br><span style="font-size:0.6rem;opacity:0.4;display:inline-block;margin-top:2px;">{wt_data['confidence']} · {len(wt_data['sources'])} sources</span>
    </div>
    <div class="wt-tap-hint">▼ tap for details</div>
  </div>

</div>

<!-- Modal -->
<div id="wtOverlay" class="wt-overlay" onclick="if(event.target===this)this.classList.remove('open')">
  <div class="wt-modal">

    <!-- Header -->
    <div class="wt-modal-header">
      <div class="wt-modal-topbar">
        <div class="wt-modal-label">🌡️ Water Temperature</div>
        <button class="wt-close" onclick="document.getElementById('wtOverlay').classList.remove('open')">✕</button>
      </div>
      <div class="wt-hero">
        <div class="wt-hero-temp">{water_temp_display}</div>
        <div class="wt-hero-sub">
          <span>median of {len(wt_data['sources'])} sources</span>
          <span class="wt-badge" style="color:{conf_color};">● {wt_data['confidence']}</span>
          <span class="wt-badge" style="color:#74b9ff;">↓ {disp_water_low}{unit_temp}</span>
          <span class="wt-badge" style="color:#e74c3c;">↑ {disp_water_high}{unit_temp}</span>
        </div>
      </div>
    </div>

    <!-- Body -->
    <div class="wt-modal-body">

      <div class="wt-section-label">Source Readings</div>
      {_src_rows_html}

      <div class="wt-section-label">24-Hour History</div>
      <div class="wt-chart-wrap">
        {wt_chart_svg}
      </div>

      <div class="wt-footer">
        Refreshes every 5 min · USGS 02334430 & 02334480 · Omnia Fishing · Lake Monster<br>
        ⚠ Surface temp varies by depth, cove, and time of day
      </div>

    </div>
  </div>
</div>
"""
st.components.v1.html(wt_modal_html, height=210, scrolling=False)


# --- Info Pills ---
try:
    sr_time = datetime.strptime(d["sunrise"], "%I:%M %p").time()
    ss_time = datetime.strptime(d["sunset"], "%I:%M %p").time()
    curr_time = now_est.time()
    sr_mins = sr_time.hour * 60 + sr_time.minute
    ss_mins = ss_time.hour * 60 + ss_time.minute
    curr_mins = curr_time.hour * 60 + curr_time.minute
    total_daylight = ss_mins - sr_mins
    base_sun_str = f"🌅 {d['sunrise']} | 🌇 {d['sunset']}"
    if curr_mins < sr_mins:
        sun_prog = 0
        rem = sr_mins - curr_mins
        sun_lbl = f"{base_sun_str}<br><span style='font-size:0.68rem; opacity:0.8;'>Rises in {rem // 60}h {rem % 60}m</span>"
        sun_bg = f"background: linear-gradient(90deg, rgba(253,203,110,0.4) 0%, {theme['card_bg']} 0%);"
    elif curr_mins >= ss_mins:
        sun_prog = 100
        sun_lbl = f"{base_sun_str}<br><span style='font-size:0.68rem; opacity:0.8; color:#74b9ff;'>🌙 Night Operations</span>"
        sun_bg = f"background: linear-gradient(90deg, rgba(41,128,185,0.2) 100%, {theme['card_bg']} 100%);"
    else:
        elapsed = curr_mins - sr_mins
        sun_prog = int((elapsed / total_daylight) * 100)
        rem = ss_mins - curr_mins
        sun_lbl = f"{base_sun_str}<br><span style='font-size:0.68rem; opacity:0.8;'>{rem // 60}h {rem % 60}m till Sunset</span>"
        sun_bg = f"background: linear-gradient(90deg, rgba(253,203,110,0.4) {sun_prog}%, {theme['card_bg']} {sun_prog}%);"
except Exception:
    sun_lbl = f"🌅 {d['sunrise']} | 🌇 {d['sunset']}"
    sun_bg = f"background: {theme['card_bg']};"

rain_anim_class = "rain-anim" if d['rain_chance'] > 30 else ""
fog_anim_class = "fog-anim" if d['visibility'] != "N/A" and d['visibility'] < 5 else ""
uv_anim_class = "uv-pulse" if d['uv'] > 6 else ""

st.markdown(f"""
<div class="pill-container">
    <div id="live-sun-pill" class="info-pill" style="{sun_bg}">{sun_lbl}</div>
    <div class="info-pill {rain_anim_class}">🌧️ Rain: {d["rain_chance"]}%</div>
    <div class="info-pill {fog_anim_class}">🌫️ Vis: {disp_vis} {unit_vis}</div>
    <div class="info-pill">🌡️ Pres: {disp_press} {unit_press}</div>
    <div class="info-pill">☁️ Clouds: {d["clouds"]}%</div>
    <div class="info-pill {uv_anim_class}">☀️ UV: {round(d["uv"],1)}</div>
</div>
""", unsafe_allow_html=True)

# Live clock JS
live_js = f"""
<script>
try {{
    const sr = "{d['sunrise']}"; const ss = "{d['sunset']}";
    function parseTime(t) {{
        if(!t||t==="N/A") return 0;
        let p=t.split(' '), tp=p[0].split(':'), h=parseInt(tp[0],10), m=parseInt(tp[1],10);
        if(h===12) h=0; if(p[1]==='PM'&&h!==12) h+=12; return h*60+m;
    }}
    const srMins=parseTime(sr), ssMins=parseTime(ss), totalDaylight=ssMins-srMins;
    function updateLive() {{
        try {{
            const doc=window.parent.document, now=new Date();
            const clockEl=doc.getElementById('live-clock-text');
            if(clockEl) {{ clockEl.innerHTML='📅 '+now.toLocaleDateString('en-US',{{weekday:'long',month:'long',day:'numeric'}})+' | '+now.toLocaleTimeString('en-US',{{hour:'2-digit',minute:'2-digit',second:'2-digit'}}); }}
            const sunEl=doc.getElementById('live-sun-pill');
            if(sunEl&&srMins>0) {{
                const currMins=now.getHours()*60+now.getMinutes(); let lbl='',bg='';
                const baseStr='🌅 '+sr+' | 🌇 '+ss;
                if(currMins<srMins) {{ let rem=srMins-currMins; lbl=baseStr+"<br><span style='font-size:0.68rem;opacity:0.8;'>Rises in "+Math.floor(rem/60)+"h "+(rem%60)+"m</span>"; bg="linear-gradient(90deg,rgba(253,203,110,0.4) 0%,{theme['card_bg']} 0%)"; }}
                else if(currMins>=ssMins) {{ lbl=baseStr+"<br><span style='font-size:0.68rem;opacity:0.8;color:#74b9ff;'>🌙 Night Operations</span>"; bg="linear-gradient(90deg,rgba(41,128,185,0.2) 100%,{theme['card_bg']} 100%)"; }}
                else {{ let prog=Math.floor(((currMins-srMins)/totalDaylight)*100), rem=ssMins-currMins; lbl=baseStr+"<br><span style='font-size:0.68rem;opacity:0.8;'>"+Math.floor(rem/60)+"h "+(rem%60)+"m till Sunset</span>"; bg="linear-gradient(90deg,rgba(253,203,110,0.4) "+prog+"%,{theme['card_bg']} "+prog+"%)"; }}
                sunEl.innerHTML=lbl; sunEl.style.background=bg;
            }}
        }} catch(e) {{}}
    }}
    updateLive(); setInterval(updateLive,1000);
}} catch(e) {{}}
</script>
"""
st.components.v1.html(live_js, height=0, width=0)

# ===================================================
# LAKE LEVEL 24H CHART
# ===================================================
st.markdown('<div class="section-header">📈 Lake Level — Last 24 Hours</div>', unsafe_allow_html=True)

if chart_points and len(chart_points) >= 3:
    levels = [pt[1] for pt in chart_points]
    labels = [pt[0] for pt in chart_points]
    min_l = min(levels)
    max_l = max(levels)
    padding = max(0.05, (max_l - min_l) * 0.3)
    y_min = min_l - padding
    y_max = max_l + padding
    n = len(chart_points)

    chart_w = 560
    chart_h = 120
    pad_left = 58
    pad_right = 14
    pad_top = 12
    pad_bottom = 28
    plot_w = chart_w - pad_left - pad_right
    plot_h = chart_h - pad_top - pad_bottom

    def cx(i): return pad_left + (i / (n - 1)) * plot_w
    def cy(v): return pad_top + plot_h - ((v - y_min) / (y_max - y_min)) * plot_h

    # Smooth polyline points
    pts = " ".join([f"{cx(i):.1f},{cy(v):.1f}" for i, v in enumerate(levels)])
    area_pts = f"{cx(0):.1f},{pad_top + plot_h} " + pts + f" {cx(n-1):.1f},{pad_top + plot_h}"

    # Y-axis gridlines (3 lines)
    y_ticks = [y_min + (y_max - y_min) * k / 2 for k in range(3)]
    grid_lines = ""
    y_labels = ""
    for yv in y_ticks:
        yp = cy(yv)
        grid_lines += f'<line x1="{pad_left}" y1="{yp:.1f}" x2="{chart_w - pad_right}" y2="{yp:.1f}" stroke="{theme["border"]}" stroke-width="1" stroke-dasharray="4,3"/>'
        y_labels += f'<text x="{pad_left - 5}" y="{yp + 4:.1f}" text-anchor="end" font-size="9" fill="{theme["sub_text"]}" font-family="Barlow Condensed,sans-serif" font-weight="600">{yv:.2f}</text>'

    # X-axis labels (show ~5 evenly spaced)
    x_label_indices = [0, n // 4, n // 2, 3 * n // 4, n - 1]
    x_labels = ""
    for idx in x_label_indices:
        if 0 <= idx < n:
            xp = cx(idx)
            x_labels += f'<text x="{xp:.1f}" y="{chart_h - 4}" text-anchor="middle" font-size="9" fill="{theme["sub_text"]}" font-family="Barlow Condensed,sans-serif" font-weight="600">{labels[idx]}</text>'

    # Trend color for last dot
    dot_color = "#2ecc71" if trend_24h >= 0 else "#e74c3c"
    last_cx = cx(n - 1)
    last_cy = cy(levels[-1])

    chart_svg = f"""
    <svg class="chart-svg" viewBox="0 0 {chart_w} {chart_h}" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#3498db" stop-opacity="0.35"/>
                <stop offset="100%" stop-color="#3498db" stop-opacity="0.03"/>
            </linearGradient>
        </defs>
        {grid_lines}
        {y_labels}
        {x_labels}
        <polyline points="{area_pts}" class="chart-area"/>
        <polyline points="{pts}" class="chart-line"/>
        <circle cx="{last_cx:.1f}" cy="{last_cy:.1f}" r="4.5" fill="{dot_color}" stroke="{theme['card_bg']}" stroke-width="2"/>
    </svg>
    """

    trend_dir = "▲" if trend_24h >= 0 else "▼"
    trend_col = "#2ecc71" if trend_24h >= 0 else "#e74c3c"
    st.markdown(f"""
    <div class="chart-wrapper">
        <div class="chart-title" style="display:flex; justify-content:space-between; align-items:center;">
            <span>ELEVATION (ft AMSL) — 24h window</span>
            <span style="color:{trend_col}; font-size:0.82rem;">{trend_dir} {abs(trend_24h)} ft over 24h</span>
        </div>
        {chart_svg}
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown(f"""
    <div class="chart-wrapper" style="text-align:center; padding: 28px; color:{theme['sub_text']};">
        📊 Level trend data unavailable
    </div>
    """, unsafe_allow_html=True)

# ===================================================
# BOATING SCORE
# ===================================================
st.markdown('<div class="section-header">🚦 Boating Conditions</div>', unsafe_allow_html=True)
boat_score, score_reasons = calculate_boat_score(d, wave_height)

if boat_score >= 85:
    score_label, score_color = "🟢 Excellent", "#2ecc71"
elif boat_score >= 65:
    score_label, score_color = "🟡 Good", "#f1c40f"
elif boat_score >= 40:
    score_label, score_color = "🟠 Marginal", "#e67e22"
else:
    score_label, score_color = "🔴 Stay Home", "#e74c3c"

reasons_html = "".join([f'<span class="reason-pill">{r}</span>' for r in score_reasons])
if not reasons_html:
    reasons_html = '<span class="reason-pill">✅ Ideal Conditions</span>'

st.markdown(f"""
<div class="score-card">
    <div class="metric-title">Overall Boating Score</div>
    <div style="display:flex; align-items:baseline; gap:6px; margin-top:6px;">
        <span style="font-size:2.8rem; font-weight:900; color:{score_color}; font-family:'Barlow Condensed',sans-serif; line-height:1;">{boat_score}</span>
        <span style="font-size:1rem; color:{theme['sub_text']};">/100</span>
        <span style="font-size:1rem; font-weight:700; color:{score_color}; margin-left:8px;">{score_label}</span>
    </div>
    <div class="score-bar-bg">
        <div class="score-bar-fill" style="width:{boat_score}%; background: linear-gradient(90deg, {score_color}aa, {score_color});"></div>
    </div>
    <div style="font-size:0.75rem; color:{theme['sub_text']}; margin-bottom:10px;">Factors: water temp · wind · gusts · rain · waves · lake level · visibility · air temp · UV</div>
    <div>{reasons_html}</div>
</div>
""", unsafe_allow_html=True)

# ===================================================
# LIVE CAMERA & WAVE SIMULATOR
# ===================================================
st.markdown('<div class="section-header">📷 Live Camera & Wave Simulator</div>', unsafe_allow_html=True)
cam_col, sim_col = st.columns([1, 1])

with cam_col:
    st.markdown(f'<div class="metric-title" style="margin-bottom:8px;">🔴 LLSC Live Stream</div>', unsafe_allow_html=True)
    st.video("https://www.youtube.com/watch?v=QjJC9ORyOMQ")

with sim_col:
    st.markdown(f'<div class="metric-title" style="margin-bottom:8px;">🌊 Wave Height Simulation</div>', unsafe_allow_html=True)
    css_wave_scale = max(0.2, min(wave_height * 0.8 + 0.2, 2.5))
    css_speed_front = max(1.5, 8.0 - (d["wind_mph"] * 0.25))
    css_speed_back = max(1.2, 6.0 - (d["wind_mph"] * 0.25))
    st.markdown(f"""
    <div class="metric-card" style="padding:14px; height:100%; display:flex; flex-direction:column; justify-content:space-between; margin-bottom:0;">
        <div style="text-align:center; margin-bottom:8px;">
            <div style="font-size:2.4rem; font-weight:900; color:{theme['text']}; line-height:1; font-family:'Barlow Condensed',sans-serif;">{disp_wave} {unit_dist}</div>
            <div style="font-size:0.85rem; font-weight:600; color:{theme['sub_text']}; margin-top:4px;">Estimated Surface Chop</div>
        </div>
        <div class="sim-wave-box" style="--wave-scale:{css_wave_scale}; --wave-speed-front:{css_speed_front}s; --wave-speed-back:{css_speed_back}s;">
            <div class="sim-wave-back"></div>
            <div class="sim-wave-front"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ===================================================
# WIND DETAILS
# ===================================================
st.markdown('<div class="section-header">💨 Live Wind Details</div>', unsafe_allow_html=True)
st.markdown(f"""
<div class="wind-container">
<div class="wind-merged">
<div style="text-align:center;">
    <div style="font-size:0.72rem; font-weight:700; letter-spacing:1px; margin-bottom:6px; opacity:0.85; font-family:'Barlow Condensed',sans-serif; text-transform:uppercase;">Wind Dir</div>
    <div style="transform:rotate({wind_rotation}deg); display:inline-block;">
        <div class="{wind_anim_class}">
            <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="{wind_icon_color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>
            </svg>
        </div>
    </div>
    <div style="font-size:1.5rem; font-weight:900; margin-top:6px; font-family:'Barlow Condensed',sans-serif;">{direction_text}</div>
    <div style="font-size:0.85rem; opacity:0.75;">{d['wind_dir']}°</div>
</div>
<div class="wind-stats-box">
    <div style="font-size:0.72rem; font-weight:700; letter-spacing:1px; margin-bottom:4px; opacity:0.85; font-family:'Barlow Condensed',sans-serif; text-transform:uppercase;">Surface Condition</div>
    <div style="color:{chop_color}; font-weight:800; font-size:1.2rem; margin-bottom:14px; font-family:'Barlow Condensed',sans-serif;">{chop_text}</div>
    <div style="display:flex; justify-content:space-around; gap:12px;">
        <div>
            <div style="font-size:0.7rem; text-transform:uppercase; opacity:0.8; font-family:'Barlow Condensed',sans-serif;">Sustained</div>
            <div style="font-size:1.3rem; font-weight:900; font-family:'Barlow Condensed',sans-serif;">{disp_wind} <span style="font-size:0.72rem;">{unit_speed}</span></div>
        </div>
        <div>
            <div style="font-size:0.7rem; text-transform:uppercase; opacity:0.8; font-family:'Barlow Condensed',sans-serif;">Gusts</div>
            <div style="font-size:1.3rem; font-weight:900; color:#ff7675; font-family:'Barlow Condensed',sans-serif;">{disp_gusts} <span style="font-size:0.72rem;">{unit_speed}</span></div>
        </div>
    </div>
</div>
</div>
</div>
""", unsafe_allow_html=True)

# ===================================================
# MAP & NAVIGATION — EXPANDED LOCATIONS
# ===================================================
st.markdown('<div class="section-header">📍 Dock & Dine Navigation</div>', unsafe_allow_html=True)

places = [
    # ══════════════════════════════════════════════════════
    # DINING — dock-accessible restaurants
    # ══════════════════════════════════════════════════════
    {"name": "Pig Tales BBQ",             "lat": 34.2034893, "lon": -83.9704504, "type": "Dining", "hours": "Mon–Thu 11am–9pm · Fri–Sat 11am–10pm · Sun 11am–9pm",   "web": "https://www.pigtaleslakelanier.com/"},
    {"name": "Fish Tales",                "lat": 34.1839329, "lon": -83.9391580, "type": "Dining", "hours": "Mon–Thu 11am–9pm · Fri–Sat 11am–10pm · Sun 11am–9pm",   "web": "https://www.fishtaleslakelanier.com/"},
    {"name": "Pelican Pete's Tiki Bar",   "lat": 34.2433778, "lon": -83.9616827, "type": "Dining", "hours": "Thu 4–9pm · Fri–Sun 11am–9pm",                          "web": "https://www.pelicanpetes.com/"},
    {"name": "The Twisted Oar",           "lat": 34.1725558, "lon": -84.0029522, "type": "Dining", "hours": "Mon–Thu 11am–10pm · Fri–Sat 11am–11pm · Sun 11am–10pm", "web": "https://www.twistedoar.com/"},
    {"name": "LandShark Bar & Grill",     "lat": 34.1737378, "lon": -84.0290675, "type": "Dining", "hours": "Wed–Sun (see Margaritaville site for current hours)",    "web": "https://www.margaritavilleresorts.com/"},
    {"name": "Skogies Lakefront",         "lat": 34.3153074, "lon": -83.8740115, "type": "Dining", "hours": "Fri–Sat 11am–9pm · Sun 10am–8pm",                       "web": "https://lakelanier.com/directory/restaurants/"},
    {"name": "Bullfrogs Bar & Grille",    "lat": 34.1877198, "lon": -84.0163927, "type": "Dining", "hours": "Daily 11:30am–midnight (Fri–Sat till 1am)",              "web": "https://www.lanierislands.com/dining/"},
    {"name": "Sidney's Restaurant",       "lat": 34.1875035, "lon": -84.0165245, "type": "Dining", "hours": "Breakfast daily · Dinner Fri–Sat 6–9pm",                 "web": "https://www.lanierislands.com/dining/"},
    {"name": "Paradise Beach Cantina",    "lat": 34.1777770, "lon": -84.0294344, "type": "Dining", "hours": "Seasonal (waterpark hours)",                             "web": "https://www.margaritavilleresorts.com/"},
    {"name": "Smokey Q BBQ",              "lat": 34.2088524, "lon": -84.0993836, "type": "Dining", "hours": "Call ahead — seasonal hours",                           "web": "https://lakelanier.com/directory/restaurants/"},

    # ══════════════════════════════════════════════════════
    # FUEL — on-water fuel docks
    # ══════════════════════════════════════════════════════
    {"name": "Holiday Marina Fuel",        "lat": 34.1725471, "lon": -84.0029407, "type": "Fuel", "hours": "Daily 9am–5pm",      "web": "https://holidaylakelanier.com/"},
    {"name": "Port Royale Marina Fuel",    "lat": 34.2432297, "lon": -83.9617131, "type": "Fuel", "hours": "Daily 9am–5pm",      "web": "https://www.bestinboating.com/"},
    {"name": "Bald Ridge Marina Fuel",     "lat": 34.2098813, "lon": -84.1001233, "type": "Fuel", "hours": "Mon–Fri 9am–5pm",    "web": "https://lakelanier.com/directory/marinas/bald-ridge-marina/"},
    {"name": "Gainesville Marina Fuel",    "lat": 34.3159402, "lon": -83.8739903, "type": "Fuel", "hours": "Daily 9am–5pm",      "web": "https://lakelanier.com/directory/marinas/gainesville-marina/"},
    {"name": "Sunrise Cove Marina Fuel",   "lat": 34.2377157, "lon": -83.9362697, "type": "Fuel", "hours": "Mon/Wed–Sun 9am–5pm","web": "https://lakelanier.com/directory/marinas/sunrise-cove-marina/"},

    # ══════════════════════════════════════════════════════
    # MARINAS
    # ══════════════════════════════════════════════════════
    {"name": "Aqualand Marina",            "lat": 34.2005787, "lon": -83.9588154, "type": "Marina", "hours": "Mon–Sat 10am–5pm",      "web": "https://lakelanier.com/directory/marinas/aqualand-marina/"},
    {"name": "Port Royale Marina",         "lat": 34.2432297, "lon": -83.9617131, "type": "Marina", "hours": "Mon–Sat 9am–5pm · Sun 10am–4pm", "web": "https://www.bestinboating.com/"},
    {"name": "Safe Harbor Hideaway Bay",   "lat": 34.1840423, "lon": -83.9387991, "type": "Marina", "hours": "Daily 9am–5pm",          "web": "https://lakelanier.com/directory/marinas/hideaway-bay-marina/"},
    {"name": "Bald Ridge Marina",          "lat": 34.2098813, "lon": -84.1001233, "type": "Marina", "hours": "Mon–Fri 9am–5pm",        "web": "https://lakelanier.com/directory/marinas/bald-ridge-marina/"},
    {"name": "Holiday on Lake Lanier",     "lat": 34.1725471, "lon": -84.0029407, "type": "Marina", "hours": "Daily 9am–5pm",          "web": "https://holidaylakelanier.com/"},
    {"name": "Sunrise Cove Marina",        "lat": 34.2377157, "lon": -83.9362697, "type": "Marina", "hours": "Mon/Wed–Sun 9am–5pm",    "web": "https://lakelanier.com/directory/marinas/sunrise-cove-marina/"},
    {"name": "Lazy Days Marina",           "lat": 34.1670332, "lon": -83.9995203, "type": "Marina", "hours": "Mon/Wed–Sun 9am–5pm",    "web": "https://lazydaysmarina.com/"},
    {"name": "Habersham Marina",           "lat": 34.1915273, "lon": -84.1026953, "type": "Marina", "hours": "Daily 9am–5pm",          "web": "https://habersham-marina.com/"},
    {"name": "Gainesville Marina",         "lat": 34.3159402, "lon": -83.8739903, "type": "Marina", "hours": "Daily 9am–5pm",          "web": "https://lakelanier.com/directory/marinas/gainesville-marina/"},

    # ══════════════════════════════════════════════════════
    # LAUNCH / PARKS — every verified ramp on the lake
    # Sources: Army Corps schedule + lakelanier.com/boat-ramps
    # ══════════════════════════════════════════════════════
    # --- Army Corps / USACE parks ---
    {"name": "Balus Creek Park",           "lat": 34.2533889, "lon": -83.9144083, "type": "Launch", "hours": "Daily 7am–10pm",          "web": "https://lakelanier.com/boat-ramps/"},
    {"name": "Belton Bridge Park",         "lat": 34.4374510, "lon": -83.6807130, "type": "Launch", "hours": "Mar 24–Sep 22, 8am–10pm", "web": "https://lakelanier.com/boat-ramps/"},
    {"name": "Bolding Mill Park & Ramp",   "lat": 34.3382421, "lon": -83.9542324, "type": "Launch", "hours": "Open year-round",         "web": "https://lakelanier.com/directory/parks/bolding-mill-park/"},
    {"name": "Burton Mill Park Ramp",      "lat": 34.1673665, "lon": -83.9762467, "type": "Launch", "hours": "Mar 24–Sep 22",           "web": "https://lakelanier.com/directory/parks/burton-mill-park/"},
    {"name": "East Bank Park Ramp",        "lat": 34.1519190, "lon": -84.0592933, "type": "Launch", "hours": "Open 24 hours",           "web": "https://lakelanier.com/directory/parks/east-bank-park/"},
    {"name": "Keith's Bridge Park Ramp",   "lat": 34.2826786, "lon": -83.9440260, "type": "Launch", "hours": "Mar 24–Sep 22",           "web": "https://lakelanier.com/directory/parks/keith-bridge-park/"},
    {"name": "Little Hall Park Ramp",      "lat": 34.3104649, "lon": -83.9423999, "type": "Launch", "hours": "Open year-round",         "web": "https://lakelanier.com/directory/parks/little-hall-park/"},
    {"name": "Long Hollow Park Ramp",      "lat": 34.2817938, "lon": -83.9720393, "type": "Launch", "hours": "Mar 24–Sep 22",           "web": "https://lakelanier.com/directory/parks/long-hollow-park/"},
    {"name": "Mountain View Park Ramp",    "lat": 34.2558365, "lon": -83.9444105, "type": "Launch", "hours": "Open year-round",         "web": "https://lakelanier.com/directory/parks/mountain-view-park/"},
    {"name": "Old Federal Park Ramp",      "lat": 34.2277107, "lon": -83.9361777, "type": "Launch", "hours": "Open year-round",         "web": "https://lakelanier.com/directory/campgrounds/old-federal-park/"},
    {"name": "Robinson Park Ramp",         "lat": 34.2639000, "lon": -84.0321000, "type": "Launch", "hours": "Mar 24–Sep 22",           "web": "https://lakelanier.com/directory/parks/robinson-park/"},
    {"name": "Thompson Creek Park Ramp",   "lat": 34.3520976, "lon": -84.0196308, "type": "Launch", "hours": "Open year-round",         "web": "https://lakelanier.com/directory/parks/thompson-creek-park/"},
    {"name": "Tidwell Park Ramp",          "lat": 34.1948953, "lon": -84.0641132, "type": "Launch", "hours": "Open 24 hours",           "web": "https://lakelanier.com/directory/parks/tidwell-park/"},
    {"name": "Toto Creek Park Ramp",       "lat": 34.3950219, "lon": -83.9802421, "type": "Launch", "hours": "Feb 28–Oct 31",           "web": "https://lakelanier.com/directory/parks/toto-creek-park/"},
    {"name": "Two Mile Creek Ramp",        "lat": 34.2215435, "lon": -84.0013254, "type": "Launch", "hours": "Open year-round",         "web": "https://lakelanier.com/directory/parks/two-mile-creek-park/"},
    {"name": "Van Pugh North Park",        "lat": 34.1873153, "lon": -83.9791274, "type": "Launch", "hours": "Open year-round",         "web": "https://lakelanier.com/directory/parks/van-pugh-park/"},
    {"name": "Van Pugh South Ramp",        "lat": 34.1843066, "lon": -83.9872652, "type": "Launch", "hours": "May–Sep (Sat–Sun)",       "web": "https://lakelanier.com/van-pugh-south-park-day-camping-on-the-lake/"},
    {"name": "Vanns Tavern Ramp",          "lat": 34.2348805, "lon": -83.9821556, "type": "Launch", "hours": "Open year-round",         "web": "https://lakelanier.com/boat-ramps/"},
    # --- Forsyth County parks ---
    {"name": "Charleston Park Ramp",       "lat": 34.2439624, "lon": -84.0461362, "type": "Launch", "hours": "Daily 7am–10pm",          "web": "https://lakelanier.com/directory/parks/charleston-park/"},
    {"name": "Shady Grove Campground",     "lat": 34.2100000, "lon": -84.0730000, "type": "Launch", "hours": "Seasonal (call ahead)",   "web": "https://lakelanier.com/directory/campgrounds/shady-grove-campground/"},
    {"name": "Six Mile Creek Park Ramp",   "lat": 34.2466862, "lon": -84.0393655, "type": "Launch", "hours": "Daily 7am–10pm",          "web": "https://lakelanier.com/directory/parks/six-mile-park/"},
    {"name": "Young Deer Creek Park",      "lat": 34.2206540, "lon": -84.0564720, "type": "Launch", "hours": "Daily 7am–10pm",          "web": "https://lakelanier.com/directory/parks/young-deer-park/"},
    {"name": "Mary Alice Park Ramp",       "lat": 34.1973656, "lon": -84.0984482, "type": "Launch", "hours": "Daily (fee $5)",          "web": "https://lakelanier.com/directory/parks/mary-alice-park/"},
    {"name": "Little Ridge Park",          "lat": 34.1904847, "lon": -84.0886591, "type": "Launch", "hours": "Daily 8am–10pm",          "web": "https://lakelanier.com/directory/parks/little-ridge-park/"},
    # --- Hall County / Gainesville parks ---
    {"name": "Clarks Bridge Park",         "lat": 34.3533160, "lon": -83.7938753, "type": "Launch", "hours": "Open year-round",         "web": "https://lakelanier.com/directory/parks/clarks-bridge-park/"},
    {"name": "Duckett Mill Park Ramp",     "lat": 34.3073924, "lon": -83.9309592, "type": "Launch", "hours": "Mar 26–Nov 16",           "web": "https://lakelanier.com/directory/parks/duckett-mill-park/"},
    {"name": "Lanier Point Park",          "lat": 34.2990922, "lon": -83.8680517, "type": "Launch", "hours": "Open 24 hours",           "web": "https://lakelanier.com/directory/parks/lanier-point-park/"},
    {"name": "Laurel Park Ramp",           "lat": 34.3550532, "lon": -83.8133850, "type": "Launch", "hours": "Open 24 hours",           "web": "https://lakelanier.com/directory/parks/laurel-park/"},
    {"name": "Little River Park Ramp",     "lat": 34.3591053, "lon": -83.8290524, "type": "Launch", "hours": "Daily 7am–10pm",          "web": "https://lakelanier.com/directory/parks/little-river-park/"},
    {"name": "Longwood Park",              "lat": 34.3038509, "lon": -83.8468570, "type": "Launch", "hours": "Open year-round",         "web": "https://lakelanier.com/directory/parks/river-forks-park/"},
    {"name": "River Forks Park Ramp",      "lat": 34.2880390, "lon": -83.9054126, "type": "Launch", "hours": "Open year-round",         "web": "https://lakelanier.com/directory/parks/river-forks-park/"},
    {"name": "Sardis Creek Park",          "lat": 34.3360965, "lon": -83.8875300, "type": "Launch", "hours": "Open 24 hours",           "web": "https://lakelanier.com/directory/parks/sardis-creek-park/"},
    {"name": "Simpson Park Ramp",          "lat": 34.3203405, "lon": -83.8917663, "type": "Launch", "hours": "Open year-round",         "web": "https://lakelanier.com/directory/parks/simpson-park/"},
    {"name": "Nix Bridge Park",            "lat": 34.3629432, "lon": -83.9850366, "type": "Launch", "hours": "Daily 8am–10pm",          "web": "https://lakelanier.com/directory/parks/nix-bridge-park/"},
    {"name": "Thompson Bridge Park",       "lat": 34.3720000, "lon": -83.9660000, "type": "Launch", "hours": "Mar 24–Sep 22",           "web": "https://lakelanier.com/directory/parks/thompson-bridge-park/"},
    # --- Dawson County parks ---
    {"name": "War Hill Park Ramp",         "lat": 34.3341563, "lon": -83.9627713, "type": "Launch", "hours": "Daily (fee $3)",          "web": "https://lakelanier.com/directory/campgrounds/war-hill/"},
    {"name": "Wahoo Creek Park Ramp",      "lat": 34.3865982, "lon": -83.8598834, "type": "Launch", "hours": "Daily 7am–10pm",          "web": "https://lakelanier.com/directory/parks/wahoo-creek-park/"},
    {"name": "Toto Creek Campground",      "lat": 34.3950219, "lon": -83.9802421, "type": "Launch", "hours": "Feb 28–Oct 31",           "web": "https://www.recreation.gov/camping/toto-creek-campground/r/campgroundDetails.do?contractCode=NRSO&parkId=151041"},
    # --- Lumpkin County ---
    {"name": "Shoal Creek Park Ramp",      "lat": 34.1586087, "lon": -84.0078342, "type": "Launch", "hours": "Daily 7am–10pm",          "web": "https://lakelanier.com/directory/parks/shoal-creek-park/"},
    {"name": "Big Creek Park Ramp",        "lat": 34.1659897, "lon": -83.9950671, "type": "Launch", "hours": "Daily 6am–10pm",          "web": "https://lakelanier.com/directory/parks/big-creek-park/"},
    # --- State Park ---
    {"name": "Don Carter State Park",      "lat": 34.3875314, "lon": -83.7479736, "type": "Launch", "hours": "Daily 8am–5pm (fee req)", "web": "https://gastateparks.org/DonCarter"},
]



places_json = json.dumps(places)
map_tile_url = ("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                if st.session_state.dark_mode else
                "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png")
js_metric_flag = "true" if st.session_state.is_metric else "false"
dash_bg = "rgba(20, 24, 38, 0.97)" if st.session_state.dark_mode else "rgba(255, 255, 255, 0.97)"

nav_html = f"""
<!DOCTYPE html><html><head>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
*, *::before, *::after {{ box-sizing: border-box; }}
body {{ margin:0; padding:0; font-family:'Barlow',-apple-system,sans-serif; background:transparent; overflow:hidden; }}

/* ── BASE MAP CONTAINER (embedded mode) ── */
#map-container {{
    position:relative; height:600px; width:100%;
    border-radius:14px; overflow:hidden;
    border:1px solid {theme['border']};
    box-shadow:0 4px 20px rgba(0,0,0,0.15);
    transition: all 0.3s ease;
}}
#map {{ height:100%; width:100%; z-index:1; }}

/* ── FULLSCREEN MODE ── */
body.fullscreen-active {{
    position:fixed; inset:0; z-index:999999; overflow:hidden;
    background:#000;
}}
body.fullscreen-active #map-container {{
    position:fixed; inset:0; height:100dvh; width:100vw;
    border-radius:0; border:none; box-shadow:none;
    z-index:999999;
}}

/* ── FULLSCREEN TOGGLE BUTTON ── */
#fullscreen-btn {{
    position:absolute; bottom:14px; left:14px; z-index:1002;
    background:{theme['card_bg']}; color:{theme['text']};
    border:1px solid {theme['border']}; border-radius:10px;
    padding:8px 12px; cursor:pointer; font-size:0.78rem; font-weight:700;
    display:flex; align-items:center; gap:6px;
    box-shadow:0 2px 8px rgba(0,0,0,0.3); transition:all 0.2s;
    font-family:'Barlow Condensed',sans-serif; letter-spacing:0.5px;
}}
#fullscreen-btn:active {{ transform:scale(0.96); }}
body.fullscreen-active #fullscreen-btn {{
    bottom:20px; left:20px;
    background:rgba(20,24,38,0.92); color:white; border-color:rgba(255,255,255,0.2);
}}

/* ── NAV DASHBOARD (slides up from bottom) ── */
#nav-dashboard {{
    position:absolute; bottom:0; left:0; width:100%; z-index:1001;
    background:{dash_bg}; backdrop-filter:blur(16px); -webkit-backdrop-filter:blur(16px);
    color:{theme['text']}; padding:16px 20px 22px; border-top:3px solid #3498db;
    box-sizing:border-box; border-radius:20px 20px 0 0;
    transform:translateY(110%); transition:transform 0.3s cubic-bezier(0.2,0.9,0.3,1);
    box-shadow:0 -8px 30px rgba(0,0,0,0.35);
}}
#nav-dashboard.active {{ transform:translateY(0); }}

.nav-header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }}
.nav-dest {{ font-size:1rem; font-weight:800; color:#3498db; font-family:'Barlow Condensed',sans-serif; letter-spacing:0.3px; max-width:70%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.stop-btn {{ background:#e74c3c; color:white; border:none; padding:8px 16px; border-radius:20px; font-weight:700; cursor:pointer; font-size:0.82rem; font-family:'Barlow Condensed',sans-serif; letter-spacing:0.5px; }}
.stop-btn:active {{ background:#c0392b; }}

.stats-grid {{ display:grid; grid-template-columns:repeat(3,1fr); text-align:center; gap:8px; }}
.stat-box {{ background:{'rgba(255,255,255,0.05)' if st.session_state.dark_mode else 'rgba(0,0,0,0.04)'}; border-radius:12px; padding:10px 6px; }}
.stat-val {{ font-size:1.8rem; font-weight:900; line-height:1; font-family:'Barlow Condensed',sans-serif; }}
.stat-lbl {{ font-size:0.62rem; opacity:0.65; font-weight:700; text-transform:uppercase; letter-spacing:1px; margin-bottom:2px; }}
.stat-unit {{ font-size:0.6rem; opacity:0.5; margin-top:2px; }}

/* ── SEARCH ── */
#search-container {{ position:absolute; top:12px; left:12px; z-index:1000; width:58%; max-width:280px; }}
#poi-search {{
    width:100%; padding:11px 16px; border-radius:24px;
    border:2px solid #3498db; background:{theme['card_bg']}; color:{theme['text']};
    font-weight:600; font-size:0.9rem; outline:none;
    box-shadow:0 4px 14px rgba(0,0,0,0.28); box-sizing:border-box;
}}
#search-results {{
    display:none; background:{theme['card_bg']}; margin-top:6px; border-radius:14px;
    border:1px solid {theme['border']}; box-shadow:0 6px 20px rgba(0,0,0,0.35);
    overflow:hidden; max-height:220px; overflow-y:auto;
}}
.search-item {{ padding:11px 15px; cursor:pointer; border-bottom:1px solid {theme['border']}; color:{theme['text']}; font-size:0.85rem; }}
.search-item:last-child {{ border-bottom:none; }}
.search-item:active {{ background:rgba(52,152,219,0.2); }}

/* ── FILTER PANEL ── */
#filter-panel {{
    position:absolute; top:12px; right:12px; z-index:1000;
    background:{dash_bg}; backdrop-filter:blur(8px);
    color:{theme['text']}; padding:8px 12px; border-radius:12px;
    box-shadow:0 4px 14px rgba(0,0,0,0.28); border:1px solid {theme['border']};
    font-size:0.82rem; font-weight:700;
}}
.filter-cb {{ margin-right:5px; transform:scale(1.2); cursor:pointer; accent-color:#3498db; }}
.filter-row {{ margin-bottom:5px; display:flex; align-items:center; cursor:pointer; gap:2px; }}
.filter-row:last-child {{ margin-bottom:0; }}

/* ── MARKERS ── */
.map-marker {{
    width:36px; height:36px; background:white; border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    box-shadow:0 3px 10px rgba(0,0,0,0.4); font-size:18px; border:2.5px solid white;
    transition:transform 0.15s; cursor:pointer;
}}
.map-marker:active {{ transform:scale(1.2); }}
.marker-dining {{ border-color:#e74c3c; background:#fff5f5; }}
.marker-fuel {{ border-color:#f39c12; background:#fffbf0; }}
.marker-marina {{ border-color:#3498db; background:#eaf4fd; }}
.marker-launch {{ border-color:#27ae60; background:#edfaf1; }}

.poi-label {{
    background:transparent!important; border:none!important; box-shadow:none!important;
    color:{theme['text']}!important; font-weight:800!important; font-size:0.82rem!important;
    text-shadow:1px 1px 0 {theme['bg']},-1px -1px 0 {theme['bg']},1px -1px 0 {theme['bg']},-1px 1px 0 {theme['bg']}!important;
    opacity:0!important; pointer-events:none!important; transition:opacity 0.3s!important;
    white-space:nowrap!important;
}}
#map.show-labels .poi-label {{ opacity:1!important; }}

/* ── POPUP ── */
.leaflet-popup-content-wrapper {{ border-radius:14px!important; box-shadow:0 8px 24px rgba(0,0,0,0.2)!important; }}
.start-btn {{
    background:linear-gradient(135deg,#2980b9,#3498db); color:white; border:none;
    padding:11px 16px; border-radius:10px; font-weight:700; font-size:0.88rem;
    cursor:pointer; margin-top:10px; width:100%;
    font-family:'Barlow Condensed',sans-serif; letter-spacing:0.5px;
}}
.start-btn:active {{ background:#2980b9; }}

/* ── RECENTER ── */
#recenter-btn {{
    display:none; position:absolute; bottom:58px; right:14px; z-index:1002;
    background:{theme['card_bg']}; color:#3498db;
    border:2px solid #3498db; width:46px; height:46px; border-radius:50%; padding:0;
    box-shadow:0 4px 14px rgba(0,0,0,0.3); cursor:pointer;
    align-items:center; justify-content:center; transition:all 0.2s;
}}
#recenter-btn:active {{ background:#3498db; color:white; }}

.nav-arrow-marker {{ display:flex; align-items:center; justify-content:center; transition:transform 0.08s linear; transform-origin:center; }}

/* ── MOBILE ── */
@media (max-width:600px) {{
    #search-container {{ width:calc(100% - 110px); max-width:none; left:10px; }}
    #filter-panel {{ top:10px; right:10px; padding:6px 10px; font-size:0.76rem; }}
    #map-container {{ height:480px; border-radius:12px; }}
    .stat-val {{ font-size:1.5rem; }}
    #nav-dashboard {{ padding:14px 16px 20px; }}
    body.fullscreen-active #map-container {{ height:100dvh; }}
}}
</style></head><body>
<div id="map-container">

    <!-- Search -->
    <div id="search-container">
        <input type="text" id="poi-search" placeholder="🔍 Search destinations..." oninput="filterSearch()" autocomplete="off">
        <div id="search-results"></div>
    </div>

    <!-- Filters -->
    <div id="filter-panel">
        <label class="filter-row"><input type="checkbox" class="filter-cb" value="Dining" checked onchange="renderMarkers()"> 🍔</label>
        <label class="filter-row"><input type="checkbox" class="filter-cb" value="Fuel" checked onchange="renderMarkers()"> ⛽</label>
        <label class="filter-row"><input type="checkbox" class="filter-cb" value="Marina" checked onchange="renderMarkers()"> ⚓</label>
        <label class="filter-row"><input type="checkbox" class="filter-cb" value="Launch" checked onchange="renderMarkers()"> 🚤</label>
    </div>

    <!-- Recenter -->
    <button id="recenter-btn" onclick="recenterMap()">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/><line x1="22" y1="12" x2="18" y2="12"/><line x1="6" y1="12" x2="2" y2="12"/><line x1="12" y1="6" x2="12" y2="2"/><line x1="12" y1="22" x2="12" y2="18"/>
        </svg>
    </button>

    <!-- Fullscreen toggle -->
    <button id="fullscreen-btn" onclick="toggleFullscreen()">
        <svg id="fs-icon-expand" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/>
        </svg>
        <svg id="fs-icon-shrink" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="display:none">
            <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 0 2-2h3M3 16h3a2 2 0 0 0 2 2v3"/>
        </svg>
        <span id="fs-label">Full Screen</span>
    </button>

    <!-- Nav dashboard -->
    <div id="nav-dashboard">
        <div class="nav-header">
            <div class="nav-dest" id="nav-title">Navigating…</div>
            <button class="stop-btn" onclick="stopNav()">🛑 Stop Nav</button>
        </div>
        <div class="stats-grid">
            <div class="stat-box">
                <div class="stat-lbl">Speed</div>
                <div class="stat-val" id="gps-speed">--</div>
                <div class="stat-unit" id="lbl-speed">mph</div>
            </div>
            <div class="stat-box">
                <div class="stat-lbl">Distance</div>
                <div class="stat-val" id="gps-dist" style="color:#e74c3c">--</div>
                <div class="stat-unit" id="lbl-dist">miles</div>
            </div>
            <div class="stat-box">
                <div class="stat-lbl">ETA</div>
                <div class="stat-val" id="gps-eta" style="color:#3498db">--</div>
                <div class="stat-unit">mins</div>
            </div>
        </div>
    </div>

    <div id="map"></div>
</div>

<script>
var isMetric={js_metric_flag};
var map=L.map('map',{{zoomControl:false}}).setView([34.20,-83.97],11);
L.tileLayer('{map_tile_url}',{{attribution:'&copy; Carto',maxZoom:19}}).addTo(map);
L.control.zoom({{position:'topright'}}).addTo(map);

var places={places_json};
var markersLayer=L.layerGroup().addTo(map);
var isFullscreen=false;

/* ── FULLSCREEN ── */
window.toggleFullscreen=function(){{
    isFullscreen=!isFullscreen;
    document.body.classList.toggle('fullscreen-active',isFullscreen);
    document.getElementById('fs-icon-expand').style.display=isFullscreen?'none':'block';
    document.getElementById('fs-icon-shrink').style.display=isFullscreen?'block':'none';
    document.getElementById('fs-label').innerText=isFullscreen?'Exit Full':'Full Screen';

    if(isFullscreen){{
        // Lock parent page scroll so fullscreen covers everything
        try{{
            let ps=window.parent.document.getElementById('nav-fs-style');
            if(!ps){{ ps=window.parent.document.createElement('style'); ps.id='nav-fs-style'; window.parent.document.head.appendChild(ps); }}
            ps.innerHTML='body,html{{ overflow:hidden!important; }} header[data-testid="stHeader"]{{ display:none!important; }}';
            window.parent.document.body.style.overflow='hidden';
        }}catch(e){{}}
    }} else {{
        try{{
            let ps=window.parent.document.getElementById('nav-fs-style');
            if(ps) ps.innerHTML='';
            window.parent.document.body.style.overflow='';
        }}catch(e){{}}
    }}
    setTimeout(()=>map.invalidateSize(),50);
}};

/* ── MARKERS ── */
var iconMap={{
    "Dining":L.divIcon({{className:'',html:'<div class="map-marker marker-dining">🍔</div>',iconSize:[36,36],iconAnchor:[18,18],popupAnchor:[0,-18]}}),
    "Fuel":  L.divIcon({{className:'',html:'<div class="map-marker marker-fuel">⛽</div>',  iconSize:[36,36],iconAnchor:[18,18],popupAnchor:[0,-18]}}),
    "Marina":L.divIcon({{className:'',html:'<div class="map-marker marker-marina">⚓</div>',iconSize:[36,36],iconAnchor:[18,18],popupAnchor:[0,-18]}}),
    "Launch":L.divIcon({{className:'',html:'<div class="map-marker marker-launch">🚤</div>',iconSize:[36,36],iconAnchor:[18,18],popupAnchor:[0,-18]}})
}};
var targetIcon=L.divIcon({{className:'',html:'<div style="font-size:32px;filter:drop-shadow(0 3px 6px rgba(0,0,0,0.5));">📍</div>',iconSize:[32,32],iconAnchor:[16,32],popupAnchor:[0,-32]}});

window.renderMarkers=function(){{
    markersLayer.clearLayers();
    var active=Array.from(document.querySelectorAll('.filter-cb')).filter(c=>c.checked).map(c=>c.value);
    places.forEach((p,i)=>{{
        if(!active.includes(p.type)) return;
        var icon=iconMap[p.type]||iconMap["Marina"];
        var m=L.marker([p.lat,p.lon],{{icon}}).addTo(markersLayer);
        m.bindTooltip(L.tooltip({{permanent:true,direction:'bottom',className:'poi-label',offset:[0,8]}}).setContent(p.name));
        m.bindPopup(`<div style="text-align:center;min-width:170px;font-family:-apple-system,sans-serif;padding:4px 2px;">
            <b style="font-size:1rem;color:#1a1a2e;display:block;margin-bottom:3px;">${{p.name}}</b>
            <span style="font-size:0.72rem;color:#7f8c8d;text-transform:uppercase;font-weight:700;letter-spacing:0.5px;">${{p.type}}</span>
            <div style="font-size:0.82rem;margin:8px 0;color:#2c3e50;background:#f8f9fa;padding:6px 8px;border-radius:8px;line-height:1.4;">🕒 ${{p.hours}}</div>
            <a href="${{p.web}}" target="_blank" rel="noopener" style="font-size:0.85rem;color:#3498db;text-decoration:none;font-weight:700;">🌐 More Info</a><br/>
            <button class="start-btn" onclick="startNav(${{i}})">🧭 Navigate Here</button>
        </div>`);
    }});
}};
renderMarkers();

map.on('zoomend',()=>document.getElementById('map').classList[map.getZoom()>=13?'add':'remove']('show-labels'));

/* ── SEARCH ── */
window.filterSearch=function(){{
    var q=document.getElementById('poi-search').value.toLowerCase().trim();
    var rd=document.getElementById('search-results');
    if(!q){{rd.style.display='none';return;}}
    var matches=places.filter(p=>p.name.toLowerCase().includes(q)||p.type.toLowerCase().includes(q));
    if(!matches.length){{rd.style.display='none';return;}}
    rd.innerHTML=''; rd.style.display='block';
    matches.slice(0,8).forEach(m=>{{
        var idx=places.indexOf(m);
        var div=document.createElement('div'); div.className='search-item';
        div.innerHTML=`<b>${{m.name}}</b> <span style="font-size:0.7rem;opacity:0.6;">· ${{m.type}}</span>`;
        div.onclick=()=>{{
            document.getElementById('poi-search').value=''; rd.style.display='none';
            map.setView([m.lat,m.lon],15,{{animate:true}});
            setTimeout(()=>startNav(idx),400);
        }};
        rd.appendChild(div);
    }});
}};

/* ── NAV STATE ── */
var watchId=null,userMarker=null,routeLine=null,targetMarker=null,currentTarget=null;
var isNavigating=false,mapLocked=true,lastLat=null,lastLon=null,currentHeading=0;

map.on('dragstart',()=>{{
    if(isNavigating){{ mapLocked=false; document.getElementById('recenter-btn').style.display='flex'; }}
}});
window.recenterMap=function(){{
    mapLocked=true; document.getElementById('recenter-btn').style.display='none';
    if(lastLat!=null) map.setView([lastLat,lastLon],15,{{animate:true}});
}};

function handleOrientation(e){{
    if(!isNavigating) return;
    var h=e.webkitCompassHeading?e.webkitCompassHeading:(e.alpha!=null?360-e.alpha:0);
    currentHeading=h;
    var arr=document.getElementById('map-nav-arrow');
    if(arr) arr.style.transform=`rotate(${{h}}deg)`;
}}

function getDistance(lat1,lon1,lat2,lon2){{
    const R=isMetric?6371:3958.8;
    const dLat=(lat2-lat1)*Math.PI/180, dLon=(lon2-lon1)*Math.PI/180;
    const a=Math.sin(dLat/2)**2+Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dLon/2)**2;
    return R*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}}

window.startNav=function(index){{
    currentTarget=places[index]; map.closePopup();
    isNavigating=true; mapLocked=true;
    markersLayer.clearLayers();

    // Auto enter fullscreen on mobile when nav starts
    if(!isFullscreen && window.innerWidth<=768) toggleFullscreen();

    document.getElementById('nav-dashboard').classList.add('active');
    document.getElementById('search-container').style.display='none';
    document.getElementById('filter-panel').style.display='none';
    document.getElementById('recenter-btn').style.display='none';
    document.getElementById('nav-title').innerText='→ '+currentTarget.name;
    document.getElementById('lbl-speed').innerText=isMetric?'km/h':'mph';
    document.getElementById('lbl-dist').innerText=isMetric?'km':'miles';

    if(targetMarker) map.removeLayer(targetMarker);
    targetMarker=L.marker([currentTarget.lat,currentTarget.lon],{{icon:targetIcon}}).addTo(map);

    if(typeof DeviceOrientationEvent!=='undefined'&&typeof DeviceOrientationEvent.requestPermission==='function'){{
        DeviceOrientationEvent.requestPermission()
            .then(s=>{{ if(s==='granted') window.addEventListener('deviceorientation',handleOrientation,true); }})
            .catch(()=>{{}});
    }} else {{
        window.addEventListener('deviceorientationabsolute',handleOrientation,true);
        window.addEventListener('deviceorientation',handleOrientation,true);
    }}
    if(navigator.geolocation)
        watchId=navigator.geolocation.watchPosition(updateNav,handleGpsError,{{enableHighAccuracy:true,maximumAge:1000,timeout:8000}});
}};

window.stopNav=function(){{
    isNavigating=false; mapLocked=false;
    if(watchId) navigator.geolocation.clearWatch(watchId);
    window.removeEventListener('deviceorientation',handleOrientation,true);
    window.removeEventListener('deviceorientationabsolute',handleOrientation,true);

    // Exit fullscreen when nav stops
    if(isFullscreen) toggleFullscreen();

    renderMarkers();
    document.getElementById('nav-dashboard').classList.remove('active');
    document.getElementById('search-container').style.display='block';
    document.getElementById('filter-panel').style.display='block';
    document.getElementById('recenter-btn').style.display='none';
    if(routeLine){{ map.removeLayer(routeLine); routeLine=null; }}
    if(targetMarker){{ map.removeLayer(targetMarker); targetMarker=null; }}
    if(userMarker){{ map.removeLayer(userMarker); userMarker=null; }}
    map.setView([34.20,-83.97],11,{{animate:true}});
}};

function updateNav(pos){{
    if(!isNavigating||!currentTarget) return;
    lastLat=pos.coords.latitude; lastLon=pos.coords.longitude;
    var uLL=[lastLat,lastLon], tLL=[currentTarget.lat,currentTarget.lon];

    if(!userMarker){{
        var arrowHtml=`<div id="map-nav-arrow" class="nav-arrow-marker" style="transform:rotate(${{currentHeading}}deg);">
            <svg viewBox="0 0 24 24" width="48" height="48" style="filter:drop-shadow(0 4px 8px rgba(0,0,0,0.6));">
                <path d="M12 2L22 22L12 18L2 22L12 2Z" fill="#3498db" stroke="#fff" stroke-width="1.5"/>
            </svg></div>`;
        userMarker=L.marker(uLL,{{
            icon:L.divIcon({{className:'',html:arrowHtml,iconSize:[48,48],iconAnchor:[24,24]}}),
            zIndexOffset:1000
        }}).addTo(map);
    }} else {{ userMarker.setLatLng(uLL); }}

    if(mapLocked) map.setView(uLL,16,{{animate:true}});

    if(!routeLine) routeLine=L.polyline([uLL,tLL],{{color:'#3498db',weight:5,dashArray:'10,8',opacity:0.85}}).addTo(map);
    else routeLine.setLatLngs([uLL,tLL]);

    var dist=getDistance(lastLat,lastLon,currentTarget.lat,currentTarget.lon);
    document.getElementById('gps-dist').innerText=dist.toFixed(2);

    var spd=0;
    if(pos.coords.speed!=null){{
        spd=isMetric?(pos.coords.speed*3.6):(pos.coords.speed*2.23694);
        document.getElementById('gps-speed').innerText=spd.toFixed(1);
    }} else {{ document.getElementById('gps-speed').innerText='0.0'; }}

    document.getElementById('gps-eta').innerText=spd>1?Math.round((dist/spd)*60):'--';
}}

function handleGpsError(e){{
    console.warn('GPS error:',e.message);
    document.getElementById('gps-eta').innerText='GPS?';
}}
</script></body></html>
"""
st.components.v1.html(nav_html, height=640, scrolling=False)

# ===================================================
# UTILITIES
# ===================================================
st.markdown("---")

with st.expander("✅ Pre-Departure Checklist"):
    st.checkbox("Hull drain plug securely installed")
    st.checkbox("Battery switch set to ON (or ALL/1+2)")
    st.checkbox("Engine blower run for 4 minutes before starting")
    st.checkbox("Life jackets counted & readily accessible")
    st.checkbox("Anchor and dock lines ready")
    st.checkbox("Sufficient fuel for the trip")
    st.checkbox("Float plan left with someone onshore")
    st.checkbox("VHF radio or phone fully charged")
    st.checkbox("Navigation lights checked and working")
    st.checkbox("Fire extinguisher charged and accessible")

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
        if current_browns > boat_height:
            st.success("🟢 Safe to pass Browns Bridge")
        else:
            st.error("🔴 DO NOT PASS Browns Bridge")
        st.markdown(f"**Boling Bridge Clearance:** {round(current_boling, 1)} ft")
        if current_boling > boat_height:
            st.success("🟢 Safe to pass Boling Bridge")
        else:
            st.error("🔴 DO NOT PASS Boling Bridge")
    else:
        st.warning("Lake level data currently unavailable.")
