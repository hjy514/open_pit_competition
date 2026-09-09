import unittest

from open_pit_competition.simulation.vehicle_behavior import (
    BehaviorContext,
    DrivingState,
    ObstacleSnapshot,
    VehicleBehavior,
    VehicleSnapshot,
)


class VehicleBehaviorTest(unittest.TestCase):

    def setUp(self):

        self.behavior = VehicleBehavior()

        self.ego = VehicleSnapshot(
            vehicle_id="truck_01",
            x=0.0,
            y=0.0,
            z=0.0,
            yaw_deg=0.0,
            speed_mps=15.0 / 3.6,
        )

        self.context = BehaviorContext(
            cruise_speed_kmh=25.0
        )


    def test_free_drive(self):

        decision = self.behavior.decide(
            self.ego,
            [],
            self.context,
        )

        self.assertEqual(
            decision.state,
            DrivingState.CRUISE,
        )

        self.assertEqual(
            decision.target_speed_kmh,
            25.0,
        )


    def test_follow_front_vehicle(self):

        front = VehicleSnapshot(
            vehicle_id="truck_02",
            x=30.0,
            y=0.0,
            z=0.0,
            yaw_deg=0.0,
            speed_mps=10.0 / 3.6,
        )

        decision = self.behavior.decide(
            self.ego,
            [front],
            self.context,
        )

        self.assertIn(
            decision.state,
            {
                DrivingState.FOLLOW,
                DrivingState.DECELERATE,
            },
        )

        self.assertEqual(
            decision.front_vehicle_id,
            "truck_02",
        )


    def test_wait_for_stopped_front_vehicle(self):

        front = VehicleSnapshot(
            vehicle_id="truck_02",
            x=20.0,
            y=0.0,
            z=0.0,
            yaw_deg=0.0,
            speed_mps=0.0,
        )

        decision = self.behavior.decide(
            self.ego,
            [front],
            self.context,
        )

        self.assertEqual(
            decision.state,
            DrivingState.WAIT_FRONT,
        )

        self.assertEqual(
            decision.target_speed_kmh,
            0.0,
        )


    def test_resume_after_front_vehicle_moves(self):

        stopped = VehicleSnapshot(
            vehicle_id="truck_02",
            x=20.0,
            y=0.0,
            z=0.0,
            yaw_deg=0.0,
            speed_mps=0.0,
        )

        self.behavior.decide(
            self.ego,
            [stopped],
            self.context,
        )

        moving = VehicleSnapshot(
            vehicle_id="truck_02",
            x=20.0,
            y=0.0,
            z=0.0,
            yaw_deg=0.0,
            speed_mps=3.0 / 3.6,
        )

        decision = self.behavior.decide(
            self.ego,
            [moving],
            self.context,
        )

        self.assertEqual(
            decision.state,
            DrivingState.RESUME,
        )


    def test_emergency_obstacle_stop(self):

        obstacle = ObstacleSnapshot(
            obstacle_id="rock_01",
            distance_m=2.0,
        )

        context = BehaviorContext(
            cruise_speed_kmh=25.0,
            obstacles=(obstacle,),
        )

        decision = self.behavior.decide(
            self.ego,
            [],
            context,
        )

        self.assertEqual(
            decision.state,
            DrivingState.EMERGENCY_STOP,
        )

        self.assertEqual(
            decision.brake_override,
            1.0,
        )


    def test_fault_stop(self):

        failed = VehicleSnapshot(
            vehicle_id="truck_01",
            x=0.0,
            y=0.0,
            z=0.0,
            yaw_deg=0.0,
            speed_mps=5.0,
            healthy=False,
        )

        decision = self.behavior.decide(
            failed,
            [],
            self.context,
        )

        self.assertEqual(
            decision.state,
            DrivingState.FAULT_STOP,
        )


    def test_road_hold(self):

        context = BehaviorContext(
            cruise_speed_kmh=25.0,
            road_open=False,
        )

        decision = self.behavior.decide(
            self.ego,
            [],
            context,
        )

        self.assertEqual(
            decision.state,
            DrivingState.ROAD_HOLD,
        )


    def test_yield(self):

        context = BehaviorContext(
            cruise_speed_kmh=25.0,
            yield_required=True,
            yield_reason="opposite_vehicle_priority",
        )

        decision = self.behavior.decide(
            self.ego,
            [],
            context,
        )

        self.assertEqual(
            decision.state,
            DrivingState.YIELD,
        )


if __name__ == "__main__":
    unittest.main()
