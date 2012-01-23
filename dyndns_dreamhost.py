#!/usr/bin python3
'''Provides DNS update script for accessing Dreamhost DNS API.

To update IP addresses dynamically, run on crontab.'''

import sys
import time
import argparse
import socket
import urllib.request
import urllib.parse
import uuid
import json

__version__ = '1.0.0'
__license__ = 'BSD-new'
__copyright__ = '''Copyright (c) 2012, Eric J. Suh
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * The name of Eric J. Suh may not be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL ANY CONTRIBUTER BE LIABLE FOR ANY
DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.'''

class ConnectionError(Exception):
    '''Exceptions just to pretty print network errors'''
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return repr(self.msg)


class Log:
    def __init__(self, logfile, do_log=False):
        self.do_log = do_log
        if self.do_log:
            self.logfile = open(logfile, 'a')

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        if self.do_log:
            self.logfile.close()

    def log(msg):
        if self.do_log:
            self.logfile.write('{} {}\n'.format(time.asctime(), msg))


def request_json(url):
    '''Get and parse JSON from url'''
    try:
        data = urllib.request.urlopen(url)
    except urllib.error.URLError as e:
        raise ConnectionError(e.strerror)
    try:
        x = json.loads(data.read().decode('utf-8'))
    except ValueError as e:
        return None
    finally:
        data.close()
    return x

def dyndns_add(key, record, type, value, comment=''):
    '''Access to Dreamhost dns-add_record API'''
    params = dict(key=key, uuid=str(uuid.uuid5(uuid.NAMESPACE_URL, record)),
        cmd='dns-add_record', record=record, type=type, value=value,
        format='json')
    if comment != '':
        params['comment'] = comment

    try:
        result = request_json("https://api.dreamhost.com/?{}".format(
            urllib.parse.urlencode(params)))
    except urllib.error.URLError as e:
        raise ConnectionError(e.strerror)
    if result['result'] == 'success':
        return True
    else:
        return False

def dyndns_rem(key, record, type, value):
    '''Access to Dreamhost dns-remove_record API'''
    params = dict(key=key, uuid=str(uuid.uuid5(uuid.NAMESPACE_URL, record)),
        cmd='dns-remove_record', record=record, type=type, value=value,
        format='json')
    try:
        result = request_json("https://api.dreamhost.com/?{}".format(
            urllib.parse.urlencode(params)))
    except urllib.error.URLError as e:
        raise ConnectionError(e.strerror)
    if result['result'] == 'success':
        return True
    else:
        return False

def dyndns_list(key, editable=None, record=None, type=None):
    '''Access to Dreamhost dns-list_records API'''
    params = dict(key=key, uuid=str(uuid.uuid4()), cmd='dns-list_records',
        format='json')
    try:
        result = request_json("https://api.dreamhost.com/?{}".format(
            urllib.parse.urlencode(params)))
    except urllib.error.URLError as e:
        raise ConnectionError(e.strerror)

    if result['result'] == 'success':
        r = result['data']
        if editable is not None:
            r = list(filter((lambda x: x['editable'] == editable), r))
        if record is not None:
            r = list(filter((lambda x: x['record'] == record), r))
        if type is not None:
            r = list(filter((lambda x: x['type'] == type), r))
        return r
    else:
        return None

def dyndns_clean(key, record, type='A'):
    '''Remove all editable, matching Dreamhost DNS entries'''
    results = dyndns_list(key, editable='1', type=type, record=record)
    if results is not None:
        for r in results:
            dyndns_rem(key=key, record=record, type=type, value=r['value'])

def get_current_ip():
    '''Sometimes gethostbyname(gethostname()) doesn't work'''
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("google.com",80))
        ip = s.getsockname()[0]
    except socket.error as e:
        raise ConnectionError('Error connecting to Google. {}.'.format(
            e.strerror))
    finally:
        s.close()
    return ip

def main(args=None):
    '''Entry point'''
    argparser = argparse.ArgumentParser(
        description='Update DNS at Dreamhost account')
    argparser.add_argument('key', type=str, help='Dreamhost API key')
    argparser.add_argument('hostname',
        help='Name of DNS Record to set/update')
    argparser.add_argument('-l','--log', dest='logfile', default='',
        help='Log file')
    argparser.add_argument('-c','--clean', action='store_const', const=True,
        default=False, help='Remove DNS record and cache files if exist'
            '(default: set/update IP in record)')
    argparser.add_argument('-h','--hard', action='store_const', const=True,
        default=False, help='Force hard overwrite of DNS record'
            '(default: only set/update IP if not the same as current IP)')
    params = argparser.parse_args(args)

    if params.logfile != '':
        do_log = True
    else:
        do_log = False

    with Log(params.logfile, do_log) as logfile:
        ip_cachename = 'dyndns-{}.txt'.format(params.hostname)

        if params.clean:
            dyndns_clean(params.key, params.hostname)
            logfile.log(params.hostname + ': Removed A record(s).')
            try:
                os.remove(ip_cachename)
                logfile.log('{}: Removed cache file {}.'.format(params.hostname,
                    ip_cachename))
            except OSError as e:
                logfile.log('{}: Unable to remove cache file {}. {}.'.format(
                    params.hostname, ip_cachename, e.strerror))
            return 0

        try:
            ip_cache = open(ip_cachename)
        except IOError as e:
            cached_ip = None
            logfile.log('{}: Warning, couldn\'t read IP cache file {}. {}.'.format(
                params.hostname, ip_cachename, e.strerror))
        else:
            cached_ip = ip_cache.read().rstrip()
            ip_cache.close()

        try:
            current_ip = get_current_ip()
        except ConnectionError as e:
            logfile.log('{}: {}'.format(params.hostname, e))

        if (current_ip is not None and
                (cached_ip is None or cached_ip != current_ip
                or params.hard)):
            dyndns_clean(params.key, params.hostname)
            logfile.log(params.hostname + ': Removed A record(s).')

            dyndns_add(key=params.key, record=params.hostname, type='A',
                value=current_ip)
            with open(ip_cachename, 'w') as ip_cache:
                ip_cache.write(current_ip + '\n')
            logfile.log('{}: Set A record to {}'.format(params.hostname,
                current_ip))
    return 0
            
if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
