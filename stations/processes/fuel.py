import math


def build_fuel_plan(
    distance_m: float,
    mpg: float,
    tank_capacity_gal: float,
    start_fuel_percent: float,
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


def calculate_fuel_metrics(
    distance_m: float,
    mpg: float,
    tank_capacity_gal: float,
    start_fuel_percent: float,
):
    plan = build_fuel_plan(
        distance_m=distance_m,
        mpg=mpg,
        tank_capacity_gal=tank_capacity_gal,
        start_fuel_percent=start_fuel_percent,
    )
    fuel_consumed_gal = plan["gallons_needed"]
    fuel_purchased_gal = max(0.0, fuel_consumed_gal - plan["initial_fuel_gal"])
    return {
        **plan,
        "fuel_consumed_gal": fuel_consumed_gal,
        "fuel_purchased_gal": fuel_purchased_gal,
    }


def calculate_route_fuel_cost(
    distance_m: float,
    mpg: float,
    fuel_price: float,
    tank_capacity_gal: float,
    start_fuel_percent: float,
) -> tuple[dict, float]:
    if fuel_price < 0:
        raise ValueError("fuel price cannot be negative")

    metrics = calculate_fuel_metrics(
        distance_m=distance_m,
        mpg=mpg,
        tank_capacity_gal=tank_capacity_gal,
        start_fuel_percent=start_fuel_percent,
    )
    return metrics, metrics["fuel_consumed_gal"] * float(fuel_price)


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
