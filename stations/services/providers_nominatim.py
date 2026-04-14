import httpx

from stations.services.provider_errors import (
    ProviderBadResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)


class NominatimGeocodingProvider:
    def __init__(self, timeout: float = 2.0, max_retries: int = 1):
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = "https://nominatim.openstreetmap.org/search"

    def geocode(self, query: str) -> dict:
        last_error = None

        for _ in range(self.max_retries):
            try:
                response = httpx.get(
                    self.base_url,
                    params={
                        "q": query,
                        "format": "jsonv2",
                        "limit": 1,
                    },
                    timeout=self.timeout,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                continue
            except Exception as exc:
                raise ProviderUnavailableError(str(exc)) from exc

            if response.status_code != 200:
                raise ProviderBadResponseError(
                    f"Nominatim returned status {response.status_code}"
                )

            data = response.json()
            if not isinstance(data, list) or not data:
                raise ProviderBadResponseError("Nominatim returned empty results")

            first = data[0]
            try:
                lat = float(first["lat"])
                lon = float(first["lon"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderBadResponseError("Invalid geocoding payload") from exc

            return {
                "lat": lat,
                "lon": lon,
                "display_name": first.get("display_name", query),
            }

        raise ProviderTimeoutError("Nominatim request timed out") from last_error
