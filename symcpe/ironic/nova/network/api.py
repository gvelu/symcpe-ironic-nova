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

from nova.network.neutronv2 import api
from nova.virt.ironic import client_wrapper

from symcpe.ironic.nova.network import dnstool

LOG = api.LOG
excutils = api.excutils


# here is the ugly magic in order to avoid copy-pasting allocate_for_instance
def set_patch(iterable=None):
    from symcpe.ironic.nova.virt.ironic.driver import MacFactory
    if isinstance(iterable, MacFactory):
        return iterable
    else:
        return set(iterable)

api.set = set_patch


class API(api.API):
    pxe_net = 'mgmt'
    prod_net = 'prod'

    def __init__(self, *args, **kwargs):
        super(API, self).__init__(*args, **kwargs)
        self.ironicclient = client_wrapper.IronicClientWrapper()
        self.dns_api = dnstool.DNSTool()

    def _create_port(self, port_client, instance, network_id, port_req_body,
                     fixed_ip=None, security_group_ids=None,
                     available_macs=None, dhcp_opts=None):
        """ Overload port creation in order to implement:
         1. Using rack-aware subnet selection
         2. Add DNS integration
        """
        api.LOG.info('Create port for host: %s', instance.host)
        # Pick the rack's subnet
        subnet_name = instance.metadata['rack']
        network = port_client.show_network(network_id)['network']
        subnets = port_client.list_subnets(network_id=network_id,
                                           name=subnet_name)['subnets']
        macs = set([available_macs(network)])
        if subnets:
            fixed_ip_dict = {'subnet_id': subnets[0]['id']}
        if fixed_ip:
            fixed_ip_dict['ip_address'] = str(fixed_ip)
        port_req_body['port']['fixed_ips'] = [fixed_ip_dict]
        # This may cause the IpAddressInUseClient exception miss the IP
        fixed_ip = None

        port_id = super(API, self)._create_port(
            port_client, instance, network_id, port_req_body, fixed_ip,
            security_group_ids, macs, dhcp_opts)

        # Add port to FQDN
        port = port_client.show_port(port_id)
        fqdn = self._get_host_fqdn(instance, network)
        self.dns_api.register(fqdn, port['port']['fixed_ips'][0]['ip_address'])
        return port_id

    def _delete_ports(self, neutron, instance, ports, raise_if_fail=False):
        """ Overload port deletion in order to implement DNS integration
        """
        for port_id in ports:
            try:
                port = neutron.show_port(port_id)['port']
                network = neutron.show_network(port['network_id'])['network']
                fqdn = self._get_host_fqdn(instance, network)
                self.dns_api.delete(fqdn, port['fixed_ips'][0]['ip_address'])
            except api.neutron_client_exc.NeutronClientException:
                api.LOG.info('DNS record delete failed for {0}, '
                             'Unable to get port'.format(instance.uuid))
        return super(API, self)._delete_ports(neutron, instance, ports,
                                              raise_if_fail)

    @classmethod
    def _get_host_fqdn(cls, instance, network):
        """
        :type instance: nova.objects.instance.Instance
        :type network: dict
        :rtype: str
        """
        name = instance.hostname.rsplit('-', 1)
        net_name = network['name']
        environment = net_name if net_name != cls.prod_net else name[-1]
        name = '{0}-{1}.{2}'.format(name[0], environment,
                                    instance.metadata['dns_domain'])
        return name

    def setup_instance_network_on_host(self, context, instance, host):
        """Setup network is not required. Need to insure it."""
        pass
