#!/usr/bin/python
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
author: "Olivier Pouilly (@OliPou)"
module: pcs_quorum_qdevice
short_description: "wrapper module for 'pcs quorum setup/destroy/change qdevice setting'"
description:
  - "module for setup/destroy/change qdevice setting 'pcs' utility"
version_added: "2.10"
options:
  state:
    description:
      - "'present' - ensure that the qdevice exists"
      - "'absent' - ensure qdevice doesn't exist"
    required: false
    default: present
    choices: ['present', 'absent']
    type: str
  qdevice:
    description:
      - qdevice name (hostname or IP address)
    required: false
    type: str
  algorithm:
    description:
      - algorithm use by the cluster
    required: false
    choices: ['ffsplit', 'lms']
    default: ffsplit
    type: str
  allowed_qdevice_changes:
    description:
      - "'none' - existing qdevice and algorithm must match"
      - "'update' - allow qdevice and/or algorithm update"
    default: none
    required: false
    choices: ['none', 'update']
    type: str
notes:
   - Tested on Debian 10
   - "When adding/removing qdevice, make sure to use 'run_once=True' on a cluster node"
'''

EXAMPLES = '''
- name: Setup qdevice with default algorithm (ffsplit)
  pcs_quorum_qdevice:
    qdevice: qdevice-name
  run_once: True

- name: Setup qdevice with lms algorithm
  pcs_quorum_qdevice:
    qdevice: qdevice-name
    algorithm: lms
  run_once: True

- name: Delete qdevice
  pcs_quorum_qdevice:
    state: absent
  run_once: True

- name: Setup or modify qdevice to use lms algorith
  pcs_quorum_qdevice:
    qdevice: qdevice-name
    algorithm: lms
    allowed_qdevice_changes: update
  run_once: True
'''

import os.path
import re
from distutils.spawn import find_executable

from ansible.module_utils.basic import AnsibleModule


def run_module():
    module = AnsibleModule(
        argument_spec=dict(
            state=dict(required=False, default="present", choices=['present', 'absent']),
            qdevice=dict(required=False, type='str'),
            algorithm=dict(required=False, default="ffsplit", choices=['ffsplit', 'lms']),
            allowed_qdevice_changes=dict(required=False, default="none", choices=['none', 'update']),
        ),
        supports_check_mode=True
    )

    state = module.params['state']
    allowed_qdevice_changes = module.params['allowed_qdevice_changes']
    qdevice = module.params['qdevice']
    algorithm = module.params['algorithm']
    if state == 'present' and (not module.params['qdevice']):
        module.fail_json(msg='When creating/updating qdevice you must specify qdevice name')
    result = {}

    if find_executable('pcs') is None:
        module.fail_json(msg="'pcs' executable not found. Install 'pcs'.")

    # get the pcs major.minor version
    rc, out, err = module.run_command('pcs --version')
    if rc == 0:
        pcs_version = out.split('.')[0] + '.' + out.split('.')[1]
    else:
        module.fail_json(msg="pcs --version exited with non-zero exit code (" + rc + "): " + out + err)

    if pcs_version != '0.10':
        module.fail_json(msg="unsupported version of pcs (" + pcs_version + "). Only version 0.10 is supported.")

    # EL 7 configuration file
    corosync_conf_exists = os.path.isfile('/etc/corosync/corosync.conf')

    if state == 'present' and not corosync_conf_exists:
        module.fail_json(msg='When creating/updating qdevice you must have a cluster set')

    try:
        corosync_conf = open('/etc/corosync/corosync.conf', 'r')
        qdevice_defined = re.compile(r"device\s*\{([^}]+)\}", re.M + re.S)
        re_qdevice_defined = qdevice_defined.findall(corosync_conf.read())
    except IOError as e:
        module.fail_json(msg='Could not open corosync.conf')

    if len(re_qdevice_defined) == 0:
        no_conf, config_qdevice_name_diff, config_qdevice_algo_diff = True, False, False
    else:
        no_conf = False

        qdevice_name = re.compile(r"host\s*:\s*([\w.-]+)\s*", re.M)
        qd_name = qdevice_name.findall(re_qdevice_defined[0])

        if len(qd_name) == 0 or qd_name[0] != qdevice:
            config_qdevice_name_diff = True
        else:
            config_qdevice_name_diff = False

        algorithm_name = re.compile(r"algorithm\s*:\s*([\w.-]+)\s*", re.M)
        algo_name = algorithm_name.findall(re_qdevice_defined[0])
        if len(algo_name) == 0 or algo_name[0] != algorithm:
            config_qdevice_algo_diff = True
        else:
            config_qdevice_algo_diff = False

    update, mismatch_options = False, False
    msg = ''

    if no_conf and state == 'present':
        result['changed'] = True
        result['new_qdevice'] = qdevice
        result['new_algorithm'] = algorithm
        cmd = 'pcs quorum device add model net host=%(qdevice)s algorithm=%(algorithm)s' % module.params
        update = True

    elif (config_qdevice_name_diff or config_qdevice_algo_diff) and allowed_qdevice_changes != 'none' and state == 'present':
        result['changed'] = True
        result['old_qdevice'] = qd_name
        result['new_qdevice'] = qdevice
        result['old_algorithm'] = algo_name
        result['new_algorithm'] = algorithm
        cmd = 'pcs quorum device update model host=%(qdevice)s algorithm=%(algorithm)s' % module.params
        update = True

    elif state == 'absent' and not no_conf:
        result['changed'] = True
        result['delete_qdevice'] = qd_name[0]
        cmd = 'pcs quorum device remove'
        update = True

    if config_qdevice_name_diff and allowed_qdevice_changes == 'none' and state == 'present':
        mismatch_options = True
        result['qdevice'] = qdevice
        result['qdevice_detected'] = qd_name

    if config_qdevice_algo_diff and allowed_qdevice_changes == 'none' and state == 'present':
        mismatch_options = True
        result['algorithm'] = algorithm
        result['algorithm_detected'] = algo_name

    if mismatch_options:
        if 'qdevice' in result:
            msg += "'Detected qdevice' and 'Requested qdevice' are different, but changes are not allowed."
        if 'algorithm' in result:
            msg += "'Detected algorithm' and 'Requested algorithm' are different, but changes are not allowed."
        result['msg'] = msg
        module.fail_json(**result)

    if not module.check_mode and update:
        rc, out, err = module.run_command(cmd)
        if rc == 0:
            module.exit_json(**result)
        else:
            module.fail_json(msg="Failed to setup qdevice using command '" + cmd + "'", output=out, error=err)

    # END of module
    module.exit_json(**result)


def main():
    run_module()


if __name__ == '__main__':
    main()
