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
This module contains the Relay class which is a secure way to pipe data to a
local socket connection. This is useful for Telnet which is not secure by
default.
"""

import logging
import random
import select
import socket
import ssl
import threading
import time
import sys
# -------------------------------------------------------------------
# Note: when using a proxy server, the socket class is overlayed with
# pysocks class.  Keep around a local copy so that local socket
# connections don't use the proxy
# -------------------------------------------------------------------
non_proxy_socket = None

# yocto supports websockets, not websocket, so check for that
try:
    import websocket
except ImportError:
    import websockets as websocket

CONNECT_MSG = "CONNECTED-129812"
CONNECT_MULTI_MSG = 'CONNECTED-581273'
DISCONNECT_MULTI_MSG = 'DISCONNECTED-581273'
RELAY_VERSION = '2.0.0'

class Relay(object):
    """
    Class for establishing a secure pipe between a cloud based websocket and a
    local socket. This is useful for things like Telnet which are not secure to
    use remotely.
    """

    def __init__(self, wsock_host, sock_host, sock_port, secure=True,
                 log=None, local_socket=None, reconnect=False):
        """
        Initialize a relay object for piping data between a websocket and a
        local socket
        """

        self.wsock_host = wsock_host
        self.sock_host = sock_host
        self.sock_port = sock_port
        self.secure = secure
        self.log = log
        self.proxy = None

        # for python3 str transformation
        self.def_enc = "ISO-8859-1"
        self.log_name = "Relay:{}:{}({:0>5})".format(self.sock_host,
                                                    self.sock_port,
                                                    random.randint(0,99999))
        self.reconnect = reconnect
        if self.log is None:
            self.logger = logging.getLogger(self.log_name)
            log_handler = logging.StreamHandler()
            #log_formatter = logging.Formatter(constants.LOG_FORMAT, datefmt=constants.LOG_TIME_FORMAT)
            #log_handler.setFormatter(log_formatter)
            self.logger.addHandler(log_handler)
            self.logger.setLevel(logging.DEBUG)
            self.log = self.logger.log

        self.running = False
        self.thread = None
        self.ws_thread = None
        self.lsock = []
        self.wsock = None
        self.lconnect = 0
        self._multi_channel = False

        # track sockets and idx
        self.lsocket_map = {}

    def _connect_local(self, idx=0):
        self.log(logging.DEBUG, "_connect_local idx {}".format(idx))
        ret = False
        try:
            # check for proxy.  If not proxy, this
            # is None.
            s = None
            if non_proxy_socket:
                s = non_proxy_socket(socket.AF_INET,
                                       socket.SOCK_STREAM)
            else:
                s = socket.socket(socket.AF_INET,
                                       socket.SOCK_STREAM)

            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
            s.connect((self.sock_host, self.sock_port))
            s.setblocking(0)

            self.lsock.append(s)
            self.lsocket_map[s] = idx
            self.log(logging.DEBUG, "connected to {}.".format(self.sock_port))
        except socket.error as err:
            self.running = False
            ret = True
            self.log(logging.ERROR, "{} Failed to open local socket.".format(self.log_name))
            self.log(logging.ERROR, "Reason: {} ".format(str(err)))
        return ret

    def _prepend_index(self, idx, data):

        # python3 data is in bytes format and must be decoded before
        # prepending.  Python2 is in str format so you can easily
        # prepend the idx.
        if sys.version_info[0] > 2:
            d = chr(idx)
            d += data.decode(self.def_enc)
            d = bytes(d, self.def_enc)
        else:
            d = chr(idx) + data
        return d

    def _encode_data(self, d):
        """
        Python 3 has different encoding for streams, bytes vs
        bytearray.  Need to encode for py3.  Py2 just return the data.
        """
        if sys.version_info[0] > 2:
            # Only encode if the type is str, some protocols are mixed
            if isinstance(d, str):
                raw_data = bytes(d, self.def_enc)
            else:
                raw_data = d
        else:
            raw_data = d
        return raw_data

    def _strip_index(self, d):
        if sys.version_info[0] > 2:
            raw_data = bytes(d, self.def_enc)
            idx = raw_data[0]
            data = raw_data[1:]
        else:
            raw_data = bytearray(d, self.def_enc)
            idx = raw_data[0]
            del raw_data[0]
            data = raw_data
        return data, int(idx)

    def _on_local_message(self):
        """
        Main loop that pipes all data from one socket to the next. The
        websocket connection is established first and has its own
        callback, so this is where the local socket will be handled.
        """
        # ws data must be in binary format.  The websocket lib uses
        # this op code
        op_binary = 0x2
        close_ws = False
        while self.running is True and not close_ws:
            if self.lsock:
                data = ''
                read_sockets, write_sockets, _es = select.select(self.lsock, [], [], 1)
                if len(read_sockets):
                    for s in read_sockets:
                        try:
                            data = s.recv(4096)
                        except:
                            # during a close a read might return a EBADF,
                            # that is ok, pass it don't dump an exception
                            pass
                        if data:
                            # get the idx
                            idx = self.lsocket_map[s]
                            try:
                                if self._multi_channel:
                                    d = self._prepend_index(idx, data)
                                else:
                                    d = data
                                self.wsock.send(d, opcode=op_binary)
                            except websocket.WebSocketConnectionClosedException:
                                self.log(logging.ERROR, "Websocket closed")
                                close_ws = True
                                break
                        else:
                            self.log(logging.INFO, "{}: Received NULL from local socket".format(self.log_name))
                            if self.reconnect and self.running and self._multi_channel:
                                self.log(logging.INFO, "Reconnecting local socket")

                                # multi channel: notify dra and dra
                                # will send a new connect msg in
                                # _on_message
                                idx = self.lsocket_map[s]
                                self.wsock.send(chr(idx) + DISCONNECT_MULTI_MSG, opcode=op_binary)
                                self.lsock.remove(s)
                                self.lsocket_map.pop(s, None)
                                break
                            else:
                                self.log(logging.INFO, "Disconnecting all sockets")
                                self.running = False
                                break
            else:
                time.sleep(0.1)
        for s in self.lsock:
            if s:
                s.close()
                self.lsocket_map[s] = None
        self.lsock = []
        self.lscoket_map = {}
        self.log(logging.INFO, "{} - Sockets Closed".format(self.log_name))

    def _on_open(self, ws):
        self.log(logging.INFO, "_on_open: starting thread loop")
        self.track_ws = ws
        self.thread = threading.Thread(target=self._on_local_message)
        self.thread.start()

    def _on_message(self, ws, data):

        # make sure we can parse data as a string below
        if not isinstance(data, str):
            data = str(data, self.def_enc)

        if data:
            idx = 0
            if data == CONNECT_MSG:
                # If the local socket has not been established yet,
                # and we have received the connection string, start
                # local socket.
                self._connect_local()
                self.lconnect = 1;
                self.log(logging.DEBUG, "{} Local socket opened".format(self.log_name))
            elif data == DISCONNECT_MULTI_MSG:
                self.log(logging.DEBUG, "Received disconnect message")
                self._on_error(ws, "received disconnect")
            elif CONNECT_MULTI_MSG in data:
                # this will be called for every new connection
                # on reconnect, send the idx + DISCONN message on ws
                # get the idx. data comes in as binary ascii, need to
                # ord/chr it before recv/send
                idx = ord(data[0])

                self.log(logging.DEBUG, "{} Local socket opened idx {}".format(self.log_name, idx))
                self._connect_local(idx=idx)
                self._multi_channel = True
            else:
                # send to local socket
                self.log(logging.DEBUG, "_on_message: send {} -> local socket".format(len(data)))

                if self._multi_channel:
                    s_data, idx = self._strip_index(data)
                    data = s_data
                enc_data = self._encode_data(data)
                self.lsock[idx].send(enc_data)

    def _on_error(self, ws, exception):
        self.log(logging.ERROR, "_on_error: {}".format(str(exception)))
        self._on_close(ws)
        if self.wsock:
            self.wsock.close()
        self.stop()

    def _on_close(self, ws):
        self.log(logging.INFO,"_on_close: websocket closed")
        for s in self.lsocket_map.keys():
            if s:
                self.log.debug("Closing sock {}".format(self.lsocket_map[s]))
                s.close()
        self.lsocket_map = {}
        self.running = False

    def start(self):
        """
        Establish the websocket connection and start the main loop
        """

        if not self.running:
            self.running = True
            sslopt = {}
            if not self.secure:
                sslopt["cert_reqs"] = ssl.CERT_NONE
            self.wsock = websocket.WebSocketApp(
                    self.wsock_host,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open)
            kwargs = {'sslopt': sslopt}
            if self.proxy:
                self.log(logging.DEBUG, "start:self.proxy={} ".format(self.proxy)),
                kwargs['http_proxy_host'] = self.proxy.host
                kwargs['http_proxy_port'] = self.proxy.port
            self.ws_thread = threading.Thread(target=self.wsock.run_forever, kwargs=kwargs)
            self.ws_thread.start()
        else:
            raise RuntimeError("{} - Already running!".format(self.log_name))

    def stop(self):
        """
        Stop piping data between the two connections and stop the loop thread
        """

        self.log(logging.INFO, "{} Stopping".format(self.log_name))
        self.running = False
        self.reconnect = False
        if self.track_ws:
            self.track_ws.close()
        if self.thread:
            self.thread.join()
            self.thread = None
        if self.ws_thread:
            # websocket client joins the thread
            self.ws_thread = None


relays = []

def create_relay(url, host, port, secure=True, log_func=None, local_socket=None,
                 reconnect=False, proxy=None):
    global relays, non_proxy_socket

    non_proxy_socket = local_socket
    newrelay = Relay(url, host, port, secure=secure, log=log_func, reconnect=reconnect)
    if proxy:
        newrelay.proxy = proxy
    newrelay.start()
    relays.append(newrelay)

def stop_relays():
    global relays

    threads = []
    while relays:
        relay = relays.pop()
        thread = threading.Thread(target=relay.stop)
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()

def relay_version():
    return RELAY_VERSION
