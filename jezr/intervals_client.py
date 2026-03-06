import random
import time
from typing import Any, Dict, List, Optional

import httpx


class IntervalsClient:
    def __init__(self, api_key: str, athlete_id: int = 0, debug: bool = False) -> None:
        self.api_key = api_key
        self.athlete_id = athlete_id
        self.debug = debug
        self.base_url = "https://intervals.icu/api/v1"
        self._client = httpx.Client(timeout=30)

    def close(self) -> None:
        self._client.close()

    def _auth(self) -> httpx.BasicAuth:
        return httpx.BasicAuth("API_KEY", self.api_key)

    def _maybe_sleep_for_rate_limit(self, headers: Dict[str, str]) -> None:
        remaining = headers.get("X-RateLimit-Remaining")
        limit = headers.get("X-RateLimit-Limit")
        if not remaining or not limit:
            return
        try:
            remaining_val = int(remaining)
            limit_val = int(limit)
        except ValueError:
            return
        if limit_val > 0 and (remaining_val / limit_val) <= 0.1:
            time.sleep(2)

    # Example curl for debugging:
    # curl -u "API_KEY:<INTERVALS_API_KEY>" \
    #   -H "Content-Type: application/json" \
    #   -d '[{"category":"WORKOUT","start_date_local":"2024-07-01T06:00:00","type":"Run","name":"Workout","description":"- 10m 80% Pace","external_id":"planned-run-2024-07-01-workout"}]' \
    #   "https://intervals.icu/api/v1/athlete/0/events/bulk?upsert=true"
    def upsert_events(self, events: List[Dict[str, Any]]) -> None:
        if not events:
            return
        url = f"{self.base_url}/athlete/{self.athlete_id}/events/bulk"
        params = {"upsert": "true"}
        retry_statuses = {429, 500, 502, 503, 504}
        last_exc: Optional[Exception] = None
        for attempt in range(5):
            try:
                resp = self._client.post(
                    url,
                    params=params,
                    auth=self._auth(),
                    json=events,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code in (401, 403):
                    raise RuntimeError(
                        "Intervals.icu auth failed (401/403). "
                        "Check INTERVALS_API_KEY and ensure HTTP Basic auth is supported."
                    )
                if resp.status_code in retry_statuses:
                    sleep_s = min(2 ** attempt, 30) + random.uniform(0, 0.5)
                    time.sleep(sleep_s)
                    continue
                resp.raise_for_status()
                self._maybe_sleep_for_rate_limit(resp.headers)
                return
            except httpx.RequestError as exc:
                last_exc = exc
                sleep_s = min(2 ** attempt, 30) + random.uniform(0, 0.5)
                time.sleep(sleep_s)
        if last_exc:
            raise RuntimeError(f"Network error contacting Intervals.icu: {last_exc}") from last_exc
        raise RuntimeError("Failed to contact Intervals.icu after retries.")

    def list_activities(self, oldest: str, newest: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/athlete/{self.athlete_id}/activities"
        params = {"oldest": oldest, "newest": newest}
        retry_statuses = {429, 500, 502, 503, 504}
        last_exc: Optional[Exception] = None
        for attempt in range(5):
            try:
                resp = self._client.get(url, params=params, auth=self._auth())
                if resp.status_code in (401, 403):
                    raise RuntimeError(
                        "Intervals.icu auth failed (401/403). "
                        "Check INTERVALS_API_KEY and ensure HTTP Basic auth is supported."
                    )
                if resp.status_code in retry_statuses:
                    sleep_s = min(2 ** attempt, 30) + random.uniform(0, 0.5)
                    time.sleep(sleep_s)
                    continue
                resp.raise_for_status()
                self._maybe_sleep_for_rate_limit(resp.headers)
                data = resp.json()
                if not isinstance(data, list):
                    raise RuntimeError("Unexpected Intervals.icu activities response.")
                return data
            except httpx.RequestError as exc:
                last_exc = exc
                sleep_s = min(2 ** attempt, 30) + random.uniform(0, 0.5)
                time.sleep(sleep_s)
        if last_exc:
            raise RuntimeError(f"Network error contacting Intervals.icu: {last_exc}") from last_exc
        raise RuntimeError("Failed to contact Intervals.icu after retries.")

    def list_events(self, after: str, before: str) -> List[Dict[str, Any]]:
        """Fetch planned events from Intervals.icu for the given date range.

        Args:
            after: ISO date string for the start of the range (oldest param).
            before: ISO date string for the end of the range (newest param).

        Returns:
            List of event dicts as returned by the Intervals.icu API.
        """
        url = f"{self.base_url}/athlete/{self.athlete_id}/events"
        params = {"oldest": after, "newest": before}
        retry_statuses = {429, 500, 502, 503, 504}
        last_exc: Optional[Exception] = None
        for attempt in range(5):
            try:
                resp = self._client.get(url, params=params, auth=self._auth())
                if resp.status_code in (401, 403):
                    raise RuntimeError(
                        "Intervals.icu auth failed (401/403). "
                        "Check INTERVALS_API_KEY and ensure HTTP Basic auth is supported."
                    )
                if resp.status_code in retry_statuses:
                    sleep_s = min(2 ** attempt, 30) + random.uniform(0, 0.5)
                    time.sleep(sleep_s)
                    continue
                resp.raise_for_status()
                self._maybe_sleep_for_rate_limit(resp.headers)
                data = resp.json()
                if not isinstance(data, list):
                    raise RuntimeError("Unexpected Intervals.icu events response.")
                return data
            except httpx.RequestError as exc:
                last_exc = exc
                sleep_s = min(2 ** attempt, 30) + random.uniform(0, 0.5)
                time.sleep(sleep_s)
        if last_exc:
            raise RuntimeError(f"Network error contacting Intervals.icu: {last_exc}") from last_exc
        raise RuntimeError("Failed to contact Intervals.icu after retries.")
