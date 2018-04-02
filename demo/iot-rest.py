#!/usr/bin/env python

'''
    Copyright (c) 2018 Wind River Systems, Inc.

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at:
    http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software  distributed
    under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
    OR CONDITIONS OF ANY KIND, either express or implied.
'''

import json
import os
import sys
import argparse
from device_cloud.rest import Rest

count = 0
def my_callback(response, *args, **kwargs):
    """
    Callback handler for async method invocation
    """
    global count
    print ("my_callback: {} returned {}: count {}".
        format(response.url, response.status_code, count))
    count +=1

def usage():
    print("Usage:"
          "\texport HDCADDRESS=<cloud address>\n"
          "\texport HDCUSERNAME=<cloud username>\n"
          "\texport HDCPASSWORD=<cloud password>\n"
          "\t$ ./iot-rest.py -k <thing key>")
    sys.exit(1)

def main():
    """
    Simple example application that uses the device_cloud_rest API to
    invoke an action on a device.
    """

    # ----------------------------------------------------------------
    # Credentials: instead of taking credentials on the command line,
    # environmental variables are used.   Thing key is an CLI arg.
    # ----------------------------------------------------------------
    cloud = os.environ.get("HDCADDRESS")
    username = os.environ.get("HDCUSERNAME")
    password = os.environ.get("HDCPASSWORD")
    suborg = os.environ.get("HDCORG")
    test_file = "test_file.txt"

    if not cloud or not username or not password:
        usage()

    # ----------------------------------------------------------------
    # arg parser for getting thing_key
    # ----------------------------------------------------------------
    parser = argparse.ArgumentParser(description="Example REST API app.")
    parser.add_argument("-k", "--thing_key", help="Thing key")
    args = parser.parse_args(sys.argv[1:])
    thing_key = args.thing_key
    if not thing_key:
        usage()

    # ----------------------------------------------------------------
    # 1. initialize the class
    # 2. set the suborg (optional)
    # 3. send a blocking command (device must be online)
    # 4. setup for non blocking command (set ttl, callback, num to send)
    # 5. send batch of non blocking commands (device can be on or offline)
    # 6. send a TR50 command to update the friendly name of the device
    # 7. read back the thing details to show the friendly name change
    # ----------------------------------------------------------------
    token = "E0LawLbhW6q3dfs6"
    r = Rest(cloud=cloud, sub_org=suborg, token=token)

    result = r.method_exec(thing_key, "ping")
    if not result.get("success"):
        print("Error: method failed")

    r.method_exec(thing_key, "ping",  ttl=120, async_callback=my_callback)

    # Example 1: create a file and upload it
    fh = open(test_file, "w")
    fh.write("Test upload/download file")
    fh.close()

    status, result = r.upload_to_cloud(thing_key, test_file)
    if status == False:
        print("Error: upload failed")
        print("Reason: {}".format(result.reason))

    # Example 2: download the file that was uploaded above
    status, result = r.download_from_cloud(thing_key, test_file, local_file_name="foo-down.txt")
    if status == False:
        print("Error: upload failed")
        print("Reason: {}".format(result.reason))


    # Example 3: update the things friendly name
    cmd = "thing.update"
    data = {"key":thing_key, "name":"Pauls C device_manager"}
    status, result = r.execute(cmd, data)
    print ("command: {}, status: {}".format(cmd, status))

    # Example 4: find the thing and show the thing details
    cmd = "thing.find"
    data = { "key":thing_key }
    status, result = r.execute(cmd, data)
    print ("command: {}, status: {}".format(cmd, status))
    print ("Updated name: \"{}\"".format(result["params"]["name"]))

if __name__ == "__main__":
    main()
