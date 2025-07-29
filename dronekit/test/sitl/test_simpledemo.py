"""
This test represents a simple demo for testing.
Feel free to copy and modify at your leisure.
"""

from dronekit import connect, VehicleMode
from dronekit.test import with_sitl


# This test runs first!
@with_sitl
def test_parameter(connpath):
    v = connect(connpath, wait_ready=True)

    # Perform a simple parameter check
    assert isinstance(v.parameters['THR_MIN'], float)

    v.close()


# This test runs second. Add as many tests as you like
@with_sitl
def test_mode(connpath):
    v = connect(connpath, wait_ready=True)

    # Ensure Mode is an instance of VehicleMode
    assert isinstance(v.mode, VehicleMode)

    v.close()
