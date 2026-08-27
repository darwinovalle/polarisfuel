from functools import lru_cache
import math
import os

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from stations.models import CurrentPrice
from stations.processes import candidate_selection, fuel, place_resolution, routing
from stations.processes.constants import (
    DEFAULT_START_FUEL_PERCENT,
    DEFAULT_TANK_CAPACITY_GAL,
    DEFAULT_VEHICLE_MPG,
    FALLBACK_PLACES,
    MAX_CANDIDATES,
    MAX_INITIAL_GEO_FAILS,
    MAX_REAL_STATION_CANDIDATES,
    MAX_ROUTE_CORRIDOR_M,
    MAX_STATION_GEOCODE_ATTEMPTS,
    MAX_STATION_GEOCODE_SECONDS,
    MAX_STATION_POOL_SIZE,
    MIN_ROUTE_CORRIDOR_M,
    STATE_CENTROIDS,
    SUGGEST_LIMIT,
    SUPPORTED_US_BOUNDS,
)
from stations.services.provider_errors import ProviderError
from stations.services.providers_tomtom import TomTomDirectionsProvider
from stations.services.providers_tomtom_search import TomTomSearchProvider
from stations.services.route_optimizer import RouteOptimizer


TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "").strip()
DEFAULT_DIRECTIONS_ENGINE = "tomtom"

if TOMTOM_API_KEY:
    SEARCH = TomTomSearchProvider(
        api_key=TOMTOM_API_KEY,
        timeout=3.5,
        max_retries=2,
    )
    STATION_SEARCH = TomTomSearchProvider(
        api_key=TOMTOM_API_KEY,
        timeout=2.0,
        max_retries=1,
    )
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
    SEARCH = None
    STATION_SEARCH = None
    DIRECTIONS = None
    DIRECTIONS_RETRY = None
    PATH_DIRECTIONS = None
    PATH_DIRECTIONS_RETRY = None


def normalize_query(value: str) -> str:
    return place_resolution.normalize_query(value)


@lru_cache(maxsize=5000)
def local_place_suggest(query: str, limit: int = SUGGEST_LIMIT):
    return place_resolution.local_place_suggest(
        query=query,
        fallback_places=FALLBACK_PLACES,
        limit=limit,
    )


@lru_cache(maxsize=8000)
def tomtom_suggest_cached(query: str):
    return place_resolution.tomtom_suggest_cached(
        query=query,
        search_provider=SEARCH,
        suggest_limit=SUGGEST_LIMIT,
    )


def resolve_origin_destination(query: str):
    return place_resolution.resolve_origin_destination(
        query=query,
        search_provider=SEARCH,
        local_place_suggest_fn=local_place_suggest,
    )


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return place_resolution.haversine_distance_m(lat1, lon1, lat2, lon2)


def is_within_supported_us_bounds(lat: float, lon: float) -> bool:
    return place_resolution.is_within_supported_us_bounds(
        lat=lat,
        lon=lon,
        supported_us_bounds=SUPPORTED_US_BOUNDS,
    )


def is_us_supported_location(location: dict) -> bool:
    return place_resolution.is_us_supported_location(
        location=location,
        supported_us_bounds=SUPPORTED_US_BOUNDS,
    )


@lru_cache(maxsize=30000)
def geocode_station_cached(query: str):
    return place_resolution.geocode_station_cached(
        query=query,
        station_search_provider=STATION_SEARCH,
    )


def project_progress_ratio(
    point_lat: float,
    point_lon: float,
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
) -> float:
    return place_resolution.project_progress_ratio(
        point_lat=point_lat,
        point_lon=point_lon,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        destination_lat=destination_lat,
        destination_lon=destination_lon,
    )


def distance_point_to_segment_m(
    point_lat: float,
    point_lon: float,
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
) -> float:
    return place_resolution.distance_point_to_segment_m(
        point_lat=point_lat,
        point_lon=point_lon,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        destination_lat=destination_lat,
        destination_lon=destination_lon,
    )


def distance_point_to_polyline_m(point_lat: float, point_lon: float, polyline: list) -> float:
    return place_resolution.distance_point_to_polyline_m(
        point_lat=point_lat,
        point_lon=point_lon,
        polyline=polyline,
    )


