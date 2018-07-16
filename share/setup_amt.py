#!/usr/bin/env python

'''
    Copyright (c) 2016-2017 Wind River Systems, Inc.
    
    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at:
    http://www.apache.org/licenses/LICENSE-2.0
    
    Unless required by applicable law or agreed to in writing, software  distributed
    under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
    OR CONDITIONS OF ANY KIND, either express or implied.
'''

'''
This script enables AMT and connects to an AMT presence micro service.
This micro service enables remote AMT actions such as reboot,
shutdown, boot etc.

Actions handled by this script:
    * run the setup/clean policies
    * read status of above actions and report
    * read AMT UUID and publish an attribute with the details
    * create an attributes.cfg file with the AMT UUID attribute, or
    append to an existing attributes.cfg file

Assumptions:
    * cira policies and amt tool are part of an OTA operation along
    with this script
'''
import json
import os
from os.path import abspath
import sys
from time import sleep
import argparse
import uuid

def usage():
    print ("""
    This script is designed to be run from an OTA install script.
    There are two ENVs required:
      HDC_CONFIG_DIR, which is set by the ota_handler.py
      AMT_PASSWORD, which is set as an extra parameter to the ota
      operation.
    On Windows, the device manger is expected to be running as a
    service with admin privileges.

    This script must be part of the OTA package which also contains:
      cira scripts
      meshcmd binary
    """)
    sys.exit(1)

if __name__ == "__main__":
    
    # for debugging configuration
    #for k in os.environ.keys():
        #print("ENV: {} = {}".format(k, os.environ[k]))

    # this env is set by the ota class
    default_cfg_dir = os.environ.get("HDC_RUNTIME_DIR")
    if default_cfg_dir == '' or not default_cfg_dir:
        print("Error: ENV HDC_CONFIG_DIR not defined")
        usage()

    # Get the AMT password
    # this env is pass in as an extra parameter
    p = os.environ.get("HDC_EXTRA_PARAMS")
    p_list = p.split(',')
    for x in p_list:
        if 'AMT_PASSWORD' in x:
            pass_ary = x.split('=')
            password = pass_ary[1]
            break
    if password == '' or not password:
        print("Error: ENV AMT_PASSWORD not defined")
        usage()

    print("Got password {}".format(password))
    print("Got config dir {}".format(default_cfg_dir))

    mcmd = "meshcmd.exe"
    amt_uuid = "amt_uuid.txt"
    cleanup = "{} AmtScript --script cira_cleanup.mescript --pass {}".format(mcmd, password)
    setup = "{} AmtScript --script cira_setup.mescript --pass {}".format(mcmd, password)
    get_guid = "{} AmtUUID --pass {} > {}".format(mcmd, password, amt_uuid)
    attr_file_name = "attributes.cfg"

    # Note: meshcmd returns HECI errors as it tests for the driver
    # setup.  Thus, you cannot check the ret code.  If the amt uuid
    # file is written at the end, assume it is good.
    print ("Running {}".format(cleanup))
    os.system(cleanup)

    print ("Running {}".format(setup))
    os.system(setup)

    print ("Running {}".format(get_guid))
    os.system(get_guid)

    print ("Reading amt file {}".format(amt_uuid))
    if os.path.exists(amt_uuid):
        print("Amt uuid exists")
        with open(amt_uuid) as fh:
            uuid_raw = fh.readline().rstrip()
        print("Amt uuid {}".format(uuid_raw))

        # scrub the uuid if needed
        uuid_clean = uuid_raw.rstrip()

        # validate the uuid
        try:
            v = uuid.UUID(uuid_clean)
        except ValueError:
            print("Error: UUID is not valid {}".format(uuid_clean))
            sys.exit(1)
    else:
        print("Error: amt uuid file does not exist") 
        sys.exit(1) 

    # get abs path to the attributes.cfg file
    attr_file_path = os.path.abspath(
                os.path.join(default_cfg_dir, attr_file_name) )

    print ("Updating/creating {}".format(attr_file_path))
    data = {}
    if os.path.exists(attr_file_name):
        print("{} exists, append AMT UUID".format(attr_file_name))
        with open(attr_file_path, 'r') as fh:
            data = json.load(fh)

        # if the key already exists, fine, just clobber it with the
        # one we just read above
        data['publish_attribute'] = {'AMT_UUID':uuid_clean}
    else:
        print("Creating {} to add AMT UUID".format(attr_file_name))
        data['publish_attribute'] = {}
        data['publish_attribute'] = {'AMT_UUID':uuid_clean}

    with open(attr_file_path, 'w') as fh:
        json.dump(data, fh)
    print("Attribute file written: {}".format( json.dumps(data)))
    print("Restart the device manager to publish new attribute")
    sys.exit(0)

