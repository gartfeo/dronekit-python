import time

from dronekit import connect
from dronekit.test import with_sitl


@with_sitl
def test_115(connpath):
    v = connect(connpath, wait_ready=True)
    time.sleep(5)
    assert v.capabilities.ftp is False

    # versions of ArduCopter prior to v3.3 will send out capabilities
    # flags before they are initialised.  Vehicle attempts to refetch
    # until capabilities are non-zero, but we may need to wait:
    start_time = time.time()
    slept = False
    while v.capabilities.mission_float == 0:
        if time.time() > start_time + 30:
            break
        time.sleep(0.1)
        slept = True
    if v.capabilities.mission_float:
        if slept:
            assert v.version.major <= 3
            assert v.version.minor <= 3
    else:
        # fail it
        assert v.capabilities.mission_float is True

    assert v.version.major is not None
    assert len(v.version.release_type()) >= 2
    assert v.version.release_version() is not None

    v.close()
