# PolarisFuel Algorithm and Parameter Guide

## 1. What PolarisFuel does

PolarisFuel is a Django application that combines:

- TomTom geocoding for the origin and destination.
- TomTom routing for candidate route alternatives.
- Fuel station and price data imported into PostgreSQL.
- A heuristic fuel model for deciding whether refueling is needed.
- A heuristic station-selection model for placing refueling stops.
- A weighted score that ranks route alternatives by time and estimated fuel cost.

The application does not currently solve one complete global optimization problem
over every road segment, station, fuel level, and price. It uses several stages
with bounded candidate lists and approximations.

## 2. End-to-end decision flow

When the user submits an origin and destination, the backend follows this flow:

### Step 1: Resolve the locations

1. If the user selected autocomplete suggestions, the browser sends their
   latitude and longitude to the backend.
2. Otherwise, the backend geocodes the text with TomTom.
3. The result must be inside the configured United States bounds.

The autocomplete selection is important because it prevents the final request
from having to guess which place the user intended.

### Step 2: Load current fuel prices

The backend loads `CurrentPrice` records and keeps the newest price for each
rack, based on `updated_at`.

The median current price is used as a reference price for direct-route fuel
estimates and synthetic fallback candidates.

### Step 3: Build station candidates

Candidate creation is heuristic:

1. Real station records are filtered by states and distance near the
   origin-to-destination corridor.
2. Up to 30 station geocoding attempts are made, with a six-second time budget.
3. Stations are geocoded through TomTom using progressively broader queries.
4. Candidates are ranked by corridor proximity and price.
5. State-centroid fallback candidates may be created when there are not enough
   real geocoded stations.
6. Synthetic candidates may be created from state centroids or projected
   positions on the origin-destination line.
7. The station pool is limited to 10 candidates.
8. Only the three cheapest/proximate candidates from that pool are sent to the
   route optimizer.

This means the optimizer never evaluates the entire database. A cheap or
strategically located station can be excluded before the time/price weights are
applied.

### Step 4: Request a TomTom route for each candidate

For each of the maximum three candidates, PolarisFuel requests a TomTom route:

```text
origin -> candidate station -> destination
```

The route distance and duration come from TomTom. If a candidate cannot be
routed, that candidate is skipped.

### Step 5: Estimate fuel cost for each candidate

For each candidate route:

```text
distance_miles = distance_meters / 1609.344
gallons_needed = distance_miles / vehicle_mpg
estimated_fuel_cost = gallons_needed * station_price
```

The station price is treated as USD per gallon.

This is an estimate for the entire candidate route using one station's price.
It is not a detailed fuel purchase simulation for every stop in a multi-stop
trip.

### Step 6: Normalize and score alternatives

The candidate durations and fuel costs are independently min-max normalized:

```text
time_norm  = (duration - minimum_duration)
             / (maximum_duration - minimum_duration)

price_norm = (fuel_cost - minimum_fuel_cost)
             / (maximum_fuel_cost - minimum_fuel_cost)

score = normalized_time_weight * time_norm
        + normalized_price_weight * price_norm
```

Lower values are better. The weights are normalized so their total is 1.

If every candidate has the same duration or the same fuel cost, that dimension
gets a normalized value of `0` for every candidate and therefore cannot affect
the ranking.

The current Dijkstra graph is effectively:

```text
START -> candidate -> END
```

There are no edges between stations. Therefore Dijkstra is currently a
deterministic way to choose the lowest candidate score, not a multi-stop route
optimization algorithm.

### Step 7: Decide whether refueling is required

PolarisFuel builds a fuel plan using the selected route distance:

```text
initial_fuel_gal = tank_capacity_gal * start_fuel_percent / 100
initial_range_miles = initial_fuel_gal * vehicle_mpg
maximum_range_miles = tank_capacity_gal * vehicle_mpg
remaining_distance = max(0, trip_distance - initial_range_miles)
minimum_refuel_stops = ceil(remaining_distance / maximum_range_miles)
```

If `minimum_refuel_stops` is zero, a direct route is preferred.

If one or more stops are required, the application selects stop locations from
the station pool using projected progress along the straight line between the
origin and destination.

### Step 8: Select refueling waypoints

The waypoint selector:

