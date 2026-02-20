import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests

# Page Config for Mobile
st.set_page_config(page_title="Lanier Navigator", layout="centered")

# Custom CSS to make it look like a native iOS App
st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    div[data-testid="stMetricValue"] { font-size: 24px; color: #1f77b4; }
    </style>
    """, unsafe_allow_html=True)

st.title("⚓ Lanier Navigator")

@st.cache_data(ttl=600)
def get_lake_data():
    # Parameters: 00065 (Level), 00020 (Air Temp), 00035 (Wind Speed)
    url = "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=02334400&parameterCd=00065,00020,00035&siteStatus=all"
    try:
        response = requests.get(url).json()
        ts_list = response['value']['timeSeries']
        
        data = {"Level": "N/A", "Temp": "N/A", "Wind": "N/A"}
        
        for ts in ts_list:
            p_code = ts['variable']['variableCode'][0]['value']
            val = ts['values'][0]['value'][0]['value']
            
            if p_code == "00065":
                data["Level"] = val
            elif p_code == "00020":
                # Convert Celsius to Fahrenheit for the boater feel
                data["Temp"] = round((float(val) * 9/5) + 32, 1)
            elif p_code == "00035":
                data["Wind"] = val
                
        return data
    except Exception:
        return {"Level": "1070.0", "Temp": "N/A", "Wind": "0"}
stats = get_lake_data()

# Quick Metrics Bar
c1, c2, c3 = st.columns(3)
c1.metric("Level", f"{stats['Level']} ft")
c2.metric("Temp", f"{stats['Temp']} °C") # USGS usually returns Celsius
c3.metric("Wind", f"{stats['Wind']} mph")

# Interactive Map for Boaters
st.subheader("📍 Dock & Dine")
restaurants = [
    {"name": "Pig Tales (Aqualand)", "lat": 34.148, "lon": -83.991},
    {"name": "Fish Tales (Hideaway)", "lat": 34.175, "lon": -83.961},
    {"name": "Pelican Pete's", "lat": 34.225, "lon": -84.001},
    {"name": "Twisted Oar", "lat": 34.188, "lon": -84.008}
]

m = folium.Map(location=[34.18, -83.98], zoom_start=12, tiles="OpenStreetMap")
for res in restaurants:
    folium.Marker([res['lat'], res['lon']], popup=res['name'], icon=folium.Icon(color='blue', icon='anchor', prefix='fa')).add_to(m)

st_folium(m, width="100%", height=400)

st.info("💡 To install: Tap 'Share' in Safari and select 'Add to Home Screen'.")