def measure_station_route_detour(
    origin_coords: dict,
    destination_coords: dict,
    station: dict,
    baseline_distance_m: float | None = None,
):
    if station.get("lat") is None or station.get("lon") is None:
        return None

    origin = {
        "lat": float(origin_coords["lat"]),
        "lon": float(origin_coords["lon"]),
    }
    destination = {
        "lat": float(destination_coords["lat"]),
        "lon": float(destination_coords["lon"]),
    }
    waypoint = {
        "id": "station-detour",
        "lat": float(station["lat"]),
        "lon": float(station["lon"]),
    }

    if baseline_distance_m is None:
        for provider in (PATH_DIRECTIONS, PATH_DIRECTIONS_RETRY):
            if provider is None:
                continue
            try:
                baseline = provider.route(origin, destination, waypoints=[])
                baseline_distance_m = float(baseline["distance_m"])
                break
            except (KeyError, TypeError, ValueError):
                continue
            except Exception:
                continue

    if baseline_distance_m is None:
        return None

    for provider in (PATH_DIRECTIONS, PATH_DIRECTIONS_RETRY):
        if provider is None:
            continue
        try:
            route = provider.route(origin, destination, waypoints=[waypoint])
            route_distance_m = float(route["distance_m"])
            return max(0.0, route_distance_m - baseline_distance_m)
        except (KeyError, TypeError, ValueError):
            continue
        except Exception:
            continue

    return None


def prioritize_station_rows_for_coverage(
    price_rows,
    origin_coords: dict,
    destination_coords: dict,
):
    return candidate_selection.prioritize_station_rows_for_coverage(
        price_rows=price_rows,
        origin_coords=origin_coords,
        destination_coords=destination_coords,
        state_centroids=STATE_CENTROIDS,
        project_progress_ratio_fn=project_progress_ratio,
    )


def build_real_station_candidates(
    price_rows,
    origin_coords: dict,
    destination_coords: dict,
    route_geometry: list | None = None,
    baseline_route_distance_m: float | None = None,
):
    return candidate_selection.build_real_station_candidates(
        price_rows=price_rows,
        origin_coords=origin_coords,
        destination_coords=destination_coords,
        state_centroids=STATE_CENTROIDS,
        min_route_corridor_m=MIN_ROUTE_CORRIDOR_M,
        max_route_corridor_m=MAX_ROUTE_CORRIDOR_M,
        max_real_station_candidates=MAX_REAL_STATION_CANDIDATES,
        max_station_geocode_attempts=MAX_STATION_GEOCODE_ATTEMPTS,
        max_station_geocode_seconds=MAX_STATION_GEOCODE_SECONDS,
        max_initial_geo_fails=MAX_INITIAL_GEO_FAILS,
        prioritize_station_rows_for_coverage_fn=prioritize_station_rows_for_coverage,
        geocode_station_cached_fn=geocode_station_cached,
        haversine_distance_m_fn=haversine_distance_m,
        project_progress_ratio_fn=project_progress_ratio,
        distance_point_to_segment_m_fn=distance_point_to_segment_m,
        route_geometry=route_geometry,
        distance_point_to_polyline_m_fn=distance_point_to_polyline_m,
        route_detour_m_fn=measure_station_route_detour,
        baseline_route_distance_m=baseline_route_distance_m,
    )


def build_state_corridor_fallback_candidates(
    price_rows,
    origin_coords: dict,
    destination_coords: dict,
    existing_ids=None,
):
    return candidate_selection.build_state_corridor_fallback_candidates(
        price_rows=price_rows,
        origin_coords=origin_coords,
        destination_coords=destination_coords,
        existing_ids=existing_ids,
        state_centroids=STATE_CENTROIDS,
        min_route_corridor_m=MIN_ROUTE_CORRIDOR_M,
        max_route_corridor_m=MAX_ROUTE_CORRIDOR_M,
        max_real_station_candidates=MAX_REAL_STATION_CANDIDATES,
        prioritize_station_rows_for_coverage_fn=prioritize_station_rows_for_coverage,
        haversine_distance_m_fn=haversine_distance_m,
        project_progress_ratio_fn=project_progress_ratio,
        distance_point_to_segment_m_fn=distance_point_to_segment_m,
    )


