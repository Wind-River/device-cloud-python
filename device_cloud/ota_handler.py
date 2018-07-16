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
OTA Handler for the Helix Device Cloud Python-based Device Manager. The device
manager (or other external modules) can use `update_callback` as the callback
for a HDC method, and the OTA handler will take care of running the update
process.
"""

import json
import os
import shutil
import tarfile
import threading
import zipfile
from datetime import datetime
from device_cloud import osal
import device_cloud as iot

# Alarm Constants
ALARM_NAME = "software_update"
ALARM_STARTED = 0
ALARM_PRE_INSTALL = 1
ALARM_INSTALL = 2
ALARM_POST_INSTALL = 3
ALARM_INSTALL_ERROR = 4
ALARM_COMPLETE = 5
ALARM_FAILED = 6

# General Constants
OTA_LOCKFILE = ".otalock"
OTA_PACKAGEDIR = "otapackage"
OTA_STDOUT_LOG = "ota_install.log"

class OTAHandler(object):
    """
    Class for handling OTA updates.
    """
    _runtime_dir = '.'
    _update_thread = None
    def __init__(self, offline=False):
        self.offline = offline

    ## Public Methods ##
    def is_running(self):
        """
        Checks if there is an update in progress.
        """
        if self._update_thread:
            return self._update_thread.is_alive()
        else:
            return False

    def join(self):
        """
        If the update thread exists, join it (wait until it exits).
        """
        if self._update_thread and self._update_thread.is_alive():
            self._update_thread.join()

    def update_callback(self, client, params, user_data, request):
        """
        Callback to be registered as an action in the client. This will lock the
        updater until the current update is complete, or return an error if
        there is already an update in progress. If all is OK, then a new thread
        will be started to handle the update and a success status is returned to
        the cloud.
        """
        self._runtime_dir = user_data[0]

        if not os.path.isfile(os.path.join(self._runtime_dir, OTA_LOCKFILE)):

            # Create an empty lockfile
            open(os.path.join(self._runtime_dir, OTA_LOCKFILE), 'a').close()

            # Run the updating in the background to block the main thread
            self._update_thread = threading.Thread(target=self._update_software,
                                                   args=(client, params,
                                                         request))
            self._update_thread.start()
            result = (iot.STATUS_INVOKED, "Software Update Started (Invoked)")
        else:
            result = (iot.STATUS_FAILURE, \
                      "Software update already in progress!")

        return result

    ## Private Methods ##
    def _scrub_file_name(self, client, fn):
        """
        Script used to sanitize a log file name for valid characters.
        The file is uploaded to the cloud with the scrubbed name.
        """
        safe_string = ''
        safe_special_chars = ['_', '.', '-']
        override_char = '_'
        for c in fn:
            if c.isalnum() or c in safe_special_chars:
                safe_string +=  c
            else:
                #override whatever non supported char to underscore
                safe_string += override_char
        return safe_string

    def _update_software(self, client, params, request):
        """
        Main method that will run in a new thread and perform all the software
        updates
        """

        status = iot.STATUS_BAD_PARAMETER
        update_data = None
        package_name = None

        override_ota_logfile_name = None

        client.log(iot.LOGINFO, "Started OTA Update")
        client.event_publish("OTA: Started OTA Update")
        client.action_progress_update(request.request_id, "Started OTA Update")

        package_dir = os.path.join(self._runtime_dir, OTA_PACKAGEDIR)

        # Cleanup last ota artifacts
        if os.path.isdir(package_dir):
            client.log(iot.LOGINFO,"Clean up previous update artifacts...")
            shutil.rmtree(package_dir)

        # get extra params
        extra_params = params.get("extra_params")
        client.log(iot.LOGINFO,"Extra parameters {}".format(extra_params))

        if params:
            error_notified = False

            download_timeout = params.get("ota_timeout")
            if params.get("ota_logfile"):
                override_ota_logfile_name = self._scrub_file_name(client, params.get("ota_logfile"))
                client.log(iot.LOGINFO, "Override OTA logfile name {}".format(override_ota_logfile_name))

            # 1. Download Package
            client.log(iot.LOGINFO, "Downloading Package...")
            client.event_publish("OTA: Downloading Package...")
            package_name = params.get("package")
            client.alarm_publish(ALARM_NAME, ALARM_STARTED, message="package: {}".format(package_name))
            status = self._package_download(client, package_name, download_timeout)

            # 2. Unzip Package
            if status == iot.STATUS_SUCCESS or self.offline:
                client.log(iot.LOGINFO, "Download Phase Done!")
                client.event_publish("OTA: Download Successful!")

                client.log(iot.LOGINFO, "Unzipping Package...")
                client.event_publish("OTA: Unzipping Package...")
                status = self._package_unzip(package_name, package_dir)
            elif not error_notified:
                error_notified = True
                client.log(iot.LOGERROR, "Download Failed!")
                client.event_publish("OTA: Download Failed!")

            # 3. Read Update Data from JSON File
            if status == iot.STATUS_SUCCESS:
                client.log(iot.LOGINFO, "Unzip Complete!")
                client.event_publish("OTA: Package Unzip Successful!")

                client.log(iot.LOGINFO, "Reading Update Data...")
                client.event_publish("OTA: Reading Update Data...")
                status, update_data = self._read_update_json(package_dir)
            elif not error_notified:
                error_notified = True
                client.log(iot.LOGERROR, "Unzip Failed!")
                client.event_publish("OTA: Package Unzip Failed!")

            # 4. Run Pre-Install
            if status == iot.STATUS_SUCCESS:
                client.log(iot.LOGINFO, "Data Read Successful!")
                client.event_publish("OTA: Update Data Read Successfully!")

                client.log(iot.LOGINFO, "Running Pre-Install...")
                client.event_publish("OTA: Running Pre-Install...")
                client.action_progress_update(request.request_id, "Running Pre-Install")
                client.alarm_publish(ALARM_NAME, ALARM_PRE_INSTALL, message="package: {}".format(package_name))
                if not update_data.get('pre_install', ""):
                    status = iot.STATUS_SUCCESS
                    client.log(iot.LOGINFO, "No Pre-Install specified! "
                                            "Continuing.")
                    client.event_publish("OTA: No Pre-Install specified! "
                                         "Continuing.")
                else:
                    status = self._execute(client, update_data['pre_install'], \
                                           package_dir, extra_params)
            elif not error_notified:
                error_notified = True
                client.log(iot.LOGERROR, "Data Read Failed!")
                client.event_publish("OTA: Failed to Read Update Data!")

            # 5. Run Install
            if status == iot.STATUS_SUCCESS:
                if update_data.get('pre_install', ""):
                    client.log(iot.LOGINFO, "Pre-Install Complete!")
                    client.event_publish("OTA: Pre-Install Successful!")
                    client.action_progress_update(request.request_id, "Pre-Install Successful")

                client.log(iot.LOGINFO, "Running Install...")
                client.event_publish("OTA: Running Install...")
                client.action_progress_update(request.request_id, "Running Install")
                client.alarm_publish(ALARM_NAME, ALARM_INSTALL, message="package: {}".format(package_name))
                status = self._execute(client, update_data['install'], package_dir, extra_params)
            elif not error_notified:
                error_notified = True
                client.log(iot.LOGERROR, "Pre-Install Failed!")
                client.event_publish("OTA: Pre-Install Failed!")
                client.action_progress_update(request.request_id, "Pre-Install Failed")

            # 6. Run Post-Install
            if status == iot.STATUS_SUCCESS:
                client.log(iot.LOGINFO, "Install Complete!")
                client.event_publish("OTA: Install Successful!")
                client.action_progress_update(request.request_id, "Install Successful")

                client.log(iot.LOGINFO, "Running Post-Install...")
                client.event_publish("OTA: Running Post-Install...")
                client.action_progress_update(request.request_id, "Running Post-Install")
                client.alarm_publish(ALARM_NAME, ALARM_POST_INSTALL, message="package: {}".format(package_name))
                if not update_data.get('post_install', ""):
                    status = iot.STATUS_SUCCESS
                    client.log(iot.LOGINFO, "No Post-Install specified! "
                                            "Continuing.")
                    client.event_publish("OTA: No Post-Install specified! "
                                         "Continuing.")
                else:
                    status = self._execute(client, update_data['post_install'], \
                                           package_dir, extra_params)
            elif not error_notified:
                error_notified = True
                client.log(iot.LOGERROR, "Install Failed!")
                client.event_publish("OTA: Install Failed!")
                client.action_progress_update(request.request_id, "Install Failed")

            if status == iot.STATUS_SUCCESS:
                if update_data.get('post_install', ""):
                    client.log(iot.LOGINFO, "Post-Install Complete!")
                    client.event_publish("OTA: Post-Install Successful!")
                    client.action_progress_update(request.request_id, "Post-Install Successful")
                    status = iot.STATUS_SUCCESS
            elif not error_notified:
                error_notified = True
                client.log(iot.LOGERROR, "Post-Install Failed!")
                client.event_publish("OTA: Post-Install Failed!")
                client.action_progress_update(request.request_id, "Post-Install Failed")

        # 7. Report Final Status
        if status == iot.STATUS_SUCCESS:
            client.log(iot.LOGINFO, "OTA Successful!")
            client.event_publish("OTA: Update Successful!")
            client.action_progress_update(request.request_id, "Update Successful")
            client.alarm_publish(ALARM_NAME, ALARM_COMPLETE, message="package: {}".format(package_name))
            status_string = ""

        else:
            if update_data and 'error_action' in update_data and \
               update_data['error_action']:
                client.event_publish("OTA: Running install error action!")
                client.alarm_publish(ALARM_NAME, ALARM_INSTALL_ERROR, message="package: {}".format(package_name))
                client.log(iot.LOGWARNING, "Running install error action!")
                self._execute(client, update_data['error_action'], package_dir, extra_params)

            client.log(iot.LOGERROR, "OTA Failed!")
            client.event_publish("OTA: Update Failed!")
            client.action_progress_update(request.request_id, "Update Failed")
            client.alarm_publish(ALARM_NAME, ALARM_FAILED, message="package: {}".format(package_name))
            status_string = iot.status_string(status)

        # -----------------------------------------------------------------
        # write the id,status to a file for when the agent is updated.  The
        # device manager checks for a file "message_ids" and acks the
        # action.
        # -----------------------------------------------------------------
        path = os.path.join(self._runtime_dir, "message_ids")
        open_mode = 'w'
        if os.path.exists(path):
            open_mode = 'a'
        with open(path, open_mode) as fh:
            fh.write("{},{}\n".format(request.request_id, status))
        client.action_acknowledge(request.request_id,
                                  status, status_string)

        file_name = os.path.join(self._runtime_dir, "download", package_name)
        if os.path.isfile(file_name):
            client.log(iot.LOGWARNING,"removing file name %s" % file_name)
            os.remove(file_name)

        # Unlock the updater
        try:
            os.remove(os.path.join(self._runtime_dir, OTA_LOCKFILE))
        except (OSError, IOError) as err:
            error = str(err)
            print(error+". This file will block future OTA operations. Please remove it.")

        client.log(iot.LOGINFO, \
            "Update finished with status {}".format(iot.status_string(status)))
        stdout_log = os.path.abspath( os.path.join(package_dir, OTA_STDOUT_LOG) )
        client.log(iot.LOGINFO, "Logging stdout to file {}".format( stdout_log))

        # print the stdout log to the client log
        # upload the stdout log to cloud
        if os.path.isfile(stdout_log):
            client.log(iot.LOGINFO,"OTA STDOUT log dump start")
            with open(stdout_log) as fh:
                while True:
                    line = fh.readline()
                    if line == "":
                        break
                    else:
                        client.log(iot.LOGINFO,"{}".format(line.rstrip()))
            client.log(iot.LOGINFO,"OTA STDOUT log dump complete.")
            ts = datetime.utcnow().strftime("%Y-%m-%d-%S")
            client.log(iot.LOGINFO,"override_ota_logfile_name {} \n\n".format(override_ota_logfile_name))
            if override_ota_logfile_name is not '':
                output_file = override_ota_logfile_name
            else:
                output_file = "ota_install-{}.log".format(ts)
            client.file_upload(stdout_log, upload_name=output_file,
                                blocking=True, timeout=60, file_global=False),

        # Reboot if requested
        if update_data and 'reboot' in update_data and \
           update_data['reboot'] == 'yes':
            osal.system_reboot()

    def _package_download(self, client, file_name, timeout):
        """
        Method to download the package from the cloud
        """
        status = iot.STATUS_FAILURE

        # Default timeout set as 10 mins
        if timeout in (0, None):
            timeout = 600
        if client:
            out_dir = os.path.join(self._runtime_dir, "download")
            if not os.path.isdir(out_dir):
                os.makedirs(out_dir)

            if not self.offline:
                out_file = os.path.join(self._runtime_dir, "download", file_name)
                if os.path.isfile(out_file):
                    os.remove(out_file)

                for attempts in range(20):
                    if file_name:
                        status = client.file_download(file_name, out_file, \
                                                  blocking=True, timeout=timeout, \
                                                  file_global=True)
                        if status == iot.STATUS_NOT_FOUND:
                            status = client.file_download(file_name, out_file, \
                                                      blocking=True, timeout=timeout, \
                                                      file_global=False)
                        if status == iot.STATUS_SUCCESS:
                            break

        else:
            status = iot.STATUS_BAD_PARAMETER

        return status

    def _package_unzip(self, file_name, dir_out):
        """
        Method that will unzip the downloaded package into the specified
        directory
        """
        result = iot.STATUS_BAD_PARAMETER

        file_name = os.path.join(self._runtime_dir, "download", file_name)

        if os.path.isfile(file_name):
            archive = None
            try:
                if file_name.endswith(".zip"):
                    archive = zipfile.ZipFile(file_name, 'r')
                elif file_name.endswith(".tar.gz"):
                    archive = tarfile.open(file_name, 'r:gz')
                else:
                    result = iot.STATUS_NOT_SUPPORTED

                if archive:
                    try:
                        archive.extractall(dir_out)
                        result = iot.STATUS_SUCCESS
                    except (OSError, IOError) as err:
                        print(err)
                        result = iot.STATUS_IO_ERROR
                    finally:
                        archive.close()
            except (OSError, IOError) as err:
                print(err)
                result = iot.STATUS_FILE_OPEN_FAILED

        return result

    def _read_update_json(self, package_dir):
        """
        Opens and reads the update.json file
        """
        status = iot.STATUS_FAILURE
        update_data = None

        file_path = os.path.join(package_dir, 'update.json')
        if os.path.isfile(file_path):
            try:
                with open(file_path) as data_file:
                    update_data = json.load(data_file)
                    status = iot.STATUS_SUCCESS
            except (IOError, ValueError):
                status = iot.STATUS_IO_ERROR
        else:
            status = iot.STATUS_BAD_PARAMETER

        return (status, update_data)

    def _execute(self, client, command, working_dir=None, extra_params=None):
        """
        Runs a shell command, if not empty. If there is a working directory
        specified, the command is modified to use this directory.
        """
        if command:
            # redirection to a log file is valid on windows and unix
            # like systems
            log_append = ">> {}".format(OTA_STDOUT_LOG)
            redir_output = "2>&1"
            if working_dir and os.path.isdir(working_dir):
                if osal.WIN32:
                    cmd_sep = " &"
                else:
                    cmd_sep = ";"

                command = "cd {}{} {}".format(working_dir, cmd_sep, command)
            cmd = "{}{} {}".format(command, log_append, redir_output)

            # export the extra params to an env var that the os.system
            # cmd can exexute
            if extra_params:
                os.environ["HDC_EXTRA_PARAMS"] =  extra_params

            # setup some HDC envs here
            os.environ["HDC_CONFIG_DIR"] = client.config.config_dir 
            os.environ["HDC_RUNTIME_DIR"] = os.path.dirname(os.path.realpath(__file__))

            result = os.system(cmd)
            if result:
                status = iot.STATUS_EXECUTION_ERROR
            else:
                status = iot.STATUS_SUCCESS
        else:
            status = iot.STATUS_NOT_FOUND

        return status
