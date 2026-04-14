from functools import lru_cache
import math
import os
import time

import httpx
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from stations.models import CurrentPrice
from stations.services.provider_errors import ProviderError
from stations.services.providers_nominatim import NominatimGeocodingProvider
from stations.services.providers_osrm import OsrmDirectionsProvider
from stations.services.providers_tomtom import TomTomDirectionsProvider
from stations.services.route_optimizer import RouteOptimizer


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
    # Contiguous United States
    {"lat_min": 24.3, "lat_max": 49.6, "lon_min": -125.0, "lon_max": -66.8},
    # Alaska
    {"lat_min": 51.0, "lat_max": 71.8, "lon_min": -170.5, "lon_max": -129.0},
    # Hawaii
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
    {
        "name": "San Francisco, California, United States",
        "lat": 37.7749,
        "lon": -122.4194,
        "aliases": ["san francisco", "sf", "california"],
    },
    {
        "name": "Salt Lake City, Utah, United States",
        "lat": 40.7608,
        "lon": -111.8910,
        "aliases": ["salt lake city", "slc", "utah"],
    },
    {
        "name": "Los Angeles, California, United States",
        "lat": 34.0522,
        "lon": -118.2437,
        "aliases": ["los angeles", "la", "california"],
    },
    {
        "name": "San Diego, California, United States",
        "lat": 32.7157,
        "lon": -117.1611,
        "aliases": ["san diego", "california"],
    },
    {
        "name": "Sacramento, California, United States",
        "lat": 38.5816,
        "lon": -121.4944,
        "aliases": ["sacramento", "california"],
    },
    {
        "name": "Las Vegas, Nevada, United States",
        "lat": 36.1699,
        "lon": -115.1398,
        "aliases": ["las vegas", "vegas", "nevada"],
    },
    {
        "name": "Phoenix, Arizona, United States",
        "lat": 33.4484,
        "lon": -112.0740,
        "aliases": ["phoenix", "arizona"],
    },
    {
        "name": "Denver, Colorado, United States",
        "lat": 39.7392,
        "lon": -104.9903,
        "aliases": ["denver", "colorado"],
    },
    {
        "name": "Seattle, Washington, United States",
        "lat": 47.6062,
        "lon": -122.3321,
        "aliases": ["seattle", "washington"],
    },
    {
        "name": "Portland, Oregon, United States",
        "lat": 45.5152,
        "lon": -122.6784,
        "aliases": ["portland", "oregon"],
    },
    {
        "name": "Dallas, Texas, United States",
        "lat": 32.7767,
        "lon": -96.7970,
        "aliases": ["dallas", "texas"],
    },
    {
        "name": "Austin, Texas, United States",
        "lat": 30.2672,
        "lon": -97.7431,
        "aliases": ["austin", "texas"],
    },
    {
        "name": "Houston, Texas, United States",
        "lat": 29.7604,
        "lon": -95.3698,
        "aliases": ["houston", "texas"],
    },
    {
        "name": "San Antonio, Texas, United States",
        "lat": 29.4241,
        "lon": -98.4936,
        "aliases": ["san antonio", "texas"],
    },
    {
        "name": "Chicago, Illinois, United States",
        "lat": 41.8781,
        "lon": -87.6298,
        "aliases": ["chicago", "illinois"],
    },
    {
        "name": "New York, New York, United States",
        "lat": 40.7128,
        "lon": -74.0060,
        "aliases": ["new york", "nyc", "new york city"],
    },
    {
        "name": "Boston, Massachusetts, United States",
        "lat": 42.3601,
        "lon": -71.0589,
        "aliases": ["boston", "massachusetts"],
    },
    {
        "name": "Atlanta, Georgia, United States",
        "lat": 33.7490,
        "lon": -84.3880,
        "aliases": ["atlanta", "georgia"],
    },
    {
        "name": "Miami, Florida, United States",
        "lat": 25.7617,
        "lon": -80.1918,
        "aliases": ["miami", "florida"],
    },
    {
        "name": "Orlando, Florida, United States",
        "lat": 28.5383,
        "lon": -81.3792,
        "aliases": ["orlando", "florida"],
    },
    {
        "name": "Nashville, Tennessee, United States",
        "lat": 36.1627,
        "lon": -86.7816,
        "aliases": ["nashville", "tennessee"],
    },
    {
        "name": "New Orleans, Louisiana, United States",
        "lat": 29.9511,
        "lon": -90.0715,
        "aliases": ["new orleans", "louisiana"],
    },
    {
        "name": "Washington, District of Columbia, United States",
        "lat": 38.9072,
        "lon": -77.0369,
        "aliases": ["washington dc", "dc", "district of columbia"],
    },
]

# Reuse provider instances across requests to avoid repeated setup overhead.

GEOCODER = NominatimGeocodingProvider(timeout=1.8, max_retries=1)
STATION_GEOCODER = NominatimGeocodingProvider(timeout=1.0, max_retries=1)
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "").strip()

if TOMTOM_API_KEY:
    DEFAULT_DIRECTIONS_ENGINE = "tomtom"
    DIRECTIONS = TomTomDirectionsProvider(
        api_key=TOMTOM_API_KEY,
        timeout=3.5,
        max_retries=1,
    )
    DIRECTIONS_RETRY = TomTomDirectionsProvider(
        api_key=TOMTOM_API_KEY,
        timeout=5.0,
        max_retries=1,
    )
    PATH_DIRECTIONS = TomTomDirectionsProvider(
        api_key=TOMTOM_API_KEY,
        timeout=7.0,
        max_retries=1,
    )
    PATH_DIRECTIONS_RETRY = TomTomDirectionsProvider(
        api_key=TOMTOM_API_KEY,
        timeout=10.0,
        max_retries=1,
    )
else:
    DEFAULT_DIRECTIONS_ENGINE = "osrm"
    DIRECTIONS = OsrmDirectionsProvider(timeout=3.0, max_retries=1)
    DIRECTIONS_RETRY = OsrmDirectionsProvider(timeout=4.0, max_retries=1)
    PATH_DIRECTIONS = OsrmDirectionsProvider(timeout=5.0, max_retries=1)
    PATH_DIRECTIONS_RETRY = OsrmDirectionsProvider(timeout=7.0, max_retries=1)


def normalize_query(value: str) -> str:
    return " ".join(value.lower().replace(",", " ").split())


