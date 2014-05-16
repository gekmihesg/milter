#!/usr/bin/python2
#
# Header renaming milter
# Copyright (C) 2014  Markus Weippert
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# v0.2 - 2014-05-16 - markus@gekmihesg.de
#   * RenameConfig class
#
# v0.1 - 2014-05-14 - markus@gekmihesg.de
#

import sys
import os
import re
import Milter
from syslog import *
from ConfigParser import RawConfigParser as ConfigParser
from Milter.utils import parse_header


milter_name = 'RenameMilter'
syslog_name = 'rename-milter'
config_file = '/etc/milter/rename.conf'


class RenameHeader(object):
    def __init__(self, pattern):
        self.pattern = pattern
        self.reset()

    def reset(self):
        self.count = 0
        self.occurences = []

    def check(self, value):
        return not self.pattern or \
                self.pattern.match(parse_header(value))

    def add(self, name, value, pos):
        self.count += 1
        if self.check(value):
            self.occurences.append((name, value, self.count, pos))
            return True
        return False


class RenameMilter(Milter.Base):
    def __init__(self, headers, marker, prefix):
        self.id = Milter.uniqueID()
        self.headers = {}
        for name, pattern in headers.iteritems():
            self.headers[name] = RenameHeader(pattern)
        self.marker = marker
        self.prefix = prefix
        self.message_count = 0
        self.reset()
        self.log(LOG_DEBUG, 'instance %d initialized' %(self.id))

    def reset(self):
        self.header_count = 0
        self.received_pos = 0
        self.message_count += 1

    @Milter.noreply
    def connect(self, hostname, *args, **kwargs):
        self.log(LOG_INFO, 'new connection from %s' %(hostname))
        return Milter.CONTINUE

    def header(self, name, value):
        self.header_count += 1
        nl = name.lower()
        if nl == self.marker and not self.received_pos:
            self.received_pos = self.header_count
            self.log(LOG_DEBUG, 'marking position %d as start' %(self.header_count))
        elif self.headers.has_key(nl):
            if self.headers[nl].add(name, value, self.header_count):
                self.log(LOG_DEBUG, 'matching %s at position %d' %(nl, self.header_count))
            else:
                self.log(LOG_DEBUG, 'not matching %s at postition %d' %(nl, self.header_count))
        return Milter.CONTINUE

    def eom(self):
        for nl, hdr in self.headers.iteritems():
            deleted = 0
            for name, value, idx, pos in hdr.occurences:
                if pos > self.received_pos:
                    self.addheader(self.prefix + name, value, pos + 1)
                    self.chgheader(name, idx - deleted, None)
                    deleted += 1
                    self.log(LOG_DEBUG, 'renaming %s at position %d' %(nl, pos))
            self.log(LOG_NOTICE if deleted else LOG_INFO,
                    'renamed %d %s headers in message %d' %(deleted, nl, self.message_count))
            hdr.reset()
        self.log(LOG_INFO, 'end of message %d' %(self.message_count))
        self.reset()
        return Milter.CONTINUE

    def close(self):
        self.log(LOG_INFO, 'disconnected after %d message(s)' %(self.message_count - 1))
        return Milter.CONTINUE

    def log(self, prio, msg):
        syslog(prio, '%d: %s' %(self.id, msg))


class RenameConfig(object):
    cfg_map = {
            'logfacility': { 'kern': LOG_KERN, 'user': LOG_USER, 'mail': LOG_MAIL,
                    'daemon': LOG_DAEMON, 'auth': LOG_AUTH, 'lpr': LOG_LPR, 'news': LOG_NEWS,
                    'uucp': LOG_UUCP, 'cron': LOG_CRON, 'syslog': LOG_SYSLOG, 
                    'local0': LOG_LOCAL0, 'local1': LOG_LOCAL1, 'local2': LOG_LOCAL2,
                    'local3': LOG_LOCAL3, 'local4': LOG_LOCAL4, 'local5': LOG_LOCAL5,
                    'local6': LOG_LOCAL6, 'local7': LOG_LOCAL7,
                },
            'loglevel': { 'emerg': LOG_EMERG, 'alert': LOG_ALERT, 'crit': LOG_CRIT,
                    'err': LOG_ERR, 'warning': LOG_WARNING, 'notice': LOG_NOTICE,
                    'info': LOG_INFO, 'debug': LOG_DEBUG,
                },
        }

    def __init__(self, filename, section):
        assert os.path.exists(filename), 'file not found'
        self.filename = filename
        self.cfg = {
                'socket': '/var/spool/postfix/milter/rename.sock',
                'umask': '002',
                'timeout': 600,
                'marker': 'Received',
                'prefix': 'X-Original-',
                'logfacility': LOG_MAIL,
                'loglevel': LOG_NOTICE,
            }
        cfg = ConfigParser(allow_no_value=True)
        cfg.read(self.filename)
        for key in self.cfg.iterkeys():
            if not cfg.has_option(section, key): continue
            if self.cfg_map.has_key(key):
                self.cfg[key] = self.cfg_map[key][cfg.get(section, key)]
            elif isinstance(self.cfg[key], int):
                self.cfg[key] = cfg.getint(section, key)
            elif isinstance(self.cfg[key], bool):
                self.cfg[key] = cfg.getboolean(section, key)
            else:
                self.cfg[key] = cfg.get(section, key)
        self.rules = {}
        for header, pattern in cfg.items('Rules'):
            self.rules[header] = None if pattern is None \
                    else re.compile(pattern, re.I)
        assert len(self.rules), 'no rules defined'

    def __getattr__(self, name):
        return self.cfg[name]


def main(argv):
    try:
        cfg = RenameConfig(argv[1] if len(argv) > 1 else config_file,
                milter_name)
    except Exception as e:
        print >> sys.stderr, 'cannot parse config file:', str(e)
        return 1

    openlog(syslog_name, LOG_PID, cfg.logfacility)
    setlogmask(LOG_UPTO(cfg.loglevel))
    syslog(LOG_NOTICE, 'starting with config %s' %(cfg.filename))

    os.umask(int(cfg.umask, 8))
    Milter.factory = lambda: RenameMilter(cfg.rules,
            cfg.marker.lower(), cfg.prefix)
    Milter.set_flags(Milter.CHGHDRS + Milter.ADDHDRS)
    Milter.runmilter(milter_name, cfg.socket, cfg.timeout)

    syslog(LOG_NOTICE, 'end')
    closelog()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

