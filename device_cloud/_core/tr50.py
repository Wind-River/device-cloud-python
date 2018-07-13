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
This module contains functions for generating TR50 messages relevent to the
Client application
"""

import json

from device_cloud._core import constants


CLOUD_ERROR_CODES = {
    constants.STATUS_SUCCESS:0,
    constants.STATUS_INVOKED:constants.STATUS_INVOKED,
    constants.STATUS_BAD_PARAMETER:constants.STATUS_BAD_PARAMETER,
    constants.STATUS_BAD_REQUEST:constants.STATUS_BAD_REQUEST,
    constants.STATUS_EXECUTION_ERROR:constants.STATUS_EXECUTION_ERROR,
    constants.STATUS_EXISTS:constants.STATUS_EXISTS,
    constants.STATUS_FILE_OPEN_FAILED:constants.STATUS_FILE_OPEN_FAILED,
    constants.STATUS_FULL:constants.STATUS_FULL,
    constants.STATUS_IO_ERROR:constants.STATUS_IO_ERROR,
    constants.STATUS_NO_MEMORY:constants.STATUS_NO_MEMORY,
    constants.STATUS_NO_PERMISSION:constants.STATUS_NO_PERMISSION,
    constants.STATUS_NOT_EXECUTABLE:constants.STATUS_NOT_EXECUTABLE,
    constants.STATUS_NOT_FOUND:constants.STATUS_NOT_FOUND,
    constants.STATUS_NOT_INITIALIZED:constants.STATUS_NOT_INITIALIZED,
    constants.STATUS_OUT_OF_RANGE:constants.STATUS_OUT_OF_RANGE,
    constants.STATUS_PARSE_ERROR:constants.STATUS_PARSE_ERROR,
    constants.STATUS_TIMED_OUT:constants.STATUS_TIMED_OUT,
    constants.STATUS_TRY_AGAIN:constants.STATUS_TRY_AGAIN,
    constants.STATUS_NOT_SUPPORTED:constants.STATUS_NOT_SUPPORTED,
    constants.STATUS_FAILURE:constants.STATUS_FAILURE
}


class TR50Command(object):
    """
    Holds all relevant TR50 command names
    """

    alarm_publish = "alarm.publish"
    alarm_batch = "alarm.batch"
    attribute_current = "attribute.current"
    attribute_publish = "attribute.publish"
    attribute_batch = "attribute.batch"
    diag_echo = "diag.echo"
    diag_ping = "diag.ping"
    diag_time = "diag.time"
    file_get = "file.get"
    file_put = "file.put"
    location_publish = "location.publish"
    location_batch = "location.batch"
    log_publish = "log.publish"
    mailbox_ack = "mailbox.ack"
    mailbox_check = "mailbox.check"
    mailbox_update = "mailbox.update"
    property_publish = "property.publish"
    property_batch = "property.batch"
    property_current = "property.current"
    property_history= "property.history"
    thing_find = "thing.find"
    thing_update = "thing.update"


def _generate_params(kwargs):
    """
    Generate JSON based on the arguments passed to this function
    """

    params = {}
    for key in kwargs:
        if kwargs[key] != None:
            params[key] = kwargs[key]
    return params

def create_alarm_publish(thing_key, key, state, message=None, timestamp=None,
                         corr_id=None, latitude=None, longitude=None,
                         republish=None, batch=False):
    """
    Generate a TR50 JSON request for publishing an alarm
    """

    kwargs = {
        "thingKey":thing_key,
        "key":key,
        "state":state,
        "msg":message,
        "ts":timestamp,
        "corrId":corr_id,
        "lat":latitude,
        "lng":longitude,
        "republish":republish
    }
    if batch:
        cmd = {"command":TR50Command.alarm_batch}
    else:
        cmd = {"command":TR50Command.alarm_publish}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_alarm_batch_item(key, state, timestamp=None, message=None, republish=False):
    d = {
        'key':key,
        'state':state,
        'ts':timestamp,
        'msg':message,
        'republish':republish
    }
    return d

def create_attribute_current(thing_key, key, timestamp=None):
    """
    Generate a TR50 JSON request for getting an attribute's current value
    """

    kwargs = {
        "thingKey":thing_key,
        "key":key,
        "ts":timestamp
    }
    cmd = {"command":TR50Command.attribute_current}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_attribute_publish(thing_key, key, value, timestamp=None,
                             republish=None, batch=False):
    """
    Generate a TR50 JSON request for publishing a string value
    """

    kwargs = {
        "thingKey":thing_key,
        "key":key,
        "value":value,
        "ts":timestamp,
        "republish":republish
    }
    if batch:
        cmd = {"command":TR50Command.attribute_batch}
    else:
        cmd = {"command":TR50Command.attribute_publish}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_attribute_batch_item(key, value, timestamp=None,
                             republish=None):
    d = {
        'key':key,
        'value':value,
        'ts':timestamp,
        'republish':republish
    }
    return d

def create_diag_echo(params):
    """
    Generate a TR50 JSON request for a diagnostic echo
    """
    cmd = {"command":TR50Command.diag_echo}
    cmd["params"] = params
    return cmd

def create_diag_ping():
    """
    Generate a TR50 JSON request for a diagnostic ping
    """
    cmd = {"command":TR50Command.diag_ping}
    return cmd

def create_diag_time(params=None):
    """
    Generate a TR50 JSON request for a diagnostic time
    """
    cmd = {"command":TR50Command.diag_time}
    cmd["params"] = params
    return cmd

def create_file_get(thing_key, file_name, file_global=False):
    """
    Generate a TR50 JSON request for getting a file from the Cloud
    """
    kwargs = {
        "thingKey":thing_key,
        "fileName":file_name,
        "global":file_global
    }
    cmd = {"command":TR50Command.file_get}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_file_put(thing_key, file_name, public=False, crc32=None, tags=None,
                    sec_tags=None, ttl=None, log_complete=None,
                    file_global=False):
    """
    Generate a TR50 JSON request for putting a file in the Cloud
    """

    kwargs = {
        "thingKey":thing_key,
        "fileName":file_name,
        "public":public,
        "crc32":crc32,
        "tags":tags,
        "secTags":sec_tags,
        "ttl":ttl,
        "logComplete":log_complete,
        "global":file_global
    }
    cmd = {"command":TR50Command.file_put}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_location_publish(thing_key, latitude, longitude, heading=None,
                            altitude=None, speed=None, fix_accuracy=None,
                            fix_type=None, timestamp=None, corr_id=None,
                            debounce=None, street_number=None, street=None,
                            city=None, state=None, zip_code=None,
                            country=None, batch=False):
    """
    Generate a TR50 JSON request for publishing a location to the Cloud
    """

    kwargs = {
        "thingKey":thing_key,
        "lat":latitude,
        "lng":longitude,
        "heading":heading,
        "altitude":altitude,
        "speed":speed,
        "fixAcc":fix_accuracy,
        "fixType":fix_type,
        "ts":timestamp,
        "corrId":corr_id,
        "debounce":debounce,
        "streetNumber":street_number,
        "street":street,
        "city":city,
        "state":state,
        "zipCode":zip_code,
        "country":country
    }
    if batch:
        cmd = {"command":TR50Command.location_batch}
    else:
        cmd = {"command":TR50Command.location_publish}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_location_batch_item(latitude, longitude, heading=None,
                            altitude=None, speed=None, fix_accuracy=None,
                            fix_type=None, timestamp=None, corr_id=None,
                            debounce=None, street_number=None, street=None,
                            city=None, state=None, zip_code=None,
                            country=None):
    d = {
        "lat":latitude,
        "lng":longitude,
        "heading":heading,
        "altitude":altitude,
        "speed":speed,
        "fixAcc":fix_accuracy,
        "fixType":fix_type,
        "ts":timestamp,
        "corrId":corr_id,
        "debounce":debounce,
        "streetNumber":street_number,
        "street":street,
        "city":city,
        "state":state,
        "zipCode":zip_code,
        "country":country
    }
    return d

def create_log_publish(thing_key, message, timestamp=None, level=None,
                       corr_id=None, global_log=None):
    """
    Generate a TR50 JSON request for publishing a log entry to the Cloud
    """

    kwargs = {
        "thingKey":thing_key,
        "msg":message,
        "ts":timestamp,
        "level":level,
        "corrId":corr_id,
        "global":global_log
    }
    cmd = {"command":TR50Command.log_publish}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_mailbox_ack(mail_id, error_code=None, error_message=None,
                       params=None):
    """
    Generate a TR50 JSON request for acknowledging the execution of an action
    """

    kwargs = {
        "id":mail_id,
        "errorCode":error_code,
        "errorMessage":error_message,
        "params":params
    }
    cmd = {"command":TR50Command.mailbox_ack}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_mailbox_check(auto_complete, limit=None):
    """
    Generate a TR50 JSON request for checking the mailbox in the Cloud
    """

    kwargs = {
        "autoComplete":auto_complete,
        "limit":limit
    }
    cmd = {"command":TR50Command.mailbox_check}
    params = _generate_params(kwargs)
    if params:
        cmd["params"] = params
    return cmd

def create_mailbox_update(mail_id, message):
    """
    Generate a TR50 JSON request for updating a mailbox message
    """

    kwargs = {
        "id":mail_id,
        "msg":message
    }
    cmd = {"command":TR50Command.mailbox_update}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_property_publish(thing_key, key, value, timestamp=None, corr_id=None,
                            aggregate=None, batch=False):
    """
    Generate a TR50 JSON request for publishing a numeric value to the Cloud
    """

    kwargs = {
        "thingKey":thing_key,
        "key":key,
        "value":value,
        "ts":timestamp,
        "corrId":corr_id,
        "aggregate":aggregate
    }
    if batch:
        cmd = {"command":TR50Command.property_batch}
    else:
        cmd = {"command":TR50Command.property_publish}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_property_batch_item(key, value, timestamp=None,
                                corr_id=None):
    d = {
            'key':key,
            'value':value,
            'ts':timestamp,
            'corrid':corr_id
    }
    return d

def create_property_get_current( thing_key, key, timestamp=None):

    kwargs = {
        "thingKey":thing_key,
        "key":key,
        "ts":timestamp
    }
    cmd = {"command":TR50Command.property_current}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_property_get_history( thing_key, key, start, end):

    kwargs = {
        "thingKey":thing_key,
        "key":key,
        "start":start,
        "end":end
    }
    cmd = {"command":TR50Command.property_history}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_thing_find(key):
    """
    Generate a TR50 JSON request for finding a different registered app
    """

    kwargs = {
        "key":key
    }
    cmd = {"command":TR50Command.thing_find}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def create_thing_update(key, name, description, iccid, esn, imei,
                        meid, imsi, unset=[]):
    """
    Generate a TR50 JSON request for updating a thing.
    """
    kwargs = {
        "key":key,
        "name":name,
        "desc":description,
        "iccid":iccid,
        "esn":esn,
        "imei":imei,
        "meid":meid,
        "imsi":imsi
    }
    if isinstance(unset, list):
       if len(unset) > 0:
           kwargs["unset"] = unset
    cmd = {"command":TR50Command.thing_update}
    cmd["params"] = _generate_params(kwargs)
    return cmd

def generate_request(commands):
    """
    Generate a final TR50 request string out of multiple commands
    """

    request = {}

    # Ensure we are working with a list
    command_list = commands
    if commands.__class__.__name__ != "list":
        command_list = [commands]

    # Add each command to the request
    for num, val in enumerate(command_list):
        request[str(num+1)] = val

    return json.dumps(request, separators=(",", ":"))

def translate_error_code(error_code):
    """
    Return the related Cloud error code for a given device error code
    """

    return (CLOUD_ERROR_CODES.get(error_code) if error_code in
            CLOUD_ERROR_CODES else error_code)
