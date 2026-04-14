import httpx

from stations.services.provider_errors import (
    ProviderBadResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


class OsrmDirectionsProvider:
    def __init__(self, timeout: float = 2.0, max_retries: int = 1):
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = "https://router.project-osrm.org/route/v1/driving"

    def route(
        self,
        origin: dict,
        destination: dict,
        waypoints: list | None = None,
        include_alternatives: bool = False,
    ) -> dict:
        coords = [f'{origin["lon"]},{origin["lat"]}']

        if waypoints:
            for wp in waypoints:
                coords.append(f'{wp["lon"]},{wp["lat"]}')

        coords.append(f'{destination["lon"]},{destination["lat"]}')
        path = ";".join(coords)
        url = f"{self.base_url}/{path}"

        last_error = None

        for _ in range(self.max_retries):
            try:
                params = {
                    "overview": "full",
                    "geometries": "geojson",
                }
                if include_alternatives:
                    params["alternatives"] = "true"

                response = httpx.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                continue
            except Exception as exc:
                raise ProviderUnavailableError(str(exc)) from exc

            if response.status_code != 200:
                raise ProviderBadResponseError(
                    f"OSRM returned status {response.status_code}"
                )

            data = response.json()
            if data.get("code") != "Ok":
                raise ProviderBadResponseError("OSRM response code is not Ok")

            routes = data.get("routes", [])
            if not routes:
                raise ProviderBadResponseError("OSRM returned no routes")

            parsed_routes = []
            for route in routes:
                try:
                    geometry = route.get("geometry", "")

                    if isinstance(geometry, dict):
                        coordinates = geometry.get("coordinates", [])
                        if isinstance(coordinates, list):
                            # GeoJSON coordinates are [lon, lat]; Leaflet expects [lat, lon].
                            geometry = [
                                [float(coord[1]), float(coord[0])]
                                for coord in coordinates
                                if isinstance(coord, (list, tuple)) and len(coord) >= 2
                            ]

                    parsed_routes.append(
                        {
                            "distance_m": float(route["distance"]),
                            "duration_s": float(route["duration"]),
                            "geometry": geometry,
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    continue

            if not parsed_routes:
                raise ProviderBadResponseError("Malformed OSRM route payload")

            first = parsed_routes[0]
            return {
                "distance_m": first["distance_m"],
                "duration_s": first["duration_s"],
                "geometry": first["geometry"],
                "alternatives": parsed_routes,
            }

        raise ProviderTimeoutError("OSRM request timed out") from last_error
