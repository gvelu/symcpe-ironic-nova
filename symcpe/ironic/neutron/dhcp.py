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

import netaddr
from oslo_config import cfg
from neutron.agent.linux import dhcp
from neutron.agent.linux import utils


OPTS = [
    cfg.StrOpt('dhcp_interface',
               default='eth0',
               help='The interface to be used for the only DHCP process'),
]
cfg.CONF.register_opts(OPTS, 'symcpe')


constants = dhcp.constants
METADATA_DEFAULT_IP = dhcp.METADATA_DEFAULT_IP
WIN2k3_STATIC_DNS = dhcp.WIN2k3_STATIC_DNS


class Dnsmasq(dhcp.Dnsmasq):

    def enable(self):
        """Enables DHCP for this network by spawning a local process."""
        if self.active:
            self.restart()
        elif self._enable_dhcp():
            utils.ensure_dir(self.network_conf_dir)
            self.interface_name = cfg.CONF.symcpe.dhcp_interface
            self.spawn_process()

    def _build_cmdline_callback(self, pid_file):
        cmd = [
            '--no-hosts',
            '--no-resolv',
            '--strict-order',
            '--bind-interfaces',
            '--interface=%s' % self.interface_name,
            '--except-interface=lo',
            '--pid-file=%s' % pid_file,
            '--dhcp-hostsfile=%s' % self.get_conf_file_name('host'),
            '--addn-hosts=%s' % self.get_conf_file_name('addn_hosts'),
            '--dhcp-optsfile=%s' % self.get_conf_file_name('opts'),
            '--dhcp-leasefile=%s' % self.get_conf_file_name('leases'),
        ]

        possible_leases = 0
        for i, subnet in enumerate(self.network.subnets):
            mode = None
            # if a subnet is specified to have dhcp disabled
            if not subnet.enable_dhcp:
                continue
            if subnet.ip_version == 4:
                mode = 'static'
            else:
                # Note(scollins) If the IPv6 attributes are not set, set it as
                # static to preserve previous behavior
                addr_mode = getattr(subnet, 'ipv6_address_mode', None)
                ra_mode = getattr(subnet, 'ipv6_ra_mode', None)
                if (addr_mode in [constants.DHCPV6_STATEFUL,
                                  constants.DHCPV6_STATELESS] or
                        not addr_mode and not ra_mode):
                    mode = 'static'

            cidr = netaddr.IPNetwork(subnet.cidr)

            if self.conf.dhcp_lease_duration == -1:
                lease = 'infinite'
            else:
                lease = '%ss' % self.conf.dhcp_lease_duration

            # mode is optional and is not set - skip it
            if mode:
                if subnet.ip_version == 4:
                    cmd.append('--dhcp-range=%s%s,%s,%s,%s,%s,%s' %
                               ('set:', self._TAG_PREFIX % i,
                                cidr.network, mode, cidr.netmask,
                                cidr.broadcast, lease))
                else:
                    cmd.append('--dhcp-range=%s%s,%s,%s,%d,%s' %
                               ('set:', self._TAG_PREFIX % i,
                                cidr.network, mode,
                                cidr.prefixlen, lease))
                possible_leases += cidr.size

        # Cap the limit because creating lots of subnets can inflate
        # this possible lease cap.
        cmd.append('--dhcp-lease-max=%d' %
                   min(possible_leases, self.conf.dnsmasq_lease_max))

        cmd.append('--conf-file=%s' % self.conf.dnsmasq_config_file)
        if self.conf.dnsmasq_dns_servers:
            cmd.extend(
                '--server=%s' % server
                for server in self.conf.dnsmasq_dns_servers)

        if self.conf.dhcp_domain:
            cmd.append('--domain=%s' % self.conf.dhcp_domain)

        if self.conf.dhcp_broadcast_reply:
            cmd.append('--dhcp-broadcast')

        cfg_name = self.get_conf_file_name('config')
        with open(cfg_name, 'w') as fd:
            fd.writelines(line[2:]+'\n' for line in cmd)

        return ['dnsmasq', '--conf-file=%s' % cfg_name]

    def _generate_opts_per_subnet(self):
        options = []
        subnet_index_map = {}
        if self.conf.enable_isolated_metadata:
            subnet_to_interface_ip = self._make_subnet_interface_ip_map()
        isolated_subnets = self.get_isolated_subnets(self.network)
        for i, subnet in enumerate(self.network.subnets):
            if (not subnet.enable_dhcp or
                (subnet.ip_version == 6 and
                 getattr(subnet, 'ipv6_address_mode', None)
                 in [None, constants.IPV6_SLAAC])):
                continue
            if subnet.dns_nameservers:
                options.append(
                    self._format_option(
                        subnet.ip_version, i, 'dns-server',
                        ','.join(
                            self._convert_to_literal_addrs(
                                subnet.ip_version, subnet.dns_nameservers))))
            else:
                # use the dnsmasq ip as nameservers only if there is no
                # dns-server submitted by the server
                subnet_index_map[subnet.id] = i

            if self.conf.dhcp_domain and subnet.ip_version == 6:
                options.append('tag:tag%s,option6:domain-search,%s' %
                               (i, ''.join(self.conf.dhcp_domain)))

            gateway = subnet.gateway_ip
            host_routes = []
            for hr in subnet.host_routes:
                if hr.destination == constants.IPv4_ANY:
                    if not gateway:
                        gateway = hr.nexthop
                else:
                    host_routes.append("%s,%s" % (hr.destination, hr.nexthop))

            # Add host routes for isolated network segments

            if (isolated_subnets[subnet.id] and
                    self.conf.enable_isolated_metadata and
                    subnet.ip_version == 4):
                subnet_dhcp_ip = subnet_to_interface_ip[subnet.id]
                host_routes.append(
                    '%s/32,%s' % (METADATA_DEFAULT_IP, subnet_dhcp_ip)
                )

            if subnet.ip_version == 4:
                if host_routes:
                    if gateway:
                        host_routes.append("%s,%s" % (constants.IPv4_ANY,
                                                      gateway))
                    options.append(
                        self._format_option(subnet.ip_version, i,
                                            'classless-static-route',
                                            ','.join(host_routes)))
                    options.append(
                        self._format_option(subnet.ip_version, i,
                                            WIN2k3_STATIC_DNS,
                                            ','.join(host_routes)))

                if gateway:
                    options.append(self._format_option(subnet.ip_version,
                                                       i, 'router',
                                                       gateway))
                else:
                    options.append(self._format_option(subnet.ip_version,
                                                       i, 'router'))
        return options, subnet_index_map
