import time
from dronekit import connect
from dronekit.test import with_sitl


def current_milli_time():
    return int(round(time.time() * 1000))


@with_sitl
def test_timeout(connpath):
    v = connect(connpath, wait_ready=True)

    value = v.parameters['THR_MIN']
    assert isinstance(value, float)

    start = current_milli_time()
    v.parameters['THR_MIN'] = value + 10
    end = current_milli_time()

    newvalue = v.parameters['THR_MIN']
    assert isinstance(newvalue, float)
    assert newvalue == value + 10

    # Checks that time to set parameter was <1s
    # see https://github.com/dronekit/dronekit-python/issues/12
    assert end - start < 1000, 'time to set parameter was %s, over 1s' % (end - start, )

    v.close()
