from __future__ import print_function

import logging
import time
import socket
import errno
import sys
import os
import platform
import copy
from dronekit import APIException
from pymavlink import mavutil
from queue import Queue, Empty
from threading import Thread

if platform.system() == 'Windows':
    from errno import WSAECONNRESET as ECONNABORTED
else:
    from errno import ECONNABORTED


class MAVWriter(object):
    """
    Indirection layer to take messages written to MAVlink and send them all
    on the same thread.
    """

    def __init__(self, queue):
        self._logger = logging.getLogger(__name__)
        self.queue = queue

    def write(self, pkt):
        self.queue.put(pkt)

    def read(self):
        self._logger.critical('writer should not have had a read request')
        os._exit(43)


class MAVSystem(mavutil.mavsource):
    def __init__(self, conn, target_system=0, target_component=0):
        self._logger = logging.getLogger(__name__)

        super(MAVSystem, self).__init__(conn.master, target_system, target_component)

        self.conn = conn
        self._message_listeners = []

        # at the moment we only use mavsource for sending messages to
        # the correct place.  Listening is currently done directly on
        # the upstream connection object:
        @conn.forward_message
        def listener(_, msg):
            src_system = msg.get_srcSystem()
            if src_system == self.system_id or src_system == 0 or src_system == 255:
                self.notify_message_listeners(msg)

    def remove_message_listener(self, name, fn):
        """
        Removes a message listener (that was previously added using :py:func:`add_message_listener`).
        See :ref:`mavlink_messages` for more information.
        :param String name: The name of the message for which the listener is to be removed (or '*' to remove an 'all messages' observer).
        :param fn: The listener callback function to remove.
        """
        name = str(name)
        if name in self._message_listeners:
            if fn in self._message_listeners[name]:
                self._message_listeners[name].remove(fn)
                if len(self._message_listeners[name]) == 0:
                    del self._message_listeners[name]

    def notify_message_listeners(self, msg):
        for fn in self._message_listeners:
            try:
                fn(self, msg)
            except Exception:
                self._logger.exception(f"Exception in message handler for {type(msg)}", exc_info=True)

    def start(self):
        self.conn.start()

    def alive(self):
        # should we check we've received a hearbeat from the system here?
        return self.conn._alive

    def request_data_stream(self, rate):
        self.mav.request_data_stream_send(self.system_id,
                                          self.component_id,
                                          mavutil.mavlink.MAV_DATA_STREAM_ALL,
                                          rate, 1)

    def forward_message(self, fn):
        """
        Decorator for message inputs.
        """
        self._message_listeners.append(fn)

    # APM discards information about the relative frame and treats any
    # alt value as relative. So we require relative positions for the
    # time being
    def simple_goto(self, lat, lon, alt, relative=False):
        if relative != True:
            raise APIException('relative positions required')

        self.mav.mission_item_send(self.system_id,
                                   self.component_id,
                                   0,
                                   mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                                   mavutil.mavlink.MAV_CMD_NAV_WAYPOINT, 2, 0, 0,
                                   0, 0, 0, lat, lon,
                                   alt)

    def fix_targets(self, message):
        """Set correct target IDs for our vehicle"""
        if hasattr(message, 'target_system'):
            message.target_system = self.system_id
        if hasattr(message, 'target_component'):
            message.target_component = self.component_id

    def pipe(self, out):
        '''Pipe *all* messages coming across vehicle connection into out.  This is deprecated in favour of calling pipe() on the connection itself'''
        return self.conn.pipe(out)


