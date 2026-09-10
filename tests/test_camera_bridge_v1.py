from pathlib import Path
import importlib.util


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "camera_bridge.py"


def load_module():
    spec = importlib.util.spec_from_file_location("camera_bridge_test", str(SCRIPT))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_target_role_names_are_stable():
    module = load_module()
    config = {
        "vehicle_ids": [
            "truck_1",
            "truck_2",
            "truck_3",
            "truck_4",
            "truck_5",
            "truck_6",
        ]
    }
    assert module.target_role_names(config) == [
        "truck_1",
        "truck_2",
        "truck_3",
        "truck_4",
        "truck_5",
        "truck_6",
    ]


def test_frame_path_is_per_vehicle(tmp_path):
    module = load_module()
    assert module.frame_path(tmp_path, "truck_3") == (
        tmp_path / "truck_3_latest.png"
    )


def test_camera_config_is_python37_safe_and_complete():
    module = load_module()
    project = Path(__file__).resolve().parents[1]
    config = module.load_json(
        project / "configs" / "dashboard_camera_bridge.json"
    )

    assert len(config["vehicle_ids"]) == 6
    assert config["vehicle_ids"][0] == "truck_1"
    assert config["vehicle_ids"][-1] == "truck_6"
    assert config["image_width"] == 640
    assert config["image_height"] == 360
    assert 1.0 <= float(config["fps"]) <= 10.0
    assert config["vehicle_camera"]["mode"] == "legacy_adaptive_chase"
    assert config["vehicle_camera"]["min_follow_distance_m"] == 20.0
    assert config["vehicle_camera"]["min_height_m"] == 10.0


class DummyExtent:
    def __init__(self, x, z):
        self.x = x
        self.z = z


class DummyBoundingBox:
    def __init__(self, x, z):
        self.extent = DummyExtent(x, z)


class DummyActor:
    def __init__(self, half_length, half_height):
        self.bounding_box = DummyBoundingBox(half_length, half_height)


class DummyLocation:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = x
        self.y = y
        self.z = z


class DummyRotation:
    def __init__(self, pitch=0.0, yaw=0.0, roll=0.0):
        self.pitch = pitch
        self.yaw = yaw
        self.roll = roll


class DummyTransform:
    def __init__(self, location, rotation):
        self.location = location
        self.rotation = rotation


class DummyCarla:
    Location = DummyLocation
    Rotation = DummyRotation
    Transform = DummyTransform


def test_adaptive_chase_uses_old_project_minimums():
    module = load_module()
    actor = DummyActor(half_length=4.0, half_height=2.0)
    transform = module.adaptive_chase_transform(
        DummyCarla,
        actor,
        {
            "min_follow_distance_m": 20.0,
            "extra_follow_distance_m": 8.0,
            "min_height_m": 10.0,
            "extra_height_m": 7.0,
            "pitch": -16.0,
        },
    )
    assert transform.location.x == -20.0
    assert transform.location.z == 10.0
    assert transform.rotation.pitch == -16.0


def test_adaptive_chase_scales_for_large_cat_body():
    module = load_module()
    actor = DummyActor(half_length=8.0, half_height=4.5)
    transform = module.adaptive_chase_transform(
        DummyCarla,
        actor,
        {
            "min_follow_distance_m": 20.0,
            "extra_follow_distance_m": 8.0,
            "min_height_m": 10.0,
            "extra_height_m": 7.0,
            "pitch": -16.0,
        },
    )
    assert transform.location.x == -24.0
    assert transform.location.z == 11.5
    assert transform.rotation.pitch == -16.0
