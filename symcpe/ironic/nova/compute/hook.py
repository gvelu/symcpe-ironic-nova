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


LOG = logging.getLogger(__name__)
DEFAULT_RESOURCE_NAME = 'nova'


class ComputeManager(manager.ComputeManager):
    def __init__(self, *args, **kwargs):
        # Replace periodic task update available resources
        self._periodic_tasks.remove(
            ('update_available_resource',
             manager.ComputeManager.__dict__['update_available_resource']))
        # End of black magic
        super(ComputeManager, self).__init__(*args, **kwargs)

    def _build_and_run_instance(
            self, context, instance, image, decoded_files, admin_password,
            requested_networks, security_groups, block_device_mapping, node,
            limits, filter_properties):
        LOG.debug("HookBuild PRE begin")
        name, meta = self.driver.generate_name(context, instance, node)
        instance.metadata.update(meta)
        instance.hostname = name
        instance.display_name = name
        instance.display_description = name
        instance.save()
        return super(ComputeManager, self)._build_and_run_instance(
            context, instance, image, decoded_files, admin_password,
            requested_networks, security_groups, block_device_mapping, node,
            limits, filter_properties)

    def _destroy_evacuated_instances(self, context):
        """When Ironic hostname is changed this can destroy everything"""
        our_host = self.host
        filters = {'deleted': False}
        local_instances = self._get_instances_on_driver(context, filters)
        for instance in local_instances:
            if instance.host != our_host:
                # Sergii patch on
                LOG.warning('Sergii: prevent node from deleting')
                continue

    @manager.periodic_task.periodic_task
    def update_available_resource(self, context):
        """See driver.get_available_resource()

        Periodic process that keeps that the compute host's understanding of
        resource availability and usage in sync with the underlying hypervisor.

        :param context: security context
        """
        new_resource_tracker_dict = {}
        nodenames = set(self.driver.get_available_nodes())
        for nodename in nodenames:
            rt = self._get_resource_tracker(nodename)
            rt.update_available_resource(context)
            new_resource_tracker_dict[nodename] = rt

        # Delete orphan compute node not reported by driver but still in db
        compute_nodes_in_db = self._get_compute_nodes_in_db(context,
                                                            use_slave=True)

        for cn in compute_nodes_in_db:
            if cn.hypervisor_hostname not in nodenames:
                LOG.warning("Prevent Deleting orphan compute node %s" % cn.id)

        self._resource_tracker_dict = new_resource_tracker_dict
