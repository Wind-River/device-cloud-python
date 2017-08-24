Wind River Python Agent for HDC 2.Next
======================================

Beginning implementation for pure Python agent for the latest iteration of HDC.
It is being developed alongside the C agent so many things are subject to change
as features are ironed out on that side, and more input is received. It is
recommended to make a wrapper package for testing purposes as none of the APIs
are necessarily final.

Purpose:
--------
The Python agent is designed for quick deployment on any platform that supports
Python.

Requirements:
-------------
- Python 2.7.9 or later (Including Python 3)
- paho-mqtt
- requests
- websocket-client

Pip Installation:
-----------------
The module can be installed by running `pip install .` in the root directory of
the cloned repository. This will install the module and its dependencies. The
agent can then be imported into other Python scripts as normal (`import helix`).

Configuration:
--------------
Parses the standard {APP_ID}-connect.cfg file for Cloud connection information.
Default configuration directory is the current working directory. Configuration
values can also be set from within the app by changing
`client.config.{CONFIG_KEY}` before calling `client.initialize()`. Setting
config_dir will look for the configuration file in the specified directory when
calling `client.initialize()`. This is also where the device_id is stored, so
multiple apps can share a single configuration directory to make use of the same
device_id.

Configuration Options:
----------------------
- config_dir: "/path/to/config/dir"
- config_file: "configfilename.cfg"
- cloud:
  - host: "api.cloudhost.com"
  - port: 1883/8883/443
  - token: "tokenfromcloud"
- validate_cloud_cert: true/false
- ca_bundle_file: "/path/to/cert/bundle" (default will use included file)
- log_file: "/path/to/a/log/file.log"
- keep_alive: ##
- loop_time: ##
- thread_count: ##

Device Manager:
---------------
The included device_manager.py app provides similar functionality to the old HDC
device manager application. Basic functions, such as file I/O, are available as
methods on the cloud. In addition, a basic OTA implementation is included which
is compatible with the HDC OTA package format. To run the device manager as a
service, the `share` directory contains service files for systemd and init.d
along with a readme on how to use them.

So far supports:
----------------
- Documented user APIs (can be obtained by running `pydoc helix`)
- Telemetry (known as properties on the Cloud side)
- Attributes (string telemetry)
- Actions (both function callbacks and console commands. Known as methods on
  Cloud side)
- File Download (to a specified destination)
- File Upload (with option to change file name on Cloud side)
- File Transfer callbacks
- Secure connection with TLS/SSL (this includes MQTT over TLSv1.2 and also HTTPS
  file transfer)
- Configuration files (see Configuration)
- device_id uuid (Generates a unique device_id if one is not found)
- Example apps (example of most APIs in use, but also still a work in progress)
- Logging to console with optional logging to a specified file
- Event message publishing
- Alarm publishing
- pytest (Install pytest, pytest-mock, pytest-cov with pip. Run `pytest -v .` to
  run unit tests.  `pytest --cov-report=html --cov=helix -v .` will generate a
  directory containing an HTML report of coverage. Prepending `python2/python3
  -m ` will let you specify which version of Python to test.)
- Websockets (setting the port to 443 will use websockets to send MQTT packets)
- Connection loss handling (Publishes made while offline will be cached and sent
  when connection is re-established. Now has a keep_alive configuration for how
  long the Client should remain disconnected before exiting, 0 is forever.)
- Websocket relay (Relay class used for remote login. Implemented on device
  manager for future implementation of a Cloud-side remote login server. The
  remote-access action starts the relay. The url parameter is the location for
  the websocket to connect to, host is the location for the local socket to
  connect to, and protocol is the port for the local socket (ie. 23 for Telnet).
  Telnet server on host must be started before executing the remote-access
  action.)

Issues:
-------
- MQTT over websockets on Windows does not work.
- Remote login on Windows cannot parse backspace. Don't make any typos.
- Current remote login test server has a self-signed certificate.
  validate_cloud_cert must be set to false in iot-connect.cfg in order to
  connect successfully.

Not yet supported:
------------------
- Proxy support (may not be possible for paho)
- Finalized APIs

Publishing:
-----------
*See `PUBLISHING.md` for instructions on uploading the module to Pypi*

Copyright Updates:
------------------
Configuration files for the Python [`copyright`](https://github.com/rsmz/copyright) module can be found in the
`copyright` directory in this repo. To automatically update the copyright
blurbs present in this project, first install the copyright module:
`pip install copyright`. Next, update the wr_config.json file (or use command
line flags) to reflect the new values. Finally, run `copyright -c
copyright/wr_config.json -t copyright/wr_template.json .` from the repo root.
The [current documentation](https://github.com/rsmz/copyright) for the `copyright` tool is quite sparse, but does show a few other examples for how the
tool works.
*Note: This will affect multiple files in the repo. The `wr_config.json` file
has been configured to ignore certain files and file types, however you should
double-check that no unexpected files were changed by the tool.*
