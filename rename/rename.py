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
# v0.1 - markus@gekmihesg.de
#

import sys
import os
import Milter
from syslog import *
from re import compile
from ConfigParser import RawConfigParser as ConfigParser
from Milter.utils import parse_header

cfg_defaults = {
        'Socket': '/var/spool/postfix/milter/rename.sock',
        'UMask': '002',
        'Timeout': 600,
        'Marker': 'Received',
        'Prefix': 'X-Original-',
        'LogFacility': 'mail',
        'LogLevel': 'notice',
    }

milter_name = 'RenameMilter'
syslog_name = 'rename-milter'
config_file = '/etc/milter/rename.conf'

class RenameHeader(object):
    def __init__(self, name, pattern):
        self.name = name
        self.pattern = pattern
        self.reset()

    def reset(self):
        self.count = 0
        self.occurences = []

    def check(self, value):
        return not self.pattern or \
                self.pattern.match(parse_header(value))

    def add(self, value, pos):
        self.count += 1
        if self.check(value):
            self.occurences.append( (value, self.count, pos) )
            return True
        return False

class RenameMilter(Milter.Base):
    def __init__(self, headers, marker, prefix):
        self.id = Milter.uniqueID()
        self.headers = {}
        for name, pattern in headers.iteritems():
            self.headers[name.lower()] = RenameHeader(name, pattern)
        self.marker = marker.lower()
        self.prefix = prefix
        self.message_count = 0
        self.reset()
        self.log(LOG_DEBUG, "instance %d initialized", self.id)

    def reset(self):
        self.header_count = 0
        self.received_pos = 0
        self.message_count += 1

    @Milter.noreply
    def connect(self, hostname, *args, **kwargs):
        self.log(LOG_INFO, "new connection from %s", hostname)
        return Milter.CONTINUE

    def header(self, name, value):
        self.header_count += 1
        name = name.lower()
        if name == self.marker and not self.received_pos:
            self.received_pos = self.header_count
            self.log(LOG_DEBUG, "marking position %d as start", self.header_count)
        elif self.headers.has_key(name):
            if self.headers[name].add(value, self.header_count):
                self.log(LOG_DEBUG, "matching %s at position %d", name, self.header_count)
            else:
                self.log(LOG_DEBUG, "non-matching %s at postition %d", name, self.header_count)
        return Milter.CONTINUE

    def eom(self):
        for hdr in self.headers.itervalues():
            newname = self.prefix + hdr.name
            deleted = 0
            for value, idx, pos in hdr.occurences:
                if pos > self.received_pos:
                    self.addheader(newname, value, pos + 1)
                    self.chgheader(hdr.name, idx - deleted, None)
                    deleted += 1
                    self.log(LOG_DEBUG, "renamed %s at position %d", hdr.name, pos)
            self.log(LOG_INFO, "renamed %d %s to %s", deleted, hdr.name, newname)
            hdr.reset()
        self.log(LOG_INFO, "end of message %d", self.message_count)
        self.reset()
        return Milter.CONTINUE

    def close(self):
        self.log(LOG_INFO, "disconnected")
        return Milter.CONTINUE

    def log(self, prio, msg, *args):
        syslog(prio, '%d: %s' %(self.id, msg %args))


facility_map = {
        'kern': LOG_KERN,
        'user': LOG_USER,
        'mail': LOG_MAIL,
        'daemon': LOG_DAEMON,
        'auth': LOG_AUTH,
        'lpr': LOG_LPR,
        'news': LOG_NEWS,
        'uucp': LOG_UUCP,
        'cron': LOG_CRON,
        'syslog': LOG_SYSLOG,
        'local0': LOG_LOCAL0,
        'local1': LOG_LOCAL1,
        'local2': LOG_LOCAL2,
        'local3': LOG_LOCAL3,
        'local4': LOG_LOCAL4,
        'local5': LOG_LOCAL5,
        'local6': LOG_LOCAL6,
        'local7': LOG_LOCAL7,
    }

priority_map = {
        'emerg': LOG_EMERG,
        'alert': LOG_ALERT,
        'crit': LOG_CRIT,
        'err': LOG_ERR,
        'warning': LOG_WARNING,
        'notice': LOG_NOTICE,
        'info': LOG_INFO,
        'debug': LOG_DEBUG,
    }


def main():
    cfg = ConfigParser(allow_no_value=True)
    cfg.optionxform = str
    cfg.read(sys.argv[1] if len(sys.argv) > 1 else config_file)

    if not cfg.has_section('Rules'):
        print >> sys.stderr, "no rules defined"
        sys.exit(1)

    rules = {}
    for header, pattern in cfg.items('Rules'):
        rules[header] = None if pattern is None else compile(pattern)
    get_cfg = lambda x: cfg.get(milter_name, x) \
            if cfg.has_option(milter_name, x) else cfg_defaults[x]

    openlog(syslog_name, LOG_PID, facility_map[get_cfg('LogFacility')])
    setlogmask(LOG_UPTO(priority_map[get_cfg('LogLevel')]))
    syslog(LOG_NOTICE, 'starting')

    os.umask(int(get_cfg('UMask'), 8))
    Milter.factory = lambda: RenameMilter(rules,
            get_cfg('Marker'),
            get_cfg('Prefix')
        )
    Milter.set_flags(Milter.CHGHDRS + Milter.ADDHDRS)
    Milter.runmilter(milter_name,
            get_cfg('Socket'),
            get_cfg('Timeout')
        )

    syslog(LOG_NOTICE, 'end')
    closelog()


if __name__ == "__main__":
    main()

