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

import collections

from nova.i18n import _
from oslo.config import cfg
from oslo_log import log as logging

from nova.compute import api as compute
from nova.scheduler import weights as weights_base


CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class RackDistributionWeigher(weights_base.BaseHostWeigher):
    def __init__(self, *args, **kwargs):
        super(RackDistributionWeigher, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    def weigh_objects(self, weighed_obj_list, weight_properties):
        """ Weigh multiple objects."""
        flavor = weight_properties['instance_type']
        spec = flavor.get('extra_specs', {})
        sku = spec.get('sku') or spec.get('capabilities:sku')
        if sku:
            return self._weight_bm_objects(weighed_obj_list, weight_properties)
        else:
            return super(RackDistributionWeigher, self).weigh_objects(
                weighed_obj_list, weight_properties)

    def _weight_bm_objects(self, weighed_obj_list, weight_properties):

        spec = weight_properties.get('request_spec', {})
        props = spec.get('instance_properties', {})

        if not props:
            raise compute.exception.NotFound(_('Properties not found'))

        role = props['metadata'].get('role') or props['hostname']
        context = weight_properties['context'].elevated()

        # Get all instances with the same role + project. Ignore failed BMs
        instances = self.compute_api.get_all(
            context, {'deleted': False,
                      'project_id': weight_properties['project_id']})
        instances = [_i for _i in instances
                     if _i['vm_state'] != 'error' and
                     'rack' in _i['metadata'] and
                     _i['metadata'].get('role') == role]

        # Get number of instances per rack
        instances_per_rack = collections.defaultdict(int)
        for _i in instances:
            instances_per_rack[_i['metadata']['rack']] += 1
        # Update with already consumed instances
        for rack in props.get('consumed_hosts', {}).values():
            instances_per_rack[rack] += 1

        # Store it to be passed to self._weigh_object
        weight_properties['rack2instances'] = instances_per_rack
        weight_properties['rack_max'] = float(max(instances_per_rack.values())
                                              if instances_per_rack else 1)
        LOG.debug('instances_per_rack: %s', repr(instances_per_rack))
        # Calculate the weights
        weights = []
        for obj in weighed_obj_list:
            weight = self._weigh_object(obj.obj, weight_properties)

            # Record the min and max values if they are None. If they anything
            # but none we assume that the weigher has set them
            if self.minval is None:
                self.minval = weight
            if self.maxval is None:
                self.maxval = weight

            if weight < self.minval:
                self.minval = weight
            elif weight > self.maxval:
                self.maxval = weight

            weights.append(weight)

        LOG.debug(_("Weigher returning weights: %s"), weights)
        return weights

    def _weigh_object(self, host_state, weight_properties):
        # This function returns maximum weight for a host
        # belonging to the minimum_used_hosts list.
        if weight_properties.get('rack2instances'):
            rack = host_state.stats.get('rack')
            if not rack:
                raise compute.exception.NotFound(_('Rack stats not found'))
            return (weight_properties['rack_max'] -
                    weight_properties['rack2instances'][rack])
        else:
            return 1.0
