from dronekit import connect
from dronekit.test import with_sitl


@with_sitl
def test_battery_none(connpath):
    vehicle = connect(connpath, _initialize=False)

    # Ensure we can get (possibly unpopulated) battery object without throwing error.
    assert vehicle.battery is None

    vehicle.initialize()

    # Ensure we can get battery object without throwing error.
    vehicle.wait_ready('battery')
    assert vehicle.battery is not None

    vehicle.close()
