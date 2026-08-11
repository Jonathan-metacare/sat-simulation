from __future__ import annotations

import math
from datetime import UTC, datetime

from sgp4.api import Satrec, jday

from sat_simulation.common.models import ScenarioConfig, SpacecraftState

EARTH_RADIUS_KM = 6378.137


def _gmst(datetime_utc: datetime) -> float:
    jd, fraction = jday(
        datetime_utc.year,
        datetime_utc.month,
        datetime_utc.day,
        datetime_utc.hour,
        datetime_utc.minute,
        datetime_utc.second + datetime_utc.microsecond / 1e6,
    )
    days = jd + fraction - 2451545.0
    return math.radians((280.46061837 + 360.98564736629 * days) % 360)


def propagate(config: ScenarioConfig, sampled_at: datetime) -> tuple[float, float, float]:
    sampled_at = sampled_at.astimezone(UTC)
    satellite = Satrec.twoline2rv(config.tle_line1, config.tle_line2)
    jd, fraction = jday(
        sampled_at.year,
        sampled_at.month,
        sampled_at.day,
        sampled_at.hour,
        sampled_at.minute,
        sampled_at.second + sampled_at.microsecond / 1e6,
    )
    error, position, _velocity = satellite.sgp4(jd, fraction)
    if error:
        raise ValueError(f"SGP4 propagation error {error}")
    theta = _gmst(sampled_at)
    x = position[0] * math.cos(theta) + position[1] * math.sin(theta)
    y = -position[0] * math.sin(theta) + position[1] * math.cos(theta)
    z = position[2]
    radius = math.sqrt(x * x + y * y + z * z)
    latitude = math.degrees(math.asin(z / radius))
    longitude = math.degrees(math.atan2(y, x))
    return latitude, longitude, radius - EARTH_RADIUS_KM


def _ecef(latitude: float, longitude: float, radius_km: float) -> tuple[float, float, float]:
    lat = math.radians(latitude)
    lon = math.radians(longitude)
    return (
        radius_km * math.cos(lat) * math.cos(lon),
        radius_km * math.cos(lat) * math.sin(lon),
        radius_km * math.sin(lat),
    )


def elevation_deg(
    sat_lat: float,
    sat_lon: float,
    sat_alt_km: float,
    station_lat: float,
    station_lon: float,
    station_alt_m: float,
) -> float:
    sat = _ecef(sat_lat, sat_lon, EARTH_RADIUS_KM + sat_alt_km)
    station = _ecef(station_lat, station_lon, EARTH_RADIUS_KM + station_alt_m / 1000)
    line = tuple(sat[i] - station[i] for i in range(3))
    zenith_norm = math.sqrt(sum(value * value for value in station))
    line_norm = math.sqrt(sum(value * value for value in line))
    sin_elevation = sum(line[i] * station[i] for i in range(3)) / (line_norm * zenith_norm)
    return math.degrees(math.asin(max(-1, min(1, sin_elevation))))


def target_attitude(
    config: ScenarioConfig,
    sampled_at: datetime,
    target_latitude: float,
    target_longitude: float,
    pointing_error_deg: float = 0.05,
    angular_rate_deg_s: float = 0.0,
) -> SpacecraftState:
    lat, lon, altitude = propagate(config, sampled_at)
    yaw = ((target_longitude - lon + 180) % 360) - 180
    pitch = max(-60.0, min(60.0, target_latitude - lat))
    roll = max(-35.0, min(35.0, yaw * 0.25))
    cy, sy = math.cos(math.radians(yaw) / 2), math.sin(math.radians(yaw) / 2)
    cp, sp = math.cos(math.radians(pitch) / 2), math.sin(math.radians(pitch) / 2)
    cr, sr = math.cos(math.radians(roll) / 2), math.sin(math.radians(roll) / 2)
    quaternion = (
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    )
    elevation = elevation_deg(
        lat,
        lon,
        altitude,
        config.ground_station_latitude,
        config.ground_station_longitude,
        config.ground_station_altitude_m,
    )
    return SpacecraftState(
        sampled_at=sampled_at,
        latitude=lat,
        longitude=lon,
        altitude_km=altitude,
        yaw_deg=yaw,
        pitch_deg=pitch,
        roll_deg=roll,
        quaternion_wxyz=quaternion,
        angular_rate_deg_s=angular_rate_deg_s,
        pointing_error_deg=pointing_error_deg,
        in_contact=config.deterministic_contact or elevation >= 5,
    )
