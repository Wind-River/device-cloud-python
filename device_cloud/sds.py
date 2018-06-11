'''
    Copyright (c) 2017-2018 Wind River Systems, Inc.
    
    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at:
    http://www.apache.org/licenses/LICENSE-2.0
    
    Unless required by applicable law or agreed to in writing, software  distributed
    under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
    OR CONDITIONS OF ANY KIND, either express or implied.
'''

"""
This module creates/opens a database and stores data.
"""

import sqlite3
try:
    from pysqlcipher import dbapi2 as sqlcipher
    secure_db_support = True
except ImportError:
    secure_db_support = False
    pass
import threading
import re
import os
from time import sleep
from contextlib import closing

from device_cloud._core import constants
from device_cloud._core import defs
from datetime import datetime, timedelta
import device_cloud as iot

class SmartDataStorage(object):
    """
    When enabled in the configuration settings of an app, the
    SmartDataStorage (SDS) class APIs can be used to store telemetry in
    an embedded database (sqlite).  Sqlite is supported by python
    natively, so no new software is required.

    There are two types of data retention policies supported:
      * Maximum number of days (STORAGE_MAX_DAYS)
      * Or maximum number of entries (STORAGE_LIMITED_MAX)
    Some defines are used to tune the retention process:
        * STORAGE_LIMITED_MAX
        * STORAGE_LIMITED_NUM_TO_AGE
        * STORAGE_AGE_OLDEST
        * STORAGE_KEEP_OLDEST
    These settings are set in the class instance.  The defaults are:
        <inst>.retention_policy    = <inst>.STORAGE_LIMITED
        <inst>.retention_drop_mode = <inst>.STORAGE_AGE_OLDEST
        <inst>.max_days_to_retain  = 31
        <inst>.retain_max_entries  = <inst>.STORAGE_LIMITED_MAX
        <inst>.num_to_age          = <inst>.STORAGE_LIMITED_NUM_TO_AGE

    Note: there will be serveral tables supported, one for each type
    of data: telemetry, location, alarms, attributes.  The limit will
    be imposed *per table*.

    For maximum number/size of rows, columns etc. see:
    https://www.sqlite.org/limits.html

    Note: The sqlite does not support encryption.  To add encryption install the dev
    libraries for sqlite and sqlcipher.  Then install pysqlcipher.  For
    Ubuntu:
        sudo apt-get install libsqlite3-dev libsqlcipher-dev
        sudo pip -H install pysqlcipher

    Instantiate sds class with a key to enable encryption:
        client.sds = sds.SmartDataStorage( "secure.db", logger=client.handler.logger, key=<secret key>)

    The command line tool sqlcipher is useful for debugging:
        $ sqlcipher  <DB NAME>
        SQLCipher version 3.15.2 2016-11-28 19:13:37
        Enter ".help" for instructions
        Enter SQL statements terminated with a ";"
        sqlite> pragma key='<your key>';
        sqlite> select * from telemetry;

    Test the database to make sure it was encrypted:
        hexdump -c <DB NAME> to check.  Output should be encrypted.
    """

    # Table and data_type names
    TELEMETRY = "telemetry"
    LOCATION  = "location"
    ATTRIBUTE = "attribute"
    ALARM     = "alarm"

    # Database telemetry state strings
    STATE_SENT      = 'sent'
    STATE_UNSENT    = 'unsent'
    STATE_REMOVE    = 'remove'
    STATE_RETAIN    = 'retain'
    STATE_PUBLISHED = 'published'
    STATE_IGNORE    = 'ignore'

    # Field names in table, used for the data smooth handler
    TELEMETRY_VALUE   = 'value'
    LOCATION_LATITUDE = 'latitude'
    LOCATION_LONGITUDE= 'longitude'
    LOCATION_HEADING  = 'heading'
    LOCATION_ALTITUDE = 'altitude'
    LOCATION_SPEED    = 'speed'
    LOCATION_ACCURACY = 'accuracy'

    #Storage retention types
    STORAGE_MAX_DAYS   = 'max_days'
    STORAGE_LIMITED    = 'limited'

    # storage default variables
    STORAGE_LIMITED_MAX        = 1000000
    STORAGE_LIMITED_NUM_TO_AGE = 20

    # storage optional variables
    STORAGE_AGE_OLDEST  = 1
    STORAGE_KEEP_OLDEST = 2

    def __init__(self, db_name, logger=None,
                 delete=False, key=None):
        self.logger  = logger
        self.delete  = delete
        self.db_name = db_name
        self.quit    = False
        self.retention_policy    = self.STORAGE_LIMITED
        self.retention_drop_mode = self.STORAGE_AGE_OLDEST
        self.max_days_to_retain  = 31
        self.db_key = key
        self.table_list = [ self.TELEMETRY,
                            self.LOCATION,
                            self.ATTRIBUTE,
                            self.ALARM ]
        self.field_list = [ self.TELEMETRY_VALUE,
                            self.LOCATION_LATITUDE,
                            self.LOCATION_LONGITUDE,
                            self.LOCATION_HEADING,
                            self.LOCATION_ALTITUDE,
                            self.LOCATION_SPEED,
                            self.LOCATION_ACCURACY ]

        # if storage policy is limitend, set the max to retain
        self.retain_max_entries = self.STORAGE_LIMITED_MAX

        # number of entries to age at a time
        self.num_to_age = self.STORAGE_LIMITED_NUM_TO_AGE

        if self.db_key:
            if secure_db_support:
                self.logger.info("Using secure sqlcipher driver")
                self.conn = sqlcipher.connect(db_name, isolation_level=None)
                self.conn.executescript('pragma key="{}"; pragma kdf_iter=64000;'.format(self.db_key))
            else:
                self.conn = None
                self.logger.error("Secure driver pysqlcipher not found")
        else:
            self.logger.info("Using sqlite3 driver")
            self.conn = sqlite3.connect(db_name, isolation_level=None)

        self.c    = self.conn.cursor()

        # Simple file security: make sure the permissions on the db
        # are limited to rw by owner only.  On windows this will be
        # ignored 0o600 means rw by file owner only.  Not read/write
        # by anyone else.  SqlCipher can be used to encrypt the
        # database.
        os.chmod(db_name, 0o600)

        # Create table if it doesn't exist
        try:
            # telemetry
            self.c.execute("""CREATE TABLE IF NOT EXISTS {} (
                                    idx INTEGER PRIMARY KEY AUTOINCREMENT,
                                    data_type TEXT,
                                    name TEXT,
                                    value REAL,
                                    msg TEXT,
                                    ts TEXT,
                                    desc TEXT,
                                    status TEXT)""".format(self.TELEMETRY))
            # location
            self.c.execute("""CREATE TABLE IF NOT EXISTS {} (
                                    idx INTEGER PRIMARY KEY AUTOINCREMENT,
                                    data_type TEXT,
                                    name TEXT,
                                    latitude REAL,
                                    longitude REAL,
                                    heading REAL,
                                    altitude REAL,
                                    speed REAL,
                                    accuracy REAL,
                                    fix_type REAL,
                                    msg TEXT,
                                    ts TEXT,
                                    status TEXT)""".format(self.LOCATION))
            # alarms
            # corrid, lat, lng are not supported by the API yet.
            self.c.execute("""CREATE TABLE IF NOT EXISTS {} (
                                    idx INTEGER PRIMARY KEY AUTOINCREMENT,
                                    data_type TEXT,
                                    name TEXT,
                                    alarm_state REAL,
                                    msg TEXT,
                                    repub BOOL,
                                    ts TEXT,
                                    corr_id TEXT,
                                    lat REAL,
                                    lng REAL,
                                    desc TEXT,
                                    status TEXT)""".format(self.ALARM))
            # attributes
            self.c.execute("""CREATE TABLE IF NOT EXISTS {} (
                                    idx INTEGER PRIMARY KEY AUTOINCREMENT,
                                    data_type TEXT,
                                    name TEXT,
                                    corr_id TEXT,
                                    desc TEXT,
                                    repub BOOL,
                                    ts TEXT,
                                    status TEXT)""".format(self.ATTRIBUTE))

            # TODO: location, alarms, attributes
            self.conn.commit()
        except self.conn.Error as err:
            self.logger.error("Error: failed to initialize database")
            self.logger.error(str(err))

    def is_type_valid(self, table):
        """
        Check if the data type is supported.

        Args:
           table 

        Returns:
            True on success, False on failure
        """
        ret = False
        for t in self.table_list:
            if t == table:
                ret = True
                break
        return ret

    def insert_alarm(self, name, alarm_state, msg=None, republish=False, ts=None, state=None):
        
        return self.insert(table=self.ALARM, name=name,
                alarm_state=alarm_state, msg=msg, republish=republish, ts=ts, state=state)

    def insert_telemetry(self, name, value, msg=None, ts=None, state=None ):
        """
        Simple interface to insert() handler specifically for telemetry.

        Args:
            name  -name of telemetry object
            value -value for the telemetry sample (e.g. float)
            state -state to set
            msg   -optional message to store
            ts    -timestamp 

        Returns
            STATUS_FAILURE, STATUS_SUCCESS
        """
        return self.insert(table=self.TELEMETRY,name=name, value=value, msg=msg, ts=ts, state=state)

    def insert_location(self, latitude, longitude, speed=None, heading=None,
            altitude=None, accuracy=None, fix_type=None, msg=None, ts=None, state=None ):
        """
        Simple interface to insert() handler specifically for location.

        Args:
            latitude
            longitude
            heading
            altitude
            accuracy
            fix_type
            state
            msg
            ts

        Returns
            STATUS_FAILURE, STATUS_SUCCESS
        """
        return self.insert(table=self.LOCATION,  latitude=latitude,
                longitude=latitude, heading=heading,
                altitude=altitude, speed=speed, accuracy=accuracy,
                fix_type=fix_type, msg=msg, ts=ts, state=state)

    def insert( #generic
            self, table, state=STATE_UNSENT, name=None, msg="", ts=None,
            #telemetry
            value=None,
            # location
            latitude=None, longitude=None, heading=None,
            altitude=None,speed=None, accuracy=None, fix_type=None,
            #alarm
            alarm_state=None, republish=False):
        """
        Generic handler to insert data into to a database.

        Args:
            table
            name
            state
            msg
            ts
            value
            latitude
            longitude
            heading
            altitude
            speed
            accuracy
            fix_type
            alarm_state
            republish

        Returns
            STATUS_FAILURE, STATUS_SUCCESS
        """
        if not state:
            state=self.STATE_SENT

        if not ts:
            ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")

        if not self.is_type_valid(table):
            self.logger.error("Data type {} is not supported".format(table))
            status = constants.STATUS_FULL
        else:
            # check the retention policy and take the appropriate
            # action
            self.apply_retention_policy(table)
            if self.TELEMETRY ==  table:
                sql = "INSERT INTO {} VALUES(null,?,?,?,?,?,?,?)".format(table)
                values = (table,name,value,msg,ts, "desc", state)
            elif self.LOCATION == table:
                sql = "INSERT INTO {} VALUES(null,?,?,?,?,?,?,?,?,?,?,?,?)".format(table)
                values = ("location", "location", latitude, longitude,
                        heading, altitude, speed, accuracy, fix_type,
                        msg, ts, state)
            elif self.ALARM == table:
                sql = "INSERT INTO {} VALUES(null,?,?,?,?,?,?,?,?,?,?,?)".format(table)
                values = (table, name, alarm_state, msg, republish,
                        ts, None, None, None, None, state)

            with closing(self.conn.cursor()) as c:
                try:
                    c.execute("begin")
                    c.execute(sql, values)
                    c.execute("commit")
                    status = constants.STATUS_SUCCESS
                except self.conn.Error as err:
                    self.logger.error("Error: insert failed")
                    self.logger.error("Reason:{}".format(str(err)))
                    c.execute("rollback")
                    status = constants.STATUS_FAILURE
        return status

    def data_smooth_on_change(self, table, field_name, plus_minus, state):
        """
        Smooth data by comparing previous field name value with the
        currnet.  If the current value is not significantly different
        (plus_minus), flag all insignificant entries to be ignored.

        Args:
            table
            field_name (one of: self.TELEMETRY_VALUE,
                            self.LOCATION_LATITUDE,
                            self.LOCATION_LONGITUDE,
                            self.LOCATION_HEADING,
                            self.LOCATION_ALTITUDE,
                            self.LOCATION_SPEED,
                            self.LOCATION_ACCURACY)
            plus_minus (float or integer)
            state  -state to mark entries flagged by this API

        Returns:
            list of items with their state updated to ignore.
        """
        ignore_list = []

        valid_field=False
        for f in self.field_list:
            if f == field_name:
                valid_field=True
                break
        if not valid_field:
            self.logger.error("Error: invalid field name specified {}".format(field_name))
            return None

        # get the table field names and indices for use below
        t = self.get_table_info(table)
        field_idx = t[field_name]
        state_idx = t['status']
        idx_idx   = t['idx']

        with closing(self.conn.cursor()) as c:
            try:
                # walk with a interation var instead of big selection
                # only select the unsent rows
                c.execute("SELECT * FROM {} WHERE status = \'{}\'".format(table, self.STATE_UNSENT))
            except self.conn.Error as err:
                self.logger.error("Error: select failed")
                self.logger.error("Reason:{}".format(str(err)))
            finally:
                last = None
                for row in c:
                    curr = row[field_idx]
                    idx =  row[idx_idx]
                    curr_state = row[state_idx]
                    if last:
                        if curr == last:
                            print("Current == last ({}=={})".format(curr, last))
                            ignore_list.append(idx)
                        elif curr > last and curr - plus_minus <= last:
                            print("Current > last ({} > {})".format(curr, last))
                            ignore_list.append(idx)
                        elif curr < last and curr + plus_minus >= last:
                            print("Current < last ({} < {})".format(curr, last))
                            ignore_list.append(idx)
                    last = curr

        # update the db
        for i in ignore_list:
            self.logger.info("update idx {} state to\
            {}".format(i, self.STATE_IGNORE))
            status = self.update_state(table, idx=i, state=self.STATE_IGNORE )
            if status != constants.STATUS_SUCCESS:
                self.logger.error("Error: unable to update row state")
        return ignore_list


    def apply_retention_policy(self, table):
        """
        Execute the actions required to satisfy the retention policy
        for data.  E.g. if max number of entries is reached, delete
        the oldest.

        Note: this API is called by the insert() handler.  It does not
        need to be called independently.

        Args:
            table

        Returns:
            STATUS_FAILURE, STATUS_SUCCESS
        """
        ret = constants.STATUS_SUCCESS
        if self.retention_policy == self.STORAGE_LIMITED:
            # get the number of entries
            count = self.get_row_count(table)
            self.logger.debug("Number of entries {}".format(count))
            if count >= self.retain_max_entries:
                if self.retention_drop_mode == self.STORAGE_AGE_OLDEST:
                    self.logger.warning("Maximum number of enties reached {}".format(count))
                    self.logger.warning("Deleting {} oldest entries".format(self.num_to_age))
                    sql = "DELETE FROM {} WHERE {} IN (SELECT {} FROM {} ORDER BY \
                    {} ASC LIMIT {})".format(table, "idx", "idx", table, "idx",self.num_to_age)
                    ret = self.custom_sql_command(sql)
                else:
                    # if retention_drop_mode is set to keep the oldest
                    # return an error
                    ret = constants.STATUS_STATUS_FULL
        if self.retention_policy == self.STORAGE_MAX_DAYS:
            if self.max_days_to_retain:
                sql = "DELETE FROM {} WHERE {} IN (SELECT {} FROM {} \
                WHERE ts < datetime('now', '-{} days') ORDER BY \
                {} )".format(table, "idx", "idx", table, self.max_days_to_retain, "idx")
                ret = self.custom_sql_command(sql)
        return ret

    def get_row_count(self, table):
        """
        Get the number of rows in the table

        Args:
            table

        Returns:
            a list of rows on success, empty list on failure
        """
        if not self.is_type_valid(table):
            self.logger.error("Data type {} is not supported".format(table))
            rows = []
        else:
            with closing(self.conn.cursor()) as c:
                try:
                    c.execute("SELECT count(idx) FROM {}".format(table))
                    count = c.fetchone()
                except self.conn.Error as err:
                    count = 0
                    self.logger.error("Error: select failed")
                    self.logger.error("Reason:{}".format(str(err)))
        # always returns a tuple, so return the first entry
        # fetchone can return None, so set that to 0
        if not count:
            count = 0
        if isinstance(count, tuple):
            count = count[0]
        return count

    def select_all_by_state(self, table, state):
        """
        Select everything from table where field state = state.

        Args:
            table
            state

        Returns:
            pointer to a cursor on success, empty on failure
        """
        if not self.is_type_valid(table):
            self.logger.error("table {} is not supported".format(table))
            c = None
        else:
            c = self.conn.cursor()
            try:
                c.execute("SELECT * FROM " + table + " WHERE status =?" , (state,))
            except self.conn.Error as err:
                c = None
                self.logger.error("Error: select failed")
                self.logger.error("Reason:{}".format(str(err)))
        return c

    def print_table(self, table):
        """
        Print to stdout the table (table) in columns.

        Args:
           table

        Returns:
            STDOUT
        """
        ptr = self.select_table(table)
        if self.TELEMETRY == table:
            for r in ptr:
                idx=r[0]
                t=r[1]
                n=r[2]
                v=r[3]
                msg=r[4]
                ts=r[5]
                desc=r[6]
                state = r[7]

                print("%4d %4s %4s %0.2f %5s %12s %4s %4s" %(
                       idx, t, n,   v,   msg, ts, desc, state))
        elif self.LOCATION == table:
            for r in ptr:
                idx=r[0]
                lat=r[3]
                lng=r[4]
                head=r[5]
                alt=r[6]
                spd=r[7]
                acc=r[8]
                fix=r[9]
                msg=r[10]
                ts=r[11]
                state = r[12]

                print("%4d %4s %4s %4s %4s %4s %4s %4s %2s %4s %4s" \
                        %(idx, lat, lng, head, alt, spd, acc, fix,
                            msg, ts, state))

        elif self.ALARM == table:
            for r in ptr:
                idx=r[0]
                a_state=r[3]
                msg=r[4]
                repub=r[5]
                ts=r[6]
                state = r[11]

                print("%4d %4s %4s %4s %4s %4s" \
                        %(idx, a_state, msg, repub, ts, state))

 
    def select_table(self, table):
        """
        Select the entire table (table) and return a list of rows.

        Args:
            table

        Returns:
            pointer to a cursor on success, empty on failure
        """
        if not self.is_type_valid(table):
            self.logger.error("Data type {} is not supported".format(table))
            c = None
        else:
            c = self.conn.cursor()
            try:
                c.execute("SELECT * FROM " + table)
            except self.conn.Error as err:
                c = None
                self.logger.error("Error: select failed")
                self.logger.error("Reason:{}".format(str(err)))
        return c

    def publish_unsent_alarms(self, client, new_state):
        """
        Publish all unsent alarms and update with the new state
        given.  Possible constant values for new_state are defined in
        the class (see above).
        The new state can be queried later depending on the retention
        policy.

        Args:
            client
            new_state

        Returns:
            STATUS_FAILURE, STATUS_SUCCESS
        """
        ptr = self.select_all_by_state(self.ALARM, state=self.STATE_UNSENT)
        update_db = {}
        status = iot.STATUS_FAILURE

        for t in ptr:
            idx = t[0]
            name = t[2]
            alarm_state = t[3]
            msg = t[4]
            repub = t[5]
            if repub == 0:
                repub = False
            else:
                repub = True
    
            status = client.alarm_publish(name, alarm_state, message=msg, republish=repub)
            if status != iot.STATUS_SUCCESS:
                break
            else:
                update_db[t[0]]= self.STATE_SENT

        if status == iot.STATUS_SUCCESS:
            # update the db entry status
            # split the publishing loop from the update loop for batching
            # performance
            for k in update_db.keys():
                self.update_state(self.ALARM, idx=k,
                    state=new_state)
        return status

    def publish_unsent_telemetry(self, client, new_state):
        """
        Publish all unsent telemetry and update with the new state
        given.  Possible constant values for new_state are defined in
        the class (see above).
        The new state can be queried later depending on the retention
        policy.

        Args:
            client
            new_state

        Returns:
            STATUS_FAILURE, STATUS_SUCCESS
        """
        ptr = self.select_all_by_state(self.TELEMETRY, state=self.STATE_UNSENT)
        update_db = {}
        status = iot.STATUS_FAILURE

        for t in ptr:
            idx = t[0]
            name = t[2]
            value = t[3]
            ts = t[5]
            status = client.telemetry_publish(name, value, corr_id=str(idx), timestamp=ts)
            if status != iot.STATUS_SUCCESS:
                break
            else:
                update_db[t[0]]= self.STATE_SENT

        if status == iot.STATUS_SUCCESS:
            # update the db entry status
            # split the publishing loop from the update loop for batching
            # performance
            for k in update_db.keys():
                self.update_state(self.TELEMETRY, idx=k,
                    state=new_state)
        return status

    def publish_unsent_location(self, client, new_state):
        """
        Publish all unsent telemetry and update with the new state
        given.  Possible constant values for new_state are defined in
        the class (see above).
        The new state can be queried later depending on the retention
        policy.

        Args:
            client
            new_state

        Returns:
            STATUS_FAILURE, STATUS_SUCCESS
        """
        ptr = self.select_all_by_state(self.LOCATION,
                 state=self.STATE_UNSENT)
        update_db = {}
        status = iot.STATUS_FAILURE

        for t in ptr:
            idx       = t[0]
            latitude  = t[3]
            longitude = t[4]
            heading   = t[5]
            altitude  = t[6]
            speed     = t[7]
            accuracy  = t[8]
            fix_type  = t[9]
            status = client.location_publish(latitude, longitude,
                    heading=heading, altitude=altitude, speed=speed,
                    accuracy=accuracy, fix_type=fix_type)
            if status != iot.STATUS_SUCCESS:
                break
            else:
                update_db[t[0]]= self.STATE_SENT

        if status == iot.STATUS_SUCCESS:
            # update the db entry status
            # split the publishing loop from the update loop for batching
            # performance
            for k in update_db.keys():
                self.update_state(self.LOCATION, idx=k,
                    state=new_state)
        return status

    def update_state(self, table, idx, state):
        """
        Update field (state) where key == (idx) and set the state ==
        (state).

        Args:
            table
            idx
            state

        Returns:
            STATUS_FAILURE, STATUS_SUCCESS
        """
        with closing(self.conn.cursor()) as c:
            try:
                c.execute("begin")
                c.execute("UPDATE {} SET status = \'{}\'  WHERE idx = {}".format(table, state, idx))
                c.execute("commit")
                status = constants.STATUS_SUCCESS
            except self.conn.Error as err:
                self.logger.error("Error: update failed")
                self.logger.error("Reason:{}".format(str(err)))
                c.execute("rollback")
                status = constants.STATUS_FAILURE
        return status

    def remove(self, table, field_name, field_value):
        """
        Remove row(s) from the given table where (field_name) =
        (field_value)

        Args:
            table
            field_name
            field_value

        Returns:
              constants.STATUS_SUCCESS, constants.STATUS_FAILURE
        """
        with closing(self.conn.cursor()) as c:
            try:
                c.execute("begin")
                d = c.execute("DELETE FROM " +table+" WHERE "+field_name+" = ?", ( field_value,))
                c.execute("commit")
                status = constants.STATUS_SUCCESS
            except self.conn.Error as err:
                self.logger.error("Error: remove failed")
                self.logger.error("Reason:{}".format(str(err)))
                c.execute("rollback")
                status = constants.STATUS_FAILURE
        return status

    def custom_sql_command(self, sql):
        """
        Execute a custom sql command (not select)

        Args:
            sql

        Returns:
            status
            Where status is one of:
                constants.STATUS_SUCCESS, constants.STATUS_FAILURE
        """
        rows = None
        with closing(self.conn.cursor()) as c:
            try:
                c.execute("begin")
                c.execute(sql)
                c.execute("commit")
                status = constants.STATUS_SUCCESS
            except self.conn.Error as err:
                self.logger.error("Error: remove failed")
                self.logger.error("Reason:{}".format(str(err)))
                c.execute("rollback")
                status = constants.STATUS_FAILURE
        return status

    def close(self):
        """
        Close the database connection
        """
        self.conn.close()

    def get_table_info(self, table):
        """
        Get a index/name map for the fields

        Args:
            table name
        Returns:
            dictionary key=field name, value = index
        returns
        """
        d = {}
        with closing(self.conn.cursor()) as c:
            try:
                c.execute("pragma table_info({})".format(table))
                rows = c.fetchall()
            except self.conn.Error as err:
                self.logger.error("Error: remove failed")
                self.logger.error("Reason:{}".format(str(err)))
            for t in rows:
                n = t[1]
                i = t[0]
                d[n] = i
        return d

    def get_cursor(self):
        """
        Return the class instance cursor for custom sql commands.  The
        cursor does not need to be closed explicity.  Best practise is
        to use "with closing" syntax.

        Args:
            None

        Returns:
            cursor
        """
        return self.conn.cursor()
