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

        for other_id in self._actors:

            if other_id == vehicle_id:
                continue

            nearby.append(
                self.get_vehicle_snapshot(
                    other_id
                )
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
        # BasicAgent / LocalPlanner still handle route + steering.
        # --------------------------------------------------------

        try:

            control = agent.run_step()

        except Exception as exc:

            raise CarlaAdapterError(
                "BasicAgent.run_step failed for '{}': {}".format(
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
