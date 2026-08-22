# PolarisFuel Optimization Implementation Plan

This checklist tracks the migration from the current heuristic optimizer to a
fuel-aware, multi-stop route optimizer. Each completed feature should be
checked, validated, and committed before the next feature starts.

## Progress status

- **Completed:** direct-route weighted scoring.
- **Completed:** deterministic Time Weight and Price Weight sensitivity tests.
- **Next:** unify MPG, tank capacity, and starting fuel in one route-cost model.
- **Overall status:** the application still uses a staged heuristic approach;
  the unchecked items are not implemented yet.

## Phase 1: Make current scoring consistent

- [x] Fix direct-route alternatives so Time Weight and Price Weight both affect
  their ranking.
- [ ] Make vehicle MPG, tank capacity, and starting fuel participate in one
  consistent route-cost model.
- [x] Attach shared fuel metrics to station and direct route alternatives as a
  foundation for complete fuel-aware scoring.
- [x] Add explicit score breakdowns and tests for parameter sensitivity.

### Phase 1 acceptance criteria

- Changing only Time Weight can change the selected route when route durations
  differ.
- Changing only Price Weight can change the selected route when fuel costs
  differ.
- MPG, tank capacity, and starting fuel are represented in the same complete
  route evaluation rather than in disconnected post-processing steps.
- The response exposes enough raw values to explain the winning score.

## Phase 2: Improve route-aware station discovery

- [x] Use the actual TomTom baseline route geometry to find nearby stations.
- [x] Replace straight-line-only corridor decisions with road-aware detour
  measurements where possible.
- [x] Keep synthetic fallback stations clearly separated from verified stations.

### Phase 2 acceptance criteria

- Station proximity is measured against TomTom route geometry.
- A station requiring a large road detour is not treated as route-adjacent merely
  because it is close to the straight origin-destination line.
- Real and synthetic candidates remain distinguishable in API responses and UI
  notices.

## Phase 3: Implement complete multi-stop optimization

- [x] Represent stations and route endpoints as graph states.
- [x] Model each edge with road distance, duration, fuel consumption, and
  detour cost.
- [x] Track remaining fuel and enforce tank/range constraints.
- [x] Calculate fuel purchases using the price at each selected station.
- [x] Add a fuel purchase primitive that refills to tank capacity and prices
  gallons using the selected station.
- [x] Search complete feasible station sequences instead of one-stop candidates.

### Phase 3 acceptance criteria

- A route plan is a complete sequence from origin to destination.
- Every selected leg is reachable with the available fuel.
- Fuel purchased at each stop uses that station's price.
- The optimizer can choose between zero, one, or multiple stops based on the
  vehicle inputs and route data.
- The selected plan is scored after all route legs and fuel purchases are known.

The graph search now requests pairwise route legs, enumerates simple
origin-to-destination paths, rejects fuel-infeasible legs, refuels at selected
stations, and scores complete plans. Provider failures on individual pairs are
omitted so the remaining graph can still produce a valid plan.

## Phase 4: Validate and explain decisions

- [x] Compare direct and fuel-stop plans using the same scoring model.
- [ ] Return total cost, duration, stops, gallons purchased, and detour details.
- [ ] Add deterministic tests covering Time Weight, Price Weight, MPG, tank
  capacity, and starting fuel.
- [ ] Document known provider/data limitations in the UI response notices.

### Phase 4 acceptance criteria

- Direct and fuel-stop plans are compared using the same score definition.
- The API and UI show route distance, duration, fuel cost, stop count, and
  parameter assumptions.
- Tests demonstrate expected changes when each user parameter changes.
- Provider outages and estimated station locations are clearly identified.

When a complete route graph is available, the optimizer includes the direct
START-to-END plan alongside station-stop plans and normalizes duration and fuel
cost across that shared alternative set. The view now preserves those scored
plans instead of replacing them with the legacy direct-route preview.

## Checkpoint workflow

For every feature:

1. Implement one scoped checklist item.
2. Add or update deterministic tests for its behavior.
3. Run the focused tests and inspect the result.
4. Mark only that item as complete.
5. Commit the implementation and checklist update together.
6. Continue with the next unchecked item.

Do not check an item merely because code exists; it is complete only when its
acceptance criteria are demonstrated by tests or a reproducible verification.

## Current checkpoint test commands

Run these commands from the repository root:

```bash
docker compose up -d db redis web
docker compose exec -T web uv run pytest \
  stations/tests/test_route_optimizer.py \
  stations/tests/test_views_path_geometry.py \
  stations/tests/test_views_optimize.py -q
```

The current completed checkpoint should pass before starting the next feature.
After changing the algorithm, repeat the focused tests and add coverage for the
new behavior before committing.

## Manual parameter test

With the Docker services running, open `http://localhost:8000/stations/` and
run the same origin and destination several times while changing one value at a
time:

1. Set Time Weight to `1.00` and Price Weight to `0.00`.
2. Set Time Weight to `0.00` and Price Weight to `1.00`.
3. Compare Vehicle MPG values such as `15` and `40`.
4. Compare Tank Capacity values such as `10` and `30`.
5. Compare Start Fuel values such as `10%` and `100%`.

Until the unchecked phases are implemented, MPG, tank capacity, and starting
fuel should be evaluated as estimates and may not change the selected route in
every scenario.

## Current algorithm limitations

The existing implementation preselects a small station pool, scores routes with
at most one candidate station, and chooses refueling waypoints afterward. The
implementation work above must preserve provider fallbacks while progressively
moving fuel feasibility and multi-stop costs into the route decision itself.
