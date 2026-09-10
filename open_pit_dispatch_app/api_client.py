# -*- coding: utf-8 -*-
"""Small HTTP client for the desktop dispatch center."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests


API_BASE_URL = os.environ.get(
    "OPENPIT_DASHBOARD_API",
    "http://127.0.0.1:8765",
).rstrip("/")


class ApiClient:
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def get(self, path: str, timeout: float = 1.2) -> Any:
        response = requests.get(
            self.base_url + path,
            timeout=timeout,
            headers={"Cache-Control": "no-cache"},
        )
        response.raise_for_status()
        return response.json()

    def post(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: float = 3.0,
    ) -> Any:
        response = requests.post(
            self.base_url + path,
            json=payload or {},
            timeout=timeout,
        )
        if not response.ok:
            try:
                message = response.json().get("error") or response.text
            except ValueError:
                message = response.text
            raise RuntimeError(message)
        return response.json()

    def state(self) -> Dict[str, Any]:
        return self.get("/api/state")

    def map_data(self) -> Dict[str, Any]:
        return self.get("/api/map", timeout=3.5)

    def scenarios(self) -> Dict[str, Any]:
        return self.get("/api/scenarios")

    def control_status(self) -> Dict[str, Any]:
        return self.get("/api/control/status")

    def generate_random(self, seed: int, mode: str) -> Dict[str, Any]:
        return self.post(
            "/api/control/generate",
            {"seed": int(seed), "mode": str(mode)},
        )

    def start(
        self,
        scenario_id: str,
        seed: Optional[int] = None,
        mode: str = "mixed",
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "scenario_id": str(scenario_id),
            "mode": str(mode),
        }
        if seed is not None:
            payload["seed"] = int(seed)
        return self.post("/api/control/start", payload)

    def stop(self) -> Dict[str, Any]:
        return self.post("/api/control/stop", {})
