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

    def route(self, origin: dict, destination: dict, waypoints: list | None = None) -> dict:
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
                response = httpx.get(
                    url,
                    params={"overview": "false"},
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

            first = routes[0]
            try:
                return {
                    "distance_m": first["distance"],
                    "duration_s": first["duration"],
                    "geometry": first.get("geometry", ""),
                }
            except KeyError as exc:
                raise ProviderBadResponseError("Malformed OSRM route payload") from exc

        raise ProviderTimeoutError("OSRM request timed out") from last_error
