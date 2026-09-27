"""Connectors, transports, resilience and adapter honesty (no network)."""
import asyncio
import json
from datetime import datetime, timezone

import pytest

from orca.config import get_settings
from orca.connectors.base import ConnectorContext
from orca.connectors.health import CircuitBreaker, HEALTH
from orca.connectors.registry import ConnectorRegistry
from orca.connectors.transport import (DemoTransport, FetchResult, Recorder, ReplayTransport, Transport, TransportError,
                                       request_key, sanitize_url)
from orca.core.schemas.common import BBox, DataMode, FreshnessStatus, GeoPoint, SourceStatus

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


class FakeTransport(Transport):
    mode = DataMode.LIVE

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    async def get_json(self, source_id, url, params=None, **kw):
        self.calls.append((source_id, url, params))
        data = self.handler(source_id, url, params or {})
        return FetchResult(data, request_key(url, params), NOW, False, 1.0, self.mode)


def reg_with(handler, mode=DataMode.LIVE):
    t = FakeTransport(handler)
    t.mode = mode
    ctx = ConnectorContext(transport=t, now=lambda: NOW, mode=mode, settings=get_settings())
    return ConnectorRegistry(ctx), t


def om_payload(var_up, values, lat=9.9, lon=75.9):
    times = [f"2026-09-26T{h:02d}:00" for h in range(len(values))]
    return {"latitude": lat, "longitude": lon, "hourly_units": {var_up: "m"}, "hourly": {"time": times, var_up: values}}


async def test_openmeteo_parses_series_with_model_run_provenance():
    def h(sid, url, p):
        if "meta.json" in url:
            return {"last_run_initialisation_time": int(datetime(2026, 9, 26, 6, tzinfo=timezone.utc).timestamp()),
                    "last_run_availability_time": int(datetime(2026, 9, 26, 11, tzinfo=timezone.utc).timestamp()),
                    "update_interval_seconds": 21600}
        return om_payload("wave_height", [1.0, 1.2, None, 1.4])
    reg, _ = reg_with(h)
    series, fails = await reg.models["om_ecmwf_wam"].point(GeoPoint(lat=9.9, lon=75.9))
    ts = series["wave_height"]
    assert not fails and ts.units == "m" and ts.values[1] == 1.2
    p = ts.provenance
    assert p.issued_at.hour == 6 and p.freshness.status == FreshnessStatus.LIVE
    assert p.source == "ECMWF WAM" and p.distributor == "Open-Meteo" and p.kind.value == "FORECAST"


async def test_openmeteo_land_point_is_reported_not_invented():
    reg, _ = reg_with(lambda s, u, p: {} if "meta" in u else om_payload("wave_height", [None, None]))
    series, fails = await reg.models["om_mfwam"].point(GeoPoint(lat=10.0, lon=76.5))
    assert series == {} and fails and fails[0].status == "NO_DATA"


async def test_restricted_adapters_never_return_live_data():
    reg, t = reg_with(lambda s, u, p: pytest.fail("adapter must not call the network for data"))
    w, prov, f = await reg.imd.marine_warnings("kerala_coast")
    assert w == [] and prov is None and f[0].status == SourceStatus.CREDENTIALS_REQUIRED.value
    feats, prov, f = await reg.incois.pfz(BBox(lon_min=75, lat_min=9, lon_max=76, lat_max=10))
    assert feats == [] and f[0].status == SourceStatus.NO_PUBLIC_API.value
    v, f = await reg.mosdac.satellite_value("sst", BBox(lon_min=75, lat_min=9, lon_max=76, lat_max=10))
    assert v is None and f[0].status == SourceStatus.CREDENTIALS_REQUIRED.value
    assert reg.copernicus.static_status() == SourceStatus.CREDENTIALS_REQUIRED
    assert reg.cmfri.static_status() == SourceStatus.NO_PUBLIC_API


async def test_gdacs_inactive_event_is_not_active():
    def h(sid, url, p):
        if "getgeometry" in url:
            return {"features": []}
        return {"features": [{"geometry": {"coordinates": [83.7, 18.1]}, "properties": {
            "eventid": 1, "episodeid": 1, "name": "TC X", "alertlevel": "Orange", "iscurrent": "true",
            "fromdate": "2026-09-22T18:00:00", "todate": "2026-09-24T00:00:00", "datemodified": "2026-09-26T10:00:00"}}]}
    reg, _ = reg_with(h)
    ev, prov, f = await reg.gdacs.cyclones()
    assert len(ev) == 1 and ev[0]["active"] is False and ev[0]["hours_since_last_advisory"] > 24


def test_circuit_breaker_opens_and_half_opens():
    cb = CircuitBreaker(fail_threshold=3, cooldown_s=0.0)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == "OPEN"
    assert cb.allow() and cb.state == "HALF_OPEN"   # cooldown elapsed
    cb.record_success()
    assert cb.state == "CLOSED"


def test_secrets_are_stripped_from_urls():
    assert "abc123" not in sanitize_url("https://x", {"token": "abc123", "q": 1})


async def test_record_and_replay_roundtrip(tmp_path):
    rec = Recorder(tmp_path, "test")
    key = request_key("https://marine-api.open-meteo.com/v1/marine", {"a": 1})
    rec.save("om_mfwam", key, FetchResult({"x": 1}, key, NOW, False, 1.0, DataMode.LIVE))
    rp = ReplayTransport(tmp_path)
    r = await rp.get_json("om_mfwam", "https://marine-api.open-meteo.com/v1/marine", {"a": 1})
    assert r.data == {"x": 1} and r.retrieved_at == NOW and r.mode == DataMode.REPLAY
    with pytest.raises(TransportError) as e:
        await rp.get_json("om_mfwam", "https://marine-api.open-meteo.com/v1/marine", {"a": 2})
    assert e.value.status == "NOT_IN_RECORDING"


async def test_demo_transport_failures_are_explicit():
    def responder(sid, url, params):
        raise TransportError(sid, "HTTP_503", "simulated")
    t = DemoTransport(responder, lambda: NOW)
    with pytest.raises(TransportError):
        await t.get_json("om_mfwam", "https://marine-api.open-meteo.com/v1/marine", {})
