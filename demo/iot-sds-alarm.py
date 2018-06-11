#!/usr/bin/env python
import errno
import json
import os
from os.path import abspath
import platform
import signal
import sys
from time import sleep
import uuid 
import argparse
import tarfile 
import random
import socket
from datetime import datetime, timedelta
from device_cloud import osal
from device_cloud import ota_handler
from device_cloud import relay
import device_cloud as iot
from device_cloud import sds
if sys.version_info.major == 2:
    input = raw_input

# set the path so that we find the device_cloud dir one level up first
head, tail = os.path.split(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, head)

running = True

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
                                     "SDS APIs")
    parser.add_argument("-i", "--app_id", help="Custom app id")
    parser.add_argument("-c", "--config_dir", help="Custom config directory")
    parser.add_argument("-f", "--config_file", help="Custom config file name "
                        "(in config directory)")
    args = parser.parse_args(sys.argv[1:])

    # Initialize client default called 'python-demo-app'
    app_id = "iot-sds-alarm"
    if args.app_id:
        app_id = args.app_id
    client = iot.Client(app_id)

    # Use the demo-connect.cfg file inside the config directory
    # (Default would be python-demo-app-connect.cfg)
    config_file = "demo-iot-sds.cfg"
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

    print("""
    This demo uses SDS to store alarm data  and does the following:
        * Store N Forward
        * use case: keep data on device for x number of days
        * show data aging works
    """)
    input(" Hit Enter to proceed to demo...")

    # ------------------------------------------
    # initialize the data store 
    # ------------------------------------------
    db_name = app_id + ".db"

    # for demo purposes, remove the db before hand
    if os.path.exists(db_name):
        os.remove(db_name)
    client.sds = sds.SmartDataStorage( app_id +".db", logger=client.handler.logger)

    # ------------------------------------------
    # configure the data storage policy
    # ------------------------------------------
    # Retention modes:
    #   STORAGE_MAX_DAYS
    #   Keep data until the time stamps are greather than
    #   max_days_to_retain, then delete those that are older
    client.sds.retention_policy   = client.sds.STORAGE_MAX_DAYS
    client.sds.max_days_to_retain = 1

    # Connect to Cloud
    if client.connect(timeout=10) != iot.STATUS_SUCCESS:
        client.error("Failed")
        sys.exit(1)

    counter = 0
    input("\nWe are connected now.  Collect telmetry but don't publish yet")
    while running and client.is_alive():
        if counter < 10:
            status = client.sds.insert_alarm(
                                    name="telemetry_alarm",
                                    alarm_state=random.randint(0,1),
                                    msg="very alarming",
                                    state=client.sds.STATE_UNSENT)
            if status is not iot.STATUS_SUCCESS:
                client.handler.logger.error("Error: inserting into data store")
        else:
            running = False
        counter += 1

    input("\nHit enter to show the alarms stored in the db...")
    client.sds.print_table(client.sds.ALARM)

    input("\nShow how data is aged.  This demo uses a retain period of\n"
          "1 day. Update the date field in last entry to\n"
          "a date outside the max configured retention time e.g. 3 days old ...")
   
    # update the time in the last sample to 3 days ago
    # Use the raw sql cursor for custom sql commands
    c = client.sds.get_cursor()
    sql = "select * from {} order by idx desc limit 1;".format(client.sds.ALARM)
    c.execute(sql)
    for rows in c:
       print rows
    old_ts =  datetime.utcnow() - timedelta(days=3)
    ts = old_ts.strftime("%Y-%m-%d %H:%M:%S.%f")
    sql = "UPDATE {} SET ts =\'{}\',msg=\'X\' WHERE idx = {}".format(client.sds.ALARM, ts, rows[0])
    print(sql)
    client.sds.custom_sql_command(sql)

    input("\nHit enter to show the updated alarms (note last entry)...")
    client.sds.print_table(client.sds.ALARM)

    input("\nData retention is calculated at INSERT time.\n"
          "Add a new sample to trigger the process")
    client.sds.insert_alarm( name="telemetry_alarm",
                            alarm_state=random.randint(0,1),
                            msg="testing retention",
                            state=client.sds.STATE_UNSENT)

    client.sds.print_table(client.sds.ALARM)

    input("\nHit enter publish all unsent alarms...")

    # ------------------------------------------------------------------
    # publish anything that is "unsent" and update state to sent
    # ------------------------------------------------------------------
    client.handler.logger.info("Publishing significant alarms...")
    status = client.sds.publish_unsent_alarms(client,
                             new_state=client.sds.STATE_SENT)
                             ##new_state=client.sds.STATE_REMOVE)
    if status != iot.STATUS_SUCCESS:
        client.handler.logger.error("Error: failed to pulbish some alarms")

    # ------------------------------------------------------------------
    # dump the table
    # ------------------------------------------------------------------
    input("\nAlarms sent, hit enter to show the states...")
    client.sds.print_table(client.sds.ALARM)
    
    client.disconnect(wait_for_replies=True)
