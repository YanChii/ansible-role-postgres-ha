#!/usr/bin/python
# Copyright: (c) 2021, Ondrej Famera <ondrej-xa2iel8u@famera.cz>
# GNU General Public License v3.0+ (see LICENSE-GPLv3.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# Apache License v2.0 (see LICENSE-APACHE2.txt or http://www.apache.org/licenses/LICENSE-2.0)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
author: "Ondrej Famera (@OndrejHome)"
module: pcs_stonith_level
short_description: "wrapper module for 'pcs stonith level'"
description:
  - "module for creating and deleting stonith levels using 'pcs' utility"
version_added: "2.4"
options:
  state:
    description:
      - "'present' - ensure that stonith level for given node and stonith device exists"
      - "'absent' - ensure that stonith level for given node and stonith device doesn't exist"
    required: false
    default: present
    choices: ['present', 'absent']
    type: str
  level:
    description:
      - numerical stonith level (1-9)
    required: true
    choices: [1, 2, 3, 4, 5, 6, 7, 8, 9]
    type: int
  node_name:
    description:
      - name of cluster node for this stonith level and stonith_device
    required: true
    type: str
  stonith_device:
    description:
      - name of existing stonith device
    required: true
    type: str
  cib_file:
    description:
      - "Apply changes to specified file containing cluster CIB instead of running cluster."
      - "This module requires the file to already contain cluster configuration."
    required: false
    type: str
notes:
   - when deleting the stonith level only exact match is being deleted - same behaviour as pcs
   - tested on CentOS 7.9/8.3
'''

EXAMPLES = '''
- name: add fence-kdump as level 1 stonith device for node-a
  pcs_stonith_level:
    level: '1'
    node_name: 'node-a'
    stonith_device: 'fence_kdump'

- name: remove fence-xvm level 2 stonith device from node-b
  pcs_stonith_level:
    level: '2'
    node_name: 'node-b'
    stonith_device: 'fence_xvm'
    state: 'absent'
'''

import os.path
import xml.etree.ElementTree as ET
from distutils.spawn import find_executable

from ansible.module_utils.basic import AnsibleModule


def run_module():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(default="present", choices=['present', 'absent']),
            level=dict(required=True, type='int', choices=[1, 2, 3, 4, 5, 6, 7, 8, 9]),
            node_name=dict(required=True, type='str'),
            stonith_device=dict(required=True, type='str'),
            cib_file=dict(required=False),
        ),
        supports_check_mode=True
    )

    state = module.params['state']
    level = module.params['level']
    node_name = module.params['node_name']
    stonith_device = module.params['stonith_device']
    cib_file = module.params['cib_file']

    result = {}

    if find_executable('pcs') is None:
        module.fail_json(msg="'pcs' executable not found. Install 'pcs'.")

    module.params['cib_file_param'] = ''
    if cib_file is not None:
        # use cib_file if specified
        if os.path.isfile(cib_file):
            try:
                current_cib = ET.parse(cib_file)
            except Exception as e:
                module.fail_json(msg="Error encountered parsing the cib_file - %s" % (e))
            current_cib_root = current_cib.getroot()
            module.params['cib_file_param'] = '-f ' + cib_file
        else:
            module.fail_json(msg="%(cib_file)s is not a file or doesn't exists" % module.params)
    else:
        # get running cluster configuration
        rc, out, err = module.run_command('pcs cluster cib')
        if rc == 0:
            current_cib_root = ET.fromstring(out)
        else:
            module.fail_json(msg='Failed to load cluster configuration', out=out, error=err)

    # try to find the fencing-level
    fencing_level = None
    fencing_levels = current_cib_root.findall("./configuration/fencing-topology/fencing-level")
    for flevel in fencing_levels:
        # level must match all criteria (level, node_name, stonith_device)
        if (flevel.attrib.get('index') == str(level)
                and flevel.attrib.get('target') == node_name
                and flevel.attrib.get('devices') == stonith_device):
            fencing_level = flevel
            break

    if fencing_level is not None:
        result.update({
            'fence_level_was_matched': True,
            'level': None if fencing_level is None else fencing_level.attrib.get('index'),
            'node_name': None if fencing_level is None else fencing_level.attrib.get('target'),
            'devices': None if fencing_level is None else fencing_level.attrib.get('devices'),
            'fence_level_id': None if fencing_level is None else fencing_level.attrib.get('id'),
        })
    else:
        result.update({'fence_level_was_matched': False})

    # commands for creating/deleting stonith levels
    cmd_create = 'pcs %(cib_file_param)s stonith level add %(level)s %(node_name)s %(stonith_device)s' % module.params
    cmd_delete = 'pcs %(cib_file_param)s stonith level remove %(level)s %(node_name)s %(stonith_device)s' % module.params

    if state == 'present' and fencing_level is None:
        # stonith level should be present, but we don't see it in configuration - lets create it
        result['changed'] = True
        if not module.check_mode:
            rc, out, err = module.run_command(cmd_create)
            if rc == 0:
                module.exit_json(**result)
            else:
                module.fail_json(msg="Failed to create stonith level with cmd: '" + cmd_create + "'", output=out, error=err)

    elif state == 'present' and fencing_level is not None:
        # stonith level should be present and it is there, nothing to do
        result['changed'] = False

    elif state == 'absent' and fencing_level is not None:
        # stonith level should not be present but we have found something - lets remove that
        result['changed'] = True
        if not module.check_mode:
            rc, out, err = module.run_command(cmd_delete)
            if rc == 0:
                module.exit_json(**result)
            else:
                module.fail_json(msg="Failed to delete stonith level with cmd: '" + cmd_delete + "'", output=out, error=err)
    else:
        # stonith level should not be present and is not there, nothing to do
        result['changed'] = False

    # END of module
    module.exit_json(**result)


def main():
    run_module()


if __name__ == '__main__':
    main()