class mavudpin_multi(mavutil.mavfile):
    '''a UDP mavlink socket'''
    def __init__(self, device, baud=None, input=True, broadcast=False, source_system=255, source_component=0, use_native=mavutil.default_native):
        self._logger = logging.getLogger(__name__)
        a = device.split(':')
        if len(a) != 2:
            self._logger.critical("UDP ports must be specified as host:port")
            sys.exit(1)
        self.port = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_server = input
        self.broadcast = False
        self.addresses = set()
        if input:
            self.port.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.port.bind((a[0], int(a[1])))
        else:
            self.destination_addr = (a[0], int(a[1]))
            if broadcast:
                self.port.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                self.broadcast = True
        mavutil.set_close_on_exec(self.port.fileno())
        self.port.setblocking(False)
        mavutil.mavfile.__init__(self, self.port.fileno(), device, source_system=source_system, source_component=source_component, input=input, use_native=use_native)

    def close(self):
        self.port.close()

    def recv(self, n=None):
        try:
            try:
                data, new_addr = self.port.recvfrom(65535)
            except socket.error as e:
                if e.errno in [errno.EAGAIN, errno.EWOULDBLOCK, errno.ECONNREFUSED]:
                    return ""
            if self.udp_server:
                try:
                    self.addresses.add(new_addr)
                except:
                    return ""
            elif self.broadcast:
                self.addresses = {new_addr}
            return data
        except Exception:
            self._logger.exception("Exception while reading data", exc_info=True)

    def write(self, buf):
        try:
            try:
                if self.udp_server:
                    for addr in self.addresses:
                        self.port.sendto(buf, addr)
                else:
                    if len(self.addresses) and self.broadcast:
                        self.destination_addr = self.addresses[0]
                        self.broadcast = False
                        self.port.connect(self.destination_addr)
                    self.port.sendto(buf, self.destination_addr)
            except socket.error:
                pass
        except Exception:
            self._logger.exception("Exception while writing data", exc_info=True)

    def recv_msg(self):
        '''message receive routine for UDP link'''
        self.pre_message()
        s = self.recv()
        if len(s) > 0:
            if self.first_byte:
                self.auto_mavlink_version(s)

        m = self.mav.parse_char(s)
        if m is not None:
            self.post_message(m)

        return m


