from dronekit import connect
from dronekit.test import with_sitl


@with_sitl
def test_modes_set(connpath):
    vehicle = connect(connpath)

    def listener(self, name, m):
        assert self._flightmode == 'STABILIZE'

    vehicle.add_message_listener('HEARTBEAT', listener)

    vehicle.close()
