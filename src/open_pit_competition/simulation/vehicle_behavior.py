"""Low-level vehicle safety behavior for open-pit mine simulation.

This module is intentionally independent from CARLA.

Responsibilities:
- detect a valid front vehicle
- cruise
- follow
- decelerate
- wait behind a stopped vehicle
- resume after the front vehicle moves
- yield
- road closure hold
- obstacle stop
- emergency stop
- vehicle fault stop

Important for custom mine maps:
road_id / lane_id are NOT hard constraints.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Sequence


class DrivingState(Enum):
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


@dataclass
class DrivingRuleConfig:
    detection_distance_m: float = 60.0
    max_elevation_delta_m: float = 4.0
    heading_alignment_cosine: float = 0.75
    forward_cone_cosine: float = 0.20
    lateral_tolerance_m: float = 6.0

    standstill_gap_m: float = 8.0
    time_headway_s: float = 2.0
    comfortable_decel_mps2: float = 1.8
    emergency_gap_m: float = 3.5
    emergency_ttc_s: float = 1.5
    follow_start_min_m: float = 30.0
    follow_start_factor: float = 1.6

    stopped_speed_mps: float = 0.30
    resume_speed_mps: float = 0.60
    resume_target_speed_kmh: float = 6.0

    # New mine-truck stopped-leader handling.
    wait_front_direct_gap_m: float = 10.0
    wait_front_stationary_gap_m: float = 20.0
    stopped_front_approach_gain: float = 0.8

    wait_brake: float = 0.70
    emergency_brake: float = 1.0
    min_closing_speed_mps: float = 0.25


@dataclass
class VehicleSnapshot:
    vehicle_id: str
    x: float
    y: float
    z: float
    yaw_deg: float
    speed_mps: float
    length_m: float = 8.5
    width_m: float = 4.0
    available: bool = True
    healthy: bool = True
    road_id: Optional[int] = None
    lane_id: Optional[int] = None
    task_priority: int = 0
    remaining_task_distance_m: Optional[float] = None


@dataclass
class ObstacleSnapshot:
    obstacle_id: str
    distance_m: float
    speed_mps: float = 0.0
    in_path: bool = True


@dataclass
class BehaviorContext:
    cruise_speed_kmh: float
    speed_limit_kmh: Optional[float] = None
    road_open: bool = True
    yield_required: bool = False
    yield_reason: Optional[str] = None
    obstacles: Sequence[ObstacleSnapshot] = field(default_factory=tuple)


@dataclass
class DrivingDecision:
    state: DrivingState
    target_speed_kmh: float
    reason: str
    brake_override: Optional[float] = None
    front_vehicle_id: Optional[str] = None
    front_gap_m: Optional[float] = None
    safe_gap_m: Optional[float] = None
    ttc_s: Optional[float] = None
    obstacle_id: Optional[str] = None
    obstacle_distance_m: Optional[float] = None


@dataclass
class _FrontVehicle:
    snapshot: VehicleSnapshot
    center_distance_m: float
    gap_m: float
    longitudinal_m: float
    lateral_m: float
    heading_alignment_cosine: float
    forward_cosine: float
    same_road: Optional[bool]
    same_lane: Optional[bool]
    score: float


class VehicleBehavior:
    """Low-level longitudinal safety behavior."""

    def __init__(self, config: Optional[DrivingRuleConfig] = None) -> None:
        self.config = config if config is not None else DrivingRuleConfig()
        self._previous_states: Dict[str, DrivingState] = {}

    def decide(
        self,
        ego: VehicleSnapshot,
        nearby_vehicles: Sequence[VehicleSnapshot],
        context: BehaviorContext,
    ) -> DrivingDecision:
        previous_state = self._previous_states.get(
            ego.vehicle_id, DrivingState.CRUISE
        )
        cruise_speed_kmh = self._effective_cruise_speed(context)

        if not ego.healthy or not ego.available:
            return self._remember(
                ego,
                DrivingDecision(
                    state=DrivingState.FAULT_STOP,
                    target_speed_kmh=0.0,
                    reason="vehicle unavailable or unhealthy",
                    brake_override=self.config.emergency_brake,
                ),
            )

        obstacle_decision = self._evaluate_obstacles(
            ego=ego,
            context=context,
            cruise_speed_kmh=cruise_speed_kmh,
            previous_state=previous_state,
        )
        if obstacle_decision is not None:
            return self._remember(ego, obstacle_decision)

        if not context.road_open:
            return self._remember(
                ego,
                DrivingDecision(
                    state=DrivingState.ROAD_HOLD,
                    target_speed_kmh=0.0,
                    reason="road is closed",
                    brake_override=self.config.wait_brake,
                ),
            )

        if context.yield_required:
            return self._remember(
                ego,
                DrivingDecision(
                    state=DrivingState.YIELD,
                    target_speed_kmh=0.0,
                    reason=context.yield_reason or "yield required",
                    brake_override=self.config.wait_brake,
                ),
            )

        front = self._find_front_vehicle(
            ego=ego,
            nearby_vehicles=nearby_vehicles,
        )

        if front is not None:
            front_speed_mps = max(0.0, front.snapshot.speed_mps)
            closing_speed_mps = ego.speed_mps - front_speed_mps
            safe_gap_m = self._safe_gap(
                ego_speed_mps=ego.speed_mps,
                front_speed_mps=front_speed_mps,
            )
            ttc_s = self._ttc(
                gap_m=front.gap_m,
                closing_speed_mps=closing_speed_mps,
            )

            critical_gap = front.gap_m <= self.config.emergency_gap_m
            critical_ttc = (
                ttc_s is not None and ttc_s <= self.config.emergency_ttc_s
            )
            if critical_gap or critical_ttc:
                return self._remember(
                    ego,
                    DrivingDecision(
                        state=DrivingState.EMERGENCY_STOP,
                        target_speed_kmh=0.0,
                        reason="critical front-vehicle collision risk",
                        brake_override=self.config.emergency_brake,
                        front_vehicle_id=front.snapshot.vehicle_id,
                        front_gap_m=front.gap_m,
                        safe_gap_m=safe_gap_m,
                        ttc_s=ttc_s,
                    ),
                )

            follow_start_m = max(
                self.config.follow_start_min_m,
                safe_gap_m * self.config.follow_start_factor,
            )

            # ----------------------------------------------------
            # Stopped front vehicle handling.
            #
            # Preserve the original rule:
            #   stopped leader + gap <= dynamic safe gap -> WAIT_FRONT
            #
            # Then add CARLA-specific compatibility rules for mine
            # trucks that BasicAgent may stop slightly farther back.
            # ----------------------------------------------------
            if front_speed_mps <= self.config.stopped_speed_mps:

                # Case A: original dynamic-safe-gap behavior.
                if front.gap_m <= safe_gap_m:
                    return self._remember(
                        ego,
                        DrivingDecision(
                            state=DrivingState.WAIT_FRONT,
                            target_speed_kmh=0.0,
                            reason="stopped front vehicle inside dynamic safe gap",
                            brake_override=self.config.wait_brake,
                            front_vehicle_id=front.snapshot.vehicle_id,
                            front_gap_m=front.gap_m,
                            safe_gap_m=safe_gap_m,
                            ttc_s=ttc_s,
                        ),
                    )

                # Case B: fixed close-range waiting guard.
                if front.gap_m <= self.config.wait_front_direct_gap_m:
                    return self._remember(
                        ego,
                        DrivingDecision(
                            state=DrivingState.WAIT_FRONT,
                            target_speed_kmh=0.0,
                            reason="waiting behind stopped front vehicle",
                            brake_override=self.config.wait_brake,
                            front_vehicle_id=front.snapshot.vehicle_id,
                            front_gap_m=front.gap_m,
                            safe_gap_m=safe_gap_m,
                            ttc_s=ttc_s,
                        ),
                    )

                # Case C: BasicAgent may already have nearly stopped
                # ego farther back than the nominal standstill gap.
                if (
                    ego.speed_mps <= self.config.resume_speed_mps
                    and front.gap_m <= self.config.wait_front_stationary_gap_m
                ):
                    return self._remember(
                        ego,
                        DrivingDecision(
                            state=DrivingState.WAIT_FRONT,
                            target_speed_kmh=0.0,
                            reason="ego nearly stopped behind stopped front vehicle",
                            brake_override=self.config.wait_brake,
                            front_vehicle_id=front.snapshot.vehicle_id,
                            front_gap_m=front.gap_m,
                            safe_gap_m=safe_gap_m,
                            ttc_s=ttc_s,
                        ),
                    )

                # Still approaching a stopped leader: use a dedicated
                # approach controller instead of normal FOLLOW.
                if front.gap_m <= follow_start_m:
                    remaining_gap_m = max(
                        0.0,
                        front.gap_m - self.config.wait_front_direct_gap_m,
                    )
                    approach_speed_kmh = (
                        remaining_gap_m * self.config.stopped_front_approach_gain
                    )
                    approach_speed_kmh = max(
                        0.0,
                        min(cruise_speed_kmh, approach_speed_kmh),
                    )
                    return self._remember(
                        ego,
                        DrivingDecision(
                            state=DrivingState.DECELERATE,
                            target_speed_kmh=approach_speed_kmh,
                            reason="approaching stopped front vehicle",
                            front_vehicle_id=front.snapshot.vehicle_id,
                            front_gap_m=front.gap_m,
                            safe_gap_m=safe_gap_m,
                            ttc_s=ttc_s,
                        ),
                    )

            # WAIT_FRONT -> RESUME when leader moves again.
            if (
                previous_state == DrivingState.WAIT_FRONT
                and front_speed_mps >= self.config.resume_speed_mps
            ):
                return self._remember(
                    ego,
                    DrivingDecision(
                        state=DrivingState.RESUME,
                        target_speed_kmh=min(
                            cruise_speed_kmh,
                            self.config.resume_target_speed_kmh,
                        ),
                        reason="front vehicle started moving",
                        front_vehicle_id=front.snapshot.vehicle_id,
                        front_gap_m=front.gap_m,
                        safe_gap_m=safe_gap_m,
                        ttc_s=ttc_s,
                    ),
                )

            if front.gap_m <= follow_start_m:
                target_speed_kmh = self._following_target_speed(
                    ego=ego,
                    front=front,
                    safe_gap_m=safe_gap_m,
                    cruise_speed_kmh=cruise_speed_kmh,
                )
                if front.gap_m < safe_gap_m:
                    state = DrivingState.DECELERATE
                    reason = "front gap below dynamic safe gap"
                else:
                    state = DrivingState.FOLLOW
                    reason = "front vehicle inside following zone"

                return self._remember(
                    ego,
                    DrivingDecision(
                        state=state,
                        target_speed_kmh=target_speed_kmh,
                        reason=reason,
                        front_vehicle_id=front.snapshot.vehicle_id,
                        front_gap_m=front.gap_m,
                        safe_gap_m=safe_gap_m,
                        ttc_s=ttc_s,
                    ),
                )

        if previous_state in {
            DrivingState.ROAD_HOLD,
            DrivingState.YIELD,
            DrivingState.OBSTACLE_STOP,
            DrivingState.EMERGENCY_STOP,
            DrivingState.FAULT_STOP,
        }:
            return self._remember(
                ego,
                DrivingDecision(
                    state=DrivingState.RESUME,
                    target_speed_kmh=min(
                        cruise_speed_kmh,
                        self.config.resume_target_speed_kmh,
                    ),
                    reason="previous hold condition cleared",
                ),
            )

        return self._remember(
            ego,
            DrivingDecision(
                state=DrivingState.CRUISE,
                target_speed_kmh=cruise_speed_kmh,
                reason="no active safety constraint",
            ),
        )

    def _find_front_vehicle(
        self,
        ego: VehicleSnapshot,
        nearby_vehicles: Sequence[VehicleSnapshot],
    ) -> Optional[_FrontVehicle]:
        """Return the best geometrically valid front vehicle.

        road_id/lane_id are auxiliary only because custom mine roads may
        change OpenDRIVE identifiers along one physically continuous road.
        """
        best = None
        ego_yaw_rad = math.radians(ego.yaw_deg)
        ego_forward_x = math.cos(ego_yaw_rad)
        ego_forward_y = math.sin(ego_yaw_rad)
        ego_left_x = -ego_forward_y
        ego_left_y = ego_forward_x

        for candidate in nearby_vehicles:
            if candidate.vehicle_id == ego.vehicle_id:
                continue
            if not candidate.available or not candidate.healthy:
                continue

            dx = candidate.x - ego.x
            dy = candidate.y - ego.y
            dz = candidate.z - ego.z
            horizontal_distance = math.sqrt(dx * dx + dy * dy)
            center_distance = math.sqrt(dx * dx + dy * dy + dz * dz)

            if center_distance > self.config.detection_distance_m:
                continue
            if center_distance <= 1e-6:
                continue
            if abs(dz) > self.config.max_elevation_delta_m:
                continue
            if horizontal_distance <= 1e-6:
                continue

            longitudinal = dx * ego_forward_x + dy * ego_forward_y
            lateral = abs(dx * ego_left_x + dy * ego_left_y)
            forward_cosine = longitudinal / horizontal_distance

            if longitudinal <= 0.0:
                continue
            if forward_cosine < self.config.forward_cone_cosine:
                continue
            if lateral > self.config.lateral_tolerance_m:
                continue

            candidate_yaw_rad = math.radians(candidate.yaw_deg)
            candidate_forward_x = math.cos(candidate_yaw_rad)
            candidate_forward_y = math.sin(candidate_yaw_rad)
            heading_alignment = (
                ego_forward_x * candidate_forward_x
                + ego_forward_y * candidate_forward_y
            )
            if heading_alignment < self.config.heading_alignment_cosine:
                continue

            half_ego_length = max(0.0, ego.length_m * 0.5)
            half_candidate_length = max(0.0, candidate.length_m * 0.5)
            gap_m = max(
                0.0,
                longitudinal - half_ego_length - half_candidate_length,
            )

            same_road = None
            if ego.road_id is not None and candidate.road_id is not None:
                same_road = ego.road_id == candidate.road_id

            same_lane = None
            if ego.lane_id is not None and candidate.lane_id is not None:
                same_lane = ego.lane_id == candidate.lane_id

            score = gap_m + lateral * 2.0 + (1.0 - heading_alignment) * 10.0
            if same_road is True:
                score -= 1.0
            if same_lane is True:
                score -= 1.0

            current = _FrontVehicle(
                snapshot=candidate,
                center_distance_m=center_distance,
                gap_m=gap_m,
                longitudinal_m=longitudinal,
                lateral_m=lateral,
                heading_alignment_cosine=heading_alignment,
                forward_cosine=forward_cosine,
                same_road=same_road,
                same_lane=same_lane,
                score=score,
            )

            if best is None or current.score < best.score:
                best = current

        return best

    def _safe_gap(
        self,
        ego_speed_mps: float,
        front_speed_mps: float,
    ) -> float:
        ego_speed_mps = max(0.0, float(ego_speed_mps))
        front_speed_mps = max(0.0, float(front_speed_mps))
        closing_speed = max(0.0, ego_speed_mps - front_speed_mps)

        gap = (
            self.config.standstill_gap_m
            + ego_speed_mps * self.config.time_headway_s
        )

        if closing_speed > 0.0:
            decel = max(0.1, self.config.comfortable_decel_mps2)
            gap += closing_speed * closing_speed / (2.0 * decel)

        return max(self.config.standstill_gap_m, gap)

    def _ttc(
        self,
        gap_m: float,
        closing_speed_mps: float,
    ) -> Optional[float]:
        if closing_speed_mps <= self.config.min_closing_speed_mps:
            return None
        return max(0.0, gap_m) / closing_speed_mps

    def _following_target_speed(
        self,
        ego: VehicleSnapshot,
        front: _FrontVehicle,
        safe_gap_m: float,
        cruise_speed_kmh: float,
    ) -> float:
        front_speed_kmh = max(0.0, front.snapshot.speed_mps * 3.6)
        safe_gap_m = max(0.1, safe_gap_m)
        gap_ratio = front.gap_m / safe_gap_m

        if gap_ratio >= 1.5:
            target = min(cruise_speed_kmh, front_speed_kmh + 4.0)
        elif gap_ratio >= 1.0:
            extra_speed = (gap_ratio - 1.0) * 4.0
            target = min(cruise_speed_kmh, front_speed_kmh + extra_speed)
        else:
            reduction = (1.0 - gap_ratio) * 8.0
            target = front_speed_kmh - reduction

        return max(0.0, min(cruise_speed_kmh, target))

    def _evaluate_obstacles(
        self,
        ego: VehicleSnapshot,
        context: BehaviorContext,
        cruise_speed_kmh: float,
        previous_state: DrivingState,
    ) -> Optional[DrivingDecision]:
        valid_obstacles = [
            obstacle
            for obstacle in context.obstacles
            if obstacle.in_path and obstacle.distance_m >= 0.0
        ]
        if not valid_obstacles:
            return None

        obstacle = min(valid_obstacles, key=lambda item: item.distance_m)
        distance_m = float(obstacle.distance_m)
        obstacle_speed_mps = max(0.0, float(obstacle.speed_mps))
        closing_speed = ego.speed_mps - obstacle_speed_mps
        ttc_s = self._ttc(
            gap_m=distance_m,
            closing_speed_mps=closing_speed,
        )

        if (
            distance_m <= self.config.emergency_gap_m
            or (
                ttc_s is not None
                and ttc_s <= self.config.emergency_ttc_s
            )
        ):
            return DrivingDecision(
                state=DrivingState.EMERGENCY_STOP,
                target_speed_kmh=0.0,
                reason="critical obstacle collision risk",
                brake_override=self.config.emergency_brake,
                ttc_s=ttc_s,
                obstacle_id=obstacle.obstacle_id,
                obstacle_distance_m=distance_m,
            )

        safe_gap_m = self._safe_gap(
            ego_speed_mps=ego.speed_mps,
            front_speed_mps=obstacle_speed_mps,
        )

        # --------------------------------------------------------
        # Latch OBSTACLE_STOP while the stopped obstacle remains.
        #
        # Without this latch, ego speed falls after the first stop
        # decision, dynamic safe_gap shrinks, and the state can fall
        # back to DECELERATE even though the obstacle is still there.
        # That also prevents the later OBSTACLE_STOP -> RESUME
        # transition when the obstacle is removed.
        # --------------------------------------------------------
        if (
            previous_state == DrivingState.OBSTACLE_STOP
            and obstacle_speed_mps <= self.config.stopped_speed_mps
        ):
            return DrivingDecision(
                state=DrivingState.OBSTACLE_STOP,
                target_speed_kmh=0.0,
                reason="holding for stopped obstacle",
                brake_override=self.config.wait_brake,
                safe_gap_m=safe_gap_m,
                ttc_s=ttc_s,
                obstacle_id=obstacle.obstacle_id,
                obstacle_distance_m=distance_m,
            )

        if (
            obstacle_speed_mps <= self.config.stopped_speed_mps
            and distance_m <= safe_gap_m
        ):
            return DrivingDecision(
                state=DrivingState.OBSTACLE_STOP,
                target_speed_kmh=0.0,
                reason="stopped obstacle inside safe gap",
                brake_override=self.config.wait_brake,
                safe_gap_m=safe_gap_m,
                ttc_s=ttc_s,
                obstacle_id=obstacle.obstacle_id,
                obstacle_distance_m=distance_m,
            )

        follow_start_m = max(
            self.config.follow_start_min_m,
            safe_gap_m * self.config.follow_start_factor,
        )

        if distance_m <= follow_start_m:
            ratio = max(0.0, min(1.0, distance_m / follow_start_m))
            target_speed = cruise_speed_kmh * ratio
            return DrivingDecision(
                state=DrivingState.DECELERATE,
                target_speed_kmh=target_speed,
                reason="obstacle inside deceleration zone",
                safe_gap_m=safe_gap_m,
                ttc_s=ttc_s,
                obstacle_id=obstacle.obstacle_id,
                obstacle_distance_m=distance_m,
            )

        return None

    @staticmethod
    def _effective_cruise_speed(context: BehaviorContext) -> float:
        cruise = max(0.0, float(context.cruise_speed_kmh))
        if context.speed_limit_kmh is not None:
            cruise = min(
                cruise,
                max(0.0, float(context.speed_limit_kmh)),
            )
        return cruise

    def _remember(
        self,
        ego: VehicleSnapshot,
        decision: DrivingDecision,
    ) -> DrivingDecision:
        self._previous_states[ego.vehicle_id] = decision.state
        return decision

    def reset_vehicle(self, vehicle_id: str) -> None:
        self._previous_states.pop(vehicle_id, None)

    def reset_all(self) -> None:
        self._previous_states.clear()

