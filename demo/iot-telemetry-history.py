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

"""
Simple app that demonstrates the telemetry APIs in the HDC Python library
"""

import argparse
import errno
import random
import signal
import sys
import os
from time import sleep
from datetime import datetime

head, tail = os.path.split(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, head)

import device_cloud as iot

running = True
sending_telemetry = True

# Return status once the cloud responds
cloud_response = False

# Second intervals between telemetry
TELEMINTERVAL = 4

check_recv = {}
def sighandler(signum, frame):
    """
    Signal handler for exiting app
    """
    global running
    if signum == signal.SIGINT:
        print("Received SIGINT, stopping application...")
        running = False

if __name__ == "__main__":
    signal.signal(signal.SIGINT, sighandler)

    # Parse command line arguments for easy customization
    parser = argparse.ArgumentParser(description="Demo app for Python HDC "
                                     "telemetry APIs")
    parser.add_argument("-i", "--app_id", help="Custom app id")
    parser.add_argument("-c", "--config_dir", help="Custom config directory")
    parser.add_argument("-f", "--config_file", help="Custom config file name "
                        "(in config directory)")
    args = parser.parse_args(sys.argv[1:])

    # Initialize client default called 'python-demo-app'
    app_id = "iot-telemetry-history"
    if args.app_id:
        app_id = args.app_id
    client = iot.Client(app_id)

    # Use the demo-connect.cfg file inside the config directory
    # (Default would be python-demo-app-connect.cfg)
    config_file = "demo-iot-telemetry-history.cfg"
    if args.config_file:
        config_file = args.config_file
    client.config.config_file = config_file

    # Look for device_id and demo-connect.cfg in this directory
    # (This is already default behaviour)
    config_dir = "."
    if args.config_dir:
        config_dir = args.config_dir
    client.config.config_dir = config_dir

    # Finish configuration and initialize client
    client.initialize()


    # Connect to Cloud
    if client.connect(timeout=10) != iot.STATUS_SUCCESS:
        client.error("Failed")
        sys.exit(1)

    start = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    track = {}
    prop = "property-1"

    # Randomly generate telemetry and attributes to send
    for x in range(3):
        # corrid must be a string
        x = str(x)
        read_complete = 0
        value = round(random.random()*1000, 2)
        track[x] = value
        status = client.telemetry_publish(prop,
                value, corr_id=x)

    # now sleep a few seconds so that the data is available in the
    # cloud.  Read back the telemetry history and validate it.  The
    # result will be a json list, with list members like:
    # {u'ts': u'2018-07-13T14:26:55Z', u'value': 906.97, u'corrId': u'0'}
    # If the sample is not found, wait longer.  There is a variable
    # time delay for a published sample to hit the database in the
    # cloud.
    sleep(3)
    ret, values = client.telemetry_read_history(prop, start)
    for s in values:
        corr_id =s.get("corrId")
        val = s.get("value")
        if corr_id in track and track[corr_id] == val:
                print("Confirmed corr ID {} == {}".format(corr_id, val))
        else:
                print("NOT found corr ID {} == {}".format(corr_id, val))

    client.disconnect(wait_for_replies=True)
    for k in check_recv.keys():
        print ("{} = {}".format(k,check_recv[k]))

