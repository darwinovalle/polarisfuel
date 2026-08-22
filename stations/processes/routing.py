

def build_path_with_waypoints(origin_coords: dict, destination_coords: dict, waypoints: list):
    path = [[float(origin_coords["lat"]), float(origin_coords["lon"])]]
    path.extend([[float(stop["lat"]), float(stop["lng"])] for stop in waypoints])
    path.append([float(destination_coords["lat"]), float(destination_coords["lon"])])
    return path


def normalize_geometry_points(geometry) -> list:
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


def route_segment_geometry(start: dict, end: dict, providers: tuple, normalize_geometry_points_fn):
    for provider in providers:
        if provider is None:
            continue
        try:
            route_data = provider.route(start, end, waypoints=[])
            geometry = normalize_geometry_points_fn(route_data.get("geometry", []))
            if len(geometry) > 1:
                return geometry
        except Exception:
            continue

    return []


def build_route_geometry_path(
    origin_coords: dict,
    destination_coords: dict,
    waypoints: list,
    providers: tuple,
    normalize_geometry_points_fn,
    route_segment_geometry_fn,
    build_path_with_waypoints_fn,
):
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

    for provider in providers:
        if provider is None:
            continue
        try:
            route_data = provider.route(origin, destination, waypoints=route_waypoints)
            geometry = normalize_geometry_points_fn(route_data.get("geometry", []))
            if len(geometry) > 1:
                return geometry
        except Exception:
            continue

    stitched = []
    current = origin

    for waypoint in route_waypoints:
        segment_geometry = route_segment_geometry_fn(current, waypoint)
        if len(segment_geometry) <= 1:
            continue

        if stitched and stitched[-1] == segment_geometry[0]:
            stitched.extend(segment_geometry[1:])
        else:
            stitched.extend(segment_geometry)

        current = waypoint

    final_segment = route_segment_geometry_fn(current, destination)
    if len(final_segment) > 1:
        if stitched and stitched[-1] == final_segment[0]:
            stitched.extend(final_segment[1:])
        else:
            stitched.extend(final_segment)

    if len(stitched) > 1:
        return stitched

    direct_geometry = route_segment_geometry_fn(origin, destination)
    if len(direct_geometry) > 1:
        return direct_geometry

    return build_path_with_waypoints_fn(origin_coords, destination_coords, waypoints)


def build_alternative_refuel_previews(
    alternatives: list,
    origin_coords: dict,
    destination_coords: dict,
    shared_waypoints: list,
    project_progress_ratio_fn,
    build_route_geometry_path_fn,
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
            stop["progress_ratio"] = project_progress_ratio_fn(
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
        enriched_alternative["geometry"] = build_route_geometry_path_fn(
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
    providers: tuple,
    normalize_geometry_points_fn,
    build_path_with_waypoints_fn,
    max_options: int,
    default_vehicle_mpg: float,
    weights: dict | None = None,
):
    origin = {
        "lat": float(origin_coords["lat"]),
        "lon": float(origin_coords["lon"]),
    }
    destination = {
        "lat": float(destination_coords["lat"]),
        "lon": float(destination_coords["lon"]),
    }

    safe_mpg = vehicle_mpg if vehicle_mpg > 0 else default_vehicle_mpg
    safe_price = reference_fuel_price if reference_fuel_price > 0 else 3.75
    weights = weights or {"time": 0.6, "price": 0.4}
    weight_total = float(weights.get("time", 0.0)) + float(weights.get("price", 0.0))
    if weight_total <= 0:
        raise ValueError("weights must have positive total")
    time_weight = float(weights.get("time", 0.0)) / weight_total
    price_weight = float(weights.get("price", 0.0)) / weight_total

    for provider in providers:
        if provider is None:
            continue
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

            geometry = normalize_geometry_points_fn(candidate.get("geometry", []))
            if len(geometry) <= 1:
                geometry = build_path_with_waypoints_fn(origin_coords, destination_coords, [])

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
            item["score"] = (time_weight * time_norm) + (price_weight * price_norm)
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
