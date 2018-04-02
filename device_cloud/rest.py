'''
    Simple Device Cloud REST API interface.  The primary goal of this
    interface is to provide a REST API for device side use.
'''

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
import requests
import sys
import grequests
import os
from binascii import crc32
import certifi
import collections
import uuid

# for path name processing on windows and linux
import ntpath
from datetime import datetime

success = 0
error = 1

class Rest(object):
    """
    Class top level for DeviceCloudRest.  This class provides Device
    Cloud interaction via REST.  This class supports a RAW TR50
    command interface where the user is expected to know the TR50
    command string and parameters.  This class also supports a subset
    of helper API calls like "upload_to_cloud".
    """

    def __init__(self, cloud, username=None, password=None, sub_org=None, token=None):
        """
        Class initialization routine.
        Default class members:
            * self.ack_timeout = 30
            * self.cloud = cloud
            * self.username = username
            * self.password = password
            * self.default_org_id = None
            * self.thing_key = None
            * self.session_id = None
            * self.output = None
            * self.validate_cloud_cert = True
        Constructor:
            The constructor does the following:
                * gets a session
                * sets a sub org if specified
        Return:
            * object
        """

        self.ack_timeout = 30
        self.cloud = cloud
        self.username = username
        self.password = password
        self.token = token
        self.default_org_id = None
        self.thing_key = None
        self.session_id = None
        self.output = None
        self.validate_cloud_cert = True
        self.default_thing_key = None
        self.app_id = None

        if not username and not token:
            self.error_quit("Error: missing username/password or token")

        if token:
            # generate the app_id and thing key for this session
            # write app id to a file otherwise it can't reconnect
            # expecting the current dir.
            self.app_id = self.set_ids(".app_id")
            if not self.app_id:
                self.error_quit("Error: .app_id is null")
            self.default_thing_key = self.set_ids(".default_thing_key")

        session_info = self._get_session()
        if session_info.get("success") is True:
            self.session_id = session_info["params"].get("sessionId")
        if self.session_id:
            print("Session ID: {} - OK".format(self.session_id))
        else:
            self.error_quit("Failed to get session id.")

        if sub_org and not self.token:
            params = {"key":sub_org}
            cmd = "session.org.switch"
            status, result = self.execute(cmd, params)
            if status == False:
                self.error_quit("Error: unable to swith to org {}".format(sub_org))

    def set_ids(self, file_name):
        if os.path.isfile(file_name):
            with open(file_name, 'r') as id_file:
                my_id = str(id_file.read())
        else:
            with open(file_name, 'w') as id_file:
                my_id = str(uuid.uuid4())
                id_file.write(my_id)
        return my_id

    def execute(self, cmd, params, debug=False):
        """
        Execute a REST command.  This is advanced command support for
        ANY REST command supported by the cloud.  This command expects
        the user to be familiar with TR50 commands and the required
        parameters.  No parameters are checked.  The status and raw
        JSOn result is returned. This API is used for all helper APIs
        below.  For details on using TR50 commands, see:
            * https://knowledge.windriver.com/@api/deki/files/381346/wr_helix_device_cloud_service_api_reference.pdf?revision=1

        Required Parameters:
            * cmd (string) name of the command to execute, e.g. "thing.list"
            * params (JSON or dict) the parameters for the command
        Returns:
            * status (boolean)
            * result (JSON) raw result returned from cloud
        """

        print("Executing command: {}".format(cmd))
        print("Parameters       : {}".format(params))

        data = {"cmd":{"command":cmd, "params":params}}
        result = self.send(data)
        status = result.get("success")
        if debug:
            print(json.dumps(result, indent=2, sort_keys=True))
        return status, result

    def get_logs(self, thing_key, thing_id=None, trigger_id=None,
                campaign_id=None, offset=None, limit=None, start=None,
                end=None, level=None, corr_id=None):
        """
        Retrive logs from the Cloud
        Parameters:
            Required:
                * thing_key (string) thing key
            Optional:
                * thing_id (string) thing ID
                * trigger_id (string) trigger ID
                * campaign_id (string) campaign ID
                * offset (integer, default:0) Starting list offset
                * limit (integer, default:?) Limit number of results
                * start (string) Start date range
                * end (string) End date range
                * level (integer) level of logged entry
                * corr_id (string) correlation ID
        Return:
            * JSON string
        """

        data_params = {"thingKey":thing_key}
        if start:
            data_params.update({"start":start})
        if end:
            data_params.update({"end":end})
        if thing_id:
            data_params.update({"thingId":thing_id})
        if trigger_id:
            data_params.update({"triggerId":trigger_id})
        if campaign_id:
            data_params.update({"campaignId":campaign_id})
        if offset:
            data_params.update({"offset":offset})
        if limit:
            data_params.update({"limit":limit})
        if level:
            data_params.update({"level":level})
        if corr_id:
            data_params.update({"corrId":corr_id})

        data = {"cmd":{"command":"log.list", "params":data_params}}
        return self.send(data)

    def _get_session(self):
        """
        Get session for future communications with Cloud.  The
        constructor calls this function.
        Parameters:
            * None
        Return:
            * JSON string with property details
            * return.get("success") will be True or False
        """

        if not self.token:
            params = {"username":self.username, "password":self.password}
            data = {"auth":{"command":"api.authenticate", "params":params}}
        else:
            params = {"appToken":self.token, "appId":self.app_id, "thingKey":self.default_thing_key}
            data = {"auth":{"command":"api.authenticate", "params":params}}
        return self.send(data)

    def method_exec(self, thing_key, method_name, params=None,
                    ttl=None, async_callback=None):
        """
        Execute an action or method on a device.  If a async_callback
        is not None, then this action is considered non blocking.
        Parameters:
        * Required:
            * thing_key
            * method_name
        Optional:
          * ttl  (integer, default:0) time to live in seconds.  Typically used with offline devices
          * async_callback (function, default:None) callback invoked after action completion
            Note: callback signature:
              def my_callback(response, *args, **kwargs):
        Return:
            * JSON string with thing details
            * return.get("success") will be True or False
        """

        data_params = {"thingKey":thing_key, "method":method_name}

        # when sending non blocking operations, override the
        # acktimeout
        if not async_callback:
            data_params["ackTimeout"] = self.ack_timeout
        else:
            self.async_callback = async_callback
            data_params["ackTimeout"] = 0

        if ttl:
            data_params["ttl"] = ttl

        if params:
            data_params["params"] = params

        data = {"cmd":{"command":"method.exec", "params":data_params }}
        result = self.send(data, async_callback=async_callback)
        if not async_callback:
            if result.get("success") is False:
                print("Error: message: {}".format(result.get("errorMessages")))
        return result

    def send(self, data, async_callback=None):
        """
        Handler used to send all device cloud commands to cloud.  This
        handler is call by APIs and not typically called directly.
        Parameters:
            Required:
                * data (string) JSON string with command to send
            Optional:
                * async_callback (function, default:None) callback on completion
        Return:
            * dict: {"success":False, "content":r.content, "status_code":r.status_code}
        """
        headers = None
        if self.session_id:
            headers = {"sessionId":self.session_id}
        datastr = json.dumps(data)
        if not async_callback:
            r = requests.post("https://"+self.cloud+"/api", headers=headers, data=datastr)
            if r.status_code == 200:
                try:
                    rjson = r.json()
                    if "auth" in rjson:
                        ret = rjson["auth"]
                    elif "cmd" in rjson:
                        ret = rjson["cmd"]
                    return ret
                except Exception as error:
                    print(error)
            result = {"success":False, "content":r.content, "status_code":r.status_code}
        else:
                async_list = []
                rs = grequests.post("https://"+self.cloud+"/api",
                            hooks={'response': async_callback},
                            headers=headers, data=datastr )
                async_list.append(rs)
                result = grequests.map(async_list)

        return result

    def set_ack_timeout(self, secs):
        """
        Set method ackTimeout
        """

        self.ack_timeout = secs
        return success

    def upload_to_cloud(self, thing_key, local_file, cloud_name=None,
                        global_store=False, public=False, tags=None,
                        sec_tags=None, ttl=None,
                        log_on_completion=True):
        """
        Upload a file to the cloud.
        Parameters:
            Required:
                * thing_key (string) think key
                * local_file (string) name of the file on the filesystem
            Optional:
                * cloud_name (string, default:local_file) name to save the file as in the cloud
                * global_store (boolean, default:False) save file to the global or thing file store
                * public (boolean, default:False) allow access to the file outside of the organization
                * tags (JSON array, default:None) tags for the file
                * sec_tags (JSON array, default:None) secure tags
                * ttl (integer, Default:?) time to live seconds before a partial upload is removed
                * log_on_completion (boolean, default:True) publish an event on completion
        Return:
            * status (boolean)
            * result (object) requests.Response raw object.
            * e.g.: get status from response.status_code, response.reason
        """
        response = requests.Response()
        response.status_code = 500
        if not os.path.exists(os.path.abspath(local_file)):
            response.reason = "Error: file {} does not exist".format(local_file)
            return False, response

        local_basename = ntpath.basename(local_file)
        local_abs_path = os.path.abspath(local_file)

        if not cloud_name:
            cloud_name = local_basename

        # Get file crc32 checksum
        checksum = self.calculate_crc32(local_abs_path)
        cmd = "file.put"
        params = {
            "thingKey":thing_key,
            "fileName":cloud_name,
            "public":public,
            "crc32":checksum,
            "tags":tags,
            "secTags":sec_tags,
            "ttl":ttl,
            "logComplete":log_on_completion,
            "global":global_store
        }

        status, result = self.execute(cmd, params)

        # now get the user ID from this
        if status == True:
            file_id = result["params"].get("fileId")
            url = "https://{}/file/{}".format(self.cloud, file_id)

            if not self.validate_cloud_cert:
                verify=False
            else:
                verify=certifi.where()

            with open(local_abs_path, "rb") as up_file:
                response = requests.post(url, data=up_file,
                                        verify=verify)

            if response.status_code == 200:
                status = True
                print("INFO: Successfully uploaded {}".format(local_file))
            else:
                status = False
                print("ERROR: failed to upload {}".format(local_file))
                print(response.json())
        return status, response

    def download_from_cloud(self, thing_key, cloud_file_name, local_file_name=None,
                            global_store=False ):
        """
        Download a file from the cloud
        Parameters:
            Required:
                * thing_key (string) thing key
                * cloud_file_name (string) name of the file on the cloud
            Optional:
                * local_file_name (string, default:cloud_file_name) name to save as locally
                * global_store (boolean, default:False) download from the global or private file share
        Returns:
            * status (boolean)
            * result (object) requests.Response raw object.
            * e.g.: get status from response.status_code, response.reason
        """
        status = False
        response = requests.Response()
        response.status_code = 500
        cmd = "file.get"
        params = {
            "thingKey":thing_key,
            "fileName":cloud_file_name,
            "global":global_store
        }
        status, result = self.execute(cmd, params)

        # now get the user ID from this
        if status == True:
            file_id = result["params"].get("fileId")
            crc32 = result["params"].get("crc32")
            file_size = result["params"].get("fileSize")
            status = False

            url = "https://{}/file/{}".format(self.cloud, file_id)

            if not self.validate_cloud_cert:
                verify=False
            else:
                verify=certifi.where()

            if not local_file_name:
                local_file_name = cloud_file_name

            hdrs = {}
            temp_file = cloud_file_name + ".part"
            response = requests.get(url, stream=True, verify=verify, timeout=3, headers=hdrs)
            if response.status_code == 200 or response.status_code == 206:
                count = 0
                download_len = 0
                chunk_size = 4096
                chunk = None
                with open(temp_file, "wb") as fh:
                    try:
                        for chunk in response.iter_content(chunk_size):
                            if not chunk:
                                break
                            fh.write(chunk)
                            if count % 100 == 0:
                                download_len = int(os.path.getsize(temp_file))
                                progress = 100 * (float(download_len)/file_size)
                                print("Download progress %0.2f(%%)" % float(progress))
                            count +=1
                    except (Exception) as e:
                        print("Exception: %s",str(e))
                response.close()
                fh.close()

                checksum = self.calculate_crc32(temp_file)
                if checksum == str(crc32):
                    try:
                        os.rename(temp_file, local_file_name )
                    except (Exception) as e:
                        print("Exception: %s",str(e))
                        os.remove(local_file_name)
                        os.rename(temp_file, local_file_name)
                    print ("Successfully downloaded {}".format(local_file_name))
                    status = True
                elif download_len != file_size:
                    print("ERROR: download was interrupted")
                else:
                    self.logger.error("Fatal error: download completed but checksum"
                       " does not match expected.  Deleting file.")
                    os.remove(file_xfer_obj.download_temp_path)
        return status, response

    # -------------------------------------------------
    # Utility functions
    # The following functions are for convenience only.
    # --------------------------------------------------
    def calculate_crc32(self, file_name):
        """
        Calculate the crc32 checksum on a file and return the string
        interpretation of it.  Checksum of None means it failed.
        Parameters:
            * file_name (string) name of the file typically an abs path.
        Returns:
            * crc32 checksum
        """
        sample = 0
        checksum = None
        if os.path.exists(file_name):
            for chunk in open(file_name, "rb"):
                sample = crc32(chunk, sample)
            checksum = "%s" % (sample & 0xffffffff)
        return checksum

    def check_for_match(self, haystack, needle):
        """
        Simple function to find a needle in a haystack
        """

        found = False
        for x in range(len(haystack)):
            if needle in haystack[x]['msg']:
                print("Log: \"{}\" - OK".format(haystack[x]['msg']))
                found = True
        return found

    def error_quit(self, args):
        """
        Print error messages and exit with error code 1
        """

        print(args)
        sys.exit(1)

    def strtotime(self, string):
        """
        Convert string to a datetime object
        """

        return datetime.strptime(string, "%Y-%m-%dT%H:%M:%S.%fZ")

    def timetostr(self, dtime):
        """
        Convert datetime into a string
        """

        return dtime.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
