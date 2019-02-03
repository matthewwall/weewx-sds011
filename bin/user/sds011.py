#!/usr/bin/env python
# Copyright 2019 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)

"""Driver for collecting data from SDS011 particulate sensor.

Credits:

2017 Martin Lutzelberger
  https://github.com/luetzel/sds011/blob/master/sds011_pylab.py

2016 Frank Heuer
  https://gitlab.com/frankrich/sds011_particle_sensor

2018 zefanja
  https://github.com/zefanja/aqi/
"""

import struct
import syslog
import time

import weewx
import weewx.drivers


DRIVER_NAME = 'SDS011'
DRIVER_VERSION = '0.1'


def logmsg(dst, msg):
    syslog.syslog(dst, 'SDS011: %s' % msg)

def logdbg(msg):
    logmsg(syslog.LOG_DEBUG, msg)

def loginf(msg):
    logmsg(syslog.LOG_INFO, msg)

def logerr(msg):
    logmsg(syslog.LOG_ERR, msg)


def loader(config_dict, _):
    return CM1Driver(**config_dict[DRIVER_NAME])

def confeditor_loader():
    return SDS011ConfEditor()


class SDS011ConfEditor(weewx.drivers.AbstractConfEditor):
    @property
    def default_stanza(self):
        return """
[SDS011]
    # This section is for SDS011 particulate sensors.

    model = NovaPM

    port = /dev/ttyUSB0

    # How often to poll the device, in seconds
    poll_interval = 10

    # The driver to use
    driver = user.sds011
"""

    def prompt_for_settings(self):
        print "Specify the serial port on which the sensor is connected, for"
        print "example /dev/ttyUSB0 or /dev/ttyS0 or /dev/tty.usbserial"
        port = self._prompt('port', '/dev/ttyUSB0')
        return {'port': port}


class SDS011Driver(weewx.drivers.AbstractDevice):

    def __init__(self, **stn_dict):
        loginf('driver version is %s' % DRIVER_VERSION)
        self.model = stn_dict.get('model', 'NovaPM')
        loginf("model is %s" % self.model)
        port = stn_dict.get('port', SDS011.DEFAULT_PORT)
        loginf("port is %s" % port)
        timeout = int(stn_dict.get('timeout', SDS011.DEFAULT_TIMEOUT))
        self.poll_interval = int(stn_dict.get('poll_interval', 10))
        loginf("poll interval is %s" % self.poll_interval)
        self.max_tries = int(stn_dict.get('max_tries', 3))
        self.retry_wait = int(stn_dict.get('retry_wait', 5))
        self.sensor = SDS011(port, timeout)

    @property
    def hardware_name(self):
        return self.model

    def closePort(self):
        self.station.serial.close()
        self.station = None

    def genLoopPackets(self):
        while True:
            data = self._get_with_retries('get_current')
            logdbg("raw data: %s" % data)
            pkt = dict()
            pkt['dateTime'] = int(time.time() + 0.5)
            pkt['usUnits'] = weewx.METRICWX
            for k in self.sensor_map:
                if self.sensor_map[k] in data:
                    pkt[k] = data[self.sensor_map[k]]
            yield pkt
            if self.poll_interval:
                time.sleep(self.poll_interval)

    def _get_with_retries(self, method):
        for n in range(self.max_tries):
            try:
                return getattr(self.station, method)()
            except (IOError, ValueError, TypeError), e:
                loginf("failed attempt %s of %s: %s" %
                       (n + 1, self.max_tries, e))
                time.sleep(self.retry_wait)
        else:
            raise weewx.WeeWxIOError("%s: max tries %s exceeded" %
                                     (method, self.max_tries))


def _fmt(x):
    return ' '.join(["%0.2X" % ord(c) for c in x])