def build_synthetic_candidates(price_rows, origin_coords: dict, destination_coords: dict, existing_ids=None):
    return candidate_selection.build_synthetic_candidates(
        price_rows=price_rows,
        origin_coords=origin_coords,
        destination_coords=destination_coords,
        existing_ids=existing_ids,
        state_centroids=STATE_CENTROIDS,
        max_candidates=MAX_CANDIDATES,
        min_route_corridor_m=MIN_ROUTE_CORRIDOR_M,
        max_route_corridor_m=MAX_ROUTE_CORRIDOR_M,
        haversine_distance_m_fn=haversine_distance_m,
        project_progress_ratio_fn=project_progress_ratio,
        distance_point_to_segment_m_fn=distance_point_to_segment_m,
    )


def select_refuel_waypoints(
    origin_coords: dict,
    destination_coords: dict,
    station_pool: list,
    required_stops: int,
    initial_reach_ratio: float = 1.0,
    max_leg_ratio: float | None = None,
):
    return candidate_selection.select_refuel_waypoints(
        origin_coords=origin_coords,
        destination_coords=destination_coords,
        station_pool=station_pool,
        required_stops=required_stops,
        initial_reach_ratio=initial_reach_ratio,
        max_leg_ratio=max_leg_ratio,
        project_progress_ratio_fn=project_progress_ratio,
        distance_point_to_segment_m_fn=distance_point_to_segment_m,
    )


def build_progress_spread_candidates(candidates: list, max_size: int):
    return candidate_selection.build_progress_spread_candidates(candidates, max_size)


def build_path_with_waypoints(origin_coords: dict, destination_coords: dict, waypoints: list):
    return routing.build_path_with_waypoints(origin_coords, destination_coords, waypoints)


def _normalize_geometry_points(geometry) -> list:
    return routing.normalize_geometry_points(geometry)


def _route_segment_geometry(start: dict, end: dict) -> list:
    return routing.route_segment_geometry(
        start=start,
        end=end,
        providers=(PATH_DIRECTIONS, PATH_DIRECTIONS_RETRY),
        normalize_geometry_points_fn=_normalize_geometry_points,
    )


def build_route_geometry_path(origin_coords: dict, destination_coords: dict, waypoints: list):
    return routing.build_route_geometry_path(
        origin_coords=origin_coords,
        destination_coords=destination_coords,
        waypoints=waypoints,
        providers=(PATH_DIRECTIONS, PATH_DIRECTIONS_RETRY),
        normalize_geometry_points_fn=_normalize_geometry_points,
        route_segment_geometry_fn=_route_segment_geometry,
        build_path_with_waypoints_fn=build_path_with_waypoints,
    )


def build_alternative_refuel_previews(
    alternatives: list,
    origin_coords: dict,
    destination_coords: dict,
    shared_waypoints: list,
):
    return routing.build_alternative_refuel_previews(
        alternatives=alternatives,
        origin_coords=origin_coords,
        destination_coords=destination_coords,
        shared_waypoints=shared_waypoints,
        project_progress_ratio_fn=project_progress_ratio,
        build_route_geometry_path_fn=build_route_geometry_path,
    )


def build_direct_route_alternatives(
    origin_coords: dict,
    destination_coords: dict,
    vehicle_mpg: float,
    reference_fuel_price: float,
    max_options: int = 3,
    weights: dict | None = None,
    tank_capacity_gal: float = DEFAULT_TANK_CAPACITY_GAL,
    start_fuel_percent: float = DEFAULT_START_FUEL_PERCENT,
):
    return routing.build_direct_route_alternatives(
        origin_coords=origin_coords,
        destination_coords=destination_coords,
        vehicle_mpg=vehicle_mpg,
        reference_fuel_price=reference_fuel_price,
        providers=(PATH_DIRECTIONS, PATH_DIRECTIONS_RETRY),
        normalize_geometry_points_fn=_normalize_geometry_points,
        build_path_with_waypoints_fn=build_path_with_waypoints,
        max_options=max_options,
        default_vehicle_mpg=DEFAULT_VEHICLE_MPG,
        weights=weights,
        tank_capacity_gal=tank_capacity_gal,
        start_fuel_percent=start_fuel_percent,
    )


