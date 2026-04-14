import httpx

from stations.services.provider_errors import (
    ProviderBadResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


class TomTomDirectionsProvider:
    def __init__(self, api_key: str, timeout: float = 3.0, max_retries: int = 1):
        if not api_key:
            raise ValueError("api_key is required")

        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = "https://api.tomtom.com/routing/1/calculateRoute"

    def route(
        self,
        origin: dict,
        destination: dict,
        waypoints: list | None = None,
        include_alternatives: bool = False,
    ) -> dict:
        # TomTom calculateRoute expects each coordinate as "lat,lon".
        coords = [f'{origin["lat"]},{origin["lon"]}']

        if waypoints:
            for wp in waypoints:
                coords.append(f'{wp["lat"]},{wp["lon"]}')

        coords.append(f'{destination["lat"]},{destination["lon"]}')
        path = ":".join(coords)
        url = f"{self.base_url}/{path}/json"

        params = {
            "key": self.api_key,
            "routeType": "fastest",
            "traffic": "true",
            "computeTravelTimeFor": "all",
        }
        if include_alternatives:
            # Request up to 3 routes total: primary + 2 alternatives.
            params["maxAlternatives"] = "2"

        last_error = None

        for _ in range(self.max_retries):
            try:
                response = httpx.get(url, params=params, timeout=self.timeout)
            except httpx.TimeoutException as exc:
                last_error = exc
                continue
            except Exception as exc:
                raise ProviderUnavailableError(str(exc)) from exc

            if response.status_code != 200:
                raise ProviderBadResponseError(
                    f"TomTom returned status {response.status_code}"
                )

            data = response.json()
            routes = data.get("routes", [])
            if not routes:
                raise ProviderBadResponseError("TomTom returned no routes")

            parsed_routes = []
            for route in routes:
                summary = route.get("summary", {})
                try:
                    distance_m = float(summary["lengthInMeters"])
                    duration_s = float(summary["travelTimeInSeconds"])
                except (KeyError, TypeError, ValueError):
                    continue

                geometry = []
                for leg in route.get("legs", []):
                    for point in leg.get("points", []):
                        try:
                            lat = float(point["latitude"])
                            lon = float(point["longitude"])
                        except (KeyError, TypeError, ValueError):
                            continue

                        coord = [lat, lon]
                        if geometry and geometry[-1] == coord:
                            continue
                        geometry.append(coord)

                parsed_routes.append(
                    {
                        "distance_m": distance_m,
                        "duration_s": duration_s,
                        "geometry": geometry,
                    }
                )

            if not parsed_routes:
                raise ProviderBadResponseError("Malformed TomTom route summary")

            first = parsed_routes[0]
            return {
                "distance_m": first["distance_m"],
                "duration_s": first["duration_s"],
                "geometry": first["geometry"],
                "alternatives": parsed_routes,
            }

        raise ProviderTimeoutError("TomTom request timed out") from last_error
