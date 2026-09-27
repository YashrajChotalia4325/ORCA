"""Unit normalisation. ORCA's canonical units:

temperature  °C        wind / current speed  km/h (knots shown alongside)
wave height  m         distance              km (nautical miles shown alongside)
pressure     hPa       precipitation         mm/h
coordinates  WGS84 decimal degrees
"""
from __future__ import annotations

KMH_PER_KNOT = 1.852
KM_PER_NM = 1.852
MS_TO_KMH = 3.6

CANONICAL = {
    "wind_speed": "km/h", "wind_gusts": "km/h", "current_speed": "km/h",
    "wave_height": "m", "swell_height": "m", "wind_wave_height": "m",
    "sst": "°C", "sst_anomaly": "°C", "chlorophyll": "mg/m³",
    "precipitation": "mm/h", "pressure": "hPa", "cape": "J/kg",
    "visibility": "km", "depth": "m", "distance": "km",
    "wave_period": "s", "direction": "°",
}

_ALIASES = {
    "km/h": "km/h", "kmh": "km/h", "kph": "km/h",
    "m/s": "m/s", "ms-1": "m/s", "m s-1": "m/s",
    "kn": "kn", "knots": "kn", "kt": "kn",
    "°c": "°C", "degree_c": "°C", "degc": "°C", "celsius": "°C", "c": "°C",
    "k": "K", "kelvin": "K",
    "m": "m", "ft": "ft", "km": "km", "nm": "nm", "nmi": "nm",
    "mm": "mm/h", "mm/h": "mm/h", "hpa": "hPa", "pa": "Pa",
    "mg m^-3": "mg/m³", "mg/m3": "mg/m³", "mg/m³": "mg/m³",
    "j/kg": "J/kg", "°": "°", "deg": "°", "s": "s",
}


class UnitError(ValueError):
    pass


def norm_unit(u: str) -> str:
    return _ALIASES.get((u or "").strip().lower(), u)


def convert(value: float | None, from_unit: str, to_unit: str) -> float | None:
    if value is None:
        return None
    f, t = norm_unit(from_unit), norm_unit(to_unit)
    if f == t:
        return value
    table = {
        ("m/s", "km/h"): lambda v: v * MS_TO_KMH,
        ("km/h", "m/s"): lambda v: v / MS_TO_KMH,
        ("kn", "km/h"): lambda v: v * KMH_PER_KNOT,
        ("km/h", "kn"): lambda v: v / KMH_PER_KNOT,
        ("m/s", "kn"): lambda v: v * MS_TO_KMH / KMH_PER_KNOT,
        ("K", "°C"): lambda v: v - 273.15,
        ("°C", "K"): lambda v: v + 273.15,
        ("ft", "m"): lambda v: v * 0.3048,
        ("m", "ft"): lambda v: v / 0.3048,
        ("km", "nm"): lambda v: v / KM_PER_NM,
        ("nm", "km"): lambda v: v * KM_PER_NM,
        ("m", "km"): lambda v: v / 1000.0,
        ("km", "m"): lambda v: v * 1000.0,
        ("Pa", "hPa"): lambda v: v / 100.0,
    }
    fn = table.get((f, t))
    if fn is None:
        raise UnitError(f"cannot convert {from_unit!r} to {to_unit!r}")
    return fn(value)


def assert_comparable(u1: str, u2: str) -> None:
    if norm_unit(u1) != norm_unit(u2):
        raise UnitError(f"incompatible units {u1!r} vs {u2!r}; normalise before comparing")


def kmh_to_kn(v: float | None) -> float | None:
    return None if v is None else v / KMH_PER_KNOT


def km_to_nm(v: float | None) -> float | None:
    return None if v is None else v / KM_PER_NM


def fmt(value: float | None, units: str, nd: int = 1) -> str:
    if value is None:
        return "n/a"
    u = norm_unit(units)
    if u == "km/h":
        return f"{value:.0f} km/h ({value / KMH_PER_KNOT:.0f} kn)"
    if u == "km":
        return f"{value:.1f} km ({value / KM_PER_NM:.1f} nm)"
    return f"{value:.{nd}f} {units}".strip()