def build_direct_route_snapshot(origin_coords: dict, destination_coords: dict):
    origin = {
        "lat": float(origin_coords["lat"]),
        "lon": float(origin_coords["lon"]),
    }
    destination = {
        "lat": float(destination_coords["lat"]),
        "lon": float(destination_coords["lon"]),
    }

    for provider in (DIRECTIONS, DIRECTIONS_RETRY, PATH_DIRECTIONS, PATH_DIRECTIONS_RETRY):
        if provider is None:
            continue
        try:
            route_data = provider.route(origin, destination, waypoints=[])
        except Exception:
            continue

        try:
            distance_m = float(route_data["distance_m"])
            duration_s = float(route_data["duration_s"])
        except (KeyError, TypeError, ValueError):
            continue

        return {
            "distance_m": distance_m,
            "duration_s": duration_s,
            "geometry": _normalize_geometry_points(route_data.get("geometry", [])),
        }

    return None


def align_estimated_waypoints_to_route_geometry(waypoints: list, route_geometry: list):
    if not waypoints or not isinstance(route_geometry, list) or len(route_geometry) < 2:
        return waypoints

    cumulative_distances = [0.0]
    for idx in range(1, len(route_geometry)):
        previous = route_geometry[idx - 1]
        current = route_geometry[idx]
        if (
            not isinstance(previous, (list, tuple))
            or not isinstance(current, (list, tuple))
            or len(previous) < 2
            or len(current) < 2
        ):
            cumulative_distances.append(cumulative_distances[-1])
            continue

        segment_m = haversine_distance_m(
            float(previous[0]),
            float(previous[1]),
            float(current[0]),
            float(current[1]),
        )
        cumulative_distances.append(cumulative_distances[-1] + segment_m)

    total_distance_m = cumulative_distances[-1]
    if total_distance_m <= 0:
        return waypoints

    aligned = []
    for stop in waypoints:
        if not stop.get("is_estimated"):
            aligned.append(stop)
            continue

        progress_ratio = min(1.0, max(0.0, float(stop.get("progress_ratio", 0.0))))
        target_distance_m = total_distance_m * progress_ratio

        best_index = min(
            range(len(cumulative_distances)),
            key=lambda idx: abs(cumulative_distances[idx] - target_distance_m),
        )

        snapped_point = route_geometry[best_index]
        snapped_stop = dict(stop)
        snapped_stop["lat"] = float(snapped_point[0])
        snapped_stop["lng"] = float(snapped_point[1])
        aligned.append(snapped_stop)

    return aligned


def _route_progress_for_point(point: dict, route_geometry: list) -> float | None:
    if not isinstance(route_geometry, list) or len(route_geometry) < 2:
        return None

    cumulative_distances = [0.0]
    for previous, current in zip(route_geometry, route_geometry[1:]):
        try:
            segment_distance = haversine_distance_m(
                float(previous[0]),
                float(previous[1]),
                float(current[0]),
                float(current[1]),
            )
        except (IndexError, TypeError, ValueError):
            segment_distance = 0.0
        cumulative_distances.append(cumulative_distances[-1] + segment_distance)

    total_distance = cumulative_distances[-1]
    if total_distance <= 0:
        return None

    try:
        point_lat = float(point["lat"])
        point_lon = float(point.get("lng", point.get("lon")))
    except (KeyError, TypeError, ValueError):
        return None

    latitude_scale = 111_320.0
    longitude_scale = latitude_scale * max(0.01, abs(math.cos(math.radians(point_lat))))
    point_x = point_lon * longitude_scale
    point_y = point_lat * latitude_scale
    best_distance = None
    best_progress = 0.0

    for index, (start, end) in enumerate(zip(route_geometry, route_geometry[1:])):
        start_x = float(start[1]) * longitude_scale
        start_y = float(start[0]) * latitude_scale
        end_x = float(end[1]) * longitude_scale
        end_y = float(end[0]) * latitude_scale
        delta_x = end_x - start_x
        delta_y = end_y - start_y
        segment_squared = (delta_x * delta_x) + (delta_y * delta_y)
        projection = (
            ((point_x - start_x) * delta_x) + ((point_y - start_y) * delta_y)
        ) / segment_squared if segment_squared else 0.0
        projection = min(1.0, max(0.0, projection))
        projected_x = start_x + (projection * delta_x)
        projected_y = start_y + (projection * delta_y)
        distance_squared = (
            (point_x - projected_x) ** 2
            + (point_y - projected_y) ** 2
        )
        if best_distance is None or distance_squared < best_distance:
            best_distance = distance_squared
            best_progress = (
                cumulative_distances[index]
                + (projection * (cumulative_distances[index + 1] - cumulative_distances[index]))
            ) / total_distance

    return best_progress


