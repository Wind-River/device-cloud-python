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
This module handles all the underlying functionality of the Client
"""

import json
import logging
import logging.handlers
import os
import random
import socket

# proxy support requires PySocks, it is an optional module
proxy_support = False
try:
    import socks
    proxy_support = True
except ImportError:
    pass
import ssl
import sys
import threading
from binascii import crc32
from datetime import datetime
from datetime import timedelta
from time import sleep
import requests

# for debugging only, uncomment the following two lines
#import httplib
#httplib.HTTPConnection.debuglevel = 1

import paho.mqtt.client as mqttlib

from device_cloud._core import constants
from device_cloud._core import defs
from device_cloud._core import tr50
from device_cloud._core.tr50 import TR50Command

original_socket = socket.socket

if sys.version_info.major == 2:
    import Queue as queue
else:
    import queue

def status_string(error_code):
    """
    Return a string describing the error code
    """

    return constants.STATUS_STRINGS[error_code]

def is_valid_status(error_code):
    """
    Check if passed object is a valid status code
    """

    return (error_code.__class__.__name__ == "int" and
            error_code >= constants.STATUS_SUCCESS and
            error_code <= constants.STATUS_FAILURE)


class Handler(object):
    """
    Handles all underlying functionality of the Client
    """

    def __init__(self, config, client):
        # Configuration
        self.config = config

        # Set Client
        self.client = client

        # Set up logging, with optional logging to a specified file
        if self.config.key:
            self.logger = logging.getLogger(self.config.key)
        else:
            self.logger = logging.getLogger("APP NAME HERE")
        log_formatter = logging.Formatter(constants.LOG_FORMAT,
                                          datefmt=constants.LOG_TIME_FORMAT)
        if not self.config.quiet:
            if self.config.use_syslog:
                print ("Logging to syslog...")
                log_handler = logging.handlers.SysLogHandler(address = '/dev/log')
            else:
                log_handler = logging.StreamHandler()
            log_handler.setFormatter(log_formatter)
            self.logger.addHandler(log_handler)

        if self.config.log_file:
            log_file_handler = logging.FileHandler(self.config.log_file)
            log_file_handler.setFormatter(log_formatter)
            self.logger.addHandler(log_file_handler)

        # Ensure we're not missing required configuration information
        if not self.config.key or not self.config.cloud.token:
            self.logger.error("Missing key or cloud token from configuration")
            raise KeyError("Missing key or cloud token from configuration")

        #log_level default set as DEBUG
        self.logger.setLevel(logging.DEBUG)
        self.qos_level(self.config.qos_level)

        # Print configuration
        self.logger.debug("CONFIG:\n%s", self.config)

        # Ensure the paho socket pair is not using proxy sockets
        # Save the original socket so that class members can use it,
        # e.g. remote login etc.
        socket.socket = original_socket
        self.original_socket = original_socket

        # Set up MQTT client
        if self.config.cloud.port == 443:
            self.mqtt = mqttlib.Client(self.config.key, transport="websockets")
        else:
            self.mqtt = mqttlib.Client(self.config.key)
        self.mqtt.on_connect = self.on_connect
        self.mqtt.on_disconnect = self.on_disconnect
        self.mqtt.on_message = self.on_message
        self.mqtt.on_publish = self.on_publish
        self.mqtt.username_pw_set(self.config.key, self.config.cloud.token)

        # Set up proxy.  Note: PySocks is required for this, but it is
        # an optional pkg.  Check for it.
        if (proxy_support == True):
            if ("host" in self.config.proxy):
                proxy_type = None
                if self.config.proxy.type.upper() == "SOCKS4":
                    proxy_type = socks.SOCKS4
                elif self.config.proxy.type.upper() == "SOCKS5":
                    proxy_type = socks.SOCKS5
                elif self.config.proxy.type.upper() == "HTTP":
                    proxy_type = socks.HTTP
                else:
                    self.logger.error("Invalid proxy type. Supported types are "
                              "SOCKS4/SOCKS5/HTTP.")
                    raise KeyError("Invalid proxy type. Supported types are "
                           "SOCKS4/SOCKS5/HTTP.")
                username = None
                if "username" in self.config.proxy:
                    username = self.config.proxy.username
                password = None
                if "password" in self.config.proxy:
                    password = self.config.proxy.password
                socks.set_default_proxy(proxy_type, self.config.proxy.host,
                            self.config.proxy.port, True, username,
                            password)
                socket.socket = socks.socksocket
        elif ("host" in self.config.proxy and proxy_support == False):
            self.logger.error("PySocks module required for proxy support "
                     "Install PySocks.")
            raise KeyError("PySocks module required for proxy support "
                    "Install PySocks.")

        # Dict to associate action names with callback functions and any user
        # data
        self.callbacks = defs.Callbacks()

        # Connection state of the Client
        self.state = constants.STATE_DISCONNECTED

        # Track last time the app was connected so keep alive can time out
        self.last_connected = datetime.utcnow()

        # Lock for thread safety
        self.lock = threading.Lock()

        # Queue for any pending publishes (number, string, location, etc.)
        self.publish_queue = queue.Queue()

        # Dicts to track which messages sent out have not received replies. Also
        # stores any actions to be taken when the reply is received.
        self.reply_tracker = defs.OutTracker()
        self.no_reply = []

        # Counter to allow every message to be sent on a unique topic
        self.topic_counter = 1

        # Flag for notifying client to exit
        self.to_quit = True

        # Telemetry Response Flag
        self.pub_wait = self.pub_response = False
        self.pub_topic = '0000'

        # Thread trackers. Main thread for handling MQTT loop, and worker
        # threads for everything else.
        self.main_thread = None
        self.worker_threads = []

        # Queue to track any pending work (parsing messages, actions,
        # publishing, file transfer, etc.)
        self.work_queue = queue.Queue()

        # store any requested data here
        self.response = {}

    def action_deregister(self, action_name):
        """
        Disassociate any function or command from an action in the Cloud
        """

        status = constants.STATUS_SUCCESS

        try:
            self.callbacks.remove_action(action_name)
        except KeyError as error:
            self.logger.error(str(error))
            status = constants.STATUS_NOT_FOUND

        return status

    def action_acknowledge(self, request_id, error_code, error_message):
        """
        Send acknowledgement for action (method) request by the cloud
        """

        cmd = tr50.create_mailbox_ack(request_id, error_code, error_message)
        message = defs.OutMessage(cmd, "Action Acknowledge "
                                       "{} {}: \"{}\"".format(request_id,
                                                              error_code,
                                                              error_message))
        return self.send(message)

    def action_progress_update(self, request_id, message):
        """
        Update message for action (method) request in Cloud
        """

        cmd = tr50.create_mailbox_update(request_id, message)
        message = defs.OutMessage(cmd, "Update Action Progress "
                                  "{} \"{}\"".format(request_id, message))
        return self.send(message)

    def action_register_callback(self, action_name, callback_function,
                                 user_data=None):
        """
        Associate a callback function with an action in the Cloud
        """
        status = constants.STATUS_SUCCESS
        action = defs.Action(action_name, callback_function, self.client,
                             user_data=user_data)
        try:
            self.callbacks.add_action(action)
            self.logger.info("Registered action \"%s\" with function \"%s\"",
                             action_name, callback_function.__name__)
        except KeyError as error:
            self.logger.error("Failed to register action. %s", str(error))
            status = constants.STATUS_EXISTS

        return status

    def action_register_command(self, action_name, command):
        """
        Associate a console command with an action in the Cloud
        """

        status = constants.STATUS_SUCCESS
        action = defs.ActionCommand(action_name, command, self.client)
        try:
            self.callbacks.add_action(action)
            self.logger.info("Registered action \"%s\" with command \"%s\"",
                             action_name, command)
        except KeyError as error:
            self.logger.error("Failed to register action. %s", str(error))
            status = constants.STATUS_EXISTS

        return status

    def connect(self, timeout=0):
        """
        Connect to MQTT and start main thread
        """

        self.to_quit = False
        status = constants.STATUS_FAILURE
        result = -1

        # Ensure we have a host and port to connect to
        if not self.config.cloud.host or not self.config.cloud.port:
            self.logger.error("Missing host or port from configuration")
            status = constants.STATUS_BAD_PARAMETER

        else:
            current_time = datetime.utcnow()
            end_time = current_time + timedelta(seconds=timeout)
            self.state = constants.STATE_CONNECTING

            # Add network check and poll here while it is not
            # available.  Otherwise, the service will exit which is
            # not ideal if you do not have a service monitor like
            # systemd.
            test_network = True
            self.logger.info("Checking for network connectivity...")
            while test_network:
                try:
                    ret = socket.gethostbyname(self.config.cloud.host)
                    if ret:
                        self.logger.info("Network is active" )
                        test_network = False
                except socket.error as err:
                    self.logger.error("Network error detected: %s" % str(err))
                    sleep(1)

            # Start a secure connection if using a secure port and the cert file
            # is available
            if self.config.cloud.port in constants.SECURE_PORTS:
                if self.config.validate_cloud_cert is False:
                    context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
                    context.verify_mode = ssl.CERT_NONE
                    context.check_hostname = False
                    self.mqtt.tls_set_context(context)
                elif not self.config.ca_bundle_file:
                    self.logger.error("Missing certificate bundle from configuration")
                    status = constants.STATUS_BAD_PARAMETER
                elif not os.path.isfile(self.config.ca_bundle_file):
                    self.logger.error("Certificate bundle not found")
                    status = constants.STATUS_NOT_FOUND
                else:
                    context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
                    context.load_verify_locations(cafile=self.config.ca_bundle_file)
                    context.verify_mode = ssl.CERT_REQUIRED
                    context.check_hostname = True
                    self.mqtt.tls_set_context(context)

            # status != bad_parameter or not_found
            if status == constants.STATUS_FAILURE:
                # Start MQTT connection
                try:
                    result = self.mqtt.connect(self.config.cloud.host,
                                               self.config.cloud.port, 60)
                except Exception as error:
                    # socket.gaierror or ssl.SSLError
                    self.state = constants.STATE_DISCONNECTED
                    self.logger.error(str(error))

        if result == 0:
            # Successful MQTT connection
            self.logger.info("Connecting...")

            # Start main loop thread so that MQTT can make the on_connect
            # callback
            self.main_thread = threading.Thread(target=self.main_loop)
            self.main_thread.start()

            # Wait for cloud connection
            while ((timeout == 0 or current_time < end_time) and
                   self.state == constants.STATE_CONNECTING):
                sleep(0.1)
                current_time = datetime.utcnow()

            # Still connecting, timed out
            if self.state == constants.STATE_CONNECTING:
                self.logger.error("Connection timed out")
                status = constants.STATUS_TIMED_OUT

        if self.state == constants.STATE_CONNECTED:
            # Connected Successfully
            status = constants.STATUS_SUCCESS

            # Start worker threads if we have successfully connected
            for _ in range(self.config.thread_count):
                self.worker_threads.append(threading.Thread(
                    target=self.handle_work_loop))
            for thread in self.worker_threads:
                thread.start()

        else:
            # Not connected. Stop main loop.
            self.logger.error("Failed to connect")
            self.to_quit = True
            self.state = constants.STATE_DISCONNECTED
            if self.main_thread:
                self.main_thread.join()
                self.main_thread = None

        # Return result of connection
        return status

    def disconnect(self, wait_for_replies=False, timeout=0):
        """
        Stop threads and shut down MQTT client
        """

        current_time = datetime.utcnow()
        end_time = current_time + timedelta(seconds=timeout)

        # Publish any data that was queued before disconnecting
        if not self.publish_queue.empty():
            self.queue_work(defs.Work(constants.WORK_PUBLISH, None))

        # Wait for pending work that has not been dealt with
        self.logger.info("Disconnecting...")
        while ((timeout == 0 or current_time < end_time) and
               not self.work_queue.empty()):
            sleep(0.1)
            current_time = datetime.utcnow()

        # Optionally wait for any outstanding replies.
        if wait_for_replies and self.is_connected():
            self.logger.info("Waiting for replies...")
            while ((timeout == 0 or current_time < end_time) and
                   len(self.reply_tracker) != 0):
                sleep(0.1)
                current_time = datetime.utcnow()

        self.to_quit = True
        #TODO: Kill any hanging threads
        if threading.current_thread() not in self.worker_threads:
            if self.main_thread:
                self.main_thread.join()
                self.main_thread = None

        return constants.STATUS_SUCCESS

    def handle_action(self, action_request):
        """
        Handle action execution requests from Cloud
        """

        result_code = -1
        result_args = {"mail_id":action_request.request_id}
        action_result = None
        action_failed = False

        try:
            # Execute callback
            action_result = self.callbacks.execute_action(action_request)

        except Exception as error:
            # Error with action execution. Might not have been registered.
            action_failed = True
            self.logger.error("Action %s execution failed", action_request.name)
            self.logger.error(".... %s", str(error))
            result_code = constants.STATUS_FAILURE
            result_args["error_message"] = "ERROR: {}".format(str(error))
            if action_request.name not in self.callbacks:
                result_code = constants.STATUS_NOT_FOUND
            else:
                self.logger.exception("Exception:")

        # Action execution did not raise an error
        if not action_failed:
            # Handle returning a tuple or just a status code
            if action_result.__class__.__name__ == "tuple":
                result_code = action_result[0]
                if len(action_result) >= 2:
                    result_args["error_message"] = str(action_result[1])
                if len(action_result) >= 3:
                    result_args["params"] = action_result[2]
            else:
                result_code = action_result

            if not is_valid_status(result_code):
                # Returned 'status' is not a valid status
                error_string = ("Invalid return status: " +
                                str(result_code))
                self.logger.error(error_string)
                result_code = constants.STATUS_BAD_PARAMETER
                result_args["error_message"] = "ERROR: " + error_string

        # Return status to Cloud
        # Check for invoked status.  If so, return mail box update not
        # ack.  Ack is the final notification.  This breaks triggers
        # etc because it doesn't update the status.
        result_args["error_code"] = tr50.translate_error_code(result_code)
        if result_code == constants.STATUS_INVOKED:
                update_args = {"mail_id":action_request.request_id}
                update_args["message"] = "Invoked"
                mailbox_ack = tr50.create_mailbox_update(**update_args)
        else:
                mailbox_ack = tr50.create_mailbox_ack(**result_args)

        message_desc = "Action Complete \"{}\"".format(action_request.name)
        message_desc += " result : {}({})".format(result_code,
                                                  status_string(result_code))
        if result_args.get("error_message"):
            message_desc += " \"{}\"".format(result_args["error_message"])
        if result_args.get("params"):
            message_desc += " \"{}\"".format(str(result_args["params"]))
        message = defs.OutMessage(mailbox_ack, message_desc)
        status = self.send(message)
        return status

    def handle_attribute_get(self, attribute_name ):
        command = tr50.create_attribute_current(self.config.key, attribute_name)
        message_desc = "Reading current attribute..."
        message = defs.OutMessage(command, message_desc)

        self.pub_wait = True
        status = self.send(message)
        value = None
        timestamp = None

        # Wait for response from sending to cloud
        while self.pub_wait:
            sleep(0.5)
        # Convert to return codes
        if self.pub_response:
            ret = constants.STATUS_SUCCESS
        else:
            ret = constants.STATUS_FAILURE

        # make sure the key exists or there will be a KeyError
        # exception
        if 'attribute_current_value' in self.response.keys():
            value = self.response['attribute_current_value']

        if 'attribute_current_timestamp' in self.response.keys():
            timestamp = self.response['attribute_current_timestamp']
        return ret, value, timestamp

    def calc_file_checksum(self, file_name):
        """
        Calculate the crc32 checksum on a file and return the string
        interpretation of it.  Checksum of None means it failed.
        """
        sample = 0
        checksum = None
        if os.path.exists(file_name):
            for chunk in open(file_name, "rb"):
                sample = crc32(chunk, sample)
            checksum = "%s" % (sample & 0xffffffff)
        return checksum

    def do_file_get(self, url, validate, file_xfer_obj):
        """
        Perform a get on the specified file.  Handle all errors and
        exceptions and resumuption from where the download left off.
        """
        response = None

        # -------------------------------------------------------
        # Resume download:
        # -the .part file should exist, but if it doesn't force a
        # clean download
        # -for resume, set the Range header for resume
        # -set the file args to append or overwrite mode
        # -------------------------------------------------------
        if file_xfer_obj.resume_download and os.path.exists(file_xfer_obj.download_temp_path):
            resume_from = os.path.getsize(file_xfer_obj.download_temp_path)
            hdrs = {'Range':'bytes=%s-' % resume_from}
            self.logger.info("Resuming download of %s from %d bytes",
                file_xfer_obj.download_temp_path, resume_from )
            file_args = "ab"
        else:
            hdrs = {}
            file_args = "wb"

        # ---------------------------------------------------------
        # Downloading:
        # -start the download, validate and check use a connectivity
        # timeout so that we can quickly be notified and retry
        # -iterate and write chunks to file
        # -print out progress % but throttle it so that it doesn't
        # overwhelm the system, e.g. progress % 100 == 0
        # -crc32 must be added intrementally and compared later
        # -handle connection and http exceptions
        # -make sure not to retry on http errors > 400
        # -throttle printouts
        # ---------------------------------------------------------
        proxies = self.get_proxy_settings()
        response = requests.get(url, stream=True, verify=validate, timeout=3,
             headers=hdrs, proxies=proxies)
        self.logger.debug("HTTP Status %s" % response.status_code)
        if response.status_code == 200 or response.status_code == 206:
            count = 0
            download_len = 0
            chunk_size = 4096
            with open(file_xfer_obj.download_temp_path, file_args) as temp_file:
                try:
                    for chunk in response.iter_content(chunk_size):
                        if not chunk:
                            break
                        temp_file.write(chunk)
                        if count % 100 == 0:
                            download_len = int(os.path.getsize(file_xfer_obj.download_temp_path))
                            progress = 100 * (float(download_len)/file_xfer_obj.file_size)
                            self.logger.debug("Download progress %0.2f(%%)",
                                 float(progress))
                        count +=1
                except (Exception) as e:
                    self.logger.error("Exception: %s",str(e))
            response.close()
            temp_file.close()

            # -------------------------------------------------------------
            # Validation phase:
            # -if checksums match, move/rename temporary file to real file name
            # Windows requires the target file to be removed if it
            # exists
            # -if the file size is not correct, retry
            # -if the checksum is not correct, fatal, meaning we
            # downloaded everything correctly but the file content is not
            # correct.  No way to recover, just return failure.
            # -------------------------------------------------------------
            checksum = self.calc_file_checksum(file_xfer_obj.download_temp_path)
            self.logger.debug("Checksum calculated=%s, checksum expected %s",
                checksum, file_xfer_obj.file_checksum)
            if (file_xfer_obj.file_checksum == None) or (checksum == str(file_xfer_obj.file_checksum)):
                self.logger.info("Checksum is correct")
                try:
                    os.rename(file_xfer_obj.download_temp_path, file_xfer_obj.file_path)
                except:
                    os.remove(file_xfer_obj.file_path)
                    os.rename(file_xfer_obj.download_temp_path, file_xfer_obj.file_path)
                self.logger.info("Successfully downloaded %s", file_xfer_obj.file_name)
                status = constants.STATUS_SUCCESS
            elif download_len != file_xfer_obj.file_size:
                self.logger.error("Download was interrupted, trying again")
                status = constants.STATUS_TRY_AGAIN
            else:
                self.logger.error("Fatal error: download completed but checksum"
                   " does not match expected.  Deleting file.")
                os.remove(file_xfer_obj.download_temp_path)
                status = constants.STATUS_FAILURE

        elif response.status_code >= 400:
            self.logger.error("A fatal HTTP error occurred: %s", response.reason)
            status = constants.STATUS_FAILURE
        else:
            self.logger.error("File transfer interrupted.  Trying again.")
            status = constants.STATUS_TRY_AGAIN
        return status

    def handle_file_download(self, file_xfer_obj):
        """
        Handle any accepted C2D file transfers
        """
        # -----------------------------------------------------------
        # File download handler:
        # -prepare for a file download, create temp file, make sure
        # all directories exist.
        # -call do_file_get in a loop unless we get a STATUS_FAILURE,
        # which means it is fatal.
        # -----------------------------------------------------------
        status = constants.STATUS_SUCCESS
        self.logger.info("Downloading \"%s\"", file_xfer_obj.file_name)
        self.logger.info("File size \"%d\"", file_xfer_obj.file_size)

        # on prem solutions might not have port 443 for file xfer, so
        # support a config option in iot-connect.cfg for xfer host and
        # port.
        host = self.config.cloud.host
        if self.config.cloud.file_xfer_host:
            host = self.config.cloud.file_xfer_host
        if self.config.cloud.file_xfer_port:
            host += ":" + str(self.config.cloud.file_xfer_port)

        url = "https://{}/file/{}".format(host, file_xfer_obj.file_id)
        download_dir = os.path.dirname(file_xfer_obj.file_path)
        temp_file_name = "".join([random.choice("0123456789") for _ in range(10)])
        temp_file_name += ".part"
        temp_path = os.path.join(download_dir, temp_file_name)
        file_xfer_obj.download_temp_path = temp_path

        if not os.path.exists(download_dir):
            try:
                os.makedirs(download_dir)
            except OSError as err:
                self.logger.exception(err)
                status = constants.STATUS_BAD_PARAMETER
        elif not os.path.isdir(download_dir):
            self.logger.error("Failed to download %s (destination error)",
                              file_xfer_obj.file_name)
            status = constants.STATUS_IO_ERROR

        if status == constants.STATUS_SUCCESS:
            if (self.config.validate_cloud_cert is False or
                    not self.config.ca_bundle_file or
                    not os.path.isfile(self.config.ca_bundle_file)):
                validate = False
            else:
                validate = self.config.validate_cloud_cert

            # ----------
            # Retry loop
            # ----------
            status = self.do_file_get(url, validate, file_xfer_obj)
            while (status == constants.STATUS_TRY_AGAIN ):
                file_xfer_obj.resume_download = True
                status = self.do_file_get(url, validate, file_xfer_obj)
                sleep(1)

        file_xfer_obj.status = status
        file_xfer_obj.finish()
        return status

    def get_proxy_settings(self):
        if self.config.proxy:
            self.logger.debug("Proxy support detected")
            self.logger.debug("\ttype {} host {} port {}"
                .format(self.config.proxy.type,
                self.config.proxy.host,
                str(self.config.proxy.port )))

            proxy_host = self.config.proxy.host + ':' + str(self.config.proxy.port)
            proxy_type = self.config.proxy.type.lower()

            proxy_auth = ""

            # setup auth
            if self.config.proxy.username:
                proxy_auth = self.config.proxy.username
            if self.config.proxy.password:
                proxy_auth += ':' + self.config.proxy.password
                proxy_auth += '@'

            # key type is always http.  There is a bug when using
            # https.  The proxy tries to do a connect and fails with a
            # 403 error.
            proxies = {
                'http':  proxy_type + '://' + proxy_auth + proxy_host
            }
        else:
            proxies = None

        return proxies

    def handle_file_upload(self, upload):
        """
        Handle any accepted D2C file transfers
        """

        #TODO: Timeout

        status = constants.STATUS_SUCCESS

        self.logger.info("Uploading \"%s\" as \"%s\"",
                         os.path.basename(upload.file_path), upload.file_name)

        # Start creating URL for file upload
        url = "https://{}/file/{}".format(self.config.cloud.host,
                                          upload.file_id)

        response = None
        proxies = self.get_proxy_settings()

        if os.path.exists(upload.file_path):
            # If file exists attempt upload
            with open(upload.file_path, "rb") as up_file:
                # Secure or insecure HTTPS Post
                if (self.config.validate_cloud_cert is False or
                        not self.config.ca_bundle_file):
                    response = requests.post(url, data=up_file,
                    verify=False, proxies=proxies)
                else:
                    cert_location = self.config.ca_bundle_file
                    response = requests.post(url, data=up_file,
                                             verify=cert_location,
                                             proxies=proxies)

            if response.status_code == 200:
                self.logger.info("Successfully uploaded \"%s\"",
                                 upload.file_name)
                status = constants.STATUS_SUCCESS
            else:
                self.logger.error("Failed to upload \"%s\"",
                                  upload.file_name)
                self.logger.debug(".... %s", response.content)
                status = constants.STATUS_FAILURE

        else:
            # File does not exist
            self.logger.error("Cannot find file \"%s\". Upload failed.",
                              upload.file_path)
            status = constants.STATUS_NOT_FOUND

        # Update file transfer status
        upload.status = status

        # Call callback if it exists
        upload.finish()

        return status

    def handle_message(self, mqtt_message):
        """
        Handle messages received from Cloud
        """

        status = constants.STATUS_NOT_SUPPORTED

        msg_json = mqtt_message.json
        if "notify/" in mqtt_message.topic:
            # Received a notification
            if mqtt_message.topic[len("notify/"):] == "mailbox_activity":
                # Mailbox activity, send a request to check the mailbox
                self.logger.info("Recevied notification of mailbox activity")
                mailbox_check = tr50.create_mailbox_check(auto_complete=False)
                to_send = defs.OutMessage(mailbox_check, "Mailbox Check")
                self.send(to_send)
                status = constants.STATUS_SUCCESS

        elif "reply/" in mqtt_message.topic:
            # Received a reply to a previous message
            topic_num = mqtt_message.topic[len("reply/"):]
            for command_num in msg_json:
                reply = msg_json[command_num]

                # Retrieve the sent message that this is a reply for, removing
                # it from being tracked
                self.lock.acquire()
                try:
                    sent_message = self.reply_tracker.pop_message(topic_num,
                                                                  command_num)
                except KeyError as error:
                    self.logger.error(error.message)
                    continue
                finally:
                    self.lock.release()
                sent_command_type = sent_message.command.get("command")

                # Log success status of reply
                if reply.get("success"):
                    self.logger.info("Received success for %s-%s - %s",
                                     topic_num, command_num, sent_message)
                else:
                    self.logger.error("Received failure for %s-%s - %s",
                                      topic_num, command_num, sent_message)
                    self.logger.error(".... %s", str(reply))

                    if self.client.error_handler:
                        self.client.error_handler(
                        reply.get("errorCodes", []),
                        sent_message,
                        str(reply))

                # Return "success" status
                if self.pub_wait:
                    if self.pub_topic == topic_num:
                        self.pub_response = reply.get("success")
                        self.pub_wait = False
                    else:
                        self.pub_wait = self.pub_response = False

                # Check what kind of message this is a reply to
                if sent_command_type == TR50Command.file_get:
                    # Recevied a reply for a file download request
                    if reply.get("success"):
                        file_id = reply["params"].get("fileId")
                        file_checksum = reply["params"].get("crc32")
                        file_size = reply["params"].get("fileSize")
                        file_transfer = sent_message.data
                        file_transfer.file_id = file_id
                        file_transfer.file_checksum = file_checksum
                        file_transfer.file_size = file_size
                        work = defs.Work(constants.WORK_DOWNLOAD, file_transfer)
                        self.queue_work(work)
                    else:
                        if -90008 in reply.get("errorCodes", []):
                            sent_message.data.status = constants.STATUS_NOT_FOUND
                        elif sent_message.data != None:
                            sent_message.data.status = constants.STATUS_FAILURE

                elif sent_command_type == TR50Command.file_put:
                    # Received a reply for a file upload request
                    if reply.get("success"):
                        file_id = reply["params"].get("fileId")
                        file_transfer = sent_message.data
                        file_transfer.file_id = file_id
                        work = defs.Work(constants.WORK_UPLOAD, file_transfer)
                        self.queue_work(work)
                    else:
                        sent_message.data.status = constants.STATUS_FAILURE

                elif sent_command_type == TR50Command.mailbox_check:
                    # Received a reply for a mailbox check
                    if reply.get("success"):
                        try:
                            for mail in reply["params"]["messages"]:
                                mail_command = mail.get("command")
                                if mail_command == "method.exec":
                                    # Action execute request in mailbox
                                    mail_id = mail.get("id")
                                    action_name = mail["params"].get("method")
                                    action_params = mail["params"].get("params")
                                    action_request = defs.ActionRequest(mail_id,
                                                                        action_name,
                                                                        action_params)
                                    work = defs.Work(constants.WORK_ACTION,
                                                     action_request)
                                    self.queue_work(work)
                        except:
                            pass
                elif sent_command_type == TR50Command.diag_time:
                    # Recevied a reply for a ping request
                    if reply.get("success"):
                        mill = reply["params"].get("time")
                        print (datetime.fromtimestamp(mill/1000.0))

                    else:
                        if -90008 in reply.get("errorCodes", []):
                            sent_message.data.status = constants.STATUS_NOT_FOUND
                        else:
                            sent_message.data.status = constants.STATUS_FAILURE

                elif sent_command_type == TR50Command.diag_ping:
                    # Recevied a reply for a ping request
                    if reply.get("success"):
                       print ('*Connection Okay* \n')
                    else:
                        if -90008 in reply.get("errorCodes", []):
                            sent_message.data.status = constants.STATUS_NOT_FOUND
                        else:
                            sent_message.data.status = constants.STATUS_FAILURE

                elif sent_command_type == TR50Command.property_current:
                    if reply.get("success"):
                       params = reply.get("params")
                       self.response['telemetry_current_value'] = params.get("value")
                       self.response['telemetry_current_timestamp'] = params.get("ts")
                    else:
                        if -90008 in reply.get("errorCodes", []):
                            sent_message.data.status = constants.STATUS_NOT_FOUND
                        elif sent_message.data != None:
                            sent_message.data.status = constants.STATUS_FAILURE

                elif sent_command_type == TR50Command.property_history:
                    if reply.get("success"):
                       params = reply.get("params")
                       self.response['telemetry_history_values'] = params.get("values")
                    else:
                        if -90008 in reply.get("errorCodes", []):
                            sent_message.data.status = constants.STATUS_NOT_FOUND
                        elif sent_message.data != None:
                            sent_message.data.status = constants.STATUS_FAILURE
                elif sent_command_type == TR50Command.attribute_current:
                    # Recevied a reply for a ping request
                    if reply.get("success"):
                       params = reply.get("params")
                       self.response['attribute_current_value']  = params.get("value")
                       self.response['attribute_current_timestamp']  = params.get("ts")
                    else:
                        if -90008 in reply.get("errorCodes", []):
                            sent_message.data.status = constants.STATUS_NOT_FOUND
                        elif  sent_message.data != None:
                            sent_message.data.status = constants.STATUS_FAILURE
            status = constants.STATUS_SUCCESS

        return status

    def handle_publish(self):
        """
        Publish any pending publishes in the publish queue, or the cloud logger
        """

        status = constants.STATUS_SUCCESS

        # Collect all pending publishes in publish queue
        to_publish = []
        while not self.publish_queue.empty():
            try:
                to_publish.append(self.publish_queue.get())
            except queue.Empty:
                break

        if to_publish:
            # If pending publishes are found, parse into list for sending
            messages = []
            batch = {}
            batch['PublishAlarm'] = []
            batch['PublishAttribute'] = []
            batch['PublishTelemetry'] = []
            batch['PublishLocation'] = []
            batch['PublishLog'] = []
            for pub in to_publish:
                message = None
                # ------------------
                # Alarms
                # ------------------
                if pub.type == "PublishAlarm":
                    batch[pub.type].append(
                        tr50.create_alarm_batch_item(
                            pub.name,
                            pub.state,
                            pub.timestamp,
                            pub.message,
                            pub.republish))

                # ------------------
                # Attributes
                # ------------------
                elif pub.type == "PublishAttribute":
                    batch[pub.type].append(
                        tr50.create_attribute_batch_item(
                            pub.name,
                            pub.value,
                            pub.timestamp))

                elif pub.type == "PublishTelemetry":
                    batch[pub.type].append(
                        tr50.create_property_batch_item(
                            pub.name,
                            pub.value,
                            pub.timestamp,
                            corr_id=pub.corr_id))

                # ------------------
                # Location
                # ------------------
                elif pub.type == "PublishLocation":
                    batch[pub.type].append(
                        tr50.create_location_batch_item(
                            pub.latitude,
                            pub.longitude,
                            pub.heading,
                            pub.altitude,
                            pub.speed,
                            pub.accuracy,
                            pub.fix_type,
                            pub.timestamp))

                # ------------------
                # Event logs
                # ------------------
                elif pub.type == "PublishLog":
                    command = tr50.create_log_publish(self.config.key,
                                                      pub.message,
                                                      timestamp=pub.timestamp)
                    message_desc = "Log Publish {}".format(pub.message)
                    message = defs.OutMessage(command, message_desc)

                if message:
                    messages.append(message)

            # Send all publishes
            if messages:
                status = self.send(messages)

            # send out batches
            if batch['PublishAlarm']:
                timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                command = tr50.create_alarm_publish(self.config.key,
                                                    "alarm_batch",
                                                    "Alarm Batch",
                                                    timestamp=timestamp,
                                                    republish=False,
                                                    batch=True)
                message_desc = "Alarm Publish {}".format("alarm_batch")
                message_desc += " : \"{}\"".format("Alarm Batch")
                batch_msg = defs.OutMessage(command, message_desc)
                batch_msg.command['params']['state'] = 0
                batch_msg.command['params']['data'] = batch['PublishAlarm']
                status = self.send(batch_msg)

            if batch['PublishAttribute']:
                timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                command = tr50.create_attribute_publish(self.config.key,
                                                        "attribute_batch",
                                                        "Attribute Batch",
                                                        timestamp=timestamp,
                                                        batch=True)
                message_desc = "Attribute Publish {}".format("attribute_batch")
                message_desc += " : \"{}\"".format("Attribute Batch")
                batch_msg = defs.OutMessage(command, message_desc)
                batch_msg.command['params']['data'] = batch['PublishAttribute']
                status = self.send(batch_msg)

            if batch['PublishLocation']:
                timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                command = tr50.create_location_publish(self.config.key,
                                                        "location_batch",
                                                        "Location Batch",
                                                        timestamp=timestamp,
                                                        batch=True)
                message_desc = "Location Publish {}".format("location_batch")
                message_desc += " : \"{}\"".format("Location Batch")
                batch_msg = defs.OutMessage(command, message_desc)
                batch_msg.command['params']['data'] = batch['PublishLocation']
                status = self.send(batch_msg)

            if batch['PublishTelemetry']:
                timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                command = tr50.create_property_publish(self.config.key,
                                                        "property_batch",
                                                        "Property Batch",
                                                        corr_id=timestamp,
                                                        timestamp=timestamp,
                                                        batch=True)
                message_desc = "Property Publish {}".format("property_batch")
                message_desc += " : \"{}\"".format("Property Batch")
                batch_msgs = defs.OutMessage(command, message_desc)
                batch_msgs.command['params']['data'] =  batch['PublishTelemetry']
                status = self.send(batch_msgs)

        return status

    def handle_work_loop(self):
        """
        Loop for worker threads to handle any items put on the work queue
        """

        # Continuously loop while connected
        while not self.to_quit:
            work = None
            try:
                work = self.work_queue.get(timeout=self.config.loop_time)
            except queue.Empty:
                pass
            # If work is retrieved from the queue, handle it based on type
            if work:
                try:
                    if work.type == constants.WORK_MESSAGE:
                        self.handle_message(work.data)
                    elif work.type == constants.WORK_PUBLISH:
                        self.handle_publish()
                    elif work.type == constants.WORK_ACTION:
                        self.handle_action(work.data)
                    elif work.type == constants.WORK_DOWNLOAD:
                        self.handle_file_download(work.data)
                    elif work.type == constants.WORK_UPLOAD:
                        self.handle_file_upload(work.data)
                except Exception:
                    # Print traceback, but don't kill thread
                    self.logger.exception("Exception:")

        return constants.STATUS_SUCCESS

    def handle_ping(self):
        """
        Request connection check
        """
        command = tr50.create_diag_ping()
        message_desc = "Connected"
        message = defs.OutMessage(command, message_desc)
        status = self.send(message)
        return constants.STATUS_SUCCESS

    def handle_update_thing_details(self, name=None, description=None,
                            iccid=None, esn=None, imei=None, meid=None,
                            imsi=None, unset_fields=[]):
        """
        Request to update a things definition.  The thing key must be
        immutable.  Friendly name and other non connectivity tracking
        keys can be changed, e.g. name, description, ICCID, ESN, IMEI,
        IMSI.
        """
        # if any of the default values are None, unset them in the
        # thing update. Support unsetting members in the thing
        # description.  Maybe remove the unsupported tunnel
        # fields from the thing description TBD.
        unset = []
        list_test = True
        if isinstance(unset_fields, list):
            print("unset_fields is a list of %d items" % len(unset_fields))
            if len(unset_fields) > 0:
                for v in unset_fields:
                    unset.append(v)
        else:
            list_test = False
            status = constants.STATUS_PARSE_ERROR

        if list_test:
            command = tr50.create_thing_update(self.config.key, name,
                            description, iccid, esn, imei, meid, imsi,
                            unset)
            message_desc = "Update Thing Details"
            message = defs.OutMessage(command, message_desc)
            status = self.send(message)
        return status

    def handle_time(self):
        """
        Request time from the cloud
        """
        command = tr50.create_diag_time()
        message_desc = "Retrieving Time.."
        message = defs.OutMessage(command, message_desc)
        status = self.send(message)
        return constants.STATUS_SUCCESS

    def handle_telemetry_get(self, telem_name ):
        """
        Add data to publish queue and wait for cloud response
        """
        command = tr50.create_property_get_current(self.config.key, telem_name)
        message_desc = "Reading current property..."
        message = defs.OutMessage(command, message_desc)

        self.pub_wait = True
        status = self.send(message)
        value = None
        timestamp = None

        # Wait for response from sending to cloud
        while self.pub_wait:
            sleep(0.5)
        # Convert to return codes
        if self.pub_response:
            ret = constants.STATUS_SUCCESS
        else:
            ret = constants.STATUS_FAILURE

        # make sure the key exists or there will be a KeyError
        # exception
        if 'telemetry_current_value' in self.response.keys():
            value = self.response['telemetry_current_value']

        if 'telemetry_current_timestamp' in self.response.keys():
            timestamp = self.response['telemetry_current_timestamp']
        return ret, value, timestamp

    def handle_telemetry_history(self, telem_name, start, end ):
        """
        Add data to publish queue and wait for cloud response
        """
        command = tr50.create_property_get_history(self.config.key,
                telem_name, start, end)
        message_desc = "Reading current property..."
        message = defs.OutMessage(command, message_desc)

        self.pub_wait = True
        status = self.send(message)
        value = None
        timestamp = None

        # Wait for response from sending to cloud
        while self.pub_wait:
            sleep(0.5)
        # Convert to return codes
        if self.pub_response:
            ret = constants.STATUS_SUCCESS
        else:
            ret = constants.STATUS_FAILURE

        if 'telemetry_history_values' in self.response.keys():
            values = self.response['telemetry_history_values']
        return ret, values

    def is_connected(self):
        """
        Returns connection status of Client to Cloud

        """
        return self.state == constants.STATE_CONNECTED


    def log_level(self, log_level=None):
        """
        Set Logging Level

        """
        if log_level:
            if log_level in ('CRITICAL', 'DEBUG', 'ERROR', 'INFO', 'LOG', 'WARNING', 'ALL'):
                if log_level == 'ALL':
                    log_number = getattr(logging, 'DEBUG')
                    self.logger.setLevel(log_number)
                    self.logger.warning("log_level set as 'ALL', DEBUG used as default")
                else:
                    log_number = getattr(logging, log_level)
                    self.logger.setLevel(log_number)
                    self.logger.debug("log_level set as %s", log_level)
            else:
                self.logger.setLevel(logging.DEBUG)
                self.logger.warning("log_level not set or invalid, DEBUG used as default")

        # If no log_level set, set as DEBUG
        else:
            self.logger.setLevel(logging.DEBUG)

        #self.logger.critical("This is a critical")
        #self.logger.debug("This is a debug")
        #self.logger.error("This is a error")
        #self.logger.info("This is a info")
        #self.logger.log(logging.INFO, "This is a log with info")
        #self.logger.warning("This is a warning")

    def main_loop(self):
        """
        Main loop for MQTT to send and receive messages, as well as queue work
        for publishing and checking timeouts
        """

        # Continuously loop while connected or connecting
        while not self.to_quit:

            # If disconnected, attempt to reestablish connection
            if self.state == constants.STATE_DISCONNECTED:
                max_time = self.config.keep_alive
                elapsed_time = (datetime.utcnow() -
                                self.last_connected).total_seconds()
                if max_time == 0 or elapsed_time < max_time:
                    try:
                        result = self.mqtt.reconnect()
                        if result == 0:
                            self.logger.debug("Reconnecting...")
                            self.state = constants.STATE_CONNECTING
                    except Exception:
                        sleep(self.config.loop_time)
                else:
                    self.logger.error("No connection after %d seconds, "
                                      "exiting...",
                                      self.config.keep_alive)
                    self.to_quit = True
                    break

            self.mqtt.loop(timeout=self.config.loop_time)

            # Make a work item to publish anything that's pending
            if not self.publish_queue.empty():
                self.queue_work(defs.Work(constants.WORK_PUBLISH, None))

        # One last loop to send out any pending messages
        self.mqtt.loop(timeout=0.1)

        # Disconnect MQTT
        self.mqtt.disconnect()

        # Wait for worker threads to finish.
        for thread in self.worker_threads:
            thread.join()
        self.worker_threads = []

        # On disconnect, show all messages that never received replies
        if len(self.reply_tracker) > 0:
            self.logger.error("These messages never received a reply:")
            for mid, message in self.reply_tracker.items():
                self.logger.error(".... %s - %s", mid,
                                  message.description)

        return constants.STATUS_SUCCESS

    def num_unfinished(self):
        """
        Get number of unfulfilled requests
        """
        return len(self.mqtt._out_messages)

    def on_connect(self, mqtt, userdata, flags, rc):
        """
        Callback when MQTT Client connects to Cloud
        """
        unfinished = self.num_unfinished()
        if (unfinished > 0):
            self.logger.info("%s messages are pending..", unfinished)
        # Check connection result from MQTT
        self.logger.info("MQTT connected: %s", mqttlib.connack_string(rc))
        if rc == 0:
            self.state = constants.STATE_CONNECTED
        else:
            self.state = constants.STATE_DISCONNECTED
            self.last_connected = datetime.utcnow()

    def on_disconnect(self, mqtt, userdata, rc):
        """
        Callback when MQTT Client disconnects from Cloud
        """

        if self.to_quit:
            self.logger.info("MQTT disconnected")
        else:
            self.logger.error("MQTT connection lost. Attempting to reconnect...")
            self.last_connected = datetime.utcnow()
        self.state = constants.STATE_DISCONNECTED

    def on_message(self, mqtt, userdata, msg):
        """
        Callback when MQTT Client receives a message
        """

        message = defs.Message(msg.topic, json.loads(msg.payload.decode()))
        self.logger.debug("Received message on topic \"%s\"\n%s", msg.topic,
                          message)

        # Queue work to handle received message. Don't block main loop with this
        # task.
        work = defs.Work(constants.WORK_MESSAGE, message)
        self.queue_work(work)

    def on_publish(self, mqtt, userdata, mid):
        """
        Notify that a message has been published
        """
        if self.reply_tracker != {}:
            topic_num = self.reply_tracker.pop_mid(mid)
            self.logger.debug("MQTT sent %s", topic_num)

    def qos_level(self, qos_level=None):
        """
        Set QoS Level

        """
        if qos_level in range(0, 2):
            self.qos_level = qos_level
            self.logger.info("qos_level set as %s", self.qos_level)
        else:
            self.logger.warning("qos_level invalid or not set, 1 used as default")
            self.qos_level = 1

    def queue_publish(self, pub):
        """
        Place pub in the publish queue
        """

        self.publish_queue.put(pub)
        return constants.STATUS_SUCCESS

    def queue_work(self, work):
        """
        Place work in the work queue
        """

        self.work_queue.put(work)
        return constants.STATUS_SUCCESS

    def request_publish(self, data, cloud_response):
        """
        Add data to publish queue and wait for cloud response
        """
        current_time = datetime.utcnow()
        end_time = current_time + timedelta(seconds=15)
        timeout = False

        self.pub_wait = cloud_response
        status = self.queue_publish(data)
        if cloud_response:
            status = constants.STATUS_FAILURE
            # Wait for response from sending to cloud
            while self.pub_wait and not self.to_quit:
                current_time = datetime.utcnow()
                if (current_time > end_time):
                    timeout = True
                    break
                else:
                    sleep(0.5)

            # Convert to return codes
            if self.pub_response:
                status = constants.STATUS_SUCCESS
            elif timeout:
                status = constants.STATUS_TIMED_OUT
        return status

    def request_download(self, file_name, file_dest, blocking=False,
                         callback=None, timeout=0, file_global=False):
        """
        Request a C2D file transfer
        """

        current_time = datetime.utcnow()
        end_time = current_time + timedelta(seconds=timeout)

        self.logger.info("Request download of %s", file_name)

        # is file_dest the full path or the parent directory?
        if os.path.isdir(file_dest):
            file_dest = os.path.join(file_dest, file_name)

        # File Transfer object for tracking progress
        transfer = defs.FileTransfer(file_name, file_dest, self.client,
                                     callback=callback)

        # Generate and send message to request file transfer
        command = tr50.create_file_get(self.config.key, file_name, file_global)
        message = defs.OutMessage(command, "Download {}".format(file_name),
                                  data=transfer)
        status = self.send(message)

        # If blocking is set, wait for result of file transfer
        if status == constants.STATUS_SUCCESS and blocking:
            while ((timeout == 0 or current_time < end_time) and
                   transfer.status is None):
                sleep(0.1)
                current_time = datetime.utcnow()

            if transfer.status is None:
                status = constants.STATUS_TIMED_OUT
            else:
                status = transfer.status

        return status

    def request_upload(self, file_path, upload_name=None, blocking=False,
                       callback=None, timeout=0, file_global=False):
        """
        Request a D2C file transfer
        """

        status = constants.STATUS_SUCCESS
        current_time = datetime.utcnow()
        end_time = current_time + timedelta(seconds=timeout)
        transfer = None

        self.logger.info("Request upload of %s", file_path)

        # Path must be absolute
        if not os.path.isabs(file_path):
            self.logger.error("Path must be absolute \"%s\"", file_path)
            status = constants.STATUS_NOT_FOUND

        if status == constants.STATUS_SUCCESS:
            # Check if file exists
            if not os.path.isfile(file_path):
                # No file to upload
                self.logger.error("Cannot find file %s. "
                                  "Upload cancelled.", file_path)
                status = constants.STATUS_NOT_FOUND
            else:
                transfer = None
                file_name = os.path.basename(file_path)
                if not upload_name:
                    upload_name = file_name

                # Get file crc32 checksum
                checksum = 0
                with open(file_path, "rb") as up_file:
                    for chunk in up_file:
                        checksum = crc32(chunk, checksum)
                checksum = checksum & 0xffffffff

                # File Transfer object for tracking progress
                transfer = defs.FileTransfer(upload_name, file_path,
                                             self.client,
                                             callback=callback)

                # Generate and send message to request file transfer
                command = tr50.create_file_put(self.config.key, upload_name,
                                               crc32=checksum,
                                               file_global=file_global)
                message_desc = "Upload {} as {}".format(file_name,
                                                        upload_name)
                message = defs.OutMessage(command, message_desc,
                                          data=transfer)
                status = self.send(message)

                # If blocking is set, wait for result of file transfer
                if status == constants.STATUS_SUCCESS and blocking:
                    while ((timeout == 0 or current_time < end_time) and
                           not self.to_quit and transfer.status is None):
                        sleep(0.1)
                        current_time = datetime.utcnow()

                    if transfer.status is None:
                        status = constants.STATUS_TIMED_OUT
                    else:
                        status = transfer.status

        return status

    def send(self, messages):
        """
        Send commands to the Cloud, and track them to wait for replies
        """
        status = constants.STATUS_FAILURE

        message_list = messages
        if messages.__class__.__name__ != "list":
            message_list = [messages]

        # Generate final request string
        payload = tr50.generate_request([x.command for x in message_list])

        # Lock to ensure all outgoing messages are tracked before handling
        # received messages
        self.lock.acquire()
        try:
            # Obtain new unused topic number
            while True:
                topic_num = "{:0>4}".format(self.topic_counter)
                self.topic_counter += 1
                if topic_num not in self.reply_tracker:
                    break
            self.pub_topic = topic_num
            # -----------------------------------------------------
            # Send payload over MQTT
            # Add small delay here so that we don't cross the API/s
            # threshold
            # -----------------------------------------------------
            sleep(self.client.idle_sleep)
            result, mid = self.mqtt.publish("api/{}".format(topic_num),
                                            payload, qos = self.qos_level)

            # Track the topic this message will send on
            self.reply_tracker.add_mid(mid, topic_num)

            # Current timestamp to mark when message was sent
            current_time = datetime.utcnow()

            # Track each message
            for num, msg in enumerate(message_list):
                # Add timestamps and ids
                msg.timestamp = current_time
                msg.out_id = "{}-{}".format(topic_num, num+1)

                self.reply_tracker.add_message(msg)
                self.logger.info("MQTT queued %s-%d - %s\n%s", topic_num, num+1,
                                 msg, json.dumps(msg.command, indent=2,
                                                 sort_keys=True))
            status = constants.STATUS_SUCCESS

        finally:
            self.lock.release()

        return status

