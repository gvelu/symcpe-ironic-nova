#!/usr/bin/python
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

from oslo_log import log as logging
from nova.compute import manager
from nova.compute.manager import _LI, _LE, exception


LOG = logging.getLogger(__name__)
DEFAULT_RESOURCE_NAME = 'nova'
CONF = manager.CONF


class ComputeManager(manager.ComputeManager):
    def __init__(self, *args, **kwargs):
        # Replace periodic task update available resources
        self._periodic_tasks.remove(
            ('update_available_resource',
             manager.ComputeManager.__dict__['update_available_resource']))
        # End of black magic
        super(ComputeManager, self).__init__(*args, **kwargs)

    def _build_and_run_instance(
            self, context, instance, image, injected_files,
            admin_password, requested_networks, security_groups,
            block_device_mapping, node, limits, filter_properties):
        LOG.debug("HookBuild PRE begin")
        name, meta = self.driver.generate_name(context, instance, node)
        instance.metadata.update(meta)
        instance.hostname = name
        instance.display_name = name
        instance.display_description = name
        instance.save()
        return super(ComputeManager, self)._build_and_run_instance(
            context, instance, image, injected_files,
            admin_password, requested_networks, security_groups,
            block_device_mapping, node, limits, filter_properties)

    def _destroy_evacuated_instances(self, context):
        """Destroys evacuated instances.
        """
        return

    @manager.periodic_task.periodic_task(spacing=CONF.update_resources_interval)
    def update_available_resource(self, context):
        """See driver.get_available_resource()

        Periodic process that keeps that the compute host's understanding of
        resource availability and usage in sync with the underlying hypervisor.

        :param context: security context
        """
        new_resource_tracker_dict = {}

        compute_nodes_in_db = self._get_compute_nodes_in_db(context,
                                                            use_slave=True)
        nodenames = set(self.driver.get_available_nodes())
        for nodename in nodenames:
            rt = self._get_resource_tracker(nodename)
            try:
                rt.update_available_resource(context)
            except exception.ComputeHostNotFound:
                # NOTE(comstud): We can get to this case if a node was
                # marked 'deleted' in the DB and then re-added with a
                # different auto-increment id. The cached resource
                # tracker tried to update a deleted record and failed.
                # Don't add this resource tracker to the new dict, so
                # that this will resolve itself on the next run.
                LOG.info(_LI("Compute node '%s' not found in "
                             "update_available_resource."), nodename)
                continue
            except Exception:
                LOG.exception(_LE("Error updating resources for node "
                              "%(node)s."), {'node': nodename})
            new_resource_tracker_dict[nodename] = rt

        # NOTE(comstud): Replace the RT cache before looping through
        # compute nodes to delete below, as we can end up doing greenthread
        # switches there. Best to have everyone using the newest cache
        # ASAP.
        self._resource_tracker_dict = new_resource_tracker_dict

        # Delete orphan compute node not reported by driver but still in db
        for cn in compute_nodes_in_db:
            if cn.hypervisor_hostname not in nodenames:
                LOG.warning("Prevent Deleting orphan compute node %s" % cn.id)
