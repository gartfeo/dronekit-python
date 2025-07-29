from dronekit import connect, SystemStatus
from dronekit.test import with_sitl


@with_sitl
def test_state(connpath):
    vehicle = connect(connpath, wait_ready=['system_status'])

    assert isinstance(vehicle.system_status, SystemStatus)
    assert isinstance(vehicle.system_status.state, str)

    vehicle.close()
