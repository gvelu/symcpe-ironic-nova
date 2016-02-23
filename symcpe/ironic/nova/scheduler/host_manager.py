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
from nova.compute import hv_type
from nova.scheduler import ironic_host_manager
from nova.scheduler import host_manager


class IronicHostManager(ironic_host_manager.IronicHostManager):
    def host_state_cls(self, host, node, **kwargs):
        """Factory function/property to create a new HostState."""
        compute = kwargs.get('compute')
        if compute and compute.get('hypervisor_type') == hv_type.IRONIC:
            return IronicNodeState(host, node, **kwargs)
        else:
            return host_manager.HostState(host, node, **kwargs)


class IronicNodeState(ironic_host_manager.IronicNodeState):
    def consume_from_instance(self, instance):
        if 'consumed_hosts' not in instance:
            instance['consumed_hosts'] = dict()
        instance['consumed_hosts'][self.nodename] = self.stats.get('rack')
        return super(IronicNodeState, self).consume_from_instance(instance)
