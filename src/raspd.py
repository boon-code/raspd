#!/usr/bin/env python
import socket
import subprocess
import RPi.GPIO as gpio
import sys
import time
import threading
import logging
import logging.handlers

__author__ = 'Manuel Huber'
__copyright__ = "Copyright (c) 2014 Manuel Huber."
__version__ = '0.6b'
__docformat__ = "restructuredtext en"

_DEFAULT_LOG_FORMAT = "%(name)s : %(threadName)s : %(levelname)s \
: %(message)s"

_SYSLOG_FORMAT = "[raspd] %(name)s : %(levelname)s : %(message)s"

logging.basicConfig(stream=sys.stderr, format=_DEFAULT_LOG_FORMAT,
                    level=logging.DEBUG)
logging.debug("Start raspd")


class Udp(object):
    DEFAULT_SIZE = 1024

    def __init__(self, ip, port):
        self._ip = ip
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _get_settings(self, ip, port):
        if ip is None:
            ip = self._ip
        if port is None:
            port = self._port
        return (ip, port)

    def set_broadcast(self, enable=True):
        flag = 0
        if enable:
            flag = 1

        rc = self._sock.setsockopt(socket.SOL_SOCKET,
                                   socket.SO_BROADCAST,
                                   flag)
        return (rc == 0)

    def set_timeout(self, timeout=None):
        self._sock.settimeout(timeout)
    def broadcast(self, msg, port=None, addr=None):
        # TODO: Maybe add auto-enable for broadcasting...
        if addr is None:
            addr = self._get_settings(None, port)
        addr = ('<broadcast>', addr[1])
        self._sock.sendto(msg, addr)

    def bind(self, ip=None, port=None):
        addr = self._get_settings(ip, port)
        self._sock.bind(addr)

    def send(self, msg, ip=None, port=None, addr=None):
        if addr is None:
            addr = self._get_settings(ip, port)
        self._sock.sendto(msg, addr)

    def recv(self, size=None):
        if size is None:
            size = self.DEFAULT_SIZE
        data, addr = self._sock.recvfrom(size)
        return (data, addr)

    def close(self):
        self._sock.close()


class ShutdownMan(object):
    ST_RUNNING = 0
    ST_REQUEST_QUIT = 1
    ST_REQUEST_CANCEL = 2
    ST_WAIT_QUIT = 3
    ST_QUIT = 4
    TIMEOUT_PRESS_S = 1
    TIMEOUT_WAIT_S = 10

    def __init__ (self):
        self._state = self.ST_RUNNING
        self._lock = threading.RLock()
        self._log = logging.getLogger("shutdownd")
        self._to = None
        self._rq = 0

    def _timer_cancel (self):
        self._lock.acquire()
        try:
            if self._state == self.ST_REQUEST_CANCEL:
                self._log.info("Shutdown has been canceled")
                self._state = self.ST_RUNNING
                self._to = None
        finally:
            self._lock.release()

    def _timer_press (self):
        self._lock.acquire()
        try:
            if self._state == self.ST_REQUEST_QUIT:
                self._log.info("Wait for cancel button press")
                self._state = self.ST_WAIT_QUIT
                self._to = threading.Timer(self.TIMEOUT_WAIT_S,
                                           self._timer_sd)
                self._to.setName("timer-sd")
                self._to.start()
        finally:
            self._lock.release()

    def _timer_sd (self):
        do_sd = False
        self._lock.acquire()
        try:
            if self._state == self.ST_WAIT_QUIT:
                self._log.info("Shutting down...")
                self._state = self.ST_QUIT
                do_sd = True
                self._to = None
        finally:
            self._lock.release()
        if do_sd:
            self._log.info("Shutting down now")
            subprocess.call(["shutdown", "-hP", "now"])

    def __call__ (self, channel):
        self._lock.acquire()
        try:
            self._rq += 1
            self._log.debug("trigger #%d" % self._rq)
            if self._state == self.ST_RUNNING:
                self._log.info("Receive shutdown event")
                self._state = self.ST_REQUEST_QUIT
                self._to = threading.Timer(self.TIMEOUT_PRESS_S,
                                           self._timer_press)
                self._to.setName("timer-press")
                self._to.start()
            elif self._state == self.ST_WAIT_QUIT:
                self._log.info("Cancel shutdown request")
                self._state = self.ST_REQUEST_CANCEL
                if self._to is not None:
                    self._to.cancel()
                self._to = threading.Timer(self.TIMEOUT_PRESS_S,
                                           self._timer_cancel)
                self._to.setName("timer-cancel")
                self._to.start()
        finally:
            self._lock.release()

class GPIOTrigger (object):
    ST_WAIT = 0
    ST_EXECUTING = 1
    SHORT_TIMEOUT_S = 0.3

    def __init__ (self, func):
        self._state = self.ST_WAIT
        self._lock = threading.RLock()
        self._log = logging.getLogger("trigger")
        self._func = func
        self._rq = 0
        self._to = None

    def _reset (self):
        self._lock.acquire()
        try:
            self._log.info("Waiting for event")
            self._state = self.ST_WAIT
            self._to = None
        finally:
            self._lock.release()

    def _execute (self):
        try:
            self._func()
        finally:
            self._lock.acquire()
            try:
                self._to = threading.Timer(self.SHORT_TIMEOUT_S,
                                           self._reset)
                self._to.setName("trigger-reset")
                self._to.start()
            finally:
                self._lock.release()

    def __call__ (self, channel):
        execute = False
        self._lock.acquire()
        try:
            self._rq += 1
            self._log.debug("Trigger #%d" % self._rq)
            if self._state == self.ST_WAIT:
                self._state = self.ST_EXECUTING
                execute = True
        finally:
            self._lock.release()
        if execute:
            self._log.info("Execute payload")
            self._execute()


