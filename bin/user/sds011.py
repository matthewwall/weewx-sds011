#!/usr/bin/env python
# Copyright 2019 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)

"""Driver for collecting data from SDS011 particulate sensor.

Apparently if you poll the device too often you will get bogus data.

Credits:

2016 Frank Heuer
  https://gitlab.com/frankrich/sds011_particle_sensor

2017 Martin Lutzelberger
  https://github.com/luetzel/sds011/blob/master/sds011_pylab.py

2018 zefanja
  https://github.com/zefanja/aqi/
"""

import struct
import syslog
import time

import weewx
import weewx.drivers
import weewx.units


DRIVER_NAME = 'SDS011'
DRIVER_VERSION = '0.2'


printlog = False

def logmsg(dst, msg):
    msg = 'SDS011: %s' % msg
    if printlog:
        print(msg)
    syslog.syslog(dst, msg)

def logdbg(msg):
    logmsg(syslog.LOG_DEBUG, msg)

def loginf(msg):
    logmsg(syslog.LOG_INFO, msg)

def logerr(msg):
    logmsg(syslog.LOG_ERR, msg)


def loader(config_dict, _):
    return SDS011Driver(**config_dict[DRIVER_NAME])

def confeditor_loader():
    return SDS011ConfEditor()


schema = [
    ('dateTime', 'INTEGER NOT NULL PRIMARY KEY'),
    ('usUnits', 'INTEGER NOT NULL'),
    ('interval', 'INTEGER NOT NULL'),
    ('pm2_5', 'REAL'),
    ('pm10_0', 'REAL'),
]

# set up appropriate units
weewx.units.USUnits['group_concentration'] = 'microgram_per_meter_cubed'
weewx.units.MetricUnits['group_concentration'] = 'microgram_per_meter_cubed'
weewx.units.MetricWXUnits['group_concentration'] = 'microgram_per_meter_cubed'
weewx.units.default_unit_format_dict['microgram_per_meter_cubed'] = '%.3f'
weewx.units.default_unit_label_dict['microgram_per_meter_cubed']  = ' \xc2\xb5g/m\xc2\xb3'

# assign types of units to specific measurements
weewx.units.obs_group_dict['pm2_5'] = 'group_concentration'
weewx.units.obs_group_dict['pm10_0'] = 'group_concentration'

