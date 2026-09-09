"""Mine truck low-level driving safety rules.

This module decides HOW a truck should drive safely.

It does NOT:
- assign tasks
- re-dispatch vehicles
- optimize routes
- handle production scheduling

Those responsibilities belong to the decision layer.

The output of this module is a DrivingDecision that can later be
translated into CARLA BasicAgent / VehicleControl commands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import cos, radians, sin, sqrt
from typing import Dict, Optional, Sequence


# ============================================================
# Driving states
# ============================================================


class DrivingState(str, Enum):
    """Low-level mine truck driving state."""

    CRUISE = "cruise"

    FOLLOW = "follow"

    DECELERATE = "decelerate"

    WAIT_FRONT = "wait_front"

    RESUME = "resume"

    YIELD = "yield"

    ROAD_HOLD = "road_hold"

    OBSTACLE_STOP = "obstacle_stop"

    EMERGENCY_STOP = "emergency_stop"

    FAULT_STOP = "fault_stop"


# ============================================================
# Rule parameters
# ============================================================


@dataclass(frozen=True)
class DrivingRuleConfig:
    """Configuration of mine-truck safety rules."""

    # Maximum distance used for front-vehicle / obstacle detection.
    detection_distance_m: float = 60.0

    # Ignore vehicles on clearly different elevations.
    max_elevation_delta_m: float = 4.0

    # Same-direction judgement.
    #
    # cos(41 deg) ~= 0.75
    heading_alignment_cosine: float = 0.75

    # Vehicle must be sufficiently in front of ego.
    forward_cone_cosine: float = 0.20

    # Geometry fallback when CARLA lane ids are unavailable.
    lateral_tolerance_m: float = 6.0

    # Minimum desired gap when stopped.
    standstill_gap_m: float = 8.0

    # Time gap used by dynamic following.
    time_headway_s: float = 2.0

    # Comfortable longitudinal deceleration.
    comfortable_decel_mps2: float = 1.8

    # Physical emergency distance.
    emergency_gap_m: float = 3.5

    # Time-to-collision emergency threshold.
    emergency_ttc_s: float = 1.5

    # Start following no later than this distance.
    follow_start_min_m: float = 30.0

    # Follow region = dynamic safe gap * this factor.
    follow_start_factor: float = 1.6

    # Front vehicle slower than this is considered stopped.
    stopped_speed_mps: float = 0.30

    # Front vehicle faster than this can trigger RESUME.
    resume_speed_mps: float = 0.60

    # Initial speed after release from a stop.
    resume_target_speed_kmh: float = 6.0

    # Brake used for normal controlled waiting.
    wait_brake: float = 0.70

    # Emergency brake override.
    emergency_brake: float = 1.0

    # Very small relative speeds should not produce unstable TTC.
    min_closing_speed_mps: float = 0.25


# ============================================================
# Input snapshots
# ============================================================


@dataclass(frozen=True)
class VehicleSnapshot:
    """Minimum vehicle state required by the behavior layer."""

    vehicle_id: str

    x: float
    y: float
    z: float

    yaw_deg: float

    speed_mps: float

    # Used to calculate bumper-to-bumper distance.
    length_m: float = 8.5
    width_m: float = 4.0

    # Vehicle-level availability.
    available: bool = True
    healthy: bool = True

    # Optional CARLA topology information.
    road_id: Optional[int] = None
    lane_id: Optional[int] = None

    # These fields are mainly reserved for right-of-way logic.
    task_priority: int = 0
    remaining_task_distance_m: Optional[float] = None


@dataclass(frozen=True)
class ObstacleSnapshot:
    """Obstacle detected in the current driving corridor."""

    obstacle_id: str

    # Distance from ego vehicle to obstacle boundary.
    distance_m: float

    # Zero for a static obstacle.
    speed_mps: float = 0.0

    # False means that the object is nearby but not blocking ego's path.
    in_path: bool = True


@dataclass(frozen=True)
class BehaviorContext:
    """External constraints provided to the driving rule engine."""

    # Speed requested by task / route / decision layer.
    cruise_speed_kmh: float

    # Current road speed limit.
    speed_limit_kmh: Optional[float] = None

    # False means the current route cannot be entered.
    road_open: bool = True

    # Set by traffic-conflict / right-of-way logic.
    yield_required: bool = False
    yield_reason: str = ""

    # Static or dynamically detected obstacles.
    obstacles: Sequence[ObstacleSnapshot] = field(
        default_factory=tuple
    )


# ============================================================
# Output
# ============================================================


@dataclass(frozen=True)
class DrivingDecision:
    """Final low-level command requested from the CARLA controller."""

    state: DrivingState

    target_speed_kmh: float

    reason: str

    # None:
    #   let BasicAgent / LocalPlanner control the brake.
    #
    # 0~1:
    #   safety layer explicitly overrides the brake.
    brake_override: Optional[float] = None

    front_vehicle_id: Optional[str] = None

    front_gap_m: Optional[float] = None

    safe_gap_m: Optional[float] = None

    ttc_s: Optional[float] = None

    obstacle_id: Optional[str] = None

    obstacle_distance_m: Optional[float] = None

    diagnostics: Dict[str, float] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class _FrontVehicle:
    vehicle: VehicleSnapshot

    gap_m: float

    longitudinal_m: float

    lateral_m: float

    heading_alignment: float


# ============================================================
# Vehicle behavior engine
# ============================================================


class VehicleBehavior:
    """Unified mine-truck low-level safety behavior."""

    HOLD_STATES = {
        DrivingState.WAIT_FRONT,
        DrivingState.YIELD,
        DrivingState.ROAD_HOLD,
        DrivingState.OBSTACLE_STOP,
        DrivingState.EMERGENCY_STOP,
        DrivingState.FAULT_STOP,
    }

    def __init__(
        self,
        config: Optional[DrivingRuleConfig] = None,
    ) -> None:

        self.config = config or DrivingRuleConfig()

        # Previous state is kept per vehicle so WAIT -> RESUME can
        # be represented explicitly.
        self._last_state: Dict[str, DrivingState] = {}


    # ========================================================
    # Public API
    # ========================================================

    def decide(
        self,
        ego: VehicleSnapshot,
        nearby_vehicles: Sequence[VehicleSnapshot],
        context: BehaviorContext,
    ) -> DrivingDecision:
        """Return the safest driving action for the current tick."""

        cruise_speed = self._effective_cruise_speed(
            context
        )

        # ----------------------------------------------------
        # Priority 1:
        # vehicle itself is not operational
        # ----------------------------------------------------

        if not ego.available or not ego.healthy:

            return self._save(

                ego.vehicle_id,

                DrivingDecision(
                    state=DrivingState.FAULT_STOP,
                    target_speed_kmh=0.0,
                    brake_override=self.config.emergency_brake,
                    reason="vehicle_not_operational",
                ),
            )


        # ----------------------------------------------------
        # Priority 2:
        # physical obstacle
        # ----------------------------------------------------

        obstacle_decision = self._handle_obstacle(

            ego=ego,

            context=context,

            cruise_speed_kmh=cruise_speed,
        )

        if obstacle_decision is not None:

            return self._save(
                ego.vehicle_id,
                obstacle_decision,
            )


        # ----------------------------------------------------
        # Priority 3:
        # current road unavailable
        # ----------------------------------------------------

        if not context.road_open:

            return self._save(

                ego.vehicle_id,

                DrivingDecision(
                    state=DrivingState.ROAD_HOLD,
                    target_speed_kmh=0.0,
                    brake_override=self.config.wait_brake,
                    reason="road_not_open",
                ),
            )


        # ----------------------------------------------------
        # Priority 4:
        # right-of-way / conflict yield
        # ----------------------------------------------------

        if context.yield_required:

            return self._save(

                ego.vehicle_id,

                DrivingDecision(
                    state=DrivingState.YIELD,
                    target_speed_kmh=0.0,
                    brake_override=self.config.wait_brake,
                    reason=(
                        context.yield_reason
                        or "right_of_way_yield"
                    ),
                ),
            )


        # ----------------------------------------------------
        # Priority 5:
        # front vehicle
        # ----------------------------------------------------

        front = self.find_front_vehicle(

            ego=ego,

            nearby_vehicles=nearby_vehicles,
        )

        if front is not None:

            front_decision = self._handle_front_vehicle(

                ego=ego,

                front=front,

                cruise_speed_kmh=cruise_speed,
            )

            if front_decision is not None:

                return self._save(
                    ego.vehicle_id,
                    front_decision,
                )


        # ----------------------------------------------------
        # Hazard disappeared -> controlled resume
        # ----------------------------------------------------

        previous = self._last_state.get(
            ego.vehicle_id
        )

        if previous in self.HOLD_STATES:

            return self._save(

                ego.vehicle_id,

                DrivingDecision(
                    state=DrivingState.RESUME,
                    target_speed_kmh=min(
                        cruise_speed,
                        self.config.resume_target_speed_kmh,
                    ),
                    reason="hazard_cleared",
                ),
            )


        # ----------------------------------------------------
        # Normal driving
        # ----------------------------------------------------

        return self._save(

            ego.vehicle_id,

            DrivingDecision(
                state=DrivingState.CRUISE,
                target_speed_kmh=cruise_speed,
                reason="free_drive",
            ),
        )


    # ========================================================
    # Front vehicle detection
    # ========================================================

    def find_front_vehicle(
        self,
        ego: VehicleSnapshot,
        nearby_vehicles: Sequence[VehicleSnapshot],
    ) -> Optional[_FrontVehicle]:

        nearest: Optional[_FrontVehicle] = None

        for other in nearby_vehicles:

            if other.vehicle_id == ego.vehicle_id:
                continue

            geometry = self._front_vehicle_geometry(
                ego,
                other,
            )

            if geometry is None:
                continue

            if (
                nearest is None
                or geometry.gap_m < nearest.gap_m
            ):

                nearest = geometry

        return nearest


    def _front_vehicle_geometry(
        self,
        ego: VehicleSnapshot,
        other: VehicleSnapshot,
    ) -> Optional[_FrontVehicle]:

        dx = other.x - ego.x
        dy = other.y - ego.y
        dz = other.z - ego.z

        distance = sqrt(
            dx * dx
            + dy * dy
        )

        if distance < 0.001:
            return None

        if distance > self.config.detection_distance_m:
            return None

        if (
            abs(dz)
            > self.config.max_elevation_delta_m
        ):
            return None


        ego_yaw = radians(
            ego.yaw_deg
        )

        other_yaw = radians(
            other.yaw_deg
        )


        ego_forward_x = cos(
            ego_yaw
        )

        ego_forward_y = sin(
            ego_yaw
        )


        other_forward_x = cos(
            other_yaw
        )

        other_forward_y = sin(
            other_yaw
        )


        # Direction similarity.
        heading_alignment = (

            ego_forward_x
            * other_forward_x

            +

            ego_forward_y
            * other_forward_y
        )


        if (
            heading_alignment
            < self.config.heading_alignment_cosine
        ):

            return None


        # Longitudinal position in ego frame.
        longitudinal = (

            ego_forward_x * dx

            +

            ego_forward_y * dy
        )


        if longitudinal <= 0.0:
            return None


        sees_other = (

            longitudinal
            / distance
        )


        if (
            sees_other
            < self.config.forward_cone_cosine
        ):

            return None


        # Lateral distance from ego centreline.
        lateral = abs(

            -ego_forward_y * dx

            +

            ego_forward_x * dy
        )


        lateral_limit = max(

            self.config.lateral_tolerance_m,

            0.5
            * (
                ego.width_m
                + other.width_m
            )
            + 1.0,
        )


        if lateral > lateral_limit:
            return None


        # If CARLA lane information is reliable, use it.
        if not self._same_lane_if_known(
            ego,
            other,
        ):

            return None


        # Convert centre-to-centre longitudinal distance
        # to approximately bumper-to-bumper gap.
        gap = max(

            0.0,

            longitudinal
            - 0.5
            * (
                ego.length_m
                + other.length_m
            ),
        )


        return _FrontVehicle(

            vehicle=other,

            gap_m=gap,

            longitudinal_m=longitudinal,

            lateral_m=lateral,

            heading_alignment=heading_alignment,
        )


    # ========================================================
    # Front vehicle behavior
    # ========================================================

    def _handle_front_vehicle(
        self,
        ego: VehicleSnapshot,
        front: _FrontVehicle,
        cruise_speed_kmh: float,
    ) -> Optional[DrivingDecision]:

        vehicle = front.vehicle

        gap = front.gap_m


        safe_gap = self.dynamic_safe_gap(

            ego_speed_mps=ego.speed_mps,

            front_speed_mps=vehicle.speed_mps,
        )


        ttc = self.time_to_collision(

            gap_m=gap,

            ego_speed_mps=ego.speed_mps,

            object_speed_mps=vehicle.speed_mps,
        )


        details = {
            "front_vehicle_id":
                vehicle.vehicle_id,

            "front_gap_m":
                gap,

            "safe_gap_m":
                safe_gap,

            "ttc_s":
                ttc,
        }


        # ----------------------------------------------------
        # Emergency condition
        # ----------------------------------------------------

        if (

            gap
            <= self.config.emergency_gap_m

            or

            (
                ttc is not None
                and
                ttc
                <= self.config.emergency_ttc_s
            )

        ):

            return DrivingDecision(

                state=DrivingState.EMERGENCY_STOP,

                target_speed_kmh=0.0,

                brake_override=
                    self.config.emergency_brake,

                reason=
                    "front_vehicle_critical_gap_or_ttc",

                **details,
            )


        # ----------------------------------------------------
        # Front truck stopped
        # ----------------------------------------------------

        if (

            vehicle.speed_mps
            <= self.config.stopped_speed_mps

            and

            gap <= safe_gap

        ):

            return DrivingDecision(

                state=DrivingState.WAIT_FRONT,

                target_speed_kmh=0.0,

                brake_override=
                    self.config.wait_brake,

                reason=
                    "front_vehicle_stopped",

                **details,
            )


        # ----------------------------------------------------
        # Front truck started moving again
        # ----------------------------------------------------

        previous = self._last_state.get(
            ego.vehicle_id
        )


        if (

            previous
            == DrivingState.WAIT_FRONT

            and

            vehicle.speed_mps
            >= self.config.resume_speed_mps

        ):

            target_speed = min(

                cruise_speed_kmh,

                max(
                    self.config.resume_target_speed_kmh,
                    vehicle.speed_mps * 3.6,
                ),
            )


            return DrivingDecision(

                state=DrivingState.RESUME,

                target_speed_kmh=target_speed,

                reason=
                    "front_vehicle_moving_again",

                **details,
            )


        # ----------------------------------------------------
        # Dynamic following zone
        # ----------------------------------------------------

        follow_start = max(

            self.config.follow_start_min_m,

            safe_gap
            * self.config.follow_start_factor,
        )


        if gap > follow_start:
            return None


        # Spacing controller:
        #
        # target velocity =
        # front velocity + K * spacing error
        #
        # When gap < safe_gap:
        # target velocity becomes lower than front vehicle.
        #
        # When gap > safe_gap:
        # vehicle is allowed to approach gradually.

        spacing_error = (
            gap - safe_gap
        )


        target_speed_mps = (

            vehicle.speed_mps

            +

            0.35
            * spacing_error
        )


        target_speed_kmh = max(

            0.0,

            min(
                cruise_speed_kmh,
                target_speed_mps * 3.6,
            ),
        )


        if gap < safe_gap:

            state = (
                DrivingState.DECELERATE
            )

        else:

            state = (
                DrivingState.FOLLOW
            )


        return DrivingDecision(

            state=state,

            target_speed_kmh=target_speed_kmh,

            reason=
                "dynamic_safe_distance_following",

            **details,
        )


    # ========================================================
    # Obstacle behavior
    # ========================================================

    def _handle_obstacle(
        self,
        ego: VehicleSnapshot,
        context: BehaviorContext,
        cruise_speed_kmh: float,
    ) -> Optional[DrivingDecision]:

        obstacle = self._nearest_obstacle(
            context.obstacles
        )

        if obstacle is None:
            return None


        distance = obstacle.distance_m


        ttc = self.time_to_collision(

            gap_m=distance,

            ego_speed_mps=ego.speed_mps,

            object_speed_mps=
                obstacle.speed_mps,
        )


        # ----------------------------------------------------
        # Emergency obstacle
        # ----------------------------------------------------

        if (

            distance
            <= self.config.emergency_gap_m

            or

            (
                ttc is not None
                and
                ttc
                <= self.config.emergency_ttc_s
            )

        ):

            return DrivingDecision(

                state=
                    DrivingState.EMERGENCY_STOP,

                target_speed_kmh=0.0,

                brake_override=
                    self.config.emergency_brake,

                reason=
                    "obstacle_critical_gap_or_ttc",

                ttc_s=ttc,

                obstacle_id=
                    obstacle.obstacle_id,

                obstacle_distance_m=
                    distance,
            )


        # ----------------------------------------------------
        # Distance required for safe stopping
        # ----------------------------------------------------

        stopping_distance = (

            self.config.standstill_gap_m

            +

            ego.speed_mps
            * self.config.time_headway_s

            +

            (
                ego.speed_mps ** 2
            )
            /
            (
                2.0
                * self.config.comfortable_decel_mps2
            )
        )


        if distance <= stopping_distance:

            return DrivingDecision(

                state=
                    DrivingState.OBSTACLE_STOP,

                target_speed_kmh=0.0,

                brake_override=
                    self.config.wait_brake,

                reason=
                    "obstacle_inside_required_stop_distance",

                ttc_s=ttc,

                obstacle_id=
                    obstacle.obstacle_id,

                obstacle_distance_m=
                    distance,
            )


        # ----------------------------------------------------
        # Obstacle is farther away:
        # reduce target speed progressively.
        # ----------------------------------------------------

        available_distance = max(

            0.0,

            distance
            - self.config.standstill_gap_m,
        )


        target_speed_mps = sqrt(

            max(
                0.0,

                2.0
                * self.config.comfortable_decel_mps2
                * available_distance,
            )
        )


        target_speed_kmh = min(

            cruise_speed_kmh,

            target_speed_mps * 3.6,
        )


        if target_speed_kmh >= cruise_speed_kmh:
            return None


        return DrivingDecision(

            state=DrivingState.DECELERATE,

            target_speed_kmh=
                target_speed_kmh,

            reason=
                "approaching_static_obstacle",

            ttc_s=ttc,

            obstacle_id=
                obstacle.obstacle_id,

            obstacle_distance_m=
                distance,
        )


    # ========================================================
    # Safety calculations
    # ========================================================

    def dynamic_safe_gap(
        self,
        ego_speed_mps: float,
        front_speed_mps: float,
    ) -> float:
        """Calculate speed-dependent safe following distance."""

        closing_speed = max(

            0.0,

            ego_speed_mps
            - front_speed_mps,
        )


        braking_buffer = (

            closing_speed ** 2

            /

            max(
                0.1,
                2.0
                * self.config.comfortable_decel_mps2,
            )
        )


        return (

            self.config.standstill_gap_m

            +

            ego_speed_mps
            * self.config.time_headway_s

            +

            braking_buffer
        )


    def time_to_collision(
        self,
        gap_m: float,
        ego_speed_mps: float,
        object_speed_mps: float,
    ) -> Optional[float]:
        """Return TTC in seconds when ego is closing on an object."""

        closing_speed = (

            ego_speed_mps
            - object_speed_mps
        )


        if (
            closing_speed
            <= self.config.min_closing_speed_mps
        ):
            return None


        if gap_m <= 0.0:
            return 0.0


        return (
            gap_m
            / closing_speed
        )


    # ========================================================
    # Internal helpers
    # ========================================================

    def _same_lane_if_known(
        self,
        first: VehicleSnapshot,
        second: VehicleSnapshot,
    ) -> bool:

        lane_known = all(

            value is not None

            for value in (
                first.road_id,
                first.lane_id,
                second.road_id,
                second.lane_id,
            )
        )


        if not lane_known:
            return True


        return (

            first.road_id
            == second.road_id

            and

            first.lane_id
            == second.lane_id
        )


    def _nearest_obstacle(
        self,
        obstacles: Sequence[ObstacleSnapshot],
    ) -> Optional[ObstacleSnapshot]:

        candidates = [

            item

            for item in obstacles

            if (
                item.in_path
                and
                item.distance_m >= 0.0
            )
        ]


        if not candidates:
            return None


        return min(

            candidates,

            key=lambda item:
                item.distance_m,
        )


    def _effective_cruise_speed(
        self,
        context: BehaviorContext,
    ) -> float:

        target = max(

            0.0,

            float(
                context.cruise_speed_kmh
            ),
        )


        if (
            context.speed_limit_kmh
            is not None
        ):

            target = min(

                target,

                max(
                    0.0,
                    float(
                        context.speed_limit_kmh
                    ),
                ),
            )


        return target


    def _save(
        self,
        vehicle_id: str,
        decision: DrivingDecision,
    ) -> DrivingDecision:

        self._last_state[
            vehicle_id
        ] = decision.state

        return decision