class SDS011(object):
    DEFAULT_PORT = '/dev/ttyUSB0'
    DEFAULT_BAUDRATE = 9600
    DEFAULT_TIMEOUT = 3.0 # seconds

    def __init__(self, port, timeout=DEFAULT_TIMEOUT):
        self.port = port
        self.baudrate = self.DEFAULT_BAUDRATE
        self.timeout = timeout
        self.serial_port = None

    def __enter__(self):
        return self

    def __exit__(self, _, value, traceback):
        pass

    def open(self):
        import serial
        self.serial_port = serial.Serial(port=self.port,
                                         baudrate=self.baudrate,
                                         timeout=self.timeout)
        self.serial_port.open()
        self.serial_port.flushInput()

    def close(self):
        if self.serial_port:
            self.serial_port.close()
            self.serial_port = None

    def sensor_wake(self):
        cmd = ['\xaa', # head
               '\xb4', # command 1
               '\x06', # data byte 1
               '\x01', # data byte 2 (set mode)
               '\x01', # data byte 3 (sleep)
               '\x00', # data byte 4
               '\x00', # data byte 5
               '\x00', # data byte 6
               '\x00', # data byte 7
               '\x00', # data byte 8
               '\x00', # data byte 9
               '\x00', # data byte 10
               '\x00', # data byte 11
               '\x00', # data byte 12
               '\x00', # data byte 13
               '\xff', # data byte 14 (device id byte 1)
               '\xff', # data byte 15 (device id byte 2)
               '\x05', # checksum
               '\xab'] # tail
        for b in cmd:
            self.serial_port.write(b)

    def sensor_sleep(self):
        cmd = ['\xaa', # head
               '\xb4', # command 1
               '\x06', # data byte 1
               '\x01', # data byte 2 (set mode)
               '\x00', # data byte 3 (sleep)
               '\x00', # data byte 4
               '\x00', # data byte 5
               '\x00', # data byte 6
               '\x00', # data byte 7
               '\x00', # data byte 8
               '\x00', # data byte 9
               '\x00', # data byte 10
               '\x00', # data byte 11
               '\x00', # data byte 12
               '\x00', # data byte 13
               '\xff', # data byte 14 (device id byte 1)
               '\xff', # data byte 15 (device id byte 2)
               '\x05', # checksum
               '\xab'] # tail
        for b in cmd:
            self.serial_port.write(b)

    def sensor_read(self):
        x = 0
        while x != "\xaa":
            x = self.serial_port.read(size=1)
            data = self.serial_port.read(size=10)
            print _fmt(data)
            if data[0] == "\xc0":
                return x + data
        return None

    def get_current(self):
        data = dict()
        raw = self.sensor_read()
        if raw:
            r = struct.unpack('<HHxxBBB', raw[2:])
            checksum = sum(ord(v) for v in raw[2:8]) % 256
            data['pm25'] = r[0] / 10.0
            data['pm10'] = r[1] / 10.0
        return data


if __name__ == '__main__':
    import optparse

    usage = """%prog [options] [--debug] [--help]"""

    syslog.openlog('wee_sds011', syslog.LOG_PID | syslog.LOG_CONS)
    parser = optparse.OptionParser(usage=usage)
    parser.add_option('--version', dest='version', action='store_true',
                      help='display driver version')
    parser.add_option('--debug', dest='debug', action='store_true',
                      help='display diagnostic information while running')
    parser.add_option('--port', dest='port', metavar='PORT',
                      help='serial port to which the station is connected',
                      default=SDS011.DEFAULT_PORT)
    parser.add_option('--timeout', dest='timeout', metavar='TIMEOUT',
                      help='modbus timeout, in seconds', type=int,
                      default=SDS011.DEFAULT_TIMEOUT)
    (options, _) = parser.parse_args()

    if options.version:
        print "driver version %s" % DRIVER_VERSION
        exit(1)

    if options.debug is not None:
        syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_DEBUG))
    else:
        syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_INFO))

    s = SDS011(options.port, options.timeout)
    s.open()
    while True:
        print "wake sensor"
        s.sensor_wake()
        print "wait 10 seconds"
        time.sleep(10)
        print "read sensor"
        print s.get_current()
