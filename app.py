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

@st.cache_data(ttl=600) # Update every 10 mins
def get_lake_data():
    # USGS API for Lanier (Buford Dam)
    url = "https://waterservices.usgs.gov/nwis/iv/?format=json&sites=02334400&parameterCd=00065,00010,00035,00036&siteStatus=all"
    try:
        data = requests.get(url).json()
        ts = data['value']['timeSeries']
        # Map parameters to readable values
        stats = {
            "Level": ts[0]['values'][0]['value'][0]['value'],
            "Temp": ts[1]['values'][0]['value'][0]['value'],
            "Wind": ts[2]['values'][0]['value'][0]['value']
        }
        return stats
    except:
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