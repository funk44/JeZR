import sys
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dateutil import parser

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_WEATHER_CACHE: Dict[Tuple[float, float, str, str], Dict[str, Any]] = {}


def _debug(message: str, enabled: bool) -> None:
    if enabled:
        print(f"Weather: {message}", file=sys.stderr)


def _first_value(activity: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for key in keys:
        value = activity.get(key)
        if value is not None:
            return value
    return None


def _extract_latlng_pair(value: Any) -> Optional[Tuple[float, float]]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return float(value[0]), float(value[1])
        except (TypeError, ValueError):
            return None
    return None


def _extract_latlng(activity: Dict[str, Any], prefix: str) -> Optional[Tuple[float, float]]:
    list_key = f"{prefix}_latlng"
    pair = _extract_latlng_pair(activity.get(list_key))
    if pair:
        return pair
    lat = _first_value(
        activity,
        [
            f"{prefix}_latitude",
            f"{prefix}_lat",
            "latitude",
            "lat",
        ],
    )
    lng = _first_value(
        activity,
        [
            f"{prefix}_longitude",
            f"{prefix}_lng",
            f"{prefix}_lon",
            f"{prefix}_long",  # Intervals.icu uses start_long
            "longitude",
            "lng",
            "lon",
            "long",
        ],
    )
    if lat is None or lng is None:
        return None
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parser.isoparse(str(value))
    except (TypeError, ValueError):
        return None


def _duration_seconds(activity: Dict[str, Any]) -> Optional[float]:
    raw = _first_value(
        activity,
        [
            "elapsed_time",
            "moving_time",
            "duration",
            "elapsed",
            "duration_sec",
            "duration_seconds",
        ],
    )
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _normalize_local(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt


def _nearest_hour_index(times: List[Optional[datetime]], target: datetime) -> Optional[int]:
    if not times:
        return None
    target_local = _normalize_local(target)
    best_idx: Optional[int] = None
    best_diff: Optional[float] = None
    for idx, ts in enumerate(times):
        if ts is None:
            continue
        ts_local = _normalize_local(ts)
        diff = abs((ts_local - target_local).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_idx = idx
    return best_idx


def _fetch_weather_payload(
    base_url: str,
    lat: float,
    lng: float,
    start_date: str,
    end_date: str,
    debug: bool,
) -> Optional[Dict[str, Any]]:
    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "temperature_2m,relativehumidity_2m",
        "timezone": "auto",
    }
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(base_url, params=params)
        response.raise_for_status()
    except Exception as exc:
        _debug(
            f"Open-Meteo request failed ({lat:.3f},{lng:.3f} {start_date}->{end_date}): {exc}",
            debug,
        )
        return None
    data = response.json()
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    rh = hourly.get("relativehumidity_2m") or []
    if not times or not temps or not rh:
        _debug(
            f"Open-Meteo response missing hourly data ({lat:.3f},{lng:.3f} {start_date}->{end_date})",
            debug,
        )
        return None
    parsed_times: List[Optional[datetime]] = []
    for value in times:
        parsed_times.append(_parse_datetime(value))
    return {
        "times": parsed_times,
        "temperature_2m": temps,
        "relativehumidity_2m": rh,
    }


def _fetch_weather(
    lat: float, lng: float, start_date: str, end_date: str, debug: bool
) -> Optional[Dict[str, Any]]:
    key = (round(lat, 3), round(lng, 3), start_date, end_date)
    cached = _WEATHER_CACHE.get(key)
    if cached is not None:
        return cached

    payload = _fetch_weather_payload(
        OPEN_METEO_ARCHIVE_URL, lat, lng, start_date, end_date, debug
    )
    today = date.today().isoformat()
    if payload is None and start_date <= today <= end_date:
        _debug(
            f"Archive missing data for {start_date}->{end_date}; trying forecast endpoint",
            debug,
        )
        payload = _fetch_weather_payload(
            OPEN_METEO_FORECAST_URL, lat, lng, start_date, end_date, debug
        )

    if payload is not None:
        _WEATHER_CACHE[key] = payload
    return payload


def _extract_start_end(activity: Dict[str, Any]) -> Tuple[Optional[datetime], Optional[datetime]]:
    start_dt = _parse_datetime(
        _first_value(activity, ["start_date_local", "start_date", "start_time"])
    )
    end_dt = _parse_datetime(
        _first_value(activity, ["end_date_local", "end_date", "end_time"])
    )
    if end_dt is None and start_dt is not None:
        duration = _duration_seconds(activity)
        if duration is not None:
            end_dt = start_dt + timedelta(seconds=duration)
    return start_dt, end_dt


def enrich_activities_with_weather(
    activities: List[Dict[str, Any]], debug: bool = False
) -> List[Dict[str, Any]]:
    """Enrich a list of Intervals.icu activity dicts with weather data in place.

    For each activity, fetches temperature and humidity from Open-Meteo for the
    start and end of the activity. Adds the following fields to each activity dict:
        wx_temp_start_c, wx_rh_start_pct, wx_temp_end_c, wx_rh_end_pct

    Intervals.icu activities use start_date_local (ISO string), elapsed_time (seconds),
    and lat/lng as start_lat/start_long or start_latlng.

    Args:
        activities: List of Intervals.icu activity dicts (modified in place).
        debug: If True, prints debug messages to stderr.

    Returns:
        The same list with weather fields added where available.
    """
    for activity in activities:
        activity_id = activity.get("id") or activity.get("activity_id")

        start_latlng = _extract_latlng(activity, "start")
        if start_latlng is None:
            _debug(f"Skipping activity {activity_id}: missing lat/lng", debug)
            continue

        start_dt, end_dt = _extract_start_end(activity)
        if start_dt is None:
            _debug(f"Skipping activity {activity_id}: missing start timestamp", debug)
            continue

        if end_dt is None:
            end_dt = start_dt

        start_date = _normalize_local(start_dt).date().isoformat()
        end_date = _normalize_local(end_dt).date().isoformat()
        if end_date < start_date:
            end_date = start_date

        weather = _fetch_weather(
            start_latlng[0],
            start_latlng[1],
            start_date,
            end_date,
            debug,
        )
        if weather is None:
            continue

        times = weather["times"]
        temps = weather["temperature_2m"]
        rhs = weather["relativehumidity_2m"]

        start_idx = _nearest_hour_index(times, start_dt)
        if start_idx is not None and start_idx < len(temps) and start_idx < len(rhs):
            activity["wx_temp_start_c"] = temps[start_idx]
            activity["wx_rh_start_pct"] = rhs[start_idx]

        end_idx = _nearest_hour_index(times, end_dt)
        if end_idx is not None and end_idx < len(temps) and end_idx < len(rhs):
            activity["wx_temp_end_c"] = temps[end_idx]
            activity["wx_rh_end_pct"] = rhs[end_idx]

    return activities
