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
