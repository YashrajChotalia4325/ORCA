"""Connector base classes and source descriptors."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

from ..config import Settings
from ..core import freshness as fr
from ..core.schemas.common import AuthorityTier, DataKind, DataMode, SourceStatus
from ..core.schemas.provenance import Provenance, SourceFailure
from .transport import FetchResult, Transport, TransportError

# Source-quality weights (A in the confidence formula; see docs/REASONING.md)
AUTHORITY_WEIGHT = {
    AuthorityTier.NATIONAL_OFFICIAL: 0.95,
    AuthorityTier.INTERGOVERNMENTAL: 0.90,
    AuthorityTier.NATIONAL_AGENCY_FOREIGN: 0.88,
    AuthorityTier.SCIENTIFIC_COMPILATION: 0.85,
    AuthorityTier.ORCA_DERIVED: 0.70,
    AuthorityTier.ORCA_CURATED: 0.50,
}


class DatasetDescriptor(BaseModel):
    id: str
    title: str
    variables: list[str]
    kind: DataKind
    spatial_resolution: str
    temporal_resolution: str
    update_interval_s: Optional[int] = None
    expected_latency_s: Optional[int] = None
    coverage: str = ""
    producer: str = ""                     # model / product producer when different from the source
    units: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


class SourceDescriptor(BaseModel):
    id: str
    name: str
    organization: str
    distributor: Optional[str] = None
    authority_tier: AuthorityTier
    integration: str                       # live | adapter | reference
    access: str                            # public | credentials | whitelist | none
    auth_env: list[str] = Field(default_factory=list)
    homepage: str = ""
    docs_url: str = ""
    license: str = ""
    rate_limit: str = ""
    datasets: list[DatasetDescriptor] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    critical_for: list[str] = Field(default_factory=list)


@dataclass
class ConnectorContext:
    transport: Transport
    now: Callable[[], datetime]
    mode: DataMode
    settings: Settings


class Connector:
    descriptor: SourceDescriptor

    def __init__(self, ctx: ConnectorContext):
        self.ctx = ctx

    # ------------------------------------------------------------ status
    def configured(self) -> bool:
        return True

    def static_status(self) -> SourceStatus:
        d = self.descriptor
        if d.integration == "reference":
            return SourceStatus.STATIC
        if d.access == "none":
            return SourceStatus.NO_PUBLIC_API if not self.configured() else SourceStatus.UNKNOWN
        if d.access in ("credentials", "whitelist") and not self.configured():
            return SourceStatus.CREDENTIALS_REQUIRED
        return SourceStatus.UNKNOWN

    @property
    def authority(self) -> float:
        return AUTHORITY_WEIGHT[self.descriptor.authority_tier]

    def dataset(self, dataset_id: str) -> DatasetDescriptor:
        return next(d for d in self.descriptor.datasets if d.id == dataset_id)

    # ------------------------------------------------------------ helpers
    async def get(self, url: str, params: dict | None = None, **kw) -> FetchResult:
        return await self.ctx.transport.get_json(self.descriptor.id, url, params, **kw)

    def failure(self, exc: Exception, impact: str = "") -> SourceFailure:
        if isinstance(exc, TransportError):
            status, reason = exc.status, exc.message
        else:
            status, reason = "ERROR", f"{type(exc).__name__}: {exc}"
        return SourceFailure(source_id=self.descriptor.id, source=self.descriptor.name, reason=reason[:300],
                             status=status, at=self.ctx.now(), impact=impact)

    def provenance(self, *, ds: DatasetDescriptor, variable: str, units: str, res: FetchResult | None,
                   source_label: str | None = None, organization: str | None = None,
                   timestamp: datetime | None = None, issued_at: datetime | None = None,
                   last_updated: datetime | None = None, extent: list[float] | None = None,
                   has_data: bool = True, notes: list[str] | None = None,
                   tier: AuthorityTier | None = None, kind: DataKind | None = None) -> Provenance:
        d = self.descriptor
        now = self.ctx.now()
        f = fr.assess(
            now=now, mode=self.ctx.mode,
            last_updated=last_updated or issued_at or timestamp,
            retrieved_at=res.retrieved_at if res else None,
            expected_update_interval_s=ds.update_interval_s,
            expected_latency_s=ds.expected_latency_s,
            from_cache=bool(res and res.from_cache),
            has_data=has_data and res is not None,
            static=d.integration == "reference" or ds.kind == DataKind.REFERENCE,
        )
        n = list(notes or [])
        if res and res.stale_fallback:
            n.append("served from cache after live request failed (stale-if-error)")
        t = tier or d.authority_tier
        return Provenance(
            source=source_label or d.name, source_id=d.id, organization=organization or d.organization,
            distributor=d.distributor, authority_tier=t, dataset=ds.id, variable=variable,
            kind=kind or ds.kind, timestamp=timestamp, issued_at=issued_at,
            retrieval_timestamp=res.retrieved_at if res else None,
            spatial_resolution=ds.spatial_resolution, temporal_resolution=ds.temporal_resolution,
            units=units, geographic_extent=extent, freshness=f, confidence=AUTHORITY_WEIGHT[t],
            source_url=res.url if res else "", license=d.license,
            status="OK" if f.status.value not in ("UNAVAILABLE",) else "UNAVAILABLE",
            mode=self.ctx.mode, notes=n,
        )

    async def probe(self) -> dict[str, Any]:
        """Lightweight health probe used by the Data Sources page."""
        return {"status": self.static_status().value, "detail": "no probe implemented"}
