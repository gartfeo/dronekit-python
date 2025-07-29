from dronekit import VehicleMode


def test_vehicle_mode_eq():
    assert VehicleMode('GUIDED') == VehicleMode('GUIDED')

def test_vehicle_mode_neq():
    assert VehicleMode('AUTO') != VehicleMode('GUIDED')