@lru_cache(maxsize=5000)
def local_place_suggest(query: str, limit: int = SUGGEST_LIMIT):
    normalized = normalize_query(query)
    if len(normalized) < 2:
        return []

    query_tokens = normalized.split()
    ranked = []

    for place in FALLBACK_PLACES:
        haystack = normalize_query(" ".join([place["name"], *place.get("aliases", [])]))

        score = 0
        if haystack.startswith(normalized):
            score += 300
        if normalized in haystack:
            score += 180

        token_hits = sum(1 for token in query_tokens if token in haystack)
        if token_hits:
            score += token_hits * 20

        if score <= 0:
            continue

        ranked.append(
            (
                -score,
                len(place["name"]),
                {
                    "name": place["name"],
                    "lat": place["lat"],
                    "lon": place["lon"],
                },
            )
        )

    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked[:limit]]


@lru_cache(maxsize=8000)
def nominatim_suggest_cached(query: str):
    response = httpx.get(
        "https://nominatim.openstreetmap.org/search",
        params={
            "q": query,
            "format": "jsonv2",
            "limit": SUGGEST_LIMIT,
            "addressdetails": 1,
        },
        headers={"User-Agent": "route-fuel-v2/0.1 (django-demo)"},
        timeout=2.5,
    )

    if response.status_code != 200:
        return []

    data = response.json()
    results = []

    for item in data:
        try:
            results.append(
                {
                    "name": item.get("display_name", ""),
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                }
            )
        except Exception:
            continue

    return results


def resolve_origin_destination(query: str):
    try:
        return GEOCODER.geocode(query)
    except Exception:
        suggestions = local_place_suggest(query, limit=1)
        if suggestions:
            best = suggestions[0]
            return {
                "lat": best["lat"],
                "lon": best["lon"],
                "display_name": best["name"],
            }
        return None


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6371000.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    hav = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(d_lambda / 2) ** 2)
    )

    return 2 * radius_m * math.atan2(math.sqrt(hav), math.sqrt(1 - hav))


def is_within_supported_us_bounds(lat: float, lon: float) -> bool:
    for bounds in SUPPORTED_US_BOUNDS:
        if (
            bounds["lat_min"] <= lat <= bounds["lat_max"]
            and bounds["lon_min"] <= lon <= bounds["lon_max"]
        ):
            return True

    return False


def is_us_supported_location(location: dict) -> bool:
    try:
        lat = float(location["lat"])
        lon = float(location["lon"])
    except (KeyError, TypeError, ValueError):
        return False

    return is_within_supported_us_bounds(lat=lat, lon=lon)


def optimize_without_osrm(
    origin_coords: dict,
    destination_coords: dict,
    candidates: list,
    weights: dict,
    vehicle_mpg: float = DEFAULT_VEHICLE_MPG,
):
    avg_speed_m_per_s = 22.22  # ~80 km/h
    if vehicle_mpg <= 0:
        vehicle_mpg = DEFAULT_VEHICLE_MPG

    origin_lat = float(origin_coords["lat"])
    origin_lon = float(origin_coords["lon"])
    destination_lat = float(destination_coords["lat"])
    destination_lon = float(destination_coords["lon"])

    alternatives = []
    for station in candidates:
        station_lat = float(station["lat"])
        station_lon = float(station["lon"])
        retail_price = float(station["retail_price"])

        first_leg = haversine_distance_m(origin_lat, origin_lon, station_lat, station_lon)
        second_leg = haversine_distance_m(station_lat, station_lon, destination_lat, destination_lon)
        distance_m = first_leg + second_leg
        duration_s = distance_m / avg_speed_m_per_s
        distance_miles = distance_m / 1609.344
        fuel_cost = (distance_miles / vehicle_mpg) * retail_price

        alternatives.append(
            {
                "station": station,
                "distance_m": distance_m,
                "duration_s": duration_s,
                "geometry": "",
                "estimated_fuel_cost": fuel_cost,
            }
        )

    durations = [item["duration_s"] for item in alternatives]
    prices = [item["estimated_fuel_cost"] for item in alternatives]

    min_d, max_d = min(durations), max(durations)
    min_p, max_p = min(prices), max(prices)

    for item in alternatives:
        if max_d == min_d:
            time_norm = 0.0
        else:
            time_norm = (item["duration_s"] - min_d) / (max_d - min_d)

        if max_p == min_p:
            price_norm = 0.0
        else:
            price_norm = (item["estimated_fuel_cost"] - min_p) / (max_p - min_p)

        item["time_norm"] = time_norm
        item["price_norm"] = price_norm
        item["score"] = (weights["time"] * time_norm) + (weights["price"] * price_norm)

    alternatives.sort(key=lambda item: item["score"])
    best_option = alternatives[0]

    return {
        "origin": origin_coords,
        "destination": destination_coords,
        "best_option": best_option,
        "alternatives": alternatives,
        "weights": weights,
        "engine": "fallback_estimate",
    }


@lru_cache(maxsize=30000)
def geocode_station_cached(query: str):
    try:
        return STATION_GEOCODER.geocode(query)
    except Exception:
        return None


def project_progress_ratio(
    point_lat: float,
    point_lon: float,
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
) -> float:
    delta_lat = destination_lat - origin_lat
    delta_lon = destination_lon - origin_lon
    denominator = (delta_lat ** 2) + (delta_lon ** 2)

    if denominator <= 0:
        return 0.0

    return (
        ((point_lat - origin_lat) * delta_lat)
        + ((point_lon - origin_lon) * delta_lon)
    ) / denominator


def distance_point_to_segment_m(
    point_lat: float,
    point_lon: float,
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
) -> float:
    progress = project_progress_ratio(
        point_lat=point_lat,
        point_lon=point_lon,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        destination_lat=destination_lat,
        destination_lon=destination_lon,
    )

    progress = min(1.0, max(0.0, progress))

    closest_lat = origin_lat + ((destination_lat - origin_lat) * progress)
    closest_lon = origin_lon + ((destination_lon - origin_lon) * progress)

    return haversine_distance_m(point_lat, point_lon, closest_lat, closest_lon)


