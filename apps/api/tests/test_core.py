"""Deterministic core: spatial, freshness, temporal, units, risk, confidence, conflicts."""
from datetime import datetime, timedelta, timezone

import pytest

from orca.core import confidence as cf
from orca.core import freshness as fr
from orca.core import risk as rm
from orca.core import spatial, temporal, units
from orca.core.clock import IST
from orca.core.schemas.assessment import EvidenceItem, Provenance
from orca.core.schemas.common import (AuthorityTier, DataKind, DataMode, Decision, FreshnessStatus, GeoPoint,
                                      RiskLevel)
from orca.geo.reference import ReferenceStore
from orca.reasoning import conflicts as cx

UTC = timezone.utc
NOW = datetime(2026, 9, 26, 0, 30, tzinfo=UTC)
MUMBAI, GOA = GeoPoint(lat=18.93, lon=72.83), GeoPoint(lat=15.41, lon=73.80)
KOCHI, VIZAG = GeoPoint(lat=9.965, lon=76.242), GeoPoint(lat=17.69, lon=83.29)


@pytest.fixture(scope="module")
def ref():
    return ReferenceStore.get()


# ------------------------------------------------------------------------------------------------ spatial
def test_geodesic_distance_mumbai_goa():
    d = spatial.distance_km(MUMBAI, GOA)
    assert 395 < d < 410          # ~402 km great circle


def test_destination_roundtrip():
    p = spatial.destination(KOCHI, 255, 30)
    assert abs(spatial.distance_km(KOCHI, p) - 30) < 0.01
    assert abs(spatial.bearing_deg(KOCHI, p) - 255) < 0.5


def test_offshore_point_is_seaward(ref):
    p, brg = ref.offshore_point(KOCHI, 30)
    assert ref.is_sea(p) and 200 <= brg <= 300          # Kerala coast faces west
    p2, brg2 = ref.offshore_point(VIZAG, 30)
    assert ref.is_sea(p2) and 90 <= brg2 <= 180          # Andhra coast faces south-east
    assert ref.distance_to_coast_km(p) > 15


def test_land_and_eez(ref):
    assert not ref.is_sea(GeoPoint(lat=28.6, lon=77.2))                   # Delhi
    name, india = ref.eez_at(GeoPoint(lat=9.9, lon=75.5))
    assert india is True and "India" in name
    name, india = ref.eez_at(GeoPoint(lat=6.2, lon=82.6))                  # sea east of Sri Lanka
    assert india is False


def test_boundary_distance_near_palk_bay(ref):
    hits = ref.zone_hits(GeoPoint(lat=9.6, lon=79.6), NOW, "small_craft", radius_km=200)
    b = next(h for h in hits if h.kind == "maritime_boundary")
    assert b.distance_km < 40 and "Sri Lanka" in b.name


def test_mpa_inside_and_seasonal_rules(ref):
    hits = ref.zone_hits(GeoPoint(lat=9.12, lon=78.9), NOW, "mechanized")
    mpa = next(h for h in hits if h.zone_id == "gulf_of_mannar_mnp")
    assert mpa.inside and mpa.approximate
    ban = next(z for z in ref.zones if z.id == "west_coast_monsoon_ban")
    assert ban.active_at(datetime(2026, 6, 15, tzinfo=UTC), "mechanized")
    assert not ban.active_at(NOW, "mechanized")                           # 26 Sep: ban over
    assert not ban.active_at(datetime(2026, 6, 15, tzinfo=UTC), "small_craft")  # traditional craft exempt


def test_user_geofence(ref):
    ref.add_geofence("t1", "test box", [[75.0, 9.0], [75.5, 9.0], [75.5, 9.5], [75.0, 9.5], [75.0, 9.0]])
    hits = ref.zone_hits(GeoPoint(lat=9.2, lon=75.2), NOW)
    assert any(h.zone_id == "t1" and h.inside for h in hits)
    ref.remove_geofence("t1")


def test_route_entry_distance():
    coords = [[78.0, 8.5], [79.5, 9.3]]
    lons, lats, cum = spatial.densify_route(coords, 0.5)
    from shapely.geometry import box
    d, i = spatial.first_entry_along(lons, lats, cum, box(78.5, 8.0, 79.0, 10.0))
    assert d is not None and 45 < d < 70


# ------------------------------------------------------------------------------------------------ freshness
def test_freshness_rules():
    ok = fr.assess(now=NOW, mode=DataMode.LIVE, last_updated=NOW - timedelta(hours=3),
                   retrieved_at=NOW - timedelta(minutes=2), expected_update_interval_s=6 * 3600, expected_latency_s=6 * 3600)
    assert ok.status == FreshnessStatus.LIVE and ok.factor == 1.0
    recent = fr.assess(now=NOW, mode=DataMode.LIVE, last_updated=NOW - timedelta(hours=3),
                       retrieved_at=NOW - timedelta(minutes=40), expected_update_interval_s=21600)
    assert recent.status == FreshnessStatus.RECENT
    stale = fr.assess(now=NOW, mode=DataMode.LIVE, last_updated=NOW - timedelta(days=3),
                      retrieved_at=NOW, expected_update_interval_s=21600, expected_latency_s=21600)
    assert stale.status == FreshnessStatus.STALE and stale.factor < 1
    none = fr.assess(now=NOW, mode=DataMode.LIVE, last_updated=None, retrieved_at=None,
                     expected_update_interval_s=3600, has_data=False)
    assert none.status == FreshnessStatus.UNAVAILABLE and none.factor == 0