def build_route_segments(
    origin: dict,
    destination: dict,
    stops: list,
    route_geometry: list,
    route_distance_m: float,
) -> dict:
    """Build ordered itinerary legs using the rendered route geometry."""
    ordered_stops = sorted(
        [dict(stop) for stop in stops],
        key=lambda stop: float(stop.get("progress_ratio", 0.0)),
    )
    progress_points = []
    for stop in ordered_stops:
        geometry_progress = _route_progress_for_point(stop, route_geometry)
        progress_points.append(
            geometry_progress
            if geometry_progress is not None
            else min(1.0, max(0.0, float(stop.get("progress_ratio", 0.0))))
        )

    previous_progress = 0.0
    for stop, progress in zip(ordered_stops, progress_points):
        distance_from_previous_m = max(
            0.0,
            (progress - previous_progress) * float(route_distance_m),
        )
        stop["distance_from_previous_m"] = distance_from_previous_m
        stop["distance_to_next_m"] = max(
            0.0,
            (1.0 - progress) * float(route_distance_m),
        )
        previous_progress = max(previous_progress, progress)

    destination_distance_m = max(
        0.0,
        (1.0 - previous_progress) * float(route_distance_m),
    )
    return {
        "stops": ordered_stops,
        "destination_distance_m": destination_distance_m,
    }


def build_fuel_plan(
    distance_m: float,
    mpg: float = DEFAULT_VEHICLE_MPG,
    tank_capacity_gal: float = DEFAULT_TANK_CAPACITY_GAL,
    start_fuel_percent: float = DEFAULT_START_FUEL_PERCENT,
):
    return fuel.build_fuel_plan(
        distance_m=distance_m,
        mpg=mpg,
        tank_capacity_gal=tank_capacity_gal,
        start_fuel_percent=start_fuel_percent,
    )


def parse_positive_float_param(raw_value, field_name: str, default_value: float) -> float:
    return fuel.parse_positive_float_param(raw_value, field_name, default_value)


def parse_percentage_param(raw_value, field_name: str, default_value: float) -> float:
    return fuel.parse_percentage_param(raw_value, field_name, default_value)


def stations_home(request):
    return render(
        request,
        "stations/page.html",
        {"CARTO_API_KEY": settings.CARTO_API_KEY},
    )


