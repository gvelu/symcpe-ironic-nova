#!/usr/bin/env python
# Copyright 2012 Cisco Systems, Inc.
# Copyright 2016 Symantec Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
#
# Fake neutron agent to make mechanism manager happy.

import sys
import time

import netaddr
from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging
from oslo_service import service
from oslo_utils import excutils
from six import moves

from neutron._i18n import _LI
from neutron.agent.linux import bridge_lib
from neutron.agent.linux import utils
from neutron.agent import securitygroups_rpc as sg_rpc
from neutron.common import config as common_config
from neutron.common import constants
from neutron.common import exceptions
from neutron.common import topics
from neutron.common import utils as n_utils
from neutron.plugins.ml2.drivers.agent import _agent_manager_base as amb
from neutron.plugins.ml2.drivers.agent import _common_agent as ca
from neutron.plugins.ml2.drivers.agent import config as cagt_config  # noqa
from neutron.plugins.ml2.drivers.l2pop.rpc_manager \
    import l2population_rpc as l2pop_rpc
from neutron.plugins.ml2.drivers.linuxbridge.agent.common import config  # noqa
from neutron.plugins.ml2.drivers.linuxbridge.agent.common \
    import constants as lconst


LOG = logging.getLogger(__name__)

LB_AGENT_BINARY = 'neutron-linuxbridge-agent'


class SymCpeManager(amb.CommonAgentManagerBase):
    def __init__(self, interface):
        super(SymCpeManager, self).__init__()
        self.interface = interface

    def plug_interface(self, network_id, network_segment, tap_name,
                       device_owner):
        return True

    def remove_interface(self, bridge_name, interface_name):
        return True

    def get_devices_modified_timestamps(self, devices):
        return {d: bridge_lib.get_interface_bridged_time(d) for d in devices}

    def get_all_devices(self):
        devices = set()
        time.sleep(0)
        return devices

    def get_agent_id(self):
        mac = utils.get_interface_mac(self.interface)
        return 'lb%s' % mac.replace(":", "")

    def get_agent_configurations(self):
        configurations = {}
        return configurations

    def get_rpc_callbacks(self, context, agent, sg_agent):
        return SymCpeRpcCallbacks(context, agent, sg_agent)

    def get_rpc_consumers(self):
        consumers = [[topics.PORT, topics.UPDATE],
                     [topics.NETWORK, topics.DELETE],
                     [topics.NETWORK, topics.UPDATE],
                     [topics.SECURITY_GROUP, topics.UPDATE]]
        return consumers

    def ensure_port_admin_state(self, tap_name, admin_state_up):
        LOG.debug("Setting admin_state_up to %s for device %s",
                  admin_state_up, tap_name)

    def setup_arp_spoofing_protection(self, device, device_details):
        pass

    def delete_arp_spoofing_protection(self, devices):
        pass

    def delete_unreferenced_arp_protection(self, current_devices):
        pass

    def get_extension_driver_type(self):
        return lconst.EXTENSION_DRIVER_TYPE


class SymCpeRpcCallbacks(
    sg_rpc.SecurityGroupAgentRpcCallbackMixin,
    l2pop_rpc.L2populationRpcCallBackMixin,
    amb.CommonAgentManagerRpcCallBackBase):

    # Set RPC API version to 1.0 by default.
    # history
    #   1.1 Support Security Group RPC
    #   1.3 Added param devices_to_update to security_groups_provider_updated
    #   1.4 Added support for network_update
    target = oslo_messaging.Target(version='1.4')

    def network_delete(self, context, **kwargs):
        pass

    def port_update(self, context, **kwargs):
        pass

    def network_update(self, context, **kwargs):
        pass

    def fdb_add(self, context, fdb_entries):
        LOG.debug("fdb_add received")
        pass

    def fdb_remove(self, context, fdb_entries):
        LOG.debug("fdb_remove received")
        pass

    def _fdb_chg_ip(self, context, fdb_entries):
        LOG.debug("update chg_ip received")
        pass

    def fdb_update(self, context, fdb_entries):
        LOG.debug("fdb_update received")
        pass


def main():
    common_config.init(sys.argv[1:])

    common_config.setup_logging()

    # Use random interface to get unique ID
    iface = cfg.CONF.LINUX_BRIDGE.physical_interface_mappings[0].split(':')[-1]
    manager = SymCpeManager(iface)

    # Copy past from linuxbridge
    polling_interval = cfg.CONF.AGENT.polling_interval
    quitting_rpc_timeout = cfg.CONF.AGENT.quitting_rpc_timeout
    agent = ca.CommonAgentLoop(manager, polling_interval, quitting_rpc_timeout,
                               constants.AGENT_TYPE_LINUXBRIDGE,
                               LB_AGENT_BINARY)
    LOG.info(_LI("Agent initialized successfully, now running... "))
    launcher = service.launch(cfg.CONF, agent)
    launcher.wait()