@pytest.mark.parametrize("mode,expected", [(DataMode.REPLAY, FreshnessStatus.REPLAY), (DataMode.DEMO, FreshnessStatus.SIMULATED)])
def test_replay_and_demo_are_never_live(mode, expected):
    f = fr.assess(now=NOW, mode=mode, last_updated=NOW, retrieved_at=NOW, expected_update_interval_s=3600)
    assert f.status == expected and f.status != FreshnessStatus.LIVE


# ------------------------------------------------------------------------------------------------ temporal
def test_tomorrow_5am_is_explicit_ist_window():
    r = temporal.resolve("Is it safe to leave Kochi tomorrow at 5 AM?", NOW, activity="fishing")
    s = r.window.start.astimezone(IST)
    assert (s.day, s.hour) == (27, 5) and r.window.hours == 6
    assert any("assumed 6 h" in a for a in r.window.assumptions)


def test_tomorrow_morning_and_next_hours():
    r = temporal.resolve("tomorrow morning", NOW)
    assert r.window.start.astimezone(IST).hour == 5 and r.window.end.astimezone(IST).hour == 11
    r2 = temporal.resolve("waves for the next 12 hours", NOW)
    assert abs(r2.window.hours - 12) < 1e-6


def test_past_days_gives_comparison_window():
    r = temporal.resolve("over the past 14 days", NOW)
    assert r.comparison is not None and abs((r.window.end - r.window.start).days - 14) <= 1
    assert r.comparison.end == r.window.start


@pytest.mark.parametrize("text", ["நாளை காலை", "రేపు ఉదయం", "ನಾಳೆ ಬೆಳಿಗ್ಗೆ", "আগামীকাল সকালে", "उद्या सकाळी"])
def test_multilingual_tomorrow_morning(text):
    r = temporal.resolve(text, NOW)
    s = r.window.start.astimezone(IST)
    assert s.day == 27 and s.hour == 5


# ------------------------------------------------------------------------------------------------ units
def test_units():
    assert abs(units.convert(10, "m/s", "km/h") - 36) < 1e-9
    assert abs(units.convert(1.852, "km", "nm") - 1) < 1e-9
    assert abs(units.convert(300, "K", "°C") - 26.85) < 1e-9
    with pytest.raises(units.UnitError):
        units.assert_comparable("m", "km/h")
    with pytest.raises(units.UnitError):
        units.convert(1, "m", "km/h")


# ------------------------------------------------------------------------------------------------ risk model
def _fi(fid, *vals, src="A", t=NOW):
    return rm.FactorInput(fid, [rm.SourceSamples(source=f"model {s}", source_id=s, kind=DataKind.FORECAST,
                                                 samples=[rm.Sample(time=t + timedelta(hours=k), value=v) for k, v in enumerate(vs)])
                                for s, vs in (src if isinstance(src, dict) else {src: vals}).items()])


def test_go_when_all_below_thresholds():
    a = rm.evaluate("small_craft", NOW, NOW + timedelta(hours=6),
                    {"wind_speed": _fi("wind_speed", 10, 12), "wave_height": _fi("wave_height", 0.8, 1.0)})
    assert a.decision == Decision.GO and a.risk_index is not None


def test_missing_critical_gives_insufficient_data():
    a = rm.evaluate("small_craft", NOW, NOW + timedelta(hours=6), {"wind_speed": _fi("wind_speed", 10)})
    assert a.decision == Decision.INSUFFICIENT_DATA and "wave_height" in a.missing_critical and a.risk_index is None


def test_danger_gives_dont_go_and_caution_gives_caution():
    a = rm.evaluate("small_craft", NOW, NOW + timedelta(hours=6),
                    {"wind_speed": _fi("wind_speed", 20), "wave_height": _fi("wave_height", 1.0, 2.7)})
    assert a.decision == Decision.DONT_GO and "wave_height" in a.drivers
    b = rm.evaluate("small_craft", NOW, NOW + timedelta(hours=6),
                    {"wind_speed": _fi("wind_speed", 30), "wave_height": _fi("wave_height", 1.0)})
    assert b.decision == Decision.CAUTION


def test_vessel_class_changes_thresholds_not_data():
    inputs = {"wind_speed": _fi("wind_speed", 35), "wave_height": _fi("wave_height", 2.2)}
    assert rm.evaluate("small_craft", NOW, NOW, inputs).decision == Decision.CAUTION
    assert rm.evaluate("large_vessel", NOW, NOW, inputs).decision == Decision.GO


