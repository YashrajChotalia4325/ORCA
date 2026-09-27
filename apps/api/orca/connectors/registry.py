"""Builds the full connector set for one execution context (mode + transport + clock)."""
from __future__ import annotations

from .base import Connector, ConnectorContext
from .erddap import NoaaCoastWatch
from .gdacs import GDACS
from .gebco import GEBCO
from .gibs import NasaGIBS
from .openmeteo import MODELS, OpenMeteoModel, build_openmeteo
from .restricted import (CMFRI, IMD, INCOIS, MOSDAC, REFERENCE_DESCRIPTORS, Bhuvan, CopernicusMarine,
                         NasaOceanColor, ProtectedPlanet, StaticReference)


class ConnectorRegistry:
    def __init__(self, ctx: ConnectorContext):
        self.ctx = ctx
        self.models: dict[str, OpenMeteoModel] = build_openmeteo(ctx)
        self.erddap = NoaaCoastWatch(ctx)
        self.gdacs = GDACS(ctx)
        self.gebco = GEBCO(ctx)
        self.gibs = NasaGIBS(ctx)
        self.mosdac = MOSDAC(ctx)
        self.imd = IMD(ctx)
        self.incois = INCOIS(ctx)
        self.copernicus = CopernicusMarine(ctx)
        self.protected_planet = ProtectedPlanet(ctx)
        self.oceancolor = NasaOceanColor(ctx)
        self.bhuvan = Bhuvan(ctx)
        self.cmfri = CMFRI(ctx)
        self.reference = [StaticReference(ctx, d) for d in REFERENCE_DESCRIPTORS]

    def wave_models(self, include_tiebreakers: bool = False) -> list[OpenMeteoModel]:
        return [m for m in self.models.values() if m.spec.family == "marine" and "wave_height" in m.spec.variables
                and (include_tiebreakers or m.spec.role == "primary")]

    def current_models(self) -> list[OpenMeteoModel]:
        return [m for m in self.models.values() if "ocean_current_velocity" in m.spec.variables]

    def weather_models(self, include_tiebreakers: bool = False) -> list[OpenMeteoModel]:
        return [m for m in self.models.values() if m.spec.family == "weather"
                and (include_tiebreakers or m.spec.role == "primary")]

    def tiebreaker(self, family: str) -> list[OpenMeteoModel]:
        return [m for m in self.models.values() if m.spec.role == "tiebreaker" and m.spec.family == family]

    def all(self) -> list[Connector]:
        return [*self.models.values(), self.erddap, self.gdacs, self.gebco, self.gibs, self.mosdac, self.imd,
                self.incois, self.copernicus, self.protected_planet, self.oceancolor, self.bhuvan, self.cmfri,
                *self.reference]

    def by_id(self, sid: str) -> Connector | None:
        return next((c for c in self.all() if c.descriptor.id == sid), None)

    def authority_map(self) -> dict[str, float]:
        return {c.descriptor.id: c.authority for c in self.all()}