1. Computes a target progress position for each required stop.
2. Ensures the first stop is near the distance reachable with the starting fuel.
3. Limits later stops using the vehicle's maximum range ratio.
4. Prefers real stations over synthetic candidates when both are available.
5. Adds penalties for being far from the target progress, far from the
   corridor, expensive, synthetic, or beyond a leg limit.
6. Creates estimated waypoints if no suitable station is available.

The selected waypoints are then used for route geometry previews. The waypoint
selection is based primarily on straight-line progress and corridor distance,
not on a full road-network fuel-feasibility calculation.

## 3. Parameter guide

### Time Weight

**UI range:** `0.00` to `1.00`

**Backend meaning:** Relative importance of route duration compared with fuel
cost.

The backend normalizes the time and price weights:

```text
effective_time_weight = time_weight / (time_weight + price_weight)
effective_price_weight = price_weight / (time_weight + price_weight)
```

Expected effect:

- Higher Time Weight favors shorter TomTom candidate routes.
- `1.00` time and `0.00` price means only normalized duration should affect the
  candidate ranking.
- Lower Time Weight makes duration less important.

Limitations:

- The weight only ranks the candidates that survived the earlier candidate
  filtering.
- It does not directly change TomTom's `routeType`, traffic settings, or road
  network calculation.
- It does not choose a different number of refueling stops.
- If all evaluated candidates have similar durations, changing the weight may
  produce little or no visible difference.
- When a direct route is selected, the direct-route fallback currently sets
  `score = time_norm`, so the price weight is not applied to that fallback
  ranking.

### Price Weight

**UI range:** `0.00` to `1.00`

**Backend meaning:** Relative importance of estimated fuel cost compared with
route duration.

Expected effect:

- Higher Price Weight favors lower estimated fuel cost.
- `0.00` time and `1.00` price means only normalized fuel cost should affect the
  candidate ranking.
- Lower Price Weight makes fuel cost less important.

Limitations:

- Estimated cost is based on route distance, vehicle MPG, and one station price.
- It is not the actual total cost of all fuel purchased at all selected stops.
- Only up to three candidates are scored, and those candidates are preselected
  partly by price.
- Because the candidate set is already price-biased, Price Weight can appear
  weaker than expected.
- Direct-route alternatives calculate price norms but currently assign
  `score = time_norm`, so Price Weight has no effect when ranking those direct
  alternatives.

### Vehicle MPG

**UI range:** `1` to `200`

**Backend meaning:** Estimated miles traveled per gallon.

It affects:

```text
gallons_needed = distance_miles / vehicle_mpg
estimated_fuel_cost = gallons_needed * fuel_price
initial_range = initial_fuel_gal * vehicle_mpg
maximum_range = tank_capacity_gal * vehicle_mpg
```

Expected effect:

- Higher MPG lowers estimated fuel cost.
- Higher MPG increases the distance possible with the available fuel.
- Higher MPG can reduce the required number of refueling stops.
- Lower MPG increases cost and usually increases stop requirements.

Limitations:

- MPG does not change the TomTom route duration or road geometry.
- MPG does not change station candidate discovery.
- It affects route scoring through fuel cost, but it affects waypoint selection
  later through the fuel plan. These are separate calculations.
- The model assumes constant MPG regardless of speed, traffic, terrain, load,
  weather, and idling.

### Tank Capacity (gal)

**UI range:** `1` to `400`

**Backend meaning:** Maximum gallons the vehicle can hold.

It affects only the fuel plan and waypoint planning:

```text
initial_fuel_gal = tank_capacity_gal * start_fuel_percent / 100
maximum_range = tank_capacity_gal * vehicle_mpg
minimum_refuel_stops = ceil(remaining_distance / maximum_range)
```

Expected effect:

- A larger tank increases the maximum leg distance.
- A larger tank can reduce the number of required stops.
- A smaller tank can require more stops.

Limitations:

- Tank capacity does not directly change candidate route scores.
- The algorithm assumes the tank is refilled to full at each selected stop.
- It does not model minimum reserve fuel, station detours, unavailable fuel,
  refueling time, or different fuel grades.
- Stop count is estimated from trip distance and maximum range, not validated
  against each actual road segment.

### Start Fuel (%)

**UI range:** `0` to `100`