def test_conservative_worst_case_across_sources_and_onset():
    fi = _fi("wave_height", src={"A": [1.0, 1.2, 1.3], "B": [1.0, 1.6, 1.9]})
    f = rm.evaluate_factor("wave_height", fi, rm.THRESHOLDS["small_craft"]["wave_height"])
    assert f.value == 1.9 and f.level == RiskLevel.CAUTION and f.spread == pytest.approx(0.6)
    assert f.onset == NOW + timedelta(hours=1)


def test_cape_alone_never_dont_go():
    a = rm.evaluate("small_craft", NOW, NOW, {"wind_speed": _fi("wind_speed", 10), "wave_height": _fi("wave_height", 0.8),
                                             "cape": _fi("cape", 4000)})
    assert a.decision == Decision.CAUTION
    assert next(f for f in a.factors if f.id == "cape").level == RiskLevel.CAUTION


def test_official_advisory_danger_forces_dont_go():
    a = rm.evaluate("small_craft", NOW, NOW, {"wind_speed": _fi("wind_speed", 10), "wave_height": _fi("wave_height", 0.8)},
                    rm.AdvisoryInput(available=True, level=RiskLevel.DANGER, items=[{"t": "x"}]))
    assert a.decision == Decision.DONT_GO


def test_point_risk_monotonic():
    s1, _, _ = rm.point_risk("small_craft", {"wave_height": 1.0, "wind_speed": 10})
    s2, lvl, drv = rm.point_risk("small_craft", {"wave_height": 2.6, "wind_speed": 10})
    assert s2 > s1 and lvl == RiskLevel.DANGER and "wave_height" in drv


# ------------------------------------------------------------------------------------------------ confidence
def _prov():
    return Provenance(source="x", source_id="x", organization="x", authority_tier=AuthorityTier.INTERGOVERNMENTAL,
                      dataset="d", variable="v", kind=DataKind.FORECAST)


def _item(i, lineage, supports=True, w=(0.9, 1.0, 0.9, 0.9)):
    it = EvidenceItem(id=f"E{i}", claim_id="C", source=lineage, source_id=lineage, kind=DataKind.FORECAST, variable="v",
                      provenance=_prov(), supports=supports, authority=w[0], freshness=w[1], spatial=w[2], temporal=w[3],
                      lineage=lineage)
    it.weight = cf.item_weight(*w)
    return it


def test_confidence_components_behave():
    agree = cf.claim_confidence([_item(1, "a"), _item(2, "b"), _item(3, "c")], "CAUTION")
    disagree = cf.claim_confidence([_item(1, "a"), _item(2, "b", False), _item(3, "c", False)], "CAUTION")
    single = cf.claim_confidence([_item(1, "a")], "CAUTION")
    stale = cf.claim_confidence([_item(1, "a", w=(0.9, 0.6, 0.9, 0.9)), _item(2, "b", w=(0.9, 0.6, 0.9, 0.9))], "CAUTION")
    assert agree.value > disagree.value
    assert agree.value > single.value                    # corroboration penalty
    assert agree.value > stale.value                     # freshness matters
    assert 0 <= disagree.value <= 1 and agree.formula


def test_assessment_confidence_uses_completeness_and_coverage():
    c = cf.claim_confidence([_item(1, "a"), _item(2, "b")], None)
    full = cf.assessment_confidence([(c, True)], 1.0, coverage=1.0)
    partial = cf.assessment_confidence([(c, True)], 0.8, coverage=0.5)
    assert partial.value < full.value


def test_spatial_factor_prefers_fine_resolution():
    assert cf.spatial_factor(3, "0.08° (~8 km)") > cf.spatial_factor(3, "0.25° (~28 km)")
    assert cf.spatial_factor(60, "0.25° (~28 km)") < cf.spatial_factor(10, "0.25° (~28 km)")


# ------------------------------------------------------------------------------------------------ conflicts
def test_conflict_detection_decision_relevant():
    fi = _fi("wave_height", src={"A": [2.4], "B": [1.3], "C": [1.7]})
    f = rm.evaluate_factor("wave_height", fi, rm.THRESHOLDS["small_craft"]["wave_height"])
    conf = cx.factor_conflicts([f], {"A": 0.88, "B": 0.9, "C": 0.88}, {"wave_height"})
    assert len(conf) == 1 and conf[0].decision_relevant and conf[0].difference == pytest.approx(1.1)
    assert "no averaging" in conf[0].resolution.lower()


def test_no_conflict_within_tolerance():
    fi = _fi("wave_height", src={"A": [1.0], "B": [1.1]})
    f = rm.evaluate_factor("wave_height", fi, rm.THRESHOLDS["small_craft"]["wave_height"])
    assert cx.factor_conflicts([f], {}, {"wave_height"}) == []


def test_advisory_vs_models_conflict():
    c = cx.advisory_vs_models(RiskLevel.DANGER, "IMD", RiskLevel.NOMINAL, "fishermen advised not to venture")
    assert c and c.decision_relevant
    assert cx.advisory_vs_models(RiskLevel.NOMINAL, "IMD", RiskLevel.CAUTION, "") is None