@require_GET
def places_suggest(request):
    query = request.GET.get("q", "").strip()
    if len(query) < 3:
        return JsonResponse({"results": []})

    results = []

    try:
        results = tomtom_suggest_cached(normalize_query(query))
    except Exception:
        results = []

    results = [
        item
        for item in results
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

    latest_by_rack = {}
    for cp in CurrentPrice.objects.select_related("rack__truckstop").order_by("-updated_at"):
        latest_by_rack.setdefault(cp.rack_id, cp)

    prices = sorted(latest_by_rack.values(), key=lambda row: row.retail_price)
    if prices:
        median_index = len(prices) // 2
        reference_fuel_price = float(prices[median_index].retail_price)
    else:
        reference_fuel_price = 3.75

    direct_route_snapshot = build_direct_route_snapshot(
        origin_coords=origin_coords,
        destination_coords=destination_coords,
    )

    candidates = build_real_station_candidates(
        price_rows=prices,
        origin_coords=origin_coords,
        destination_coords=destination_coords,
        route_geometry=(direct_route_snapshot or {}).get("geometry", []),
        baseline_route_distance_m=(direct_route_snapshot or {}).get("distance_m"),
    )

    candidates.sort(
        key=lambda item: (
            float(item.get("road_detour_m", item.get("corridor_distance_m", 0.0)) or 0.0),
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
    real_station_pool_count = sum(1 for item in station_pool if not item.get("synthetic"))
    synthetic_station_pool_count = len(station_pool) - real_station_pool_count

    optimizer_candidates = sorted(
        station_pool,
        key=lambda item: (
            float(item.get("retail_price", 0.0)),
            float(item.get("corridor_distance_m", 0.0)),
        ),
    )[:MAX_CANDIDATES]

    def optimize_with_provider(directions_provider):
        optimizer = RouteOptimizer(
            geocoding_provider=SEARCH,
            directions_provider=directions_provider,
            vehicle_miles_per_gallon=vehicle_mpg,
            tank_capacity_gal=tank_capacity_gal,
            start_fuel_percent=start_fuel_percent,
        )
        return optimizer.optimize(
            origin_query=origin,
            destination_query=destination,
            candidate_stations=optimizer_candidates,
            weights={"time": time_weight, "price": price_weight},
            origin_coords=origin_coords,
            destination_coords=destination_coords,
        )

    if DIRECTIONS is None or DIRECTIONS_RETRY is None:
        return JsonResponse(
            {
                "error": (
                    "TomTom routing is unavailable right now. "
                    "Please configure TOMTOM_API_KEY and try again."
                )
            },
            status=503,
        )

    try:
        result = optimize_with_provider(DIRECTIONS)
    except ProviderError:
        try:
            result = optimize_with_provider(DIRECTIONS_RETRY)
        except ProviderError:
            return JsonResponse(
                {
                    "error": (
                        "TomTom routing is unavailable right now. "
                        "Please try again in a moment."
                    )
                },
                status=503,
            )
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    best = result["best_option"]
    alternatives = result["alternatives"][:MAX_CANDIDATES]

    direct_snapshot_distance_m = None
    direct_snapshot_duration_s = None
    if direct_route_snapshot is not None:
        try:
            direct_snapshot_distance_m = float(direct_route_snapshot["distance_m"])
            direct_snapshot_duration_s = float(direct_route_snapshot["duration_s"])
        except (KeyError, TypeError, ValueError):
            direct_snapshot_distance_m = None
            direct_snapshot_duration_s = None

    fuel_distance_m = float(best["distance_m"])
    if direct_snapshot_distance_m is not None and direct_snapshot_distance_m > 0:
        fuel_distance_m = min(fuel_distance_m, direct_snapshot_distance_m)

    fuel_plan = build_fuel_plan(
        fuel_distance_m,
        mpg=vehicle_mpg,
        tank_capacity_gal=tank_capacity_gal,
        start_fuel_percent=start_fuel_percent,
    )

    graph_alternatives = result.get("multi_stop_plans", [])
    if graph_alternatives:
        alternatives = graph_alternatives
        best = graph_alternatives[0]
        actual_fuel_consumed = sum(
            float(edge.get("fuel_consumed_gal", 0.0))
            for edge in best.get("edge_metrics", [])
        )
        actual_fuel_purchased = sum(
            float(purchase.get("gallons", 0.0))
            for purchase in best.get("fuel_purchases", [])
        )
        fuel_plan = {
            **build_fuel_plan(
                best["distance_m"],
                mpg=vehicle_mpg,
                tank_capacity_gal=tank_capacity_gal,
                start_fuel_percent=start_fuel_percent,
            ),
            "fuel_consumed_gal": actual_fuel_consumed,
            "fuel_purchased_gal": actual_fuel_purchased,
            "min_refuel_stops": len(best.get("fuel_purchases", [])),
            "requires_refuel": bool(best.get("fuel_purchases")),
        }
        waypoints = [
            {
                **station,
                "lng": station["lon"],
                "station_id": station["id"],
                "is_estimated": bool(station.get("synthetic", False)),
                "station_record": bool(station.get("station_record", True)),
            }
            for station in best.get("stations", [])
        ]
        path = build_route_geometry_path(
            origin_coords=result["origin"],
            destination_coords=result["destination"],
            waypoints=waypoints,
        )
    elif fuel_plan["min_refuel_stops"] <= 0:
        direct_alternatives = build_direct_route_alternatives(
            origin_coords=result["origin"],
            destination_coords=result["destination"],
            vehicle_mpg=vehicle_mpg,
            reference_fuel_price=reference_fuel_price,
            max_options=MAX_CANDIDATES,
            weights={"time": time_weight, "price": price_weight},
            tank_capacity_gal=tank_capacity_gal,
            start_fuel_percent=start_fuel_percent,
        )

        if direct_alternatives:
            alternatives = direct_alternatives
            best = direct_alternatives[0]
        elif direct_snapshot_distance_m is not None and direct_snapshot_distance_m > 0:
            direct_distance_m = direct_snapshot_distance_m
            direct_duration_s = float(direct_snapshot_duration_s or 0.0)
            direct_geometry = direct_route_snapshot.get("geometry", [])
            direct_fuel_cost = ((direct_distance_m / 1609.344) / vehicle_mpg) * reference_fuel_price

            best = {
                "station": {
                    "id": "direct-1",
                    "name": "Direct Route #1",
                    "address": "No refuel required",
                    "lat": None,
                    "lon": None,
                    "retail_price": reference_fuel_price,
                    "synthetic": True,
                },
                "distance_m": direct_distance_m,
                "duration_s": direct_duration_s,
                "geometry": direct_geometry,
                "estimated_fuel_cost": direct_fuel_cost,
                "time_norm": 0.0,
                "price_norm": 0.0,
                "score": 0.0,
                "refuel_waypoints": [],
            }
            alternatives = [best]

        waypoints = []
        path = _normalize_geometry_points(best.get("geometry", []))
        if len(path) <= 1:
            path = build_route_geometry_path(
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

        if direct_route_snapshot is not None:
            waypoints = align_estimated_waypoints_to_route_geometry(
                waypoints,
                direct_route_snapshot.get("geometry", []),
            )

        path = build_route_geometry_path(
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

    synthetic_fallback_points = []
    verified_waypoints = []
    for index, stop in enumerate(waypoints):
        if stop.get("station_record", True) or not stop.get("is_estimated"):
            verified_waypoints.append(stop)
            continue

        synthetic_fallback_points.append(
            {
                "lat": float(stop["lat"]),
                "lng": float(stop["lng"]),
                "name": f"Minimum Refuel Point {index + 1}",
                "address": "Estimated minimum fuel-range location",
                "progress_ratio": float(stop.get("progress_ratio", 0.0)),
                "is_estimated": True,
                "is_fallback": True,
            }
        )
    waypoints = verified_waypoints

    all_estimated_waypoints = bool(waypoints) and all(stop.get("is_estimated") for stop in waypoints)
    using_direct_metrics_for_estimated_stops = False

    if all_estimated_waypoints and direct_snapshot_distance_m is not None and direct_snapshot_distance_m > 0:
        direct_distance_m = direct_snapshot_distance_m
        direct_duration_s = float(direct_snapshot_duration_s or 0.0)
        direct_geometry = direct_route_snapshot.get("geometry", [])
        direct_fuel_cost = ((direct_distance_m / 1609.344) / vehicle_mpg) * reference_fuel_price

        primary_stop = waypoints[0]
        best = {
            "station": {
                "id": primary_stop.get("station_id") or "estimated-direct-1",
                "name": primary_stop.get("name", "Estimated Fuel Stop 1"),
                "address": primary_stop.get("address", "Estimated along route (provider fallback)"),
                "lat": primary_stop.get("lat"),
                "lon": primary_stop.get("lng"),
                "retail_price": None,
                "synthetic": True,
            },
            "distance_m": direct_distance_m,
            "duration_s": direct_duration_s,
            "geometry": direct_geometry,
            "estimated_fuel_cost": None,
            "fuel_cost_is_estimated": False,
            "time_norm": 0.0,
            "price_norm": 0.0,
            "score": 0.0,
            "refuel_waypoints": waypoints,
        }
        alternatives = [best]
        path = direct_geometry if len(direct_geometry) > 1 else build_path_with_waypoints(
            result["origin"],
            result["destination"],
            [],
        )
        using_direct_metrics_for_estimated_stops = True

    estimated_waypoint_count = sum(
        1
        for stop in [*waypoints, *synthetic_fallback_points]
        if stop.get("is_estimated")
    )
    notices = []

    if result.get("multi_stop_search_used"):
        notices.append(
            "Complete fuel-aware route search was used. Route legs are based on "
            "available provider responses, and unavailable station pairs were excluded."
        )

    if fuel_plan["min_refuel_stops"] > 0 and real_station_pool_count <= 0:
        notices.append(
            "No real fuel stations were found in the local dataset for this route corridor. "
            "Estimated fallback stop placement was used."
        )

    if estimated_waypoint_count > 0:
        if estimated_waypoint_count == len(waypoints):
            notices.append(
                "Refuel stop locations are estimated along the route due to limited verified station records."
            )
        else:
            notices.append(
                "Some refuel stop locations are estimated because verified station records were incomplete."
            )

    if fuel_plan["min_refuel_stops"] > 0 and waypoints:
        first_progress = float(waypoints[0].get("progress_ratio", 0.0))
        initial_reach = float(fuel_plan.get("initial_reach_ratio", 1.0))
        if first_progress > (initial_reach + 0.03):
            notices.append(
                "Nearest reachable stop from current fuel level could not be verified from station data; "
                "first stop was estimated conservatively."
            )

    if using_direct_metrics_for_estimated_stops:
        notices.append(
            "Distance and duration are based on the direct route because estimated stop coordinates are approximate."
        )

    fallback_points = synthetic_fallback_points
    if fuel_plan["min_refuel_stops"] > 0 and fuel_plan["distance_mi"] > 0:
        initial_range_ratio = (
            fuel_plan["initial_range_mi"] / fuel_plan["distance_mi"]
        )
        max_range_ratio = fuel_plan["max_range_mi"] / fuel_plan["distance_mi"]
        target_progresses = [
            min(0.98, max(0.02, initial_range_ratio + (index * max_range_ratio)))
            for index in range(fuel_plan["min_refuel_stops"])
        ]
        station_progresses = [
            float(
                stop.get(
                    "progress_ratio",
                    project_progress_ratio(
                        point_lat=float(stop["lat"]),
                        point_lon=float(stop["lng"]),
                        origin_lat=float(result["origin"]["lat"]),
                        origin_lon=float(result["origin"]["lon"]),
                        destination_lat=float(result["destination"]["lat"]),
                        destination_lon=float(result["destination"]["lon"]),
                    ),
                )
            )
            for stop in waypoints
        ]
        matched_indexes = set()
        unmatched_targets = []
        for target_progress in target_progresses:
            available = [
                (abs(progress - target_progress), index)
                for index, progress in enumerate(station_progresses)
                if index not in matched_indexes
            ]
            if available and min(available)[0] <= 0.12:
                matched_indexes.add(min(available)[1])
            else:
                unmatched_targets.append(target_progress)

        missing_stop_count = max(
            0,
            fuel_plan["min_refuel_stops"]
            - len(waypoints)
            - len(synthetic_fallback_points),
        )
        for index, progress in enumerate(unmatched_targets[:missing_stop_count]):

            fallback_points.append(
                {
                    "lat": result["origin"]["lat"]
                    + ((result["destination"]["lat"] - result["origin"]["lat"]) * progress),
                    "lng": result["origin"]["lon"]
                    + ((result["destination"]["lon"] - result["origin"]["lon"]) * progress),
                    "name": f"Minimum Refuel Point {index + 1}",
                    "address": "Estimated minimum fuel-range location",
                    "progress_ratio": progress,
                    "is_estimated": True,
                    "is_fallback": True,
                }
            )

    fallback_route_geometry = path if len(path) > 1 else (
        direct_route_snapshot or {}
    ).get("geometry", [])
    fallback_points = align_estimated_waypoints_to_route_geometry(
        fallback_points,
        fallback_route_geometry,
    )

    route_segments = build_route_segments(
        origin=result["origin"],
        destination=result["destination"],
        stops=[*waypoints, *fallback_points],
        route_geometry=path,
        route_distance_m=float(best["distance_m"]),
    )
    ordered_points = route_segments["stops"]

    if fallback_points:
        notices.append(
            "Red markers show minimum refuel-range points estimated from the "
            "vehicle parameters; they are not verified fuel stations."
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
        "fallback_points": fallback_points,
        "route_segments": route_segments,
        "distance_m": best["distance_m"],
        "duration_s": best["duration_s"],
        "fuel_cost": best["estimated_fuel_cost"],
        "fuel_cost_is_estimated": bool(best.get("fuel_cost_is_estimated", False)),
        "fuel_purchases": best.get("fuel_purchases", []),
        "stop_count": len(best.get("stations", [])),
        "detour_m": float(best.get("detour_m", 0.0)),
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
        "notices": notices,
        "data_quality": {
            "real_station_candidates": real_station_pool_count,
            "synthetic_station_candidates": synthetic_station_pool_count,
            "estimated_waypoints": estimated_waypoint_count,
            "uses_estimated_waypoints": estimated_waypoint_count > 0,
            "uses_direct_metrics_for_estimated_waypoints": using_direct_metrics_for_estimated_stops,
        },
    }

    return JsonResponse(response)
