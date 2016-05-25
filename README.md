Welcome!
========

Package provides Ironic extensions to support DC infrastructure:
 - Multi rack topology
 - No network isolation required
 - Several L3 networks per rack (mgmt, prod, api, data)
 - mgmt network is used for PxE provisionig (also is the only network with DHCP)
 - Routing is configured on the switches
 - Switches are also configured with DHCP relay
 - IP configuration for prod/api/data is static, using bonding/tagged interfaces


Installation
========
1. Install openstack packages
 - Keystone
 - Nova
 - Ironic
 - Neutron (is required by Ironic)
 - Swift (is required by Ironic pxe agent)
 - Glance
2. Install sym_nova extension
3. Update nova configuration (/etc/nova/nova.conf):
 - compute_driver = sym_nova.virt.ironic.driver.SymIronicDriver
 - network_api_class = sym_nova.network.api.API
 - scheduler_use_baremetal_filters=True
 - baremetal_scheduler_default_filters=RetryFilter
4. Restart Nova.
5. Create prod/mgmt/api/data networks.
6. Create subnets per rack for each network
