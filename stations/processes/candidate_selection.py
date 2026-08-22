import time


def prioritize_station_rows_for_coverage(
    price_rows,
    origin_coords: dict,
    destination_coords: dict,
    state_centroids: dict,
    project_progress_ratio_fn,
):
    origin_lat = float(origin_coords["lat"])
    origin_lon = float(origin_coords["lon"])
    destination_lat = float(destination_coords["lat"])
    destination_lon = float(destination_coords["lon"])

    by_state = {}
    no_state = []

    for cp in price_rows:
        state = (cp.rack.truckstop.state or "").upper()
        if not state or state not in state_centroids:
            no_state.append(cp)
            continue
        by_state.setdefault(state, []).append(cp)

    for rows in by_state.values():
        rows.sort(key=lambda row: row.retail_price)

    ordered_states = sorted(
        by_state.keys(),
        key=lambda state: project_progress_ratio_fn(
            point_lat=state_centroids[state][0],
            point_lon=state_centroids[state][1],
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


def build_real_station_candidates(
    price_rows,
    origin_coords: dict,
    destination_coords: dict,
    state_centroids: dict,
    min_route_corridor_m: float,
    max_route_corridor_m: float,
    max_real_station_candidates: int,
    max_station_geocode_attempts: int,
    max_station_geocode_seconds: float,
    max_initial_geo_fails: int,
    prioritize_station_rows_for_coverage_fn,
    geocode_station_cached_fn,
    haversine_distance_m_fn,
    project_progress_ratio_fn,
    distance_point_to_segment_m_fn,
    route_geometry=None,
    distance_point_to_polyline_m_fn=None,
    route_detour_m_fn=None,
    baseline_route_distance_m=None,
    max_route_detour_measurements: int = 10,
):
    origin_lat = float(origin_coords["lat"])
    origin_lon = float(origin_coords["lon"])
    destination_lat = float(destination_coords["lat"])
    destination_lon = float(destination_coords["lon"])

    def corridor_distance(**kwargs):
        if route_geometry and distance_point_to_polyline_m_fn:
            return distance_point_to_polyline_m_fn(
                point_lat=kwargs["point_lat"],
                point_lon=kwargs["point_lon"],
                polyline=route_geometry,
            )
        return distance_point_to_segment_m_fn(**kwargs)

    direct_distance_m = haversine_distance_m_fn(
        origin_lat,
        origin_lon,
        destination_lat,
        destination_lon,
    )

    route_corridor_m = max(
        min_route_corridor_m,
        min(max_route_corridor_m, direct_distance_m * 0.12),
    )

    corridor_states = set()
    for state_code, (state_lat, state_lon) in state_centroids.items():
        progress_ratio = project_progress_ratio_fn(
            point_lat=state_lat,
            point_lon=state_lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        if progress_ratio < -0.2 or progress_ratio > 1.2:
            continue

        state_distance_m = corridor_distance(
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

    filtered_rows = prioritize_station_rows_for_coverage_fn(
        filtered_rows,
        origin_coords=origin_coords,
        destination_coords=destination_coords,
    )

    real_candidates = []
    attempted_queries = set()
    geocode_attempts = 0
    consecutive_geo_failures = 0
    geocode_started_at = time.monotonic()
    route_detour_attempts = 0

    def geocode_budget_exhausted() -> bool:
        return (time.monotonic() - geocode_started_at) >= max_station_geocode_seconds

    for cp in filtered_rows:
        if geocode_attempts >= max_station_geocode_attempts:
            break

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
            coord = geocode_station_cached_fn(query)
            if coord:
                break

        if not coord and geocode_budget_exhausted():
            break

        if not coord:
            consecutive_geo_failures += 1
            if not real_candidates and consecutive_geo_failures >= max_initial_geo_fails:
                break
            continue

        consecutive_geo_failures = 0

        station_lat = float(coord["lat"])
        station_lon = float(coord["lon"])

        progress_ratio = project_progress_ratio_fn(
            point_lat=station_lat,
            point_lon=station_lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        if progress_ratio < -0.2 or progress_ratio > 1.2:
            continue

        corridor_distance_m = corridor_distance(
            point_lat=station_lat,
            point_lon=station_lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        road_detour_m = None
        if route_detour_m_fn and route_detour_attempts < max_route_detour_measurements:
            route_detour_attempts += 1
            road_detour_m = route_detour_m_fn(
                origin_coords=origin_coords,
                destination_coords=destination_coords,
                station={"lat": station_lat, "lon": station_lon},
                baseline_distance_m=baseline_route_distance_m,
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
                "station_record": True,
                "progress_ratio": progress_ratio,
                "corridor_distance_m": corridor_distance_m,
                "road_detour_m": road_detour_m,
            }
        )

        if len(real_candidates) >= max_real_station_candidates:
            break

    return real_candidates


def build_state_corridor_fallback_candidates(
    price_rows,
    origin_coords: dict,
    destination_coords: dict,
    existing_ids,
    state_centroids: dict,
    min_route_corridor_m: float,
    max_route_corridor_m: float,
    max_real_station_candidates: int,
    prioritize_station_rows_for_coverage_fn,
    haversine_distance_m_fn,
    project_progress_ratio_fn,
    distance_point_to_segment_m_fn,
):
    existing_ids = existing_ids or set()

    origin_lat = float(origin_coords["lat"])
    origin_lon = float(origin_coords["lon"])
    destination_lat = float(destination_coords["lat"])
    destination_lon = float(destination_coords["lon"])

    direct_distance_m = haversine_distance_m_fn(
        origin_lat,
        origin_lon,
        destination_lat,
        destination_lon,
    )
    route_corridor_m = max(
        min_route_corridor_m,
        min(max_route_corridor_m * 1.5, direct_distance_m * 0.22),
    )

    projected = []

    prioritized_rows = prioritize_station_rows_for_coverage_fn(
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
        centroid = state_centroids.get(state)
        if not centroid:
            continue

        centroid_lat, centroid_lon = centroid
        progress_ratio = project_progress_ratio_fn(
            point_lat=centroid_lat,
            point_lon=centroid_lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        if progress_ratio < -0.15 or progress_ratio > 1.15:
            continue

        corridor_distance_m = distance_point_to_segment_m_fn(
            point_lat=centroid_lat,
            point_lon=centroid_lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        if corridor_distance_m > route_corridor_m:
            continue

        try:
            rack_seed = int(rack_id)
        except (TypeError, ValueError):
            rack_seed = sum(ord(char) for char in rack_id)

        lat_jitter = ((rack_seed % 11) - 5) * 0.03
        lon_jitter = (((rack_seed // 11) % 11) - 5) * 0.03

        projected_lat = centroid_lat + lat_jitter
        projected_lon = centroid_lon + lon_jitter

        clamped_progress = min(
            1.0,
            max(
                0.0,
                project_progress_ratio_fn(
                    point_lat=projected_lat,
                    point_lon=projected_lon,
                    origin_lat=origin_lat,
                    origin_lon=origin_lon,
                    destination_lat=destination_lat,
                    destination_lon=destination_lon,
                ),
            ),
        )

        corridor_distance_m = distance_point_to_segment_m_fn(
            point_lat=projected_lat,
            point_lon=projected_lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        projected.append(
            {
                "id": rack_id,
                "name": ts.name,
                "address": f"{ts.address}, {ts.city}, {ts.state}",
                "lat": projected_lat,
                "lon": projected_lon,
                "retail_price": float(cp.retail_price),
                "synthetic": True,
                "station_record": True,
                "progress_ratio": clamped_progress,
                "corridor_distance_m": corridor_distance_m,
            }
        )

        if len(projected) >= max_real_station_candidates:
            break

    projected.sort(
        key=lambda item: (
            float(item.get("corridor_distance_m", 0.0)),
            float(item["retail_price"]),
        )
    )
    return projected


def build_synthetic_candidates(
    price_rows,
    origin_coords: dict,
    destination_coords: dict,
    existing_ids,
    state_centroids: dict,
    max_candidates: int,
    min_route_corridor_m: float,
    max_route_corridor_m: float,
    haversine_distance_m_fn,
    project_progress_ratio_fn,
    distance_point_to_segment_m_fn,
):
    existing_ids = existing_ids or set()

    origin_lat = float(origin_coords["lat"])
    origin_lon = float(origin_coords["lon"])
    destination_lat = float(destination_coords["lat"])
    destination_lon = float(destination_coords["lon"])

    direct_distance_m = haversine_distance_m_fn(
        origin_lat,
        origin_lon,
        destination_lat,
        destination_lon,
    )
    route_corridor_m = max(
        min_route_corridor_m,
        min(max_route_corridor_m, direct_distance_m * 0.18),
    )

    synthetic = []

    for cp in price_rows:
        rack_id = str(cp.rack_id)
        if rack_id in existing_ids:
            continue

        ts = cp.rack.truckstop
        state = (ts.state or "").upper()
        centroid = state_centroids.get(state)

        if centroid:
            try:
                rack_seed = int(rack_id)
            except (TypeError, ValueError):
                rack_seed = sum(ord(char) for char in rack_id)

            lat_jitter = ((rack_seed % 9) - 4) * 0.035
            lon_jitter = (((rack_seed // 9) % 9) - 4) * 0.035
            lat = float(centroid[0]) + lat_jitter
            lon = float(centroid[1]) + lon_jitter
        else:
            lat = (origin_lat + destination_lat) / 2.0
            lon = (origin_lon + destination_lon) / 2.0

        progress_ratio = project_progress_ratio_fn(
            point_lat=lat,
            point_lon=lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        corridor_distance_m = distance_point_to_segment_m_fn(
            point_lat=lat,
            point_lon=lon,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            destination_lat=destination_lat,
            destination_lon=destination_lon,
        )

        if progress_ratio < -0.15 or progress_ratio > 1.15:
            continue

        if corridor_distance_m > (route_corridor_m * 1.25):
            continue

        synthetic.append(
            {
                "id": rack_id,
                "name": f"Estimated Fuel Stop {len(synthetic) + 1}",
                "address": "Estimated along route (provider fallback)",
                "lat": lat,
                "lon": lon,
                "retail_price": float(cp.retail_price),
                "synthetic": True,
                "station_record": True,
                "progress_ratio": min(1.0, max(0.0, progress_ratio)),
                "corridor_distance_m": corridor_distance_m,
            }
        )

        if len(synthetic) >= max_candidates:
            break

    # If route-constrained projection produced nothing, place estimated stops directly along the route
    # to avoid off-corridor cross-country detours.
    if not synthetic:
        used_ids = set(existing_ids)
        slot_index = 0

        for cp in price_rows:
            rack_id = str(cp.rack_id)
            if rack_id in used_ids:
                continue

            slot_index += 1
            progress_ratio = slot_index / (max_candidates + 1)
            lat = origin_lat + ((destination_lat - origin_lat) * progress_ratio)
            lon = origin_lon + ((destination_lon - origin_lon) * progress_ratio)

            synthetic.append(
                {
                    "id": rack_id,
                    "name": f"Estimated Fuel Stop {len(synthetic) + 1}",
                    "address": "Estimated along route (provider fallback)",
                    "lat": lat,
                    "lon": lon,
                    "retail_price": float(cp.retail_price),
                    "synthetic": True,
                    "progress_ratio": progress_ratio,
                    "corridor_distance_m": 0.0,
                }
            )
            used_ids.add(rack_id)

            if len(synthetic) >= max_candidates:
                break

    return synthetic


def select_refuel_waypoints(
    origin_coords: dict,
    destination_coords: dict,
    station_pool: list,
    required_stops: int,
    initial_reach_ratio: float,
    max_leg_ratio,
    project_progress_ratio_fn,
    distance_point_to_segment_m_fn,
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
            progress_ratio = project_progress_ratio_fn(
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
            corridor_distance_m = distance_point_to_segment_m_fn(
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
        strict_first_leg = stop_index == 0 and clamped_initial_reach < 0.98

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
            elif not strict_leg_enforcement and not strict_first_leg:
                candidate_pool = forward_pool

        if not candidate_pool and not strict_leg_enforcement and not strict_first_leg:
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

        first_leg_price_window = (
            stop_index == 0
            and clamped_initial_reach >= 0.5
        )
        if first_leg_price_window:
            price_window = [
                station
                for station in candidate_pool
                if 0.5 <= float(station["progress_ratio"]) <= leg_limit + 0.01
            ]
            if price_window:
                candidate_pool = price_window

        for station in candidate_pool:
            progress_delta = float(station["progress_ratio"]) - target_progress
            progress_penalty = abs(progress_delta) * 100.0
            if progress_delta < 0:
                progress_penalty *= 1.25

            score = (
                (float(station["retail_price"]) if first_leg_price_window else progress_penalty)
                + (station["corridor_distance_m"] / 50000.0)
                + (0.0 if first_leg_price_window else float(station["retail_price"]) / 10.0)
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
                    "station_id": None,
                    "lat": origin_lat + ((destination_lat - origin_lat) * progress),
                    "lng": origin_lon + ((destination_lon - origin_lon) * progress),
                    "name": f"Estimated Fuel Stop {stop_index + 1}",
                    "address": "Estimated along route (provider fallback)",
                    "retail_price": 0.0,
                    "progress_ratio": progress,
                    "is_estimated": True,
                    "type": f"Refuel Stop {stop_index + 1}",
                }
            )
            continue

        used_ids.add(str(best_station["id"]))
        selected.append(
            {
                "station_id": str(best_station["id"]),
                "lat": float(best_station["lat"]),
                "lng": float(best_station["lon"]),
                "name": best_station["name"],
                "address": best_station.get("address", ""),
                "retail_price": float(best_station["retail_price"]),
                "progress_ratio": float(best_station["progress_ratio"]),
                "is_estimated": bool(best_station.get("synthetic")),
                "station_record": bool(best_station.get("station_record", True)),
                "type": f"Refuel Stop {len(selected) + 1}",
            }
        )

    for stop_index in range(len(selected), required_stops):
        previous_progress = float(selected[-1].get("progress_ratio", 0.0)) if selected else 0.0
        progress = max(previous_progress + 0.03, float(target_progresses[stop_index]))
        progress = min(1.0, progress)
        selected.append(
            {
                "station_id": None,
                "lat": origin_lat + ((destination_lat - origin_lat) * progress),
                "lng": origin_lon + ((destination_lon - origin_lon) * progress),
                "name": f"Estimated Fuel Stop {stop_index + 1}",
                "address": "Estimated along route (provider fallback)",
                "retail_price": 0.0,
                "progress_ratio": progress,
                "is_estimated": True,
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
