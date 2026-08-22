# PolarisFuel Optimization Implementation Plan

This checklist tracks the migration from the current heuristic optimizer to a
fuel-aware, multi-stop route optimizer. Each completed feature should be
checked, validated, and committed before the next feature starts.

## Phase 1: Make current scoring consistent

- [x] Fix direct-route alternatives so Time Weight and Price Weight both affect
  their ranking.
- [ ] Make vehicle MPG, tank capacity, and starting fuel participate in one
  consistent route-cost model.
- [x] Add explicit score breakdowns and tests for parameter sensitivity.

## Phase 2: Improve route-aware station discovery

- [ ] Use the actual TomTom baseline route geometry to find nearby stations.
- [ ] Replace straight-line-only corridor decisions with road-aware detour
  measurements where possible.
- [ ] Keep synthetic fallback stations clearly separated from verified stations.

## Phase 3: Implement complete multi-stop optimization

- [ ] Represent stations and route endpoints as graph states.
- [ ] Model each edge with road distance, duration, fuel consumption, and
  detour cost.
- [ ] Track remaining fuel and enforce tank/range constraints.
- [ ] Calculate fuel purchases using the price at each selected station.
- [ ] Search complete feasible station sequences instead of one-stop candidates.

## Phase 4: Validate and explain decisions

- [ ] Compare direct and fuel-stop plans using the same scoring model.
- [ ] Return total cost, duration, stops, gallons purchased, and detour details.
- [ ] Add deterministic tests covering Time Weight, Price Weight, MPG, tank
  capacity, and starting fuel.
- [ ] Document known provider/data limitations in the UI response notices.

## Current algorithm limitations

The existing implementation preselects a small station pool, scores routes with
at most one candidate station, and chooses refueling waypoints afterward. The
implementation work above must preserve provider fallbacks while progressively
moving fuel feasibility and multi-stop costs into the route decision itself.
