"""Solar position (NOAA) and what it means for looking at a storm."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

BACKLIT_DEG = 35.0
FRONTLIT_DEG = 115.0
CIVIL_TWILIGHT_DEG = -6.0
LOW_SUN_DEG = 8.0


@dataclass(frozen=True)
class SolarPosition:
    """Where the sun is: compass azimuth and elevation above the horizon."""

    azimuth_deg: float
    elevation_deg: float


def _julian_day(when: datetime) -> float:
    y, m = when.year, when.month
    day = when.day + (when.hour + when.minute / 60.0 + when.second / 3600.0) / 24.0
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + day + b - 1524.5


def solar_position(when: datetime, lon: float, lat: float) -> SolarPosition:
    """Sun azimuth (degrees clockwise from N) and elevation for a UTC instant."""
    jc = (_julian_day(when) - 2451545.0) / 36525.0

    mean_long = (280.46646 + jc * (36000.76983 + jc * 0.0003032)) % 360.0
    mean_anom = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    eccent = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)

    ma = math.radians(mean_anom)
    center = (
        math.sin(ma) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
        + math.sin(2 * ma) * (0.019993 - 0.000101 * jc)
        + math.sin(3 * ma) * 0.000289
    )
    true_long = mean_long + center
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))

    secs = 21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813))
    mean_obliq = 23.0 + (26.0 + secs / 60.0) / 60.0
    obliq = math.radians(mean_obliq + 0.00256 * math.cos(math.radians(omega)))

    decl = math.asin(math.sin(obliq) * math.sin(math.radians(app_long)))

    y = math.tan(obliq / 2.0) ** 2
    ml = math.radians(mean_long)
    eq_time = 4.0 * math.degrees(
        y * math.sin(2 * ml)
        - 2 * eccent * math.sin(ma)
        + 4 * eccent * y * math.sin(ma) * math.cos(2 * ml)
        - 0.5 * y * y * math.sin(4 * ml)
        - 1.25 * eccent * eccent * math.sin(2 * ma)
    )

    minutes = when.hour * 60.0 + when.minute + when.second / 60.0
    true_solar_min = (minutes + eq_time + 4.0 * lon) % 1440.0
    hour_angle = true_solar_min / 4.0 - 180.0

    lat_r = math.radians(lat)
    ha = math.radians(hour_angle)
    cos_zen = math.sin(lat_r) * math.sin(decl) + math.cos(lat_r) * math.cos(decl) * math.cos(ha)
    cos_zen = max(-1.0, min(1.0, cos_zen))
    zenith = math.acos(cos_zen)
    elevation = 90.0 - math.degrees(zenith)

    sin_zen = math.sin(zenith)
    if abs(sin_zen) < 1e-9 or abs(math.cos(lat_r)) < 1e-9:
        azimuth = 180.0
    else:
        raw = (math.sin(lat_r) * cos_zen - math.sin(decl)) / (math.cos(lat_r) * sin_zen)
        raw = max(-1.0, min(1.0, raw))
        acos_deg = math.degrees(math.acos(raw))
        azimuth = (acos_deg + 180.0) % 360.0 if hour_angle > 0 else (540.0 - acos_deg) % 360.0

    return SolarPosition(azimuth_deg=round(azimuth, 1), elevation_deg=round(elevation, 1))


def light_regime(sun: SolarPosition, view_bearing_deg: float) -> str:
    """How the storm is lit when looked at along `view_bearing_deg`."""
    if sun.elevation_deg < CIVIL_TWILIGHT_DEG:
        return "notte"
    if sun.elevation_deg < 0.0:
        return "crepuscolo"
    delta = abs((view_bearing_deg - sun.azimuth_deg + 180.0) % 360.0 - 180.0)
    if delta <= BACKLIT_DEG:
        return "controluce"
    if delta >= FRONTLIT_DEG:
        return "illuminata"
    return "laterale"


def regime_text(regime: str, sun: SolarPosition) -> str:
    """One line a navigator can read out loud."""
    if regime == "notte":
        return "buio, struttura non visibile ma ottimo per i fulmini"
    if regime == "crepuscolo":
        return "crepuscolo, luce in rapido calo"
    if regime == "controluce":
        return f"cella controluce, sole a {sun.azimuth_deg:.0f}° dietro il target"
    if regime == "illuminata":
        if sun.elevation_deg <= LOW_SUN_DEG:
            return "cella illuminata con sole basso, luce migliore della giornata"
        return "cella illuminata di fronte, sole alle spalle"
    return "luce laterale sulla cella"
