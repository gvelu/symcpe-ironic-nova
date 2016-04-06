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
import re

from oslo_config import cfg
from nova import exception
from nova.virt.ironic import driver

LOG = driver.LOG

opts = [
    cfg.DictOpt('tag2net',
                default={'101': 'mgmt', '102': 'data', '103': 'prod'},
                help='Dictionary to match vlan tag to network name to get'
                     ' IP from'),
]

symcpe_group = cfg.OptGroup(name='symcpe', title='Symantec CPE Options')
CONF = cfg.CONF
CONF.register_group(symcpe_group)
CONF.register_opts(opts, symcpe_group)


class MacFactory(object):

    def __init__(self, instance, node):
        """
        It is expected that node should contain node.extra['network']. It
        should be a dictionary. An example:
            {'bond0': {'interfaces': ['p1p1', 'p2p1'],
                       'type': 'bond'},
             'mgmt': {'interfaces': ['em1'],
                      'vlan': 101,
                      'type': 'symlink'},
             'bond0.102': {'interfaces': ['bond0'],
                           'vlan': 102,
                           'type': u'tagged'},
             'bond0.103': {'interfaces': ['bond0'],
                           'vlan': 103,
                            'type': u'tagged'}}
        """
        self.instance = instance
        self.net_map = node.extra['network']
        self.interfaces = node.extra['interfaces']

    def __call__(self, network):
            def iface2mac(_net):
                return _net['interfaces'][0]

            def tagged2mac(_net):
                return iface2mac(self.net_map[_net['interfaces'][0]])

            type2lambda = dict(tagged=tagged2mac,
                               bond=iface2mac,
                               symlink=iface2mac)

            name = network['name']
            for net in self.net_map.values():
                vlan = str(net.get('vlan', ''))
                if vlan and CONF.symcpe.tag2net[vlan] in name:
                    mac = self.interfaces[type2lambda[net['type']](net)]
                    return mac
            else:
                raise exception.NotFound()

    def __contains__(self, item):
        return item in self.interfaces.values()


class IronicClientWrapper(object):
    def __init__(self, parent):
        self.client = parent
        self.node_list_re = re.compile(CONF.symcpe.bm_filter_value)

    def call(self, func, *args, **kwargs):
        def filter_node(_node):
            fields = CONF.symcpe.bm_filter_key.split('.')
            temp = getattr(_node, fields[0])
            for _i in fields[1:]:
                temp = temp[_i]
            return bool(self.node_list_re.findall(temp))

        if func == 'node.list':
            kwargs['detail'] = True
        result = self.client.call(func, *args, **kwargs)
        if func == 'node.list':
            return [i for i in result if filter_node(i)]
        else:
            return result


class SymIronicDriver(driver.IronicDriver):
    """Hypervisor driver for Ironic - bare metal provisioning."""

    def __init__(self, *args, **kwargs):
        super(SymIronicDriver, self).__init__(*args, **kwargs)
        if CONF.symcpe.bm_filter_enabled:
            self.ironicclient = IronicClientWrapper(self.ironicclient)

    def macs_for_instance(self, instance):
        """ Returns (mac, extra) factory. Is returned instead of MAC
        in original driver.
        :param instance:
        :return: function to generate mac-extra depending on interface
        """
        try:
            node = self.ironicclient.call("node.get", instance.node)
        except driver.ironic.exc.NotFound:
            raise exception.NotFound()
        return MacFactory(instance, node)

    def generate_name(self, context, instance, node):
        """
        Generate name. It is expected that node name is in format:
        b-spare-r<rack-position><rack-name>-<env>
        An example:
         b-spare-r01a10-prod
        :return: instance name and properties dictionary
        """
        role = instance.metadata.get('role') or instance.hostname
        cluster = instance.metadata.get('cluster') or context.project_name
        raid = instance.metadata.get('raid') or 'jbod'

        node = self.ironicclient.call("node.get", node)
        name = node.name.split('-')
        name = '-'.join([name[0], role] + name[-2:])
        zone = node.extra['dns_zone']
        rack = node.properties['rack']
        return name, {'rack': rack,
                      'dns_zone': zone,
                      'dns_domain': zone,
                      'role': role,
                      'cluster': cluster,
                      'raid': raid}

    def _generate_configdrive(self, instance, node, network_info,
                              extra_md=None, files=None):
        """ Patch meta data with node extra.
        """
        extra_md['node_extra'] = node.extra
        # Not really is required, but is convenient to have it
        extra_md['node_ips'] = dict(
            (net['network']['label'],
             dict(ip=net['network']['subnets'][0]['ips'][0]['address'],
                  mask=str(netaddr.IPNetwork(
                      net['network']['subnets'][0]['cidr']).netmask),
                  gw=net['network']['subnets'][0]['gateway']['address']))
            for net in network_info)
        return super(SymIronicDriver, self)._generate_configdrive(
            instance, node, network_info, extra_md, files)

    def _plug_vifs(self, node, instance, network_info):
        # Here we do an assumption that only mgmt is required for pxe
        self._unplug_vifs(node, instance, network_info)
        ports = self.ironicclient.call("node.list_ports", node.uuid,
                                       detail=True)
        # Workaround, we will have only one port (mgmt) per node
        if len(ports) != 1:
            raise exception.VirtualInterfacePlugException(
                "Ironic node: number of ports != 1")
        pif = ports[0]
        # Add mgmt vif_port_id to extra
        for vif in network_info:
            if vif['network']['label'] == 'mgmt':
                # Start by ensuring the ports are clear
                port_id = unicode(vif['id'])
                patch = [{'op': 'add',
                          'path': '/extra/vif_port_id',
                          'value': port_id}]
                self.ironicclient.call("port.update", pif.uuid, patch)

    def _unplug_vifs(self, node, instance, network_info):
        # We need to unplug mgmt only
        ports = self.ironicclient.call("node.list_ports", node.uuid,
                                       detail=True)
        # Workaround, we will have only one port (mgmt) per node
        if len(ports) != 1:
            raise exception.VirtualInterfacePlugException(
                "Ironic node: number of ports != 1")
        pif = ports[0]
        # Delete vif_port_id from extra if there
        if 'vif_port_id' in pif.extra:
            # we can not attach a dict directly
            patch = [{'op': 'remove', 'path': '/extra/vif_port_id'}]
            try:
                self.ironicclient.call("port.update", pif.uuid, patch)
            except driver.ironic.exc.BadRequest:
                pass

    def _add_driver_fields(self, node, instance, *args, **kwargs):
        super(SymIronicDriver, self)._add_driver_fields(
            node, instance, *args, **kwargs)
        # Add custome fields
        if 'raid' in instance.metadata:
            patch = [{'path': '/instance_info/raid', 'op': 'add',
                      'value': instance.metadata['raid']}]
            self.ironicclient.call('node.update', node.uuid, patch)
        # instance.name = node.extra['description']['fqdn']
