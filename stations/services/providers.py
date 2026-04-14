from abc import ABC, abstractmethod


class GeocodingProvider(ABC):
    @abstractmethod
    def geocode(self, query: str):
        """
        Takes a string (address, city, etc.) and returns coordinates.
        """
        pass


class DirectionsProvider(ABC):
    @abstractmethod
    def route(self, origin, destination, waypoints=None):
        """
        Returns route information between origin and destination.
        """
        pass