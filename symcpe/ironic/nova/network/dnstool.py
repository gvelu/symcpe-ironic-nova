# Copyright 2016 Symantec, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_config import cfg
from oslo_log import log as logging
from nova import utils


LOG = logging.getLogger(__name__)

opts = [
    cfg.StrOpt('script_path',
               default='/usr/local/bin/dnstool',
               help='DNS tool script location executed by DAO DNS '
                    'management back-end.'),
    cfg.StrOpt('api_url', default='', help='DNS url.'),
    cfg.StrOpt('api_key', default='', help='DNS api key')
]

dns_group = cfg.OptGroup(name='sym_dns', title='Symantec DNS Options')
CONF = cfg.CONF
CONF.register_group(dns_group)
CONF.register_opts(opts, dns_group)


class DNSTool(object):
    def __init__(self):
        super(DNSTool, self).__init__()
        self.script = CONF.sym_dns.script_path

    def delete(self, fqdn, ip):
        self._delete(fqdn, ip)

    def register(self, fqdn, ip):
        command = [self.script,
                   '--api_url', CONF.sym_dns.api_url,
                   '--api_key', CONF.sym_dns.api_key,
                   '--action', 'change',
                   '--fqdn', fqdn,
                   '--type', 'A,PTR',
                   '--value', ip,
                   '--ttl', '3600']
        LOG.debug('Running: %s', ' '.join(command))
        try:
            utils.execute(*command)
            LOG.info('DNS record {0} added for IP {1}'.format(fqdn, ip))
        except utils.processutils.ProcessExecutionError as exc:
            msg = ('Failed to add DNS record {0} for IP {1}: '
                   'message {2}').format(fqdn, ip, exc.stderr)
            LOG.warning(msg)

    def _delete(self, fqdn, ip):
        command = [self.script,
                   '--api_url', CONF.sym_dns.api_url,
                   '--api_key', CONF.sym_dns.api_key,
                   '--action', 'delete',
                   '--fqdn', fqdn,
                   '--type', 'A,PTR',
                   '--value', ip]
        LOG.debug('Running: %s', ' '.join(command))
        try:
            utils.execute(*command)
            LOG.info('DNS record {0} deleted for IP {1}'.format(fqdn, ip))
        except utils.processutils.ProcessExecutionError as exc:
            msg = ('Failed to delete DNS record {0} for IP {1}: '
                   'message {2}').format(fqdn, ip, exc.stderr)
            LOG.warning(msg)
