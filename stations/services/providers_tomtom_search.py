import httpx
from urllib.parse import quote

from stations.services.provider_errors import (
    ProviderBadResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


class TomTomSearchProvider:
    def __init__(self, api_key: str, timeout: float = 2.5, max_retries: int = 1):
        if not api_key:
            raise ValueError("api_key is required")

        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.geocode_url = "https://api.tomtom.com/search/2/geocode"
        self.search_url = "https://api.tomtom.com/search/2/search"

    def geocode(self, query: str) -> dict:
        route = f"{self.geocode_url}/{quote(query, safe='')}.json"
        data = self._request(route, limit=1)
        results = data.get("results") or []

        if not results:
            raise ProviderBadResponseError("TomTom returned empty geocode results")

        best = results[0]
        position = best.get("position") or {}

        try:
            lat = float(position["lat"])
            lon = float(position["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderBadResponseError("Malformed TomTom geocode payload") from exc

        return {
            "lat": lat,
            "lon": lon,
            "display_name": best.get("address", {}).get("freeformAddress")
            or best.get("address", {}).get("municipality")
            or query,
        }

    def suggest(self, query: str, limit: int = 6) -> list:
        route = f"{self.search_url}/{quote(query, safe='')}.json"
        data = self._request(route, limit=max(1, int(limit)))
        results = data.get("results") or []

        parsed = []
        for item in results:
            position = item.get("position") or {}
            address = item.get("address") or {}

            try:
                lat = float(position["lat"])
                lon = float(position["lon"])
            except (KeyError, TypeError, ValueError):
                continue

            parsed.append(
                {
                    "name": address.get("freeformAddress") or item.get("poi", {}).get("name") or query,
                    "lat": lat,
                    "lon": lon,
                }
            )

        return parsed

    def _request(self, url: str, limit: int) -> dict:
        params = {
            "key": self.api_key,
            "limit": max(1, int(limit)),
            "countrySet": "US",
        }

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
            if not isinstance(data, dict):
                raise ProviderBadResponseError("Malformed TomTom search response")

            return data

        raise ProviderTimeoutError("TomTom search request timed out") from last_error