class SDS011ConfEditor(weewx.drivers.AbstractConfEditor):
    @property
    def default_stanza(self):
        return """
[SDS011]
    # This section is for SDS011 particulate sensors.

    model = NovaPM

    port = /dev/ttyUSB0

    # How often to poll the device, in seconds (do not set lower than 10)
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
        self.poll_interval = int(stn_dict.get('poll_interval', 30))
        loginf("poll interval is %s" % self.poll_interval)
        if self.poll_interval < 10:
            loginf("warning: short poll interval may result in bad data")
        self.max_tries = int(stn_dict.get('max_tries', 3))
        self.retry_wait = int(stn_dict.get('retry_wait', 5))
        self.sensor = SDS011(port, timeout)
        self.sensor.open()

    @property
    def hardware_name(self):
        return self.model

    def closePort(self):
        self.sensor.close()
        self.sensor = None

    def genLoopPackets(self):
        while True:
            pm2_5, pm10_0 = self._get_with_retries()
            logdbg("data: %s %s" % (pm2_5, pm10_0))
            pkt = dict()
            pkt['dateTime'] = int(time.time() + 0.5)
            pkt['usUnits'] = weewx.METRICWX
            pkt['pm2_5'] = pm2_5
            pkt['pm10_0'] = pm10_0
            yield pkt
            if self.poll_interval:
                time.sleep(self.poll_interval)

    def _get_with_retries(self):
        for n in range(self.max_tries):
            try:
                return self.sensor.get_data()
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
    CMD_MODE = 2
    CMD_QUERY_DATA = 4
    CMD_DEVICE_ID = 5
    CMD_SLEEP = 6
    CMD_FIRMWARE = 7
    CMD_WORKING_PERIOD = 8
    MODE_ACTIVE = 0
    MODE_QUERY = 1

    def __init__(self, port, timeout=DEFAULT_TIMEOUT):
        self.port = port
        self.baudrate = self.DEFAULT_BAUDRATE
        self.timeout = timeout
        self.serial_port = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, _, value, traceback):
        self.close()

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

    @staticmethod
    def _chksum(raw):
        return sum(ord(v) for v in raw[2:8]) % 256

    @staticmethod
    def _cmd(cmd, data=[]):
        # a command is a string of 19 bytes with this format:
        #
        # 0xaa 0xb4 cmd data 0xff 0xff chksum 0xab
        #
        # where:
        #  cmd is a single byte
        #  data is 12 bytes or less
        #  chksum is a single byte
        data += [0,] * (12 - len(data))
        chksum = (sum(data) + cmd - 2) % 256
        ret = "\xaa\xb4" + chr(cmd)
        ret += ''.join(chr(x) for x in data)
        ret += "\xff\xff" + chr(chksum) + "\xab"
        return ret

    @staticmethod
    def parse_data(raw):
        r = struct.unpack('<HHxxBB', raw[2:])
        pm2_5 = r[0] / 10.0 # ug/m^3
        pm10_0 = r[1] / 10.0 # ug/m^3
        chksum = SDS011._chksum(raw)
        return [pm2_5, pm10_0]

    @staticmethod
    def parse_version(raw):
        r = struct.unpack('<BBBHBB', raw[3:])
        fwver = "20%s-%s-%s %s" % (r[0], r[1], r[2], hex(r[3]))
        chksum = SDS011._chksum(raw)
        return fwver

    def write_command(self, cmd, data=[]):
        x = SDS011._cmd(cmd, data)
        logdbg("write: %s" % _fmt(x))
        self.serial_port.write(x)

    def read_bytes(self):
        x = 0
        while x != "\xaa":
            x = self.serial_port.read(size=1)
        data = self.serial_port.read(size=9)
        logdbg("read: %s" % _fmt(data))
        return x + data

    def get_firmware_version(self):
        self.write_command(SDS011.CMD_FIRMWARE)
        raw = self.read_bytes()
        return SDS011.parse_version(raw)

    def get_data(self):
        self.write_command(SDS011.CMD_QUERY_DATA)
        raw = self.read_bytes()
        return SDS011.parse_data(raw)

    def set_sleep(self, period=1):
        mode = 0 if period else 1
        self.write_command(SDS011.CMD_SLEEP, [0x1, mode])
        raw = self.read_bytes()

    def set_working_period(self, period):
        self.write_command(SDS011.CMD_WORKING_PERIOD, [0x1, period])
        raw = self.read_bytes()

    def set_mode(self, mode=MODE_QUERY):
        self.write_command(SDS011.CMD_MODE, [0x1, mode])
        raw = self.read_bytes()

    def set_id(self, device_id):
        id_hi = (device_id >> 8) % 256
        id_lo = device_id % 256
        self.write_command(SDS011.CMD_DEVICE_ID, [0] * 10 + [id_lo, id_hi])
        raw = self.read_bytes()

    def sensor_wake(self):
        self.set_sleep(0)

    def sensor_sleep(self):
        self.set_sleep(1)


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
                      help='serial timeout, in seconds', type=int,
                      default=SDS011.DEFAULT_TIMEOUT)
    parser.add_option('--poll-interval', metavar='PERIOD', type=int, default=10,
                      help='how often to poll for data, in seconds')
    parser.add_option('--info', action='store_true',
                      help='display device information')
    parser.add_option('--set-id', metavar='ID', type=int, dest='device_id',
                      help='set device identifier')
    parser.add_option('--set-mode', metavar='MODE', dest='device_mode',
                      help='set the mode to active or query')
    parser.add_option('--set-sleep', metavar='PERIOD', type=int, dest='sleep',
                      help='set sleep period, in seconds')
    parser.add_option('--set-work', metavar='PERIOD', type=int, dest='work',
                      help='set working period, in seconds')
    (options, _) = parser.parse_args()

    if options.version:
        print "driver version %s" % DRIVER_VERSION
        exit(1)

    if options.debug is not None:
        printlog = True
        syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_DEBUG))
    else:
        syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_INFO))

    s = SDS011(options.port, options.timeout)
    s.open()

    if options.info:
        print("firmware: %s" % s.get_firmware_version())
        exit(0)

    if options.device_id is not None:
        print("set id to %s" % options.device_id)
        s.set_id(options.device_id)
    elif options.device_mode is not None:
        print("set mode to %s" % options.device_mode)
        s.set_mode(options.device_mode)
    elif options.sleep is not None:
        print("set sleep to %s" % options.sleep)
        s.set_sleep(options.sleep)
    elif options.work is not None:
        print("set work to %s" % options.work)
        s.set_work(options.work)
    else:
        while True:
            s.sensor_wake()
            time.sleep(options.poll_interval)
            pm2_5, pm10_0 = s.get_data()
            print("pm2_5=%s pm10_0=%s" % (pm2_5, pm10_0))
