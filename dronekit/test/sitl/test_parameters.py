import time
from dronekit import connect
from dronekit.test import with_sitl


@with_sitl
def test_parameters(connpath):
    vehicle = connect(connpath)

    # When called on startup, parameter (may!) be none.
    # assert_equals(vehicle.parameters.get('THR_MIN', wait_ready=False), None)

    # With wait_ready, it should not be none.
    assert vehicle.paramaters.get('THR_MIN', wait_ready=True) is not None

    try:
        assert vehicle.parameters['THR_MIN'] is not None
    except:
        assert False

    # Garbage value after all parameters are downloaded should be None.
    assert vehicle.parameters.get('xXx_extreme_garbage_value_xXx', wait_ready=False) is None

    vehicle.close()


@with_sitl
def test_iterating(connpath):
    vehicle = connect(connpath, wait_ready=True)

    # Iterate over parameters.
    for k, v in vehicle.parameters.items():
        break
    for key in vehicle.parameters:
        break

    vehicle.close()


@with_sitl
def test_setting(connpath):
    vehicle = connect(connpath, wait_ready=True)

    assert vehicle.parameters['THR_MIN'] is not None

    result = {'success': False}

    @vehicle.parameters.on_attribute('THR_MIN')
    def listener(self, name, value):
        result['success'] = (name == 'THR_MIN' and value == 3.000)

    vehicle.parameters['THR_MIN'] = 3.000

    # Wait a bit.
    i = 5
    while not result['success'] and i > 0:
        time.sleep(1)
        i = i - 1

    assert result['success']

    vehicle.close()