class MAVConnection(object):

    def stop_threads(self):
        if self.mavlink_thread_in is not None:
            self.mavlink_thread_in.join()
            self.mavlink_thread_in = None
        if self.mavlink_thread_out is not None:
            self.mavlink_thread_out.join()
            self.mavlink_thread_out = None

    def __init__(self, ip, baud=115200, source_system=255, source_component=0, use_native=False):
        self._logger = logging.getLogger(__name__)

        if ip.startswith("udpin:"):
            self.master = mavudpin_multi(ip[6:], input=True, baud=baud, source_system=source_system, source_component=source_component)
        else:
            self.master = mavutil.mavlink_connection(ip, baud=baud, source_system=source_system, source_component=source_component)

        # TODO get rid of "master" object as exposed,
        # keep it private, expose something smaller for dronekit
        self.out_queue = Queue()
        self.master.mav = mavutil.mavlink.MAVLink(
            MAVWriter(self.out_queue),
            srcSystem=self.master.source_system,
            srcComponent=self.master.source_component,
            use_native=use_native)

        # Listeners.
        self.loop_listeners = []
        self.message_listeners = []

        # Debug flag.
        self._accept_input = True
        self._alive = True
        self._death_error = None

        import atexit

        def onexit():
            self._alive = False
            self.stop_threads()

        atexit.register(onexit)

        # Heartbeats.
        self._heartbeat_lastsent = 0

        def mavlink_thread_out():
            # Huge try catch in case we see http://bugs.python.org/issue1856
            try:
                while self._alive:
                    try:
                        msg = self.out_queue.get(True, timeout=0.01)
                        self.master.write(msg)
                    except Empty:
                        continue
                    except socket.error as error:
                        # If connection reset (closed), stop polling.
                        if error.errno == ECONNABORTED:
                            raise APIException('Connection aborting during read')
                        raise
                    except Exception as e:
                        self._logger.exception('mav send error: %s' % str(e))
                        break
            except APIException as e:
                self._logger.exception("Exception in MAVLink write loop", exc_info=True)
                self._alive = False
                self.master.close()
                self._death_error = e

            except Exception as e:
                # http://bugs.python.org/issue1856
                if not self._alive:
                    pass
                else:
                    self._alive = False
                    self.master.close()
                    self._death_error = e

            # Explicitly clear out buffer so .close closes.
            self.out_queue = Queue()

        def mavlink_thread_in():
            # Huge try catch in case we see http://bugs.python.org/issue1856
            try:
                while self._alive:
                    # Loop listeners.
                    for fn in self.loop_listeners:
                        self.send_heartbeat()
                        fn(self)

                    # Sleep
                    self.master.select(0.05)

                    while self._accept_input:
                        if not self._alive:
                            break
                        try:
                            msg = self.master.recv_msg()
                        except socket.error as error:
                            # If connection reset (closed), stop polling.
                            if error.errno == ECONNABORTED:
                                raise APIException('Connection aborting during send')
                            raise
                        except mavutil.mavlink.MAVError as e:
                            # Avoid
                            #   invalid MAVLink prefix '73'
                            #   invalid MAVLink prefix '13'
                            self._logger.debug('mav recv error: %s' % str(e))
                            msg = None
                        except Exception:
                            # Log any other unexpected exception
                            self._logger.exception('Exception while receiving message: ', exc_info=True)
                            msg = None
                        if not msg:
                            break

                        # Message listeners.
                        for fn in self.message_listeners:
                            try:
                                fn(self, msg)
                            except Exception:
                                self._logger.exception(
                                    'Exception in message handler for %s' % msg.get_type(),
                                    exc_info=True
                                )

            except APIException as e:
                self._logger.exception('Exception in MAVLink input loop')
                self._alive = False
                self.master.close()
                self._death_error = e
                return

            except Exception as e:
                # http://bugs.python.org/issue1856
                if not self._alive:
                    pass
                else:
                    self._alive = False
                    self.master.close()
                    self._death_error = e

        t = Thread(target=mavlink_thread_in)
        t.daemon = True
        self.mavlink_thread_in = t

        t = Thread(target=mavlink_thread_out)
        t.daemon = True
        self.mavlink_thread_out = t

    def send_heartbeat(self):
        # Send 1 heartbeat per second
        if time.time() - self._heartbeat_lastsent > 1:
            #            print ("sending heartbeat %s" % str(self))
            self.master.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS,
                                           mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
            self._heartbeat_lastsent = time.time()

    def reset(self):
        self.out_queue = Queue()
        if hasattr(self.master, 'reset'):
            self.master.reset()
        else:
            try:
                self.master.close()
            except:
                pass
            self.master = mavutil.mavlink_connection(self.master.address)

    def forward_loop(self, fn):
        """
        Decorator for event loop.
        """
        self.loop_listeners.append(fn)

    def forward_message(self, fn):
        """
        Decorator for message inputs.
        """
        self.message_listeners.append(fn)

    def start(self):
        if not self.mavlink_thread_in.is_alive():
            self.mavlink_thread_in.start()
        if not self.mavlink_thread_out.is_alive():
            self.mavlink_thread_out.start()

    def close(self):
        # TODO this can block forever if parameters continue to be added
        self._alive = False
        while not self.out_queue.empty():
            time.sleep(0.1)
        self.stop_threads()
        self.master.close()

    # pipe all messages on this connection into target
    def pipe(self, target):

        # vehicle -> self -> target
        @self.forward_message
        def callback(_, msg):
            try:
                target.out_queue.put(msg.pack(target.master.mav))
            except:
                try:
                    assert len(msg.get_msgbuf()) > 0
                    target.out_queue.put(msg.get_msgbuf())
                except:
                    self._logger.exception('Could not pack this object on receive: %s' % type(msg), exc_info=True)

        # target -> self -> vehicle
        @target.forward_message
        def callback(_, msg):
            msg = copy.copy(msg)
            try:
                self.out_queue.put(msg.pack(self.master.mav))
            except:
                try:
                    assert len(msg.get_msgbuf()) > 0
                    self.out_queue.put(msg.get_msgbuf())
                except:
                    self._logger.exception('Could not pack this object on forward: %s' % type(msg), exc_info=True)

        return target