**Backend meaning:** Fuel already available when leaving the origin.

It affects:

```text
initial_fuel_gal = tank_capacity_gal * start_fuel_percent / 100
initial_range = initial_fuel_gal * vehicle_mpg
initial_reach_ratio = initial_range / trip_distance
```

Expected effect:

- Higher starting fuel increases the distance reachable before the first stop.
- Higher starting fuel may reduce the minimum number of stops.
- Lower starting fuel moves the first planned stop closer to the origin.
- `0%` means the model starts with no usable fuel and requires an immediate
  refueling plan.

Limitations:

- The first-stop calculation uses a progress ratio on a straight line, not
  actual road distance.
- A small tolerance is added to the first-leg limit, so the selected stop can
  be slightly beyond the calculated exact reach.
- The input changes waypoint planning, but it does not directly change the
  time/price score used to rank the initial candidate routes.

## 4. Why the behavior may not match expectations yet

### The sliders do not control the whole algorithm

Time and Price weights are applied late, after candidate discovery and
preselection. A candidate eliminated earlier cannot become the best choice by
moving a slider.

### The price score is not the total trip fuel cost

For a candidate, the score uses the candidate route distance multiplied by that
candidate station's price. For a trip with multiple stops, the final waypoint
plan is calculated separately and its individual fuel purchases are not fed back
into the score.

### Vehicle inputs are split across separate models

MPG participates in candidate fuel-cost estimation and fuel-range planning.
Tank Capacity and Start Fuel participate mainly in stop planning. They do not
cause the application to recompute a complete route score for every feasible
multi-stop station sequence.

### Direct routes bypass part of the weighting logic

When no refueling is required, direct-route alternatives are built separately.
Although time and price normalized values are calculated, the direct fallback
currently ranks them using only `time_norm`. This is a concrete reason that
changing Price Weight may appear to do nothing on short trips.

### The route graph is not a multi-stop graph

The optimizer's graph has one edge from `START` to each candidate and one edge
from each candidate to `END`. It cannot compare sequences such as:

```text
START -> cheap station A -> cheap station B -> END
```

The later waypoint selector chooses stops heuristically, after the initial
candidate scoring has already happened.

### Straight-line geometry is used for several decisions

Progress ratios and corridor distance are calculated from latitude/longitude
projection and haversine distance to the straight origin-destination segment.
Roads do not follow a straight line, so a station can look close to the
corridor mathematically while requiring a significant road detour.

### Synthetic stations are estimates

When real station geocoding is incomplete, the application may place a
synthetic stop at a state centroid or along the route. These coordinates are
not verified fuel stations and can make the displayed route or cost look more
precise than the underlying data.

### Min-max normalization is relative to the current candidates

The same route can receive different normalized scores depending on which
other candidates are present. A small change in the candidate pool can change
the score scale and the winner even when the selected route's raw duration and
price barely change.

### Provider and data quality affect the result

TomTom failures, geocoding limits, incomplete station coordinates, stale prices,
and unroutable waypoints can all change the candidate pool. The UI exposes
notices and data-quality fields for some of these cases, but the result should
still be treated as an estimate.

## 5. Practical interpretation of the current UI

The current UI should be interpreted as:

- **Time Weight:** choose the fastest among the small set of routable
  candidates.
- **Price Weight:** choose the cheapest estimated fuel option among that same
  small set.
- **Vehicle MPG:** change estimated cost and fuel range.
- **Tank Capacity:** change estimated maximum range and stop count.
- **Start Fuel:** change initial reach and the likely first stop.

It should not yet be interpreted as a globally optimal fuel-aware road route
over every available station and every possible refueling sequence.

## 6. Main files implementing the algorithm

| Responsibility | File |
| --- | --- |
| HTTP orchestration and response assembly | `stations/views.py` |
| Candidate station discovery and waypoint heuristics | `stations/processes/candidate_selection.py` |
| Fuel-range and stop-count calculations | `stations/processes/fuel.py` |
| Route geometry fallback and direct alternatives | `stations/processes/routing.py` |
| Weighted candidate scoring and current graph optimizer | `stations/services/route_optimizer.py` |
| TomTom route requests | `stations/services/providers_tomtom.py` |
| TomTom geocoding/search requests | `stations/services/providers_tomtom_search.py` |
