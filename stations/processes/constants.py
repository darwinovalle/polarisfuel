MAX_CANDIDATES = 3
SUGGEST_LIMIT = 6
MAX_STATION_GEOCODE_ATTEMPTS = 30
MAX_STATION_GEOCODE_SECONDS = 6.0
MAX_STATION_POOL_SIZE = 10
MAX_REAL_STATION_CANDIDATES = 40
MIN_ROUTE_CORRIDOR_M = 80000.0
MAX_ROUTE_CORRIDOR_M = 240000.0
MAX_INITIAL_GEO_FAILS = 8
DEFAULT_VEHICLE_MPG = 25.0
DEFAULT_TANK_CAPACITY_GAL = 16.0
DEFAULT_START_FUEL_PERCENT = 100.0

SUPPORTED_US_BOUNDS = [
    {"lat_min": 24.3, "lat_max": 49.6, "lon_min": -125.0, "lon_max": -66.8},
    {"lat_min": 51.0, "lat_max": 71.8, "lon_min": -170.5, "lon_max": -129.0},
    {"lat_min": 18.5, "lat_max": 22.7, "lon_min": -160.8, "lon_max": -154.4},
]

STATE_CENTROIDS = {
    "AL": (32.8067, -86.7911),
    "AR": (34.9697, -92.3731),
    "AZ": (33.7298, -111.4312),
    "CA": (36.1162, -119.6816),
    "CO": (39.0598, -105.3111),
    "CT": (41.5978, -72.7554),
    "DC": (38.9072, -77.0369),
    "DE": (39.3185, -75.5071),
    "FL": (27.7663, -81.6868),
    "GA": (33.0406, -83.6431),
    "IA": (42.0115, -93.2105),
    "ID": (44.2405, -114.4788),
    "IL": (40.3495, -88.9861),
    "IN": (39.8494, -86.2583),
    "KS": (38.5266, -96.7265),
    "KY": (37.6681, -84.6701),
    "LA": (31.1695, -91.8678),
    "MA": (42.2302, -71.5301),
    "MD": (39.0639, -76.8021),
    "ME": (44.6939, -69.3819),
    "MI": (43.3266, -84.5361),
    "MN": (45.6945, -93.9002),
    "MO": (38.4561, -92.2884),
    "MS": (32.7416, -89.6787),
    "MT": (46.9219, -110.4544),
    "NC": (35.6301, -79.8064),
    "ND": (47.5289, -99.7840),
    "NE": (41.1254, -98.2681),
    "NH": (43.4525, -71.5639),
    "NJ": (40.2989, -74.5210),
    "NM": (34.8405, -106.2485),
    "NV": (38.3135, -117.0554),
    "NY": (42.1657, -74.9481),
    "OH": (40.3888, -82.7649),
    "OK": (35.5653, -96.9289),
    "OR": (44.5720, -122.0709),
    "PA": (40.5908, -77.2098),
    "RI": (41.6809, -71.5118),
    "SC": (33.8569, -80.9450),
    "SD": (44.2998, -99.4388),
    "TN": (35.7478, -86.6923),
    "TX": (31.0545, -97.5635),
    "UT": (40.1500, -111.8624),
    "VA": (37.7693, -78.1700),
    "VT": (44.0459, -72.7107),
    "WA": (47.4009, -121.4905),
    "WI": (44.2685, -89.6165),
    "WV": (38.4912, -80.9545),
    "WY": (42.7560, -107.3025),
}

FALLBACK_PLACES = [
    {"name": "San Francisco, California, United States", "lat": 37.7749, "lon": -122.4194, "aliases": ["san francisco", "sf", "california"]},
    {"name": "Salt Lake City, Utah, United States", "lat": 40.7608, "lon": -111.8910, "aliases": ["salt lake city", "slc", "utah"]},
    {"name": "Los Angeles, California, United States", "lat": 34.0522, "lon": -118.2437, "aliases": ["los angeles", "la", "california"]},
    {"name": "San Diego, California, United States", "lat": 32.7157, "lon": -117.1611, "aliases": ["san diego", "california"]},
    {"name": "Sacramento, California, United States", "lat": 38.5816, "lon": -121.4944, "aliases": ["sacramento", "california"]},
    {"name": "Las Vegas, Nevada, United States", "lat": 36.1699, "lon": -115.1398, "aliases": ["las vegas", "vegas", "nevada"]},
    {"name": "Phoenix, Arizona, United States", "lat": 33.4484, "lon": -112.0740, "aliases": ["phoenix", "arizona"]},
    {"name": "Denver, Colorado, United States", "lat": 39.7392, "lon": -104.9903, "aliases": ["denver", "colorado"]},
    {"name": "Seattle, Washington, United States", "lat": 47.6062, "lon": -122.3321, "aliases": ["seattle", "washington"]},
    {"name": "Portland, Oregon, United States", "lat": 45.5152, "lon": -122.6784, "aliases": ["portland", "oregon"]},
    {"name": "Dallas, Texas, United States", "lat": 32.7767, "lon": -96.7970, "aliases": ["dallas", "texas"]},
    {"name": "Austin, Texas, United States", "lat": 30.2672, "lon": -97.7431, "aliases": ["austin", "texas"]},
    {"name": "Houston, Texas, United States", "lat": 29.7604, "lon": -95.3698, "aliases": ["houston", "texas"]},
    {"name": "San Antonio, Texas, United States", "lat": 29.4241, "lon": -98.4936, "aliases": ["san antonio", "texas"]},
    {"name": "Chicago, Illinois, United States", "lat": 41.8781, "lon": -87.6298, "aliases": ["chicago", "illinois"]},
    {"name": "New York, New York, United States", "lat": 40.7128, "lon": -74.0060, "aliases": ["new york", "nyc", "new york city"]},
    {"name": "Boston, Massachusetts, United States", "lat": 42.3601, "lon": -71.0589, "aliases": ["boston", "massachusetts"]},
    {"name": "Atlanta, Georgia, United States", "lat": 33.7490, "lon": -84.3880, "aliases": ["atlanta", "georgia"]},
    {"name": "Miami, Florida, United States", "lat": 25.7617, "lon": -80.1918, "aliases": ["miami", "florida"]},
    {"name": "Orlando, Florida, United States", "lat": 28.5383, "lon": -81.3792, "aliases": ["orlando", "florida"]},
    {"name": "Nashville, Tennessee, United States", "lat": 36.1627, "lon": -86.7816, "aliases": ["nashville", "tennessee"]},
    {"name": "New Orleans, Louisiana, United States", "lat": 29.9511, "lon": -90.0715, "aliases": ["new orleans", "louisiana"]},
    {"name": "Washington, District of Columbia, United States", "lat": 38.9072, "lon": -77.0369, "aliases": ["washington dc", "dc", "district of columbia"]},
]