def prioritize_station_rows_for_coverage(
    price_rows,
    origin_coords: dict,
    destination_coords: dict,
):
    origin_lat = float(origin_coords["lat"])
    origin_lon = float(origin_coords["lon"])
    destination_lat = float(destination_coords["lat"])
    destination_lon = float(destination_coords["lon"])

    by_state = {}
    no_state = []

    for cp in price_rows:
        state = (cp.rack.truckstop.state or "").upper()
        if not state or state not in STATE_CENTROIDS:
            no_state.append(cp)
            continue
        by_state.setdefault(state, []).append(cp)

    for rows in by_state.values():
        rows.sort(key=lambda row: row.retail_price)

    ordered_states = sorted(
        by_state.keys(),
        key=lambda state: project_progress_ratio(
            point_lat=STATE_CENTROIDS[state][0],
            point_lon=STATE_CENTROIDS[state][1],
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        ),
    )

    interleaved = []
    made_progress = True

    while made_progress:
        made_progress = False
        for state in ordered_states:
            state_rows = by_state[state]
            if not state_rows:
                continue
            interleaved.append(state_rows.pop(0))
            made_progress = True

    interleaved.extend(sorted(no_state, key=lambda row: row.retail_price))
    return interleaved


def build_real_station_candidates(price_rows, origin_coords: dict, destination_coords: dict):
    origin_lat = float(origin_coords["lat"])
    origin_lon = float(origin_coords["lon"])
    destination_lat = float(destination_coords["lat"])
    destination_lon = float(destination_coords["lon"])

    direct_distance_m = haversine_distance_m(
        origin_lat,
        origin_lon,
        destination_lat,
        destination_lon,
    )

    route_corridor_m = max(
        MIN_ROUTE_CORRIDOR_M,
        min(MAX_ROUTE_CORRIDOR_M, direct_distance_m * 0.12),
    )

    corridor_states = set()
    for state_code, (state_lat, state_lon) in STATE_CENTROIDS.items():
        progress_ratio = project_progress_ratio(
            point_lat=state_lat,
            point_lon=state_lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        if progress_ratio < -0.2 or progress_ratio > 1.2:
            continue

        state_distance_m = distance_point_to_segment_m(
            point_lat=state_lat,
            point_lon=state_lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        if state_distance_m <= (route_corridor_m * 1.4):
            corridor_states.add(state_code)

    if corridor_states:
        filtered_rows = [
            cp
            for cp in price_rows
            if (cp.rack.truckstop.state or "").upper() in corridor_states
        ]
    else:
        filtered_rows = list(price_rows)

    filtered_rows = prioritize_station_rows_for_coverage(
        filtered_rows,
        origin_coords=origin_coords,
        destination_coords=destination_coords,
    )

    real_candidates = []
    attempted_queries = set()
    geocode_attempts = 0
    consecutive_geo_failures = 0
    geocode_started_at = time.monotonic()

    def geocode_budget_exhausted() -> bool:
        return (time.monotonic() - geocode_started_at) >= MAX_STATION_GEOCODE_SECONDS

    for cp in filtered_rows:
        if geocode_attempts >= MAX_STATION_GEOCODE_ATTEMPTS:
            break

        # Keep optimize latency bounded when external geocoding is slow.
        if geocode_budget_exhausted():
            break

        ts = cp.rack.truckstop
        station_query = f"{ts.name}, {ts.city}, {ts.state}, USA"

        if station_query in attempted_queries:
            continue

        attempted_queries.add(station_query)
        geocode_attempts += 1

        coord = None
        station_queries = [
            station_query,
            f"{ts.name}, {ts.address}, {ts.city}, {ts.state}, USA",
            f"{ts.city}, {ts.state}, USA",
        ]

        for query in station_queries:
            if geocode_budget_exhausted():
                break
            coord = geocode_station_cached(query)
            if coord:
                break

        if not coord and geocode_budget_exhausted():
            break

        if not coord:
            consecutive_geo_failures += 1
            if not real_candidates and consecutive_geo_failures >= MAX_INITIAL_GEO_FAILS:
                break
            continue

        consecutive_geo_failures = 0

        station_lat = float(coord["lat"])
        station_lon = float(coord["lon"])

        progress_ratio = project_progress_ratio(
            point_lat=station_lat,
            point_lon=station_lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        # Ignore stations too far before origin or beyond destination.
        if progress_ratio < -0.2 or progress_ratio > 1.2:
            continue

        corridor_distance_m = distance_point_to_segment_m(
            point_lat=station_lat,
            point_lon=station_lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        if corridor_distance_m > route_corridor_m:
            continue

        real_candidates.append(
            {
                "id": str(cp.rack_id),
                "name": ts.name,
                "address": f"{ts.address}, {ts.city}, {ts.state}",
                "lat": station_lat,
                "lon": station_lon,
                "retail_price": float(cp.retail_price),
                "synthetic": False,
                "progress_ratio": progress_ratio,
                "corridor_distance_m": corridor_distance_m,
            }
        )

        if len(real_candidates) >= MAX_REAL_STATION_CANDIDATES:
            break

    return real_candidates


def build_state_corridor_fallback_candidates(
    price_rows,
    origin_coords: dict,
    destination_coords: dict,
    existing_ids=None,
):
    existing_ids = existing_ids or set()

    origin_lat = float(origin_coords["lat"])
    origin_lon = float(origin_coords["lon"])
    destination_lat = float(destination_coords["lat"])
    destination_lon = float(destination_coords["lon"])

    direct_distance_m = haversine_distance_m(
        origin_lat,
        origin_lon,
        destination_lat,
        destination_lon,
    )
    route_corridor_m = max(
        MIN_ROUTE_CORRIDOR_M,
        min(MAX_ROUTE_CORRIDOR_M * 1.5, direct_distance_m * 0.22),
    )

    delta_lat = destination_lat - origin_lat
    delta_lon = destination_lon - origin_lon
    norm = ((delta_lat ** 2) + (delta_lon ** 2)) ** 0.5 or 1.0
    perp_lat = -delta_lon / norm
    perp_lon = delta_lat / norm

    projected = []

    prioritized_rows = prioritize_station_rows_for_coverage(
        price_rows,
        origin_coords=origin_coords,
        destination_coords=destination_coords,
    )

    for cp in prioritized_rows:
        rack_id = str(cp.rack_id)
        if rack_id in existing_ids:
            continue

        ts = cp.rack.truckstop
        state = (ts.state or "").upper()
        centroid = STATE_CENTROIDS.get(state)
        if not centroid:
            continue

        centroid_lat, centroid_lon = centroid
        progress_ratio = project_progress_ratio(
            point_lat=centroid_lat,
            point_lon=centroid_lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        if progress_ratio < -0.15 or progress_ratio > 1.15:
            continue

        corridor_distance_m = distance_point_to_segment_m(
            point_lat=centroid_lat,
            point_lon=centroid_lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        if corridor_distance_m > route_corridor_m:
            continue

        clamped_progress = min(1.0, max(0.0, progress_ratio))
        offset_factor = ((hash(rack_id) % 7) - 3) * 0.05

        projected_lat = origin_lat + (delta_lat * clamped_progress) + (perp_lat * offset_factor)
        projected_lon = origin_lon + (delta_lon * clamped_progress) + (perp_lon * offset_factor)

        projected.append(
            {
                "id": rack_id,
                "name": ts.name,
                "address": f"{ts.address}, {ts.city}, {ts.state}",
                "lat": projected_lat,
                "lon": projected_lon,
                "retail_price": float(cp.retail_price),
                "synthetic": True,
                "progress_ratio": clamped_progress,
                "corridor_distance_m": corridor_distance_m,
            }
        )

        if len(projected) >= MAX_REAL_STATION_CANDIDATES:
            break

    projected.sort(
        key=lambda item: (
            float(item.get("corridor_distance_m", 0.0)),
            float(item["retail_price"]),
        )
    )
    return projected


def build_synthetic_candidates(price_rows, origin_coords: dict, destination_coords: dict, existing_ids=None):
    existing_ids = existing_ids or set()

    origin_lat = float(origin_coords["lat"])
    origin_lon = float(origin_coords["lon"])
    destination_lat = float(destination_coords["lat"])
    destination_lon = float(destination_coords["lon"])

    delta_lat = destination_lat - origin_lat
    delta_lon = destination_lon - origin_lon

    norm = ((delta_lat ** 2) + (delta_lon ** 2)) ** 0.5 or 1.0
    perp_lat = -delta_lon / norm
    perp_lon = delta_lat / norm

    fractions = [0.30, 0.50, 0.70, 0.42, 0.58]
    offset_step = min(0.22, max(0.06, norm * 0.04))

    synthetic = []

    for idx, cp in enumerate(price_rows):
        rack_id = str(cp.rack_id)
        if rack_id in existing_ids:
            continue

        ts = cp.rack.truckstop
        fraction = fractions[idx % len(fractions)]
        offset_multiplier = idx - 1
        offset = offset_step * offset_multiplier

        lat = origin_lat + (delta_lat * fraction) + (perp_lat * offset)
        lon = origin_lon + (delta_lon * fraction) + (perp_lon * offset)

        synthetic.append(
            {
                "id": rack_id,
                "name": f"Estimated Fuel Stop {len(synthetic) + 1}",
                "address": "Estimated along route (provider fallback)",
                "lat": lat,
                "lon": lon,
                "retail_price": float(cp.retail_price),
                "synthetic": True,
            }
        )

        if len(synthetic) >= MAX_CANDIDATES:
            break

    return synthetic


def select_refuel_waypoints(
    origin_coords: dict,
    destination_coords: dict,
    station_pool: list,
    required_stops: int,
    initial_reach_ratio: float = 1.0,
    max_leg_ratio: float | None = None,
):
    origin_lat = float(origin_coords["lat"])
    origin_lon = float(origin_coords["lon"])
    destination_lat = float(destination_coords["lat"])
    destination_lon = float(destination_coords["lon"])

    if required_stops <= 0:
        return []

    clamped_initial_reach = min(1.0, max(0.0, float(initial_reach_ratio)))
    if max_leg_ratio is None:
        clamped_max_leg_ratio = 1.0
    else:
        clamped_max_leg_ratio = min(1.0, max(0.05, float(max_leg_ratio)))
    strict_leg_enforcement = clamped_max_leg_ratio < 0.95

    # Keep a modest tolerance around each feasible leg to avoid impossible gaps.
    leg_cap = min(1.0, clamped_max_leg_ratio + 0.03)
    target_progresses = []

    if required_stops > 0 and clamped_initial_reach < 0.98:
        first_target = max(0.03, min(0.95, clamped_initial_reach * 0.97))
        target_progresses.append(first_target)

    remaining_slots = required_stops - len(target_progresses)
    if remaining_slots > 0:
        start_anchor = target_progresses[-1] if target_progresses else 0.0
        for idx in range(remaining_slots):
            target_progresses.append(
                start_anchor + (((idx + 1) / (remaining_slots + 1)) * (1.0 - start_anchor))
            )

    ranked_pool = []
    for station in station_pool:
        station_lat = float(station["lat"])
        station_lon = float(station["lon"])

        progress_ratio = station.get("progress_ratio")
        if progress_ratio is None:
            progress_ratio = project_progress_ratio(
                point_lat=station_lat,
                point_lon=station_lon,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                destination_lat=destination_lat,
                destination_lon=destination_lon,
            )

        if progress_ratio < 0.0 or progress_ratio > 1.0:
            continue

        corridor_distance_m = station.get("corridor_distance_m")
        if corridor_distance_m is None:
            corridor_distance_m = distance_point_to_segment_m(
                point_lat=station_lat,
                point_lon=station_lon,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                destination_lat=destination_lat,
                destination_lon=destination_lon,
            )

        enriched_station = dict(station)
        enriched_station["progress_ratio"] = progress_ratio
        enriched_station["corridor_distance_m"] = float(corridor_distance_m)
        ranked_pool.append(enriched_station)

    ranked_pool.sort(key=lambda item: item["progress_ratio"])

    selected = []
    used_ids = set()

    for stop_index in range(required_stops):
        target_progress = float(target_progresses[stop_index])
        best_station = None
        best_score = None

        previous_progress = float(selected[-1].get("progress_ratio", 0.0)) if selected else 0.0

        if stop_index == 0:
            leg_limit = min(1.0, clamped_initial_reach + 0.02)
        else:
            leg_limit = min(1.0, previous_progress + leg_cap)

        remaining_legs = (required_stops - stop_index - 1) + 1
        min_progress_for_finish = max(0.0, 1.0 - (remaining_legs * leg_cap))

        candidate_pool = []
        for station in ranked_pool:
            station_id = str(station["id"])
            if station_id in used_ids:
                continue

            station_progress = float(station["progress_ratio"])
            if station_progress <= (previous_progress + 0.015):
                continue

            if station_progress > (leg_limit + 0.01):
                continue

            if station_progress < (min_progress_for_finish - 0.04):
                continue

            candidate_pool.append(station)

        if not candidate_pool:
            forward_pool = [
                station
                for station in ranked_pool
                if str(station["id"]) not in used_ids
                and float(station["progress_ratio"]) > (previous_progress + 0.015)
            ]

            near_leg_limit = [
                station
                for station in forward_pool
                if float(station["progress_ratio"]) <= (leg_limit + 0.01)
            ]

            if near_leg_limit:
                candidate_pool = near_leg_limit
            elif not strict_leg_enforcement:
                candidate_pool = forward_pool

        if not candidate_pool and not strict_leg_enforcement:
            candidate_pool = [
                station
                for station in ranked_pool
                if str(station["id"]) not in used_ids
            ]

        real_candidate_pool = [
            station
            for station in candidate_pool
            if not station.get("synthetic")
        ]
        if real_candidate_pool:
            candidate_pool = real_candidate_pool

        for station in candidate_pool:
            progress_delta = float(station["progress_ratio"]) - target_progress
            progress_penalty = abs(progress_delta) * 100.0
            if progress_delta < 0:
                progress_penalty *= 1.25

            score = (
                progress_penalty
                + (station["corridor_distance_m"] / 50000.0)
                + (float(station["retail_price"]) / 10.0)
            )

            if station.get("synthetic"):
                score += 4.0

            station_progress = float(station["progress_ratio"])
            if station_progress > leg_limit:
                score += (station_progress - leg_limit) * 260.0

            if best_score is None or score < best_score:
                best_score = score
                best_station = station

        if best_station is None:
            progress = max(previous_progress + 0.03, target_progress)
            progress = min(1.0, progress)
            selected.append(
                {
                    "lat": origin_lat + ((destination_lat - origin_lat) * progress),
                    "lng": origin_lon + ((destination_lon - origin_lon) * progress),
                    "name": f"Estimated Fuel Stop {stop_index + 1}",
                    "address": "Estimated along route (insufficient geocoded stations)",
                    "retail_price": 0.0,
                    "progress_ratio": progress,
                    "type": f"Refuel Stop {stop_index + 1}",
                }
            )
            continue

        used_ids.add(str(best_station["id"]))
        selected.append(
            {
                "lat": float(best_station["lat"]),
                "lng": float(best_station["lon"]),
                "name": best_station["name"],
                "address": best_station.get("address", ""),
                "retail_price": float(best_station["retail_price"]),
                "progress_ratio": float(best_station["progress_ratio"]),
                "type": f"Refuel Stop {len(selected) + 1}",
            }
        )

    # If there are still missing stops, keep route continuity with estimated placeholders.
    for stop_index in range(len(selected), required_stops):
        previous_progress = float(selected[-1].get("progress_ratio", 0.0)) if selected else 0.0
        progress = max(previous_progress + 0.03, float(target_progresses[stop_index]))
        progress = min(1.0, progress)
        selected.append(
            {
                "lat": origin_lat + ((destination_lat - origin_lat) * progress),
                "lng": origin_lon + ((destination_lon - origin_lon) * progress),
                "name": f"Estimated Fuel Stop {stop_index + 1}",
                "address": "Estimated along route (insufficient geocoded stations)",
                "retail_price": 0.0,
                "progress_ratio": progress,
                "type": f"Refuel Stop {stop_index + 1}",
            }
        )

    selected.sort(key=lambda item: float(item.get("progress_ratio", 0.0)))
    for index, stop in enumerate(selected):
        stop["type"] = f"Refuel Stop {index + 1}"

    return selected[:required_stops]


def build_progress_spread_candidates(candidates: list, max_size: int):
    if len(candidates) <= max_size:
        return sorted(candidates, key=lambda item: float(item.get("progress_ratio", 0.0)))

    usable = [item for item in candidates if 0.0 <= float(item.get("progress_ratio", 0.0)) <= 1.0]
    if len(usable) < max_size:
        usable = list(candidates)

    chosen = []
    used_ids = set()

    for slot in range(max_size):
        target_progress = (slot + 1) / (max_size + 1)
        best = None
        best_score = None

        for candidate in usable:
            candidate_id = str(candidate["id"])
            if candidate_id in used_ids:
                continue

            progress = float(candidate.get("progress_ratio", 0.0))
            corridor = float(candidate.get("corridor_distance_m", 0.0))
            retail_price = float(candidate.get("retail_price", 0.0))

            score = (
                abs(progress - target_progress)
                + (corridor / 1_000_000.0)
                + (retail_price / 100.0)
            )

            if best_score is None or score < best_score:
                best = candidate
                best_score = score

        if best is None:
            continue

        used_ids.add(str(best["id"]))
        chosen.append(best)

    if len(chosen) < max_size:
        for candidate in sorted(
            usable,
            key=lambda item: (
                float(item.get("retail_price", 0.0)),
                float(item.get("corridor_distance_m", 0.0)),
            ),
        ):
            if len(chosen) >= max_size:
                break
            if str(candidate["id"]) in used_ids:
                continue
            used_ids.add(str(candidate["id"]))
            chosen.append(candidate)

    return sorted(chosen, key=lambda item: float(item.get("progress_ratio", 0.0)))


def build_path_with_waypoints(origin_coords: dict, destination_coords: dict, waypoints: list):
    path = [[float(origin_coords["lat"]), float(origin_coords["lon"])]]
    path.extend([[float(stop["lat"]), float(stop["lng"])] for stop in waypoints])
    path.append([float(destination_coords["lat"]), float(destination_coords["lon"])])
    return path


def _normalize_geometry_points(geometry) -> list:
    if not isinstance(geometry, list):
        return []

    normalized = []
    for point in geometry:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue

        try:
            lat = float(point[0])
            lon = float(point[1])
        except (TypeError, ValueError):
            continue

        if normalized and normalized[-1] == [lat, lon]:
            continue

        normalized.append([lat, lon])

    return normalized


def _route_segment_geometry(start: dict, end: dict) -> list:
    for provider in (PATH_DIRECTIONS, PATH_DIRECTIONS_RETRY):
        try:
            route_data = provider.route(start, end, waypoints=[])
            geometry = _normalize_geometry_points(route_data.get("geometry", []))
            if len(geometry) > 1:
                return geometry
        except Exception:
            continue

    return []


def build_osrm_geometry_path(origin_coords: dict, destination_coords: dict, waypoints: list):
    origin = {
        "lat": float(origin_coords["lat"]),
        "lon": float(origin_coords["lon"]),
    }
    destination = {
        "lat": float(destination_coords["lat"]),
        "lon": float(destination_coords["lon"]),
    }
    route_waypoints = [
        {
            "id": f"refuel-{index + 1}",
            "lat": float(stop["lat"]),
            "lon": float(stop["lng"]),
        }
        for index, stop in enumerate(waypoints)
    ]

    for provider in (PATH_DIRECTIONS, PATH_DIRECTIONS_RETRY):
        try:
            route_data = provider.route(origin, destination, waypoints=route_waypoints)
            geometry = _normalize_geometry_points(route_data.get("geometry", []))
            if len(geometry) > 1:
                return geometry
        except Exception:
            continue

    # If full multi-waypoint routing fails, stitch per-leg routes. Keep this
    # tolerant by skipping unroutable intermediate stops instead of falling
    # immediately to straight line segments.
    stitched = []
    current = origin

    for waypoint in route_waypoints:
        segment_geometry = _route_segment_geometry(current, waypoint)
        if len(segment_geometry) <= 1:
            continue

        if stitched and stitched[-1] == segment_geometry[0]:
            stitched.extend(segment_geometry[1:])
        else:
            stitched.extend(segment_geometry)

        current = waypoint

    final_segment = _route_segment_geometry(current, destination)
    if len(final_segment) > 1:
        if stitched and stitched[-1] == final_segment[0]:
            stitched.extend(final_segment[1:])
        else:
            stitched.extend(final_segment)

    if len(stitched) > 1:
        return stitched

    direct_geometry = _route_segment_geometry(origin, destination)
    if len(direct_geometry) > 1:
        return direct_geometry

    return build_path_with_waypoints(origin_coords, destination_coords, waypoints)


def build_alternative_refuel_previews(
    alternatives: list,
    origin_coords: dict,
    destination_coords: dict,
    shared_waypoints: list,
):
    if not alternatives or not shared_waypoints:
        return alternatives

    normalized_shared_waypoints = []
    for index, stop in enumerate(shared_waypoints):
        try:
            lat = float(stop["lat"])
            lng = float(stop["lng"])
        except (KeyError, TypeError, ValueError):
            continue

        normalized_shared_waypoints.append(
            {
                "lat": lat,
                "lng": lng,
                "name": stop.get("name", f"Refuel Stop {index + 1}"),
                "address": stop.get("address", ""),
                "type": stop.get("type", f"Refuel Stop {index + 1}"),
            }
        )

    if not normalized_shared_waypoints:
        return alternatives

    enriched = []
    for alternative in alternatives:
        station = alternative.get("station") or {}
        preview_waypoints = [dict(stop) for stop in normalized_shared_waypoints]

        try:
            station_lat = float(station["lat"])
            station_lon = float(station["lon"])
            station_has_coords = True
        except (KeyError, TypeError, ValueError):
            station_has_coords = False

        if station_has_coords and preview_waypoints:
            best_index = min(
                range(len(preview_waypoints)),
                key=lambda idx: (
                    (preview_waypoints[idx]["lat"] - station_lat) ** 2
                    + (preview_waypoints[idx]["lng"] - station_lon) ** 2
                ),
            )

            preview_waypoints[best_index] = {
                **preview_waypoints[best_index],
                "lat": station_lat,
                "lng": station_lon,
                "name": station.get("name", preview_waypoints[best_index]["name"]),
                "address": station.get("address", preview_waypoints[best_index].get("address", "")),
            }

        for stop in preview_waypoints:
            stop["progress_ratio"] = project_progress_ratio(
                point_lat=float(stop["lat"]),
                point_lon=float(stop["lng"]),
                origin_lat=float(origin_coords["lat"]),
                origin_lon=float(origin_coords["lon"]),
                destination_lat=float(destination_coords["lat"]),
                destination_lon=float(destination_coords["lon"]),
            )

        preview_waypoints.sort(key=lambda stop: float(stop.get("progress_ratio", 0.0)))
        for index, stop in enumerate(preview_waypoints):
            stop["type"] = f"Refuel Stop {index + 1}"

        enriched_alternative = dict(alternative)
        enriched_alternative["refuel_waypoints"] = preview_waypoints
        enriched_alternative["geometry"] = build_osrm_geometry_path(
            origin_coords=origin_coords,
            destination_coords=destination_coords,
            waypoints=preview_waypoints,
        )
        enriched.append(enriched_alternative)

    return enriched


def build_direct_route_alternatives(
    origin_coords: dict,
    destination_coords: dict,
    vehicle_mpg: float,
    reference_fuel_price: float,
    max_options: int = 3,
):
    origin = {
        "lat": float(origin_coords["lat"]),
        "lon": float(origin_coords["lon"]),
    }
    destination = {
        "lat": float(destination_coords["lat"]),
        "lon": float(destination_coords["lon"]),
    }

    safe_mpg = vehicle_mpg if vehicle_mpg > 0 else DEFAULT_VEHICLE_MPG
    safe_price = reference_fuel_price if reference_fuel_price > 0 else 3.75

    for provider in (PATH_DIRECTIONS, PATH_DIRECTIONS_RETRY):
        try:
            route_data = provider.route(
                origin,
                destination,
                waypoints=[],
                include_alternatives=True,
            )
        except Exception:
            continue

        route_candidates = route_data.get("alternatives")
        if not isinstance(route_candidates, list) or not route_candidates:
            route_candidates = [route_data]

        parsed = []
        for candidate in route_candidates:
            try:
                distance_m = float(candidate["distance_m"])
                duration_s = float(candidate["duration_s"])
            except (KeyError, TypeError, ValueError):
                continue

            geometry = _normalize_geometry_points(candidate.get("geometry", []))
            if len(geometry) <= 1:
                geometry = build_path_with_waypoints(origin_coords, destination_coords, [])

            fuel_cost = ((distance_m / 1609.344) / safe_mpg) * safe_price
            parsed.append(
                {
                    "distance_m": distance_m,
                    "duration_s": duration_s,
                    "geometry": geometry,
                    "estimated_fuel_cost": fuel_cost,
                }
            )

        if not parsed:
            continue

        parsed.sort(key=lambda item: (item["duration_s"], item["distance_m"]))
        parsed = parsed[:max_options]

        durations = [item["duration_s"] for item in parsed]
        prices = [item["estimated_fuel_cost"] for item in parsed]
        min_duration, max_duration = min(durations), max(durations)
        min_price, max_price = min(prices), max(prices)

        for index, item in enumerate(parsed):
            if max_duration == min_duration:
                time_norm = 0.0
            else:
                time_norm = (item["duration_s"] - min_duration) / (max_duration - min_duration)

            if max_price == min_price:
                price_norm = 0.0
            else:
                price_norm = (item["estimated_fuel_cost"] - min_price) / (max_price - min_price)

            item["time_norm"] = time_norm
            item["price_norm"] = price_norm
            # In no-refuel mode prioritize quickest arrival.
            item["score"] = time_norm
            item["station"] = {
                "id": f"direct-{index + 1}",
                "name": f"Direct Route #{index + 1}",
                "address": "No refuel required",
                "lat": None,
                "lon": None,
                "retail_price": safe_price,
                "synthetic": True,
            }
            item["refuel_waypoints"] = []

        return parsed

    return []


def build_fuel_plan(
    distance_m: float,
    mpg: float = DEFAULT_VEHICLE_MPG,
    tank_capacity_gal: float = DEFAULT_TANK_CAPACITY_GAL,
    start_fuel_percent: float = DEFAULT_START_FUEL_PERCENT,
):
    if mpg <= 0 or tank_capacity_gal <= 0:
        return {
            "distance_mi": 0.0,
            "gallons_needed": 0.0,
            "avg_mpg": mpg,
            "tank_capacity_gal": tank_capacity_gal,
            "start_fuel_percent": start_fuel_percent,
            "initial_fuel_gal": 0.0,
            "initial_range_mi": 0.0,
            "initial_reach_ratio": 0.0,
            "max_range_mi": 0.0,
            "min_refuel_stops": 0,
            "requires_refuel": False,
        }

    normalized_start_fuel = min(100.0, max(0.0, float(start_fuel_percent)))
    distance_mi = float(distance_m) / 1609.344
    gallons_needed = distance_mi / mpg
    initial_fuel_gal = tank_capacity_gal * (normalized_start_fuel / 100.0)
    initial_range_mi = initial_fuel_gal * mpg
    max_range_mi = mpg * tank_capacity_gal
    remaining_after_initial_mi = max(0.0, distance_mi - initial_range_mi)
    min_refuel_stops = max(0, math.ceil(remaining_after_initial_mi / max_range_mi))
    initial_reach_ratio = min(1.0, initial_range_mi / distance_mi) if distance_mi > 0 else 1.0

    return {
        "distance_mi": distance_mi,
        "gallons_needed": gallons_needed,
        "avg_mpg": mpg,
        "tank_capacity_gal": tank_capacity_gal,
        "start_fuel_percent": normalized_start_fuel,
        "initial_fuel_gal": initial_fuel_gal,
        "initial_range_mi": initial_range_mi,
        "initial_reach_ratio": initial_reach_ratio,
        "max_range_mi": max_range_mi,
        "min_refuel_stops": min_refuel_stops,
        "requires_refuel": min_refuel_stops > 0,
    }


def parse_positive_float_param(raw_value, field_name: str, default_value: float) -> float:
    value = (raw_value or "").strip()
    if value == "":
        return default_value

    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a number") from exc

    if parsed <= 0:
        raise ValueError(f"{field_name} must be > 0")

    return parsed


def parse_percentage_param(raw_value, field_name: str, default_value: float) -> float:
    value = (raw_value or "").strip()
    if value == "":
        return default_value

    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a number") from exc

    if parsed < 0 or parsed > 100:
        raise ValueError(f"{field_name} must be between 0 and 100")

    return parsed


def stations_home(request):
    return render(request, "stations/page.html")


@require_GET
def places_suggest(request):
    query = request.GET.get("q", "").strip()
    if len(query) < 3:
        return JsonResponse({"results": []})

    results = []

    try:
        results = nominatim_suggest_cached(query)
    except Exception:
        results = []

    results = [
        item for item in results
        if is_us_supported_location(
            {
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "display_name": item.get("name", ""),
            }
        )
    ]

    if not results:
        results = local_place_suggest(query, limit=SUGGEST_LIMIT)

    return JsonResponse({"results": results})


@require_GET
def optimize_route(request):
    origin = request.GET.get("origin", "").strip()
    destination = request.GET.get("destination", "").strip()

    if not origin or not destination:
        return JsonResponse({"error": "origin and destination are required"}, status=400)

    try:
        time_weight = float(request.GET.get("time_weight", "0.6"))
        price_weight = float(request.GET.get("price_weight", "0.4"))
    except ValueError:
        return JsonResponse({"error": "invalid weights"}, status=400)

    try:
        vehicle_mpg = parse_positive_float_param(
            request.GET.get("avg_mpg"),
            "avg_mpg",
            DEFAULT_VEHICLE_MPG,
        )
        tank_capacity_gal = parse_positive_float_param(
            request.GET.get("tank_capacity_gal"),
            "tank_capacity_gal",
            DEFAULT_TANK_CAPACITY_GAL,
        )
        start_fuel_percent = parse_percentage_param(
            request.GET.get("start_fuel_percent"),
            "start_fuel_percent",
            DEFAULT_START_FUEL_PERCENT,
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    provided_origin_lat = request.GET.get("origin_lat", "").strip()
    provided_origin_lon = request.GET.get("origin_lon", "").strip()
    provided_destination_lat = request.GET.get("destination_lat", "").strip()
    provided_destination_lon = request.GET.get("destination_lon", "").strip()

    provided_coords = any(
        value
        for value in [
            provided_origin_lat,
            provided_origin_lon,
            provided_destination_lat,
            provided_destination_lon,
        ]
    )

    origin_coords = None
    destination_coords = None

    if provided_coords:
        try:
            origin_coords = {
                "lat": float(provided_origin_lat),
                "lon": float(provided_origin_lon),
                "display_name": origin,
            }
            destination_coords = {
                "lat": float(provided_destination_lat),
                "lon": float(provided_destination_lon),
                "display_name": destination,
            }
        except ValueError:
            return JsonResponse({"error": "invalid coordinate parameters"}, status=400)

    if time_weight < 0 or price_weight < 0 or (time_weight + price_weight) <= 0:
        return JsonResponse(
            {"error": "weights must be non-negative and not both zero"},
            status=400,
        )

    # Resolve origin/destination once in the view and pass coordinates to optimizer.
    if origin_coords is None or destination_coords is None:
        origin_coords = resolve_origin_destination(origin)
        destination_coords = resolve_origin_destination(destination)

        if origin_coords is None or destination_coords is None:
            return JsonResponse(
                {
                    "error": (
                        "Could not geocode origin/destination right now. "
                        "Select an autocomplete suggestion or try 'City, State'."
                    )
                },
                status=400,
            )

    if not is_us_supported_location(origin_coords) or not is_us_supported_location(destination_coords):
        return JsonResponse(
            {
                "error": (
                    "Pathfinder currently supports routes inside the United States only. "
                    "Select origin and destination in the U.S."
                )
            },
            status=400,
        )

    # Build a latest-price snapshot per rack, then prioritize cheaper options first.
    latest_by_rack = {}
    for cp in (
        CurrentPrice.objects
        .select_related("rack__truckstop")
        .order_by("-updated_at")
    ):
        latest_by_rack.setdefault(cp.rack_id, cp)

    prices = sorted(latest_by_rack.values(), key=lambda row: row.retail_price)
    if prices:
        median_index = len(prices) // 2
        reference_fuel_price = float(prices[median_index].retail_price)
    else:
        reference_fuel_price = 3.75

    candidates = build_real_station_candidates(
        price_rows=prices,
        origin_coords=origin_coords,
        destination_coords=destination_coords,
    )

    candidates.sort(
        key=lambda item: (
            float(item.get("corridor_distance_m", 0.0)),
            float(item["retail_price"]),
        )
    )

    if len(candidates) < MAX_STATION_POOL_SIZE:
        needed = MAX_STATION_POOL_SIZE - len(candidates)
        corridor_fallback = build_state_corridor_fallback_candidates(
            price_rows=prices,
            origin_coords=origin_coords,
            destination_coords=destination_coords,
            existing_ids={str(item["id"]) for item in candidates},
        )

        if corridor_fallback and needed > 0:
            spread_fallback = build_progress_spread_candidates(
                corridor_fallback,
                min(len(corridor_fallback), needed),
            )
            candidates.extend(spread_fallback[:needed])

    if len(candidates) < MAX_CANDIDATES:
        synthetic = build_synthetic_candidates(
            price_rows=prices,
            origin_coords=origin_coords,
            destination_coords=destination_coords,
            existing_ids={str(item["id"]) for item in candidates},
        )

        for item in synthetic:
            if len(candidates) >= MAX_CANDIDATES:
                break
            candidates.append(item)

    if not candidates:
        return JsonResponse(
            {"error": "No geocoded station candidates available"},
            status=400,
        )

    station_pool = build_progress_spread_candidates(candidates, MAX_STATION_POOL_SIZE)
    optimizer_candidates = sorted(
        station_pool,
        key=lambda item: (
            float(item.get("retail_price", 0.0)),
            float(item.get("corridor_distance_m", 0.0)),
        ),
    )[:MAX_CANDIDATES]

    def optimize_with_provider(directions_provider):
        optimizer = RouteOptimizer(
            geocoding_provider=GEOCODER,
            directions_provider=directions_provider,
            vehicle_miles_per_gallon=vehicle_mpg,
        )
        return optimizer.optimize(
            origin_query=origin,
            destination_query=destination,
            candidate_stations=optimizer_candidates,
            weights={"time": time_weight, "price": price_weight},
            origin_coords=origin_coords,
            destination_coords=destination_coords,
        )

    try:
        result = optimize_with_provider(DIRECTIONS)
    except ProviderError:
        try:
            result = optimize_with_provider(DIRECTIONS_RETRY)
        except ProviderError:
            result = optimize_without_osrm(
                origin_coords=origin_coords,
                destination_coords=destination_coords,
                candidates=optimizer_candidates,
                weights={"time": time_weight, "price": price_weight},
                vehicle_mpg=vehicle_mpg,
            )
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    best = result["best_option"]
    alternatives = result["alternatives"][:MAX_CANDIDATES]

    fuel_plan = build_fuel_plan(
        best["distance_m"],
        mpg=vehicle_mpg,
        tank_capacity_gal=tank_capacity_gal,
        start_fuel_percent=start_fuel_percent,
    )

    if fuel_plan["min_refuel_stops"] <= 0:
        direct_alternatives = build_direct_route_alternatives(
            origin_coords=result["origin"],
            destination_coords=result["destination"],
            vehicle_mpg=vehicle_mpg,
            reference_fuel_price=reference_fuel_price,
            max_options=MAX_CANDIDATES,
        )

        if direct_alternatives:
            alternatives = direct_alternatives
            best = direct_alternatives[0]

        waypoints = []
        path = _normalize_geometry_points(best.get("geometry", []))
        if len(path) <= 1:
            path = build_osrm_geometry_path(
                origin_coords=result["origin"],
                destination_coords=result["destination"],
                waypoints=waypoints,
            )
    else:
        if fuel_plan.get("distance_mi", 0.0) > 0:
            max_leg_ratio = fuel_plan.get("max_range_mi", 0.0) / fuel_plan["distance_mi"]
        else:
            max_leg_ratio = 1.0

        waypoints = select_refuel_waypoints(
            origin_coords=result["origin"],
            destination_coords=result["destination"],
            station_pool=station_pool,
            required_stops=fuel_plan["min_refuel_stops"],
            initial_reach_ratio=fuel_plan.get("initial_reach_ratio", 1.0),
            max_leg_ratio=max_leg_ratio,
        )
        path = build_osrm_geometry_path(
            origin_coords=result["origin"],
            destination_coords=result["destination"],
            waypoints=waypoints,
        )

        if waypoints:
            alternatives = build_alternative_refuel_previews(
                alternatives=alternatives,
                origin_coords=result["origin"],
                destination_coords=result["destination"],
                shared_waypoints=waypoints,
            )

    response = {
        "origin": {
            "lat": result["origin"]["lat"],
            "lng": result["origin"]["lon"],
            "name": origin,
        },
        "destination": {
            "lat": result["destination"]["lat"],
            "lng": result["destination"]["lon"],
            "name": destination,
        },
        "waypoints": waypoints,
        "distance_m": best["distance_m"],
        "duration_s": best["duration_s"],
        "fuel_cost": best["estimated_fuel_cost"],
        "score": best["score"],
        "path": path,
        "alternatives": alternatives,
        "weights": {"time": time_weight, "price": price_weight},
        "engine": result.get("engine", DEFAULT_DIRECTIONS_ENGINE),
        "assumptions": {
            "fuel_price_unit": "usd_per_gallon",
            "avg_mpg": vehicle_mpg,
            "tank_capacity_gal": tank_capacity_gal,
            "start_fuel_percent": start_fuel_percent,
        },
        "fuel_plan": fuel_plan,
    }

    return JsonResponse(response)
