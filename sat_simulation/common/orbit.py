from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from sgp4.api import Satrec, jday

from sat_simulation.common.models import (
    ContactWindow,
    OrbitSample,
    OrbitTrack,
    PlannedWindows,
    ScenarioConfig,
    SpacecraftState,
)

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


def _propagate_satellite(satellite: Satrec, sampled_at: datetime) -> tuple[float, float, float]:
    sampled_at = sampled_at.astimezone(UTC)
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


def propagate(config: ScenarioConfig, sampled_at: datetime) -> tuple[float, float, float]:
    satellite = Satrec.twoline2rv(config.tle_line1, config.tle_line2)
    return _propagate_satellite(satellite, sampled_at)


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


def visibility_radius_m(altitude_km: float, minimum_elevation_deg: float = 5) -> float:
    elevation = math.radians(minimum_elevation_deg)
    orbital_radius = EARTH_RADIUS_KM + altitude_km
    central_angle = math.acos(EARTH_RADIUS_KM / orbital_radius * math.cos(elevation)) - elevation
    return EARTH_RADIUS_KM * central_angle * 1000


def orbit_track(
    config: ScenarioConfig,
    center: datetime,
    *,
    history_minutes: int = 20,
    forecast_minutes: int = 80,
    pass_horizon_minutes: int = 24 * 60,
    step_seconds: int = 30,
    minimum_elevation_deg: float = 5,
) -> OrbitTrack:
    """Build a deterministic SGP4 ground track and geometric contact forecast."""
    satellite = Satrec.twoline2rv(config.tle_line1, config.tle_line2)

    def sample(sampled_at: datetime) -> OrbitSample:
        latitude, longitude, altitude = _propagate_satellite(satellite, sampled_at)
        elevation = elevation_deg(
            latitude,
            longitude,
            altitude,
            config.ground_station_latitude,
            config.ground_station_longitude,
            config.ground_station_altitude_m,
        )
        return OrbitSample(
            sampled_at=sampled_at,
            latitude=latitude,
            longitude=longitude,
            altitude_km=altitude,
            elevation_deg=elevation,
            visible=elevation >= minimum_elevation_deg,
        )

    center = center.astimezone(UTC)
    history = [
        sample(center - timedelta(seconds=offset))
        for offset in range(history_minutes * 60, 0, -step_seconds)
    ]
    current = sample(center)
    forecast = [
        sample(center + timedelta(seconds=offset))
        for offset in range(step_seconds, forecast_minutes * 60 + 1, step_seconds)
    ]

    windows: list[ContactWindow] = []
    scan_start = center - timedelta(minutes=history_minutes)
    scan_end = center + timedelta(minutes=pass_horizon_minutes)
    active_start: datetime | None = None
    maximum: OrbitSample | None = None
    sampled_at = scan_start
    while sampled_at <= scan_end:
        value = sample(sampled_at)
        if value.visible:
            if active_start is None:
                active_start = sampled_at
                maximum = value
            elif maximum is None or value.elevation_deg > maximum.elevation_deg:
                maximum = value
        elif active_start is not None and maximum is not None:
            windows.append(
                ContactWindow(
                    aos=active_start,
                    los=sampled_at,
                    max_elevation_at=maximum.sampled_at,
                    max_elevation_deg=maximum.elevation_deg,
                )
            )
            active_start = None
            maximum = None
        sampled_at += timedelta(seconds=step_seconds)
    if active_start is not None and maximum is not None:
        windows.append(
            ContactWindow(
                aos=active_start,
                los=scan_end,
                max_elevation_at=maximum.sampled_at,
                max_elevation_deg=maximum.elevation_deg,
            )
        )

    relevant_windows = [window for window in windows if window.los >= center][:3]
    return OrbitTrack(
        generated_at=center,
        satellite_name=config.satellite_name,
        ground_station_name=config.ground_station_name,
        minimum_elevation_deg=minimum_elevation_deg,
        visibility_radius_m=visibility_radius_m(current.altitude_km, minimum_elevation_deg),
        contact_mode="deterministic" if config.deterministic_contact else "geometric",
        current=current,
        history=history,
        forecast=forecast,
        contact_windows=relevant_windows,
    )


def plan_mission_windows(
    config: ScenarioConfig,
    start: datetime,
    *,
    horizon_hours: int = 48,
    step_seconds: int = 20,
    minimum_elevation_deg: float = 5,
) -> PlannedWindows:
    """Freeze the three real SGP4 windows used by a stepwise mission.

    The capture target is the sub-satellite point after the first Beijing LOS,
    so it is spatially and temporally distinct from the uplink pass.
    """
    satellite = Satrec.twoline2rv(config.tle_line1, config.tle_line2)
    start = start.astimezone(UTC)
    end = start + timedelta(hours=horizon_hours)
    windows: list[ContactWindow] = []
    active_start: datetime | None = None
    maximum_at: datetime | None = None
    maximum_elevation = -90.0
    sampled_at = start
    skip_partial_window = True
    while sampled_at <= end:
        lat, lon, altitude = _propagate_satellite(satellite, sampled_at)
        elevation = elevation_deg(
            lat,
            lon,
            altitude,
            config.ground_station_latitude,
            config.ground_station_longitude,
            config.ground_station_altitude_m,
        )
        visible = elevation >= minimum_elevation_deg
        if skip_partial_window:
            if not visible:
                skip_partial_window = False
            sampled_at += timedelta(seconds=step_seconds)
            continue
        if visible:
            if active_start is None:
                active_start = sampled_at
                maximum_at = sampled_at
                maximum_elevation = elevation
            elif elevation > maximum_elevation:
                maximum_at = sampled_at
                maximum_elevation = elevation
        elif active_start is not None and maximum_at is not None:
            windows.append(
                ContactWindow(
                    aos=active_start,
                    los=sampled_at,
                    max_elevation_at=maximum_at,
                    max_elevation_deg=maximum_elevation,
                )
            )
            active_start = None
            maximum_at = None
            maximum_elevation = -90.0
        sampled_at += timedelta(seconds=step_seconds)

    if len(windows) < 2:
        raise ValueError("未来 48 小时内未找到两次北京站几何可见窗口")

    uplink = windows[0]
    capture_at = uplink.los + timedelta(minutes=15)
    target_lat, target_lon, _ = _propagate_satellite(satellite, capture_at)
    capture = ContactWindow(
        aos=capture_at - timedelta(seconds=60),
        los=capture_at + timedelta(seconds=60),
        max_elevation_at=capture_at,
        max_elevation_deg=90.0,
    )
    downlink = next((window for window in windows[1:] if window.aos > capture.los), None)
    if downlink is None:
        raise ValueError("未来 48 小时内未找到拍摄后的北京站可见窗口")
    return PlannedWindows(
        uplink=uplink,
        capture=capture,
        downlink=downlink,
        target_name=f"自动目标 {target_lat:.2f}°, {target_lon:.2f}°",
        target_latitude=target_lat,
        target_longitude=target_lon,
        tle_line1=config.tle_line1,
        tle_line2=config.tle_line2,
        minimum_elevation_deg=minimum_elevation_deg,
    )


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
