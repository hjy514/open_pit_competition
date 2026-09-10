"""Minimal CARLA 0.9.10 adapter for mine-truck safety-rule validation.

Responsibilities:
- locate/import CARLA 0.9.10 PythonAPI
- connect to CARLA
- optionally load/check map
- spawn mine trucks
- create BasicAgent navigation
- convert CARLA actors to VehicleSnapshot
- execute VehicleBehavior
- apply target speed and safety brake override
- stop vehicles
- safely release BasicAgent / LocalPlanner
- destroy actors created by this adapter

This module intentionally does NOT contain:
- scenario business logic
- scheduling
- task reassignment
- closed-loop optimization
- database logic
"""

from __future__ import annotations

import glob
import math
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from .vehicle_behavior import (
    BehaviorContext,
    DrivingDecision,
    VehicleBehavior,
    VehicleSnapshot,
)


class CarlaAdapterError(RuntimeError):
    """Raised when CARLA cannot satisfy a requested operation."""


class CarlaAdapter:
    """Small CARLA execution layer used by the competition project."""

    def __init__(
        self,
        carla_root: str,
        host: str = "127.0.0.1",
        port: int = 2000,
        timeout_seconds: float = 10.0,
        map_name: Optional[str] = None,
        load_map: bool = False,
        behavior: Optional[VehicleBehavior] = None,
    ) -> None:

        self.carla_root = str(carla_root)
        self.host = str(host)
        self.port = int(port)
        self.timeout_seconds = float(timeout_seconds)

        self.map_name = (
            str(map_name)
            if map_name
            else None
        )

        self.load_map = bool(load_map)

        self.behavior = (
            behavior
            if behavior is not None
            else VehicleBehavior()
        )

        self.carla = None
        self.client = None
        self.world = None

        self._basic_agent_class = None

        self._actors: Dict[str, object] = {}
        self._agents: Dict[str, object] = {}

        self._cruise_speeds_kmh: Dict[str, float] = {}

        self._healthy: Dict[str, bool] = {}
        self._available: Dict[str, bool] = {}

        # Only these actors may be destroyed by destroy_spawned_vehicles().
        self._owned_vehicle_ids = set()

        self._carla_api_root = None
        self._carla_egg_path = None

        # Closed Loop V1.1 explicit route-execution cache.
        self._global_route_planner = None
        self._global_route_planner_resolution_m = None
        self._active_route_ids: Dict[str, str] = {}
        self._active_route_end_xyz: Dict[str, tuple] = {}
        self._active_route_total_waypoints: Dict[str, int] = {}
        self._active_route_traces: Dict[str, list] = {}
        self._active_route_specs: Dict[str, dict] = {}
        self._last_driving_decisions: Dict[str, DrivingDecision] = {}


    # ============================================================
    # CARLA connection
    # ============================================================

    def connect(self) -> None:
        """Import CARLA PythonAPI and connect to the server."""

        self._import_carla()

        try:

            self.client = self.carla.Client(
                self.host,
                self.port,
            )

            self.client.set_timeout(
                self.timeout_seconds
            )

            if (
                self.load_map
                and self.map_name
            ):

                print(
                    "[CARLA] loading map: {}".format(
                        self.map_name
                    )
                )

                self.world = self.client.load_world(
                    self.map_name
                )

            else:

                self.world = self.client.get_world()

        except RuntimeError as exc:

            raise CarlaAdapterError(
                "Unable to connect to CARLA at {}:{}: {}".format(
                    self.host,
                    self.port,
                    exc,
                )
            ) from exc


        if self.world is None:

            raise CarlaAdapterError(
                "CARLA returned no world"
            )


        try:

            current_map = (
                self.world
                .get_map()
                .name
                .split("/")[-1]
            )

        except RuntimeError as exc:

            raise CarlaAdapterError(
                "Failed to read current CARLA map: {}".format(
                    exc
                )
            ) from exc


        if (
            self.map_name
            and current_map != self.map_name
        ):

            raise CarlaAdapterError(
                "Current CARLA map is '{}', expected '{}'. "
                "Start the expected map or use --load-map.".format(
                    current_map,
                    self.map_name,
                )
            )


        print(
            "[CARLA] connected: {}:{} | map={}".format(
                self.host,
                self.port,
                current_map,
            )
        )


    # ============================================================
    # Vehicle creation
    # ============================================================

    def spawn_vehicle(
        self,
        vehicle_id: str,
        spawn_point_index: int,
        blueprint_id: str = "vehicle.cat.cat",
        role_name: Optional[str] = None,
        allow_spawn_fallback: bool = False,
    ):
        """Spawn one CARLA vehicle at a configured spawn point."""

        self._require_connected()

        vehicle_id = str(
            vehicle_id
        )


        if vehicle_id in self._actors:

            raise CarlaAdapterError(
                "Vehicle already exists: {}".format(
                    vehicle_id
                )
            )


        spawn_points = (
            self.world
            .get_map()
            .get_spawn_points()
        )


        if not spawn_points:

            raise CarlaAdapterError(
                "Current CARLA map has no spawn points"
            )


        preferred_index = int(
            spawn_point_index
        )


        if not (
            0 <= preferred_index < len(spawn_points)
        ):

            raise CarlaAdapterError(
                "Spawn point {} is out of range 0..{}".format(
                    preferred_index,
                    len(spawn_points) - 1,
                )
            )


        blueprint = self._get_blueprint(
            blueprint_id
        )


        if blueprint.has_attribute(
            "role_name"
        ):

            blueprint.set_attribute(
                "role_name",
                role_name or vehicle_id,
            )


        candidate_indices = [
            preferred_index
        ]


        if allow_spawn_fallback:

            candidate_indices.extend(

                index

                for index in range(
                    len(spawn_points)
                )

                if index != preferred_index
            )


        actor = None
        selected_index = None


        for index in candidate_indices:

            try:

                actor = self.world.try_spawn_actor(
                    blueprint,
                    spawn_points[index],
                )

            except RuntimeError:

                actor = None


            if actor is not None:

                selected_index = index
                break


        if actor is None:

            raise CarlaAdapterError(
                "Failed to spawn '{}' at spawn point {}".format(
                    vehicle_id,
                    preferred_index,
                )
            )


        self._actors[
            vehicle_id
        ] = actor

        self._owned_vehicle_ids.add(
            vehicle_id
        )

        self._healthy[
            vehicle_id
        ] = True

        self._available[
            vehicle_id
        ] = True


        print(
            "[CARLA] spawned {} | actor={} | spawn={}".format(
                vehicle_id,
                actor.id,
                selected_index,
            )
        )


        return actor


    # ============================================================
    # Navigation
    # ============================================================

    def set_destination(
        self,
        vehicle_id: str,
        destination_xyz: Sequence[float],
        target_speed_kmh: float,
    ) -> None:
        """Assign one BasicAgent navigation destination."""

        self._require_connected()

        actor = self._actor(
            vehicle_id
        )


        if len(destination_xyz) != 3:

            raise ValueError(
                "destination_xyz must contain exactly x, y, z"
            )


        # A vehicle may have only one active LocalPlanner.
        #
        # CARLA 0.9.10 LocalPlanner.__del__() destroys its bound vehicle,
        # therefore the old planner must be detached first.
        if vehicle_id in self._agents:

            self._release_agent(
                vehicle_id
            )


        target_speed_kmh = max(
            0.0,
            float(target_speed_kmh),
        )


        try:

            agent = self._basic_agent_class(
                actor,
                target_speed=
                    target_speed_kmh,
            )

            # Register before route construction.
            self._agents[
                vehicle_id
            ] = agent


            destination = [

                float(
                    destination_xyz[0]
                ),

                float(
                    destination_xyz[1]
                ),

                float(
                    destination_xyz[2]
                ),
            ]


            # CARLA 0.9.10 BasicAgent expects [x, y, z].
            agent.set_destination(
                destination
            )


            planner = self._local_planner_for(
                agent
            )


            if planner is None:

                raise CarlaAdapterError(
                    "BasicAgent has no LocalPlanner"
                )


            set_speed = getattr(
                planner,
                "set_speed",
                None,
            )


            if callable(set_speed):

                set_speed(
                    target_speed_kmh
                )


            self._cruise_speeds_kmh[
                vehicle_id
            ] = target_speed_kmh

            self._active_route_ids.pop(
                vehicle_id,
                None,
            )
            self._active_route_end_xyz.pop(
                vehicle_id,
                None,
            )
            self._active_route_total_waypoints.pop(
                vehicle_id,
                None,
            )
            self._active_route_traces.pop(
                vehicle_id,
                None,
            )
            self._active_route_specs.pop(
                vehicle_id,
                None,
            )


            print(
                "[CARLA] destination set "
                "{} -> ({:.2f}, {:.2f}, {:.2f}) "
                "| cruise={:.1f} km/h".format(
                    vehicle_id,
                    destination[0],
                    destination[1],
                    destination[2],
                    target_speed_kmh,
                )
            )


        except Exception as exc:

            self._release_agent(
                vehicle_id
            )

            raise CarlaAdapterError(
                "Failed to initialize BasicAgent for '{}': {}".format(
                    vehicle_id,
                    exc,
                )
            ) from exc


    def set_destination_spawn_point(
        self,
        vehicle_id: str,
        spawn_point_index: int,
        target_speed_kmh: float,
    ) -> None:
        """Set destination using a map spawn-point index."""

        self._require_connected()

        spawn_points = (
            self.world
            .get_map()
            .get_spawn_points()
        )


        index = int(
            spawn_point_index
        )


        if not (
            0 <= index < len(spawn_points)
        ):

            raise CarlaAdapterError(
                "Destination spawn point {} is out of range 0..{}".format(
                    index,
                    len(spawn_points) - 1,
                )
            )


        location = (
            spawn_points[index]
            .location
        )


        self.set_destination(

            vehicle_id=vehicle_id,

            destination_xyz=(
                location.x,
                location.y,
                location.z,
            ),

            target_speed_kmh=
                target_speed_kmh,
        )


    def set_route_spawn_points(
        self,
        vehicle_id: str,
        route_id: str,
        from_spawn_point_index: int,
        to_spawn_point_index: int,
        target_speed_kmh: float,
        sampling_resolution_m: float = 2.0,
        expected_distance_m: Optional[float] = None,
        distance_tolerance_ratio: float = 0.08,
        route_start_tolerance_m: float = 30.0,
        skip_ahead_waypoints: int = 2,
    ) -> None:
        """Execute one Decision-selected OD route with CARLA GlobalRoutePlanner.

        The matrix stores the selected OD pair and precomputed route distance.
        This method rebuilds that OD trace with the same sampling resolution,
        verifies the distance, trims the already-passed prefix nearest the CAT,
        and injects the trace directly into LocalPlanner.set_global_plan().
        """

        self._require_connected()
        actor = self._actor(vehicle_id)

        spawn_points = self.world.get_map().get_spawn_points()
        from_index = int(from_spawn_point_index)
        to_index = int(to_spawn_point_index)

        for index, label in ((from_index, "route start"), (to_index, "route end")):
            if not (0 <= index < len(spawn_points)):
                raise CarlaAdapterError(
                    "{} spawn point {} is out of range 0..{}".format(
                        label, index, len(spawn_points) - 1
                    )
                )

        resolution = max(0.5, float(sampling_resolution_m))
        planner = self._global_route_planner_for(resolution)

        try:
            route = planner.trace_route(
                spawn_points[from_index].location,
                spawn_points[to_index].location,
            )
        except Exception as exc:
            raise CarlaAdapterError(
                "Failed to trace selected route '{}': {}".format(route_id, exc)
            ) from exc

        if not route:
            raise CarlaAdapterError(
                "Selected route '{}' produced an empty CARLA trace".format(route_id)
            )

        full_distance_m = self._route_trace_distance(route)

        if expected_distance_m is not None:
            expected = max(0.0, float(expected_distance_m))
            tolerance = max(
                5.0,
                expected * max(0.0, float(distance_tolerance_ratio)),
            )
            error = abs(full_distance_m - expected)
            if error > tolerance:
                raise CarlaAdapterError(
                    "Selected route '{}' no longer matches matrix: "
                    "matrix={:.1f}m runtime={:.1f}m error={:.1f}m "
                    "(tolerance={:.1f}m)".format(
                        route_id, expected, full_distance_m, error, tolerance
                    )
                )

        actor_location = actor.get_location()
        nearest_index = 0
        nearest_distance = float("inf")
        for index, item in enumerate(route):
            location = item[0].transform.location
            distance = self._location_distance(actor_location, location)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_index = index

        if nearest_distance > max(1.0, float(route_start_tolerance_m)):
            raise CarlaAdapterError(
                "Vehicle '{}' is {:.1f}m away from selected route '{}' "
                "near its logical start {}. Refusing a forced turn-back.".format(
                    vehicle_id, nearest_distance, route_id, from_index
                )
            )

        start_index = min(
            len(route) - 1,
            nearest_index + max(0, int(skip_ahead_waypoints)),
        )
        active_route = route[start_index:]
        if len(active_route) < 2:
            active_route = route[max(0, len(route) - 2):]

        if vehicle_id in self._agents:
            self._release_agent(vehicle_id)

        target_speed_kmh = max(0.0, float(target_speed_kmh))
        try:
            agent = self._basic_agent_class(actor, target_speed=target_speed_kmh)
            self._agents[vehicle_id] = agent

            local_planner = self._local_planner_for(agent)
            if local_planner is None:
                raise CarlaAdapterError("BasicAgent has no LocalPlanner")

            setter = getattr(local_planner, "set_global_plan", None)
            if not callable(setter):
                raise CarlaAdapterError("CARLA LocalPlanner has no set_global_plan()")
            # CARLA 0.9.10/0.9.11 LocalPlanner APIs differ from newer
            # versions.  Explicitly clear any stale buffered waypoints before
            # installing the Decision route, then mark the planner as being
            # under a global plan so it cannot append random waypoints after
            # the selected route.
            waypoint_buffer = getattr(
                local_planner,
                "_waypoint_buffer",
                None,
            )
            if waypoint_buffer is not None:
                clear_buffer = getattr(waypoint_buffer, "clear", None)
                if callable(clear_buffer):
                    clear_buffer()

            setter(active_route)

            if hasattr(local_planner, "_stop_waypoint_creation"):
                try:
                    local_planner._stop_waypoint_creation = True
                except Exception:
                    pass

            if hasattr(local_planner, "_global_plan"):
                try:
                    local_planner._global_plan = True
                except Exception:
                    pass

            set_speed = getattr(local_planner, "set_speed", None)
            if callable(set_speed):
                set_speed(target_speed_kmh)

            self._cruise_speeds_kmh[vehicle_id] = target_speed_kmh
            self._active_route_ids[vehicle_id] = str(route_id)

            final_location = route[-1][0].transform.location
            self._active_route_end_xyz[vehicle_id] = (
                float(final_location.x),
                float(final_location.y),
                float(final_location.z),
            )
            self._active_route_total_waypoints[vehicle_id] = len(active_route)
            self._active_route_traces[vehicle_id] = list(route)
            self._active_route_specs[vehicle_id] = {
                "route_id": str(route_id),
                "from_spawn_point_index": from_index,
                "to_spawn_point_index": to_index,
                "target_speed_kmh": target_speed_kmh,
                "sampling_resolution_m": resolution,
                "expected_distance_m": (
                    None
                    if expected_distance_m is None
                    else float(expected_distance_m)
                ),
                "distance_tolerance_ratio": float(distance_tolerance_ratio),
                "route_start_tolerance_m": float(route_start_tolerance_m),
                "skip_ahead_waypoints": int(skip_ahead_waypoints),
            }

            print(
                "[CARLA] route set {} | {} | {}->{} | "
                "matrix={:.1f}m runtime={:.1f}m | wp={}/{} | "
                "start_gap={:.1f}m | cruise={:.1f} km/h".format(
                    vehicle_id,
                    route_id,
                    from_index,
                    to_index,
                    float(expected_distance_m) if expected_distance_m is not None else full_distance_m,
                    full_distance_m,
                    len(active_route),
                    len(route),
                    nearest_distance,
                    target_speed_kmh,
                )
            )
        except Exception as exc:
            self._release_agent(vehicle_id)
            self._active_route_ids.pop(vehicle_id, None)
            self._active_route_end_xyz.pop(vehicle_id, None)
            self._active_route_total_waypoints.pop(vehicle_id, None)
            self._active_route_traces.pop(vehicle_id, None)
            self._active_route_specs.pop(vehicle_id, None)
            if isinstance(exc, CarlaAdapterError):
                raise
            raise CarlaAdapterError(
                "Failed to activate selected route '{}' for '{}': {}".format(
                    route_id, vehicle_id, exc
                )
            ) from exc

    def _global_route_planner_for(self, sampling_resolution_m: float):
        resolution = float(sampling_resolution_m)
        if (
            self._global_route_planner is not None
            and self._global_route_planner_resolution_m is not None
            and abs(self._global_route_planner_resolution_m - resolution) <= 1e-9
        ):
            return self._global_route_planner

        try:
            from agents.navigation.global_route_planner import GlobalRoutePlanner
            from agents.navigation.global_route_planner_dao import GlobalRoutePlannerDAO

            dao = GlobalRoutePlannerDAO(self.world.get_map(), resolution)
            planner = GlobalRoutePlanner(dao)
            planner.setup()
        except Exception as exc:
            raise CarlaAdapterError(
                "Unable to initialize GlobalRoutePlanner at {:.2f}m: {}".format(
                    resolution, exc
                )
            ) from exc

        self._global_route_planner = planner
        self._global_route_planner_resolution_m = resolution
        return planner

    @staticmethod
    def _location_distance(a, b) -> float:
        dx = float(a.x) - float(b.x)
        dy = float(a.y) - float(b.y)
        dz = float(a.z) - float(b.z)
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    @classmethod
    def _route_trace_distance(cls, route) -> float:
        if not route:
            return 0.0
        locations = [item[0].transform.location for item in route]
        return sum(
            cls._location_distance(locations[index - 1], locations[index])
            for index in range(1, len(locations))
        )


    @classmethod
    def _route_forward_index(
        cls,
        route,
        start_index: int,
        forward_distance_m: float,
    ) -> int:
        """Pick a route index at least forward_distance_m ahead."""

        if not route:
            return 0

        start = max(
            0,
            min(
                int(start_index),
                len(route) - 1,
            ),
        )
        target_distance = max(
            0.0,
            float(forward_distance_m),
        )
        if target_distance <= 1e-6:
            return start

        travelled = 0.0
        previous = route[start][0].transform.location

        for index in range(start + 1, len(route)):
            current = route[index][0].transform.location
            travelled += cls._location_distance(
                previous,
                current,
            )
            if travelled >= target_distance:
                return index
            previous = current

        return len(route) - 1


    def _controlled_clearance_at(
        self,
        vehicle_id: str,
        location,
    ) -> float:
        """Nearest other controlled CAT center distance."""

        nearest = float("inf")

        for other_id, other_actor in self._actors.items():
            if other_id == vehicle_id:
                continue

            try:
                other_location = other_actor.get_location()
            except Exception:
                continue

            nearest = min(
                nearest,
                self._location_distance(
                    location,
                    other_location,
                ),
            )

        return nearest


    def recover_stalled_route(
        self,
        vehicle_id: str,
        forward_distance_m: float = 18.0,
        z_offset_m: float = 0.5,
        clearance_m: float = 12.0,
        max_extra_forward_m: float = 30.0,
    ) -> Dict[str, object]:
        """Recover a physically stalled CAT on its current selected route.

        Recovery is deliberately bounded:
        - only works for an already-active explicit Decision route;
        - finds the CAT's nearest point on that same route;
        - relocates a short distance forward on that route;
        - refuses a target occupied by another controlled CAT;
        - re-installs the exact same Decision OD route afterwards.

        This method does not alter Decision assignments or task state.
        """

        self._require_connected()
        actor = self._actor(vehicle_id)

        route = self._active_route_traces.get(vehicle_id)
        spec = self._active_route_specs.get(vehicle_id)

        if not route or not spec:
            raise CarlaAdapterError(
                "Vehicle '{}' has no recoverable explicit route".format(
                    vehicle_id
                )
            )

        current_location = actor.get_location()
        nearest_index = 0
        nearest_gap_m = float("inf")

        for index, item in enumerate(route):
            location = item[0].transform.location
            gap = self._location_distance(
                current_location,
                location,
            )
            if gap < nearest_gap_m:
                nearest_gap_m = gap
                nearest_index = index

        requested_forward_m = max(
            4.0,
            float(forward_distance_m),
        )
        target_index = self._route_forward_index(
            route,
            nearest_index,
            requested_forward_m,
        )

        # If another controlled CAT occupies the first recovery target,
        # move a little farther forward, but only inside a strict bound.
        extra_limit_m = max(
            0.0,
            float(max_extra_forward_m),
        )
        extra_used_m = 0.0

        while True:
            target_waypoint = route[target_index][0]
            target_location = target_waypoint.transform.location
            clearance = self._controlled_clearance_at(
                vehicle_id,
                target_location,
            )

            if clearance >= max(0.0, float(clearance_m)):
                break

            if target_index >= len(route) - 1:
                raise CarlaAdapterError(
                    "No clear forward recovery point for '{}'".format(
                        vehicle_id
                    )
                )

            next_index = min(
                len(route) - 1,
                target_index + 2,
            )
            step_distance = self._location_distance(
                route[target_index][0].transform.location,
                route[next_index][0].transform.location,
            )
            extra_used_m += step_distance

            if extra_used_m > extra_limit_m:
                raise CarlaAdapterError(
                    "Recovery target for '{}' remains occupied inside "
                    "{:.1f}m extra-forward bound".format(
                        vehicle_id,
                        extra_limit_m,
                    )
                )

            target_index = next_index

        target_transform = route[target_index][0].transform

        # Build a fresh Transform instead of mutating the map waypoint's
        # shared transform object.
        relocation = self.carla.Transform(
            self.carla.Location(
                x=float(target_transform.location.x),
                y=float(target_transform.location.y),
                z=float(target_transform.location.z) + float(z_offset_m),
            ),
            self.carla.Rotation(
                pitch=float(target_transform.rotation.pitch),
                yaw=float(target_transform.rotation.yaw),
                roll=float(target_transform.rotation.roll),
            ),
        )

        old_transform = actor.get_transform()
        old_location = old_transform.location
        shift_m = self._location_distance(
            old_location,
            relocation.location,
        )

        # Keep local copies because _release_agent() clears active-route caches.
        route_spec = dict(spec)

        try:
            self._release_agent(vehicle_id)

            actor.set_transform(relocation)

            # Cancel residual motion before the new LocalPlanner takes over.
            zero = self.carla.Vector3D(0.0, 0.0, 0.0)
            set_target_velocity = getattr(
                actor,
                "set_target_velocity",
                None,
            )
            if callable(set_target_velocity):
                set_target_velocity(zero)

            set_target_angular_velocity = getattr(
                actor,
                "set_target_angular_velocity",
                None,
            )
            if callable(set_target_angular_velocity):
                set_target_angular_velocity(zero)

            self.set_route_spawn_points(
                vehicle_id=vehicle_id,
                route_id=route_spec["route_id"],
                from_spawn_point_index=route_spec[
                    "from_spawn_point_index"
                ],
                to_spawn_point_index=route_spec[
                    "to_spawn_point_index"
                ],
                target_speed_kmh=route_spec[
                    "target_speed_kmh"
                ],
                sampling_resolution_m=route_spec[
                    "sampling_resolution_m"
                ],
                expected_distance_m=route_spec[
                    "expected_distance_m"
                ],
                distance_tolerance_ratio=route_spec[
                    "distance_tolerance_ratio"
                ],
                route_start_tolerance_m=max(
                    30.0,
                    float(
                        route_spec[
                            "route_start_tolerance_m"
                        ]
                    ),
                ),
                skip_ahead_waypoints=route_spec[
                    "skip_ahead_waypoints"
                ],
            )

        except Exception as exc:
            # Best-effort rollback: restore the actor pose, then try to restore
            # the same route. Recovery failure must be explicit, not silent.
            try:
                actor.set_transform(old_transform)
                self.set_route_spawn_points(
                    vehicle_id=vehicle_id,
                    route_id=route_spec["route_id"],
                    from_spawn_point_index=route_spec[
                        "from_spawn_point_index"
                    ],
                    to_spawn_point_index=route_spec[
                        "to_spawn_point_index"
                    ],
                    target_speed_kmh=route_spec[
                        "target_speed_kmh"
                    ],
                    sampling_resolution_m=route_spec[
                        "sampling_resolution_m"
                    ],
                    expected_distance_m=route_spec[
                        "expected_distance_m"
                    ],
                    distance_tolerance_ratio=route_spec[
                        "distance_tolerance_ratio"
                    ],
                    route_start_tolerance_m=max(
                        30.0,
                        float(
                            route_spec[
                                "route_start_tolerance_m"
                            ]
                        ),
                    ),
                    skip_ahead_waypoints=route_spec[
                        "skip_ahead_waypoints"
                    ],
                )
            except Exception:
                pass

            raise CarlaAdapterError(
                "Stall recovery failed for '{}': {}".format(
                    vehicle_id,
                    exc,
                )
            ) from exc

        print(
            "[CARLA RECOVERY] {} | route={} | nearest_wp={} | "
            "target_wp={} | shift={:.1f}m | route_gap={:.1f}m | "
            "clearance={:.1f}m".format(
                vehicle_id,
                route_spec["route_id"],
                nearest_index,
                target_index,
                shift_m,
                nearest_gap_m,
                clearance,
            )
        )

        return {
            "vehicle_id": vehicle_id,
            "route_id": route_spec["route_id"],
            "nearest_route_index": nearest_index,
            "target_route_index": target_index,
            "shift_m": float(shift_m),
            "route_gap_m": float(nearest_gap_m),
            "clearance_m": float(clearance),
        }


    # ============================================================
    # Runtime behavior
    # ============================================================

    def step_vehicle(
        self,
        vehicle_id: str,
        context: Optional[BehaviorContext] = None,
    ) -> DrivingDecision:
        """Execute one low-level behavior + BasicAgent step."""

        self._require_connected()

        actor = self._actor(
            vehicle_id
        )


        agent = self._agents.get(
            vehicle_id
        )


        if agent is None:

            raise CarlaAdapterError(
                "Vehicle '{}' has no active BasicAgent".format(
                    vehicle_id
                )
            )


        ego = self.get_vehicle_snapshot(
            vehicle_id
        )


        nearby = []

        ego_route_id = self._active_route_ids.get(
            vehicle_id
        )

        for other_id in self._actors:

            if other_id == vehicle_id:
                continue

            other_snapshot = self.get_vehicle_snapshot(
                other_id
            )

            other_route_id = self._active_route_ids.get(
                other_id
            )

            if (
                ego_route_id is not None
                and other_route_id is not None
                and ego_route_id != other_route_id
                and not self._same_current_road_lane(
                    ego,
                    other_snapshot,
                )
            ):
                # Different Decision routes can pass close to one another on
                # stacked/parallel mine roads.  VehicleBehavior intentionally
                # uses generous geometric tolerances on curves, so feeding it
                # every CAT can create false front-vehicle cycles.  Keep
                # cross-route CATs only when CARLA currently places both on
                # the same road/lane. BasicAgent still performs its own
                # immediate route/lane hazard handling underneath.
                continue

            nearby.append(
                other_snapshot
            )


        if context is None:

            context = BehaviorContext(

                cruise_speed_kmh=
                    self._cruise_speeds_kmh.get(
                        vehicle_id,
                        0.0,
                    )
            )


        decision = self.behavior.decide(

            ego=ego,

            nearby_vehicles=nearby,

            context=context,
        )


        # --------------------------------------------------------
        # VehicleBehavior decides desired longitudinal speed.
        # --------------------------------------------------------

        planner = self._local_planner_for(
            agent
        )


        if planner is not None:

            set_speed = getattr(
                planner,
                "set_speed",
                None,
            )


            if callable(set_speed):

                set_speed(
                    float(
                        decision.target_speed_kmh
                    )
                )


        # --------------------------------------------------------
        # Route + steering are handled ONLY by LocalPlanner.
        #
        # Do NOT call BasicAgent.run_step() here. BasicAgent has its own
        # independent vehicle / traffic-light hazard detector and may apply
        # an emergency stop after VehicleBehavior has already made the mine
        # truck safety decision. On the custom open-pit map, different
        # Decision routes can pass close to each other, so that second hazard
        # layer can stop trucks that VehicleBehavior correctly considered
        # unrelated.
        #
        # Architecture contract:
        #   VehicleBehavior = longitudinal safety owner
        #   LocalPlanner    = route following + steering/PID
        #   CarlaAdapter    = execution only
        # --------------------------------------------------------

        if planner is None:

            raise CarlaAdapterError(
                "Vehicle '{}' has no active LocalPlanner".format(
                    vehicle_id
                )
            )

        try:

            control = planner.run_step()

        except Exception as exc:

            raise CarlaAdapterError(
                "LocalPlanner.run_step failed for '{}': {}".format(
                    vehicle_id,
                    exc,
                )
            ) from exc


        # --------------------------------------------------------
        # Safety layer is allowed to override longitudinal control.
        # --------------------------------------------------------

        if decision.brake_override is not None:

            existing_brake = float(
                getattr(
                    control,
                    "brake",
                    0.0,
                )
            )


            requested_brake = float(
                decision.brake_override
            )


            control.throttle = 0.0

            control.brake = min(
                1.0,
                max(
                    existing_brake,
                    requested_brake,
                ),
            )

            # Never use hand brake for temporary safety holds.
            # WAIT_FRONT must be able to transition to RESUME.
            control.hand_brake = False


        # --------------------------------------------------------
        # CAT smooth-control V1.7
        #
        # Soften normal LocalPlanner actuator commands for the large CAT.
        # VehicleBehavior remains the sole safety owner.
        # brake_override remains immediate and is never smoothed down.
        # --------------------------------------------------------

        try:
            previous_control = actor.get_control()
        except Exception:
            previous_control = None

        requested_steer = float(
            getattr(
                control,
                "steer",
                0.0,
            )
        )

        previous_steer = (
            float(
                getattr(
                    previous_control,
                    "steer",
                    0.0,
                )
            )
            if previous_control is not None
            else 0.0
        )

        max_steer_delta = 0.035
        control.steer = max(
            -1.0,
            min(
                1.0,
                max(
                    previous_steer - max_steer_delta,
                    min(
                        previous_steer + max_steer_delta,
                        requested_steer,
                    ),
                ),
            ),
        )

        if decision.brake_override is None:

            previous_throttle = (
                float(
                    getattr(
                        previous_control,
                        "throttle",
                        0.0,
                    )
                )
                if previous_control is not None
                else 0.0
            )

            previous_brake = (
                float(
                    getattr(
                        previous_control,
                        "brake",
                        0.0,
                    )
                )
                if previous_control is not None
                else 0.0
            )

            requested_throttle = max(
                0.0,
                min(
                    1.0,
                    float(
                        getattr(
                            control,
                            "throttle",
                            0.0,
                        )
                    ),
                ),
            )

            requested_brake = max(
                0.0,
                min(
                    1.0,
                    float(
                        getattr(
                            control,
                            "brake",
                            0.0,
                        )
                    ),
                ),
            )

            current_speed_kmh = max(
                0.0,
                float(ego.speed_mps) * 3.6,
            )
            desired_speed_kmh = max(
                0.0,
                float(decision.target_speed_kmh),
            )
            overspeed_kmh = current_speed_kmh - desired_speed_kmh

            if overspeed_kmh > 0.8:
                control.throttle = 0.0
                control.brake = max(
                    requested_brake,
                    min(
                        0.28,
                        0.05 + 0.05 * overspeed_kmh,
                    ),
                )
            else:
                throttle_rise = 0.04
                throttle_fall = 0.08
                brake_rise = 0.08
                brake_fall = 0.10

                control.throttle = max(
                    0.0,
                    min(
                        1.0,
                        max(
                            previous_throttle - throttle_fall,
                            min(
                                previous_throttle + throttle_rise,
                                requested_throttle,
                            ),
                        ),
                    ),
                )

                control.brake = max(
                    0.0,
                    min(
                        1.0,
                        max(
                            previous_brake - brake_fall,
                            min(
                                previous_brake + brake_rise,
                                requested_brake,
                            ),
                        ),
                    ),
                )

                if control.brake > 0.05:
                    control.throttle = 0.0

            control.hand_brake = False



        self._last_driving_decisions[
            vehicle_id
        ] = decision

        try:

            actor.apply_control(
                control
            )

        except RuntimeError as exc:

            raise CarlaAdapterError(
                "apply_control failed for '{}': {}".format(
                    vehicle_id,
                    exc,
                )
            ) from exc


        return decision


    def step_all(
        self,
        contexts: Optional[
            Dict[str, BehaviorContext]
        ] = None,
    ) -> Dict[str, DrivingDecision]:
        """Execute one control step for every vehicle with an active Agent."""

        results = {}


        for vehicle_id in list(
            self._agents.keys()
        ):

            context = None

            if contexts is not None:

                context = contexts.get(
                    vehicle_id
                )


            results[
                vehicle_id
            ] = self.step_vehicle(

                vehicle_id,

                context=context,
            )


        return results


    # ============================================================
    # Vehicle state conversion
    # ============================================================

    def get_vehicle_snapshot(
        self,
        vehicle_id: str,
    ) -> VehicleSnapshot:
        """Convert CARLA Actor state into behavior-layer state."""

        self._require_connected()

        actor = self._actor(
            vehicle_id
        )


        try:

            transform = actor.get_transform()

            location = transform.location

            velocity = actor.get_velocity()

        except RuntimeError as exc:

            raise CarlaAdapterError(
                "Failed to read actor state for '{}': {}".format(
                    vehicle_id,
                    exc,
                )
            ) from exc


        speed_mps = math.sqrt(

            velocity.x ** 2

            +

            velocity.y ** 2

            +

            velocity.z ** 2
        )


        bounding_box = getattr(
            actor,
            "bounding_box",
            None,
        )


        extent = getattr(
            bounding_box,
            "extent",
            None,
        )


        # CARLA bounding_box.extent is half-size.
        length_m = max(

            0.1,

            float(
                getattr(
                    extent,
                    "x",
                    4.25,
                )
            )
            * 2.0,
        )


        width_m = max(

            0.1,

            float(
                getattr(
                    extent,
                    "y",
                    2.0,
                )
            )
            * 2.0,
        )


        road_id = None
        lane_id = None


        try:

            waypoint = (
                self.world
                .get_map()
                .get_waypoint(
                    location
                )
            )


            if waypoint is not None:

                road_id = int(
                    waypoint.road_id
                )

                lane_id = int(
                    waypoint.lane_id
                )


        except (
            AttributeError,
            RuntimeError,
        ):

            # Some imported/custom maps may provide incomplete
            # topology information. VehicleBehavior has a
            # geometry fallback when road/lane ids are unavailable.
            pass


        return VehicleSnapshot(

            vehicle_id=str(
                vehicle_id
            ),

            x=float(
                location.x
            ),

            y=float(
                location.y
            ),

            z=float(
                location.z
            ),

            yaw_deg=float(
                transform.rotation.yaw
            ),

            speed_mps=float(
                speed_mps
            ),

            length_m=float(
                length_m
            ),

            width_m=float(
                width_m
            ),

            available=bool(
                self._available.get(
                    vehicle_id,
                    True,
                )
            ),

            healthy=bool(
                self._healthy.get(
                    vehicle_id,
                    True,
                )
            ),

            road_id=road_id,

            lane_id=lane_id,
        )


    def get_all_snapshots(
        self,
    ) -> Dict[str, VehicleSnapshot]:

        return {

            vehicle_id:
                self.get_vehicle_snapshot(
                    vehicle_id
                )

            for vehicle_id
            in self._actors
        }


    # ============================================================
    # Runtime vehicle state
    # ============================================================

    def set_vehicle_operational(
        self,
        vehicle_id: str,
        healthy: bool,
        available: Optional[bool] = None,
    ) -> None:
        """Update low-level vehicle availability.

        Scenario events will later call this method.
        """

        self._actor(
            vehicle_id
        )


        healthy = bool(
            healthy
        )


        if available is None:

            available = healthy


        self._healthy[
            vehicle_id
        ] = healthy

        self._available[
            vehicle_id
        ] = bool(
            available
        )


    def stop_vehicle(
        self,
        vehicle_id: str,
        hand_brake: bool = False,
    ) -> None:
        """Immediately command a vehicle to stop."""

        self._require_connected()

        actor = self._actor(
            vehicle_id
        )


        try:

            actor.apply_control(

                self.carla.VehicleControl(

                    throttle=0.0,

                    brake=1.0,

                    hand_brake=
                        bool(hand_brake),
                )
            )


            if hand_brake:

                zero_velocity = (
                    self.carla.Vector3D(
                        x=0.0,
                        y=0.0,
                        z=0.0,
                    )
                )


                actor.set_target_velocity(
                    zero_velocity
                )

                actor.set_target_angular_velocity(
                    zero_velocity
                )


        except RuntimeError as exc:

            raise CarlaAdapterError(
                "Failed to stop '{}': {}".format(
                    vehicle_id,
                    exc,
                )
            ) from exc


    @staticmethod
    def _same_current_road_lane(
        ego: VehicleSnapshot,
        other: VehicleSnapshot,
    ) -> bool:
        if (
            ego.road_id is None
            or ego.lane_id is None
            or other.road_id is None
            or other.lane_id is None
        ):
            return False

        return (
            int(ego.road_id) == int(other.road_id)
            and int(ego.lane_id) == int(other.lane_id)
        )

    def get_route_status(self, vehicle_id: str) -> Dict[str, object]:
        """Return progress for the currently active explicit Closed Loop route."""

        self._require_connected()
        actor = self._actor(vehicle_id)
        agent = self._agents.get(vehicle_id)

        route_id = self._active_route_ids.get(vehicle_id)
        end_xyz = self._active_route_end_xyz.get(vehicle_id)

        remaining_waypoints = None
        if agent is not None:
            planner = self._local_planner_for(agent)
            if planner is not None:
                getter = getattr(planner, "get_plan", None)
                if callable(getter):
                    try:
                        remaining_waypoints = len(getter())
                    except Exception:
                        remaining_waypoints = None

                # CARLA 0.9.10/0.9.11 LocalPlanner may not expose
                # get_plan().  Those versions keep a waypoint queue plus a
                # small active buffer.  Read both without mutating them.
                if remaining_waypoints is None:
                    queue = getattr(
                        planner,
                        "_waypoints_queue",
                        None,
                    )
                    if queue is None:
                        queue = getattr(
                            planner,
                            "waypoints_queue",
                            None,
                        )

                    buffer_ = getattr(
                        planner,
                        "_waypoint_buffer",
                        None,
                    )

                    queue_len = (
                        len(queue)
                        if queue is not None
                        else 0
                    )
                    buffer_len = (
                        len(buffer_)
                        if buffer_ is not None
                        else 0
                    )

                    if queue is not None or buffer_ is not None:
                        remaining_waypoints = queue_len + buffer_len

        final_gap_m = None
        if end_xyz is not None:
            location = actor.get_location()
            dx = float(location.x) - float(end_xyz[0])
            dy = float(location.y) - float(end_xyz[1])
            dz = float(location.z) - float(end_xyz[2])
            final_gap_m = math.sqrt(dx * dx + dy * dy + dz * dz)

        last_decision = self._last_driving_decisions.get(
            vehicle_id
        )

        behavior_state = None
        behavior_reason = None
        if last_decision is not None:
            state = getattr(last_decision, "state", None)
            behavior_state = getattr(state, "value", None)
            if behavior_state is None and state is not None:
                behavior_state = str(state)
            behavior_reason = getattr(
                last_decision,
                "reason",
                None,
            )

        return {
            "active": route_id is not None,
            "route_id": route_id,
            "done": self.is_done(vehicle_id),
            "remaining_waypoints": remaining_waypoints,
            "total_waypoints": self._active_route_total_waypoints.get(vehicle_id),
            "final_gap_m": final_gap_m,
            "behavior_state": behavior_state,
            "behavior_reason": behavior_reason,
        }


    # ============================================================
    # BasicAgent helpers
    # ============================================================

    def is_done(
        self,
        vehicle_id: str,
    ) -> bool:
        """Return whether BasicAgent reached its current destination."""

        agent = self._agents.get(
            vehicle_id
        )


        if agent is None:

            return True


        done = getattr(
            agent,
            "done",
            None,
        )


        if not callable(done):

            return False


        try:

            return bool(
                done()
            )

        except Exception:

            return False


    def set_cruise_speed(
        self,
        vehicle_id: str,
        speed_kmh: float,
    ) -> None:
        """Update upper-layer cruise speed without replacing the route."""

        self._actor(
            vehicle_id
        )


        speed_kmh = max(
            0.0,
            float(speed_kmh),
        )


        self._cruise_speeds_kmh[
            vehicle_id
        ] = speed_kmh


        agent = self._agents.get(
            vehicle_id
        )


        if agent is None:

            return


        planner = self._local_planner_for(
            agent
        )


        if planner is None:

            return


        setter = getattr(
            planner,
            "set_speed",
            None,
        )


        if callable(setter):

            setter(
                speed_kmh
            )


    # ============================================================
    # Map utility
    # ============================================================

    def get_spawn_point_xyz(
        self,
        index: int,
    ) -> Tuple[float, float, float]:

        self._require_connected()


        spawn_points = (
            self.world
            .get_map()
            .get_spawn_points()
        )


        index = int(
            index
        )


        if not (
            0 <= index < len(spawn_points)
        ):

            raise CarlaAdapterError(
                "Spawn point {} is out of range 0..{}".format(
                    index,
                    len(spawn_points) - 1,
                )
            )


        location = (
            spawn_points[index]
            .location
        )


        return (
            float(
                location.x
            ),
            float(
                location.y
            ),
            float(
                location.z
            ),
        )


    @property
    def vehicle_ids(self):

        return tuple(
            self._actors.keys()
        )


    # ============================================================
    # Cleanup
    # ============================================================

    def destroy_spawned_vehicles(
        self,
    ) -> int:
        """Destroy only actors created by this adapter."""

        destroyed = 0


        for vehicle_id in list(
            self._owned_vehicle_ids
        ):

            self._release_agent(
                vehicle_id
            )


            actor = self._actors.get(
                vehicle_id
            )


            if actor is not None:

                try:

                    actor.destroy()

                    destroyed += 1

                except (
                    AttributeError,
                    RuntimeError,
                ):

                    pass


            self._actors.pop(
                vehicle_id,
                None,
            )

            self._healthy.pop(
                vehicle_id,
                None,
            )

            self._available.pop(
                vehicle_id,
                None,
            )

            self._cruise_speeds_kmh.pop(
                vehicle_id,
                None,
            )

            self._owned_vehicle_ids.discard(
                vehicle_id
            )


        return destroyed


    def close(
        self,
    ) -> None:
        """Stop controlled vehicles and release BasicAgent references."""

        for vehicle_id in list(
            self._agents.keys()
        ):

            try:

                self.stop_vehicle(
                    vehicle_id,
                    hand_brake=True,
                )

            except Exception:

                pass


            self._release_agent(
                vehicle_id
            )


    # ============================================================
    # Internal CARLA import
    # ============================================================

    def _import_carla(
        self,
    ) -> None:
        """Locate CARLA 0.9.10 PythonAPI automatically.

        Supported examples:

        Source tree:
            /home/xiaoa/carla/PythonAPI/carla

        Packaged tree:
            /home/xiaoa/carla/Dist/.../LinuxNoEditor/PythonAPI/carla
        """

        configured_root = (

            os.environ.get(
                "OPENPIT_CARLA_ROOT"
            )

            or self.carla_root
        )


        root = Path(
            configured_root
        ).expanduser().resolve()


        if not root.exists():

            raise CarlaAdapterError(
                "CARLA root does not exist: {}".format(
                    root
                )
            )


        candidate_api_roots = []


        # --------------------------------------------------------
        # Layout 1:
        #
        # /home/xiaoa/carla/PythonAPI/carla
        # --------------------------------------------------------

        candidate_api_roots.append(

            root
            / "PythonAPI"
            / "carla"
        )


        # --------------------------------------------------------
        # Layout 2:
        #
        # /home/xiaoa/carla/Dist/<package>/LinuxNoEditor/
        # PythonAPI/carla
        # --------------------------------------------------------

        candidate_api_roots.extend(

            sorted(
                root.glob(
                    "Dist/*/LinuxNoEditor/PythonAPI/carla"
                )
            )
        )


        # --------------------------------------------------------
        # General fallback
        # --------------------------------------------------------

        candidate_api_roots.extend(

            sorted(
                root.glob(
                    "Dist/**/PythonAPI/carla"
                )
            )
        )


        # If carla_root itself is already LinuxNoEditor.
        candidate_api_roots.append(

            root
            / "PythonAPI"
            / "carla"
        )


        seen = set()

        selected_api_root = None
        selected_egg = None


        for api_root in candidate_api_roots:

            try:

                api_root = (
                    api_root
                    .expanduser()
                    .resolve()
                )

            except OSError:

                continue


            key = str(
                api_root
            )


            if key in seen:

                continue


            seen.add(
                key
            )


            if not api_root.exists():

                continue


            dist_dir = (
                api_root
                / "dist"
            )


            if not dist_dir.exists():

                continue


            # Exact preferred package on this machine.
            egg_candidates = sorted(

                dist_dir.glob(
                    "carla-0.9.10-py3.7-linux-x86_64.egg"
                )
            )


            # Generic Python 3.7 fallback.
            if not egg_candidates:

                egg_candidates = sorted(

                    dist_dir.glob(
                        "carla-*-py3.7-linux-x86_64.egg"
                    )
                )


            # Last fallback.
            if not egg_candidates:

                egg_candidates = sorted(

                    dist_dir.glob(
                        "carla-*-linux-x86_64.egg"
                    )
                )


            if not egg_candidates:

                continue


            selected_api_root = (
                api_root
            )

            selected_egg = (
                egg_candidates[-1]
            )

            break


        # --------------------------------------------------------
        # Additional broad search.
        # Useful for unusual packaged builds.
        # --------------------------------------------------------

        if (
            selected_api_root is None
            or selected_egg is None
        ):

            broad_matches = sorted(

                root.glob(
                    "**/PythonAPI/carla/dist/"
                    "carla-0.9.10-py3.7-linux-x86_64.egg"
                )
            )


            if broad_matches:

                selected_egg = (
                    broad_matches[-1]
                )

                selected_api_root = (
                    selected_egg
                    .parent
                    .parent
                )


        if (
            selected_api_root is None
            or selected_egg is None
        ):

            raise CarlaAdapterError(
                "Unable to locate CARLA 0.9.10 PythonAPI + "
                "Python 3.7 egg under '{}'".format(
                    root
                )
            )


        # --------------------------------------------------------
        # Import paths
        #
        # egg:
        #   import carla
        #
        # PythonAPI/carla:
        #   from agents.navigation...
        # --------------------------------------------------------

        paths = [
            str(
                selected_egg
            ),
            str(
                selected_api_root
            ),
        ]


        # Insert in reverse so egg remains highest priority.
        for entry in reversed(
            paths
        ):

            if entry not in sys.path:

                sys.path.insert(
                    0,
                    entry,
                )


        try:

            import carla

            from agents.navigation.basic_agent import (
                BasicAgent,
            )

        except ImportError as exc:

            raise CarlaAdapterError(
                "Failed to import CARLA 0.9.10 / BasicAgent "
                "from '{}': {}".format(
                    selected_api_root,
                    exc,
                )
            ) from exc


        self.carla = carla

        self._basic_agent_class = (
            BasicAgent
        )

        self._carla_api_root = str(
            selected_api_root
        )

        self._carla_egg_path = str(
            selected_egg
        )


        print(
            "[CARLA] PythonAPI: {}".format(
                self._carla_api_root
            )
        )

        print(
            "[CARLA] egg: {}".format(
                self._carla_egg_path
            )
        )


    # ============================================================
    # Internal utilities
    # ============================================================

    def _get_blueprint(
        self,
        blueprint_id: str,
    ):

        library = (
            self.world
            .get_blueprint_library()
        )


        try:

            return library.find(
                str(
                    blueprint_id
                )
            )

        except RuntimeError as exc:

            available_examples = []

            try:

                available_examples = [

                    item.id

                    for item in list(
                        library.filter(
                            "vehicle.*"
                        )
                    )[:10]
                ]

            except Exception:

                pass


            raise CarlaAdapterError(
                "CARLA blueprint '{}' not found. "
                "Example available vehicles: {}".format(
                    blueprint_id,
                    available_examples,
                )
            ) from exc


    def _actor(
        self,
        vehicle_id: str,
    ):

        actor = self._actors.get(
            vehicle_id
        )


        if actor is None:

            raise CarlaAdapterError(
                "Unknown CARLA vehicle: '{}'".format(
                    vehicle_id
                )
            )


        return actor


    @staticmethod
    def _local_planner_for(
        agent,
    ):

        getter = getattr(
            agent,
            "get_local_planner",
            None,
        )


        if callable(getter):

            try:

                planner = getter()

                if planner is not None:

                    return planner

            except Exception:

                pass


        return getattr(
            agent,
            "_local_planner",
            None,
        )


    def _release_agent(
        self,
        vehicle_id: str,
    ) -> None:
        """Detach CARLA 0.9.10 LocalPlanner before dropping an Agent.

        CARLA 0.9.10 LocalPlanner.__del__() destroys the ego vehicle
        when the planner still owns a vehicle reference.

        Calling reset_vehicle() first prevents accidental destruction
        of our mine-truck actor.
        """

        agent = self._agents.get(
            vehicle_id
        )


        if agent is None:

            return


        planner = self._local_planner_for(
            agent
        )


        if planner is not None:

            reset_vehicle = getattr(
                planner,
                "reset_vehicle",
                None,
            )


            if callable(
                reset_vehicle
            ):

                try:

                    reset_vehicle()

                except Exception:

                    pass


        self._agents.pop(
            vehicle_id,
            None,
        )

        self._active_route_ids.pop(
            vehicle_id,
            None,
        )
        self._active_route_end_xyz.pop(
            vehicle_id,
            None,
        )
        self._active_route_total_waypoints.pop(
            vehicle_id,
            None,
        )
        self._active_route_traces.pop(
            vehicle_id,
            None,
        )
        self._active_route_specs.pop(
            vehicle_id,
            None,
        )
        self._last_driving_decisions.pop(
            vehicle_id,
            None,
        )


    def _require_connected(
        self,
    ) -> None:

        if (
            self.world is None
            or self.client is None
        ):

            raise CarlaAdapterError(
                "CarlaAdapter is not connected"
            )
