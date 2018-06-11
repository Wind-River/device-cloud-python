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
This module contains the Client class for user applications
"""

import certifi
import json
import os
import uuid

from device_cloud._core.constants import DEFAULT_CONFIG_DIR
from device_cloud._core.constants import DEFAULT_CONFIG_FILE
from device_cloud._core.constants import DEFAULT_KEEP_ALIVE
from device_cloud._core.constants import DEFAULT_LOOP_TIME
from device_cloud._core.constants import DEFAULT_THREAD_COUNT
from device_cloud._core.constants import STATUS_SUCCESS
from device_cloud._core.constants import WORK_PUBLISH
from device_cloud._core.constants import STATUS_NOT_FOUND
from device_cloud._core.constants import TIME_FORMAT
from device_cloud._core import defs
from device_cloud._core.handler import Handler
from device_cloud.identity import Identity


class Client(object):
    """
    This class is used by apps to connect to and communicate with the HDC Cloud

    Logging Functions:
        critical(message)
        debug(message)
        error(message)
        info(message)
        log(log_level, message)
        warning(message)
    """

    def __init__(self, app_id, kwargs=None, offline=False, error_handler=None):
        """
        Start configuration of client. Configuration file location and name can
        be updated after this if necessary. MUST be followed by
        client.initialize() before anything else can be done.

        Parameters:
          app_id              (string) ID of application that will be used to
                                       generate a key. Also used as part of
                                       default configuration file
                                       {APP_ID}-connect.cfg. Maximum 27
                                       characters.
          kwargs                (dict) Optional dict to override any
                                       configuration values. These can also be
                                       overridden individually later.
        """

        # Setup default config structure and file location
        self.config = defs.Config()

        self.offline = offline
        if self.offline:
            print("Warning: running in offline mode")

        default_config = {
            "app_id":app_id,
            "config_dir":DEFAULT_CONFIG_DIR,
            "config_file":DEFAULT_CONFIG_FILE.format(app_id),
            "cloud":{},
            "proxy":{}
        }


        self.config.update(default_config)

        # Override config defaults with any passed values
        if kwargs:
            self.config.update(kwargs)

        self.identity = Identity()

        self.sds = None

        # Add sleep for idle loop
        # default is 0.1
        self.idle_sleep = 0.1

        # Client notification handler for reply errors
        # 3 parameters: error list, sent_message, reply
        self.error_handler = error_handler

    def initialize(self):
        """
        Finish client setup by reading config files using any config values
        already set, and initializing the client handler. This is required
        before connection can be attempted.

        Returns:
          STATUS_SUCCESS               Configuration completed successfully
          Exception                    Error in configuration
        """

        # Read JSON from config file. Does not overwrite any configuration set
        # in application.
        kwargs = {}
        config_path = os.path.join(self.config.config_dir, self.config.config_file)
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as config_file:
                    kwargs.update(json.load(config_file))
            except IOError as error:
                print("Error parsing JSON from "
                        "{}".format(self.config.config_file))
                raise error
        else:
            print("Cannot find {}".format(self.config.config_file))
            raise IOError("Cannot find {}".format(self.config.config_file))
        self.config.update(kwargs, False)

        kwargs = {}
        # Check config directory for device_id. If it does not exist, generate a
        # uuid and write it to device_id.
        device_id_path = os.path.join(self.config.config_dir, "device_id")
        if os.path.exists(device_id_path):
            try:
                with open(device_id_path, "r") as id_file:
                    self.config.device_id = id_file.read().strip()
            except:
                print("Failed to read device_id")
                raise IOError("Failed to read device_id")
        else:
            try:
                with open(device_id_path, "w") as id_file:
                    self.config.device_id = self.identity.get_device_id()
                    id_file.write(self.config.device_id)
            except:
                print("Failed to write device_id")
                raise IOError("Failed to write device_id")
        self.config.update(kwargs, False)

        # Check that all necessary configuration has been obtained
        if not self.config.cloud.token:
            print("Cloud token not set. Must be set in config")
            raise KeyError("Cloud token not set. Must be set in config")
        if not self.config.cloud.host:
            print("Cloud host addess not set. Must be set in config")
            raise KeyError("Cloud host address not set. Must be set in config")
        if not self.config.cloud.port:
            print("Cloud port not set. Must be set in config")
            raise KeyError("Cloud port not set. Must be set in config")

        # Generate key
        if self.config.app_id and self.config.device_id:
            self.config.key = "{}-{}".format(self.config.device_id,
                                             self.config.app_id)

        # for migration, customers may not want to use the app_id
        elif not self.config.app_id and self.config.device_id:
            print("No app_id specified, using device ID")
            self.config.key = "{}".format(self.config.device_id)

        else:
            print("device_id not set. Required for key.")
            raise KeyError("device_id not set. Required for key.")

        if len(self.config.key) > 64:
            print("Key exceeds 64 bytes. Please specify an app_id under {} "
                  "bytes in length".format(64-len(self.config.device_id)))
            raise KeyError("Key exceeds 64 bytes. Please specify an app_id "
                           "under {} bytes in length".format(
                               64-len(self.config.device_id)))

        # Final precedence config defaults
        config_defaults = {
            "keep_alive":DEFAULT_KEEP_ALIVE,
            "loop_time":DEFAULT_LOOP_TIME,
            "thread_count":DEFAULT_THREAD_COUNT,
            "ca_bundle_file":certifi.where()
        }
        self.config.update(config_defaults, False)

        # Initialize handler
        self.handler = Handler(self.config, self)

        # Access logger functions
        self.critical = self.handler.logger.critical
        self.debug = self.handler.logger.debug
        self.error = self.handler.logger.error
        self.info = self.handler.logger.info
        self.log = self.handler.logger.log
        self.warning = self.handler.logger.warning

        return STATUS_SUCCESS


    def action_acknowledge(self, request_id, error_code=0, error_message=""):
        """
        Send an acknowledgement for an action request
        Intended for internal use only

        Parameters:
          request_id          (string) If action_request.request_id was
                                       retreived from an action callback, it can
                                       be used here
          error_code             (int) Error code produced by the action
          error_message       (string) Error message to accompany the error code

        Returns:
          STATUS_SUCCESS               Sent acknowledgement for action request
          STATUS_FAILURE               Failed to send acknowledgement of action
                                       request
        """

        ret = None
        if not self.offline:
            ret = self.handler.action_acknowledge(request_id,
                                               error_code,
                                               error_message)
        return ret

    def action_progress_update(self, request_id, message):
        """
        Update message for an action request from the Cloud

        Parameters:
          request_id          (string) If action_request.request_id was
                                       retreived from an action callback, it can
                                       be used here
          message             (string) New message for Cloud request

        Returns:
          STATUS_SUCCESS               Sent progress update for action request
          STATUS_FAILURE               Failed to update progress of action
                                       request
        """
        ret = None
        if not self.offline:
            ret = self.handler.action_progress_update(request_id, message)
        return ret


    def action_deregister(self, action_name):
        """
        Dissociates a Cloud action action from any command or callback

        Parameters:
          action_name         (string) Action to deregister

        Returns:
          STATUS_NOT_FOUND             No action with that name registered
          STATUS_SUCCESS               Action deregistered
        """

        return self.handler.action_deregister(action_name)

    def action_register_callback(self, action_name, callback_function,
                                 user_data=None):
        """
        Associate a callback function with an action in the Cloud

        Parameters:
          action_name         (string) Action to register
          callback_function     (func) Function to execute when triggered by
                                       action. Callback function must take
                                       parameters of the form (client,
                                       parameters, user_data[, action_request])
                                       where action_request is optional, but
                                       contains the request_id for later use.
                                       The callback function must also return
                                       status_code, or (status_code,
                                       status_message) in a tuple.

        Returns:
          STATUS_EXISTS                Action with that name already exists
          STATUS_SUCCESS               Successfully registered callback
        """
        return self.handler.action_register_callback(action_name,
                                                     callback_function,
                                                     user_data)

    def action_register_command(self, action_name, command):
        """
        Associate a console command with an action in the Cloud

        Parameters:
          action_name         (string) Action to register
          command             (string) Console command to execute when
                                       triggered by action
        Returns:
          STATUS_EXISTS                Action with that name already exists
          STATUS_SUCCESS               Successfully registered command
        """

        return self.handler.action_register_command(action_name, command)

    def alarm_publish(self, alarm_name, state, message=None, republish=False):
        """
        Publish an alarm to the Cloud

        Parameters:
          alarm_name          (string) Name of alarm to publish
          state                  (int) State of publish
          message             (string) Optional message to accompany alarm

        Returns:
          STATUS_SUCCESS               Alarm has been queued for publishing
        """

        ret = None
        if not self.offline:
            alarm = defs.PublishAlarm(alarm_name, state, message, republish)
            self.handler.queue_publish(alarm)
            work = defs.Work(WORK_PUBLISH, None)
            ret =  self.handler.queue_work(work)
        return ret

    def attribute_publish(self, attribute_name, value):
        """
        Publish string telemetry to the Cloud

        Parameters:
          attribute_name      (string) Key of the attribute to publish
          value               (string) Value to publish

        Returns:
          STATUS_SUCCESS               Attribute has been queued for publishing
        """

        attr = defs.PublishAttribute(attribute_name, value)
        return self.handler.queue_publish(attr)

    def connect(self, timeout=0):
        """
        Connect the Client to the Cloud

        Parameters:
          timeout             (number) Maximum time to try to connect

        Returns:
          STATUS_FAILURE               Failed to connect to Cloud
          STATUS_SUCCESS               Successfully connected to Cloud
          STATUS_TIMED_OUT             Connection attempt timed out
        """

        return self.handler.connect(timeout)

    def disconnect(self, wait_for_replies=False, timeout=0):
        """
        End Client connection to the Cloud

        Parameters:
          wait_for_replies      (bool) When True, wait for any pending replies
                                       to be received or time out before
                                       disconnecting
          timeout             (number) Maximum time to wait before returning

        Returns:
          STATUS_SUCCESS               Successfully disconnected
        """

        return self.handler.disconnect(wait_for_replies=wait_for_replies,
                                       timeout=timeout)

    def diag_ping(self):
        """
        Request diagonstic ping from the cloud

        Returns:
          STATUS_SUCCESS               True
        """
        return self.handler.handle_ping()

    def diag_time(self):
        """
        Request diagonstic time from the cloud

        Returns:
          STATUS_SUCCESS               Current cloud time
        """
        return self.handler.handle_time()

    def log_level(self, level):
        """
        Set the log level
        
        Parameters:
          level             (string) Requested level
        """
        return self.handler.log_level(level)

    def event_publish(self, message):
        """
        Publishes an event message to the Cloud

        Parameters:
          message             (string) Message to publish

        Returns:
          STATUS_SUCCESS               Event has been queued for publishing
        """
        ret = None
        if not self.offline:
            log = defs.PublishLog(message)
            ret = self.handler.queue_publish(log)
        return ret

    def file_download(self, file_name, download_dest, blocking=False,
                      callback=None, timeout=0, file_global=False):
        """
        Download a file from the Cloud to the device (C2D)

        Parameters:
          file_name           (string) File in Cloud to download
          download_dest       (string) Destination for downloaded file
          blocking              (bool) Wait for file transfer to complete
                                       before returning. Otherwise return
                                       immediately.
          callback              (func) Function to be executed as soon as file
                                       transfer is complete. It will be passed
                                       (client, file_name, status).
          timeout             (number) If blocking, maximum time to wait
                                       before returning
          file_global                  Flag that indicates whether or not the
                                       file to download is in the global file
                                       store or the thing's file store

        Returns:
          STATUS_FAILURE               Failed to download file.
          STATUS_NOT_FOUND             Could not find download directory to
                                       download file to.
          STATUS_SUCCESS               File download successful
          STATUS_TIMED_OUT             Wait for file transfer timed out. File
                                       transfer is still in progress.
        """

        return self.handler.request_download(file_name, download_dest, blocking,
                                             callback, timeout, file_global)

    def file_upload(self, file_path, upload_name=None, blocking=False,
                    callback=None, timeout=0, file_global=False):
        """
        Upload a file from the device to the Cloud (D2C)

        Parameters:
          file_path           (string) Absolute path for file to upload.
          upload_name         (string) Name for file uploaded in Cloud.
                                       Default is the file name on the device.
          blocking              (bool) Wait for file transfer to complete
                                       before returning. Otherwise return
                                       immediately.
          callback              (func) Function to be executed as soon as file
                                       transfer is complete. It will be passed
                                       (client, file_name, status).
          timeout             (number) If blocking, maximum time to wait
                                       before returning
          file_global                  Flag that indicates whether or not the
                                       file should be uploaded to the global
                                       file store or the thing's file store

        Returns:
          STATUS_FAILURE               Failed to upload file.
          STATUS_NOT_FOUND             Could not find find to upload in upload
                                       directory.
          STATUS_SUCCESS               File upload successful
          STATUS_TIMED_OUT             Wait for file transfer timed out. File
                                       transfer is still in progress.
        """
        ret = None
        if not self.offline:
            if os.path.isdir(file_path):
                result = []
                for fn in os.listdir(file_path):
                    result.append(self.handler.request_upload((file_path+os.sep+fn), fn, blocking,
                                               callback, timeout, file_global))
                if not result:
                    return STATUS_NOT_FOUND
                return max(result)
            ret = self.handler.request_upload(file_path, upload_name, blocking,
                                              callback, timeout, file_global)
        return ret

    def is_alive(self):
        """
        Return whether or not the Client has exited

        Returns:
          True                         Client is running
          False                        Client is not running
        """

        return not self.handler.to_quit

    def is_connected(self):
        """
        Return the current connect status of the Client

        Returns:
          True                         Connected to Cloud
          False                        Not connected to Cloud
        """

        return self.handler.is_connected()

    def location_publish(self, latitude, longitude, heading=None, altitude=None,
                         speed=None, accuracy=None, fix_type=None):
        """
        Publish a location metric to the Cloud

        Parameters:
          latitude            (number) Latitude coordinate
          longitude           (number) Longitude coordinate
          heading             (number) Heading
          altitude            (number) Altitude
          speed               (number) Speed
          accuracy            (number) Accuracy of fix
          fix_type            (string) Fix type

        Returns:
          STATUS_SUCCESS               Location has been queued for publishing
        """

        location = defs.PublishLocation(latitude, longitude, heading=heading,
                                        altitude=altitude, speed=speed,
                                        accuracy=accuracy, fix_type=fix_type)
        return self.handler.queue_publish(location)

    def telemetry_publish(self, telemetry_name, value, cloud_response=False,
             timestamp=None, corr_id=None, aggregate=False):
        """
        Publish telemetry to the Cloud

        Parameters:
          telemetry_name      (string) Key of property to publish
          value               (number) Value to publish
          cloud_response      (bool) Wait for response from cloud
                                     If true, the return status indicates if
                                     it was sent to the cloud. Otherwise,
                                     the return status is if it was queued.
          timestamp           (string) Optional datetime format timestamp to
                                       override the timestamp applied by the API
        Returns:
          STATUS_SUCCESS             Telemetry has been queued for publishing
        """

        telem = defs.PublishTelemetry(telemetry_name, value, timestamp, corr_id, aggregate)
        return self.handler.request_publish(telem, cloud_response)

    def telemetry_read_last_sample(self, telemetry_name):
        """
        Read back last/current telemetry sample from the Cloud

        Parameters
          telemetry_name      (string) Key of property to publish

        Returns:
          STATUS_SUCCESS               Telemetry has been queued for publishing
          value                        Value for last telemetry sample in cloud
          timestamp                    Timestamp for the sample
        """

        return self.handler.handle_telemetry_get(telemetry_name)

    def attribute_read_last_sample(self, attribute_name):
        """
        Read back last/current attribute sample from the Cloud

        Parameters
          attribute_name      (string) Key of property to publish

        Returns:
          STATUS_SUCCESS               Telemetry has been queued for publishing
          value                        Value for last attribute sample in cloud
          timestamp                    Timestamp for the sample
        """

        return self.handler.handle_attribute_get(attribute_name)

    def update_thing_details(self, name=None, description=None,
                             iccid=None, esn=None, imei=None, meid=None,
                             imsi=None, unset_fields=[]):
        """
        Update a things description.  All fields are optional, if none
        are specified, then the action is a noop.

        Parameters:
            name              (string) Friendly name.
            description       (string) Description of thing.
            iccid             (string) ICCID
            esn               (string) ESN
            imei              (string) IMEI
            meid              (string) MEID
            imsi              (string) IMSI
            unset_fields      (list) List of field names above to unset.

        Returns:
            STATUS_SUCCESS
        """

        return self.handler.handle_update_thing_details(name, description,
                                    iccid, esn, imei, meid, imsi, unset_fields)
