import math


def normalize_query(value: str) -> str:
    return " ".join(value.lower().replace(",", " ").split())


def local_place_suggest(query: str, fallback_places: list, limit: int):
    normalized = normalize_query(query)
    if len(normalized) < 2:
        return []

    query_tokens = normalized.split()
    ranked = []

    for place in fallback_places:
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


def tomtom_suggest_cached(query: str, search_provider, suggest_limit: int):
    if search_provider is None:
        return []

    try:
        return search_provider.suggest(query=query, limit=suggest_limit)
    except Exception:
        return []


def resolve_origin_destination(query: str, search_provider, local_place_suggest_fn):
    if search_provider is not None:
        try:
            return search_provider.geocode(query)
        except Exception:
            pass

    suggestions = local_place_suggest_fn(query, limit=1)
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


def is_within_supported_us_bounds(lat: float, lon: float, supported_us_bounds: list) -> bool:
    for bounds in supported_us_bounds:
        if (
            bounds["lat_min"] <= lat <= bounds["lat_max"]
            and bounds["lon_min"] <= lon <= bounds["lon_max"]
        ):
            return True

    return False


def is_us_supported_location(location: dict, supported_us_bounds: list) -> bool:
    try:
        lat = float(location["lat"])
        lon = float(location["lon"])
    except (KeyError, TypeError, ValueError):
        return False

    return is_within_supported_us_bounds(
        lat=lat,
        lon=lon,
        supported_us_bounds=supported_us_bounds,
    )


def geocode_station_cached(query: str, station_search_provider):
    if station_search_provider is None:
        return None

    try:
        return station_search_provider.geocode(query)
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
):
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