class StartStopTrigger (GPIOTrigger):
    def __init__ (self):
        GPIOTrigger.__init__(self, self._startstop)
        self._stop = True
        self._log = logging.getLogger("start-stop-trigger")

    def _startstop (self):
        if self._stop:
            self._log.info("Stop playback (if running)")
            subprocess.call(["mpc", "pause"])
        else:
            self._log.info("Start playback (if not running)")
            subprocess.call(["mpc", "play"])
        self._stop = not self._stop


class GPIOService (object):
    SHUTDOWN_GPIO = 18
    MPD_STOP_GPIO = 16
    DEBOUNCE_MS = 200
    isInitialized = False
    ST_UNREGISTERED = 0
    ST_REGISTERED = 1
    _log = logging.getLogger("gpio-service")

    @classmethod
    def initialize (cls, skip=False):
        if cls.isInitialized:
            if skip:
                cls._log.debug("GPIO's have already been initialized; skipping")
                return
            else:
                cls._log.warn("GPIO's have already been initialized; do it again")
        gpio.setmode(gpio.BOARD) # Use P1 header numbers
        gpio.setup(cls.SHUTDOWN_GPIO, gpio.IN, pull_up_down=gpio.PUD_UP)
        gpio.setup(cls.MPD_STOP_GPIO, gpio.IN, pull_up_down=gpio.PUD_UP)
        cls.isInitialized = True

    def __init__ (self):
        GPIOService.initialize(skip=True)
        self._state = self.ST_UNREGISTERED
        self._register_events()

    def _register_events (self):
        if self._state == self.ST_UNREGISTERED:
            self._log.info("Register shutdownd service")
            gpio.add_event_detect(self.SHUTDOWN_GPIO, gpio.FALLING,
                                  callback=ShutdownMan(),
                                  bouncetime=self.DEBOUNCE_MS)
            self._log.info("Register start-stop trigger service")
            gpio.add_event_detect(self.MPD_STOP_GPIO, gpio.FALLING,
                                  callback=StartStopTrigger(),
                                  bouncetime=self.DEBOUNCE_MS)
            self._state = self.ST_REGISTERED

    def _deregister_events (self):
        if self._state == self.ST_REGISTERED:
            self._log.info("Deregister all gpio services")
            gpio.remove_event_detect(self.SHUTDOWN_GPIO)
            gpio.remove_event_detect(self.MPD_STOP_GPIO)
            self._state = self.ST_UNREGISTERED

    def cleanup (self):
        self._log.debug("Clean-up")
        self._deregister_events()
        # Don't clean-up GPIO's, as it's better to keep them
        # configured as inputs with pull-ups

    def __del__ (self):
        self._deregister_events()


class ETHService (object):
    ST_DOWN = 0
    ST_UP = 1
    PORT = 4297
    BC_PORT = 4298
    TIMEOUT = 5

    def __init__ (self):
        self._udp = Udp('', self.BC_PORT)
        self._log = logging.getLogger("ethd")
        self._lock = threading.RLock()
        self._state = self.ST_DOWN
        self._log.info("Starting ETH Service")
        self._bind()

    def _bind (self):
        is_up = True
        try:
            self._udp.bind()
            self._udp.set_broadcast(True)
            self._udp.broadcast("[ethd]: Raspberry PI is UP",
                                port=self.PORT)
            self._udp.set_timeout(self.TIMEOUT)
        except:
            self._log.error("Caugth some exception (FIX THIS!)")
            self._log.info("Try binding again in 30 seconds")
            time.sleep(30)
        if is_up:
            self._lock.acquire()
            try:
                if self._state == self.ST_DOWN:
                    self._log.debug("ETH Service is UP now")
                    self._state = self.ST_UP
            finally:
                self._lock.release()

    def _update_udp (self):
        try:
            data, addr = self._udp.recv()
            self._log.debug("Got request from '%s' : '%s'"
                            % (addr, data))
            self._udp.send("[ethd]: Hello reply from PI", addr=addr)
        except socket.timeout:
            pass

    def update (self):
        status = self.ST_DOWN
        self._lock.acquire()
        try:
            status = self._state
            if self._state == self.ST_DOWN:
                self._log.debug("Try to bind")
                self._bind()
                status = self._state
        finally:
            self._lock.release()
        if status == self.ST_UP:
            self._update_udp()

    def close (self):
        self._udp.broadcast("[ethd]: Bye from PI")
        self._udp.close()


def enable_eth0 ():
    subprocess.call (["ifdown", "eth0"])
    subprocess.call (["ifup", "eth0"])


def main ():
    r = logging.getLogger()
    sysl = logging.handlers.SysLogHandler(address='/dev/log')
    sysl.setFormatter(logging.Formatter(_SYSLOG_FORMAT))
    sysl.setLevel(logging.INFO)
    r.addHandler(sysl)

    gpio_service = GPIOService()

    enable_eth0()
    eth_service = ETHService()

    try:
        while True:
            eth_service.update()
    except KeyboardInterrupt:
        logging.info("Caught keyboard interrupt!")
    finally:
        gpio_service.cleanup()
        eth_service.close()


if __name__ == '__main__':
    main()
