Intel AMT Support
=================

Intel processors that support AMT (tm) can take advantage of the AMT
support in HDC to remotely execute AMT commands, such as reboot,
shutdown, boot etc.  Initially only a few commands will be supported
TBD.

Requirements For AMT
--------------------
  * core supports AMT (see https://ark.intel.com/#@Processors)
  * bios MBEX password has been set for AMT

How To Enable AMT
-----------------
If you device supports AMT, then you can enable AMT as follows:
  * reboot
  * CTRL-P when boot screen appears
  * set the MBEX password
  * save and reboot
Specific details for bios setup are beyond the scope of this document.

Device Design Work Flow
-----------------------
AMT is configured via an OTA operation, where by the setup tools for
AMT are delivered to the device along with all the required
configuration and scripts.  Details about the package are below.
When, deploying the AMT OTA package, the AMT password is required
(MBEX password that was setup in the bios).  The update software
method is used to deliver the OTA package.  Note: the "Additional
params..." field is used to specify the AMT password key value pair,
e.g.:
  AMT_PASSWORD=MYPASSWORD
The "Additional params" field is a list of key=value pairs and it is
passed to the OTA install scripts via ENV variable HDC_EXTRA_PARAMS.
There could be several key value pairs, so the install scripts must
parse the HDC_EXTRA_PARAMS list to find the required key(s) and then
parse the key from the value (e.g. split('=').

Once the OTA update software action is received by the
device_manager.py, the package is downloaded and extracted as usual.
The tools contained in the package are activated by a setup_amt.py
script (see below).  The work flow is as follows:
  * parse the AMT password
  * parse the runtime directory
  * run the meshcmd tool to clear up any existing configuration
  * run the meshcmd tool to setup AMT (registers with MPS
    microservice)
  * run the meshcmd tool to query the AMT UUID
  * if the UUID is valid, the device is AMT enabled and an
    attributes.cfg file is written with the new UUID.
  * when the device manager is reset (separate action) the new
    AMT_UUID attribute is published.
  * Now the MPS micro service will process the new AMT activation and
    setup a new thing key (==current device ID -vpro).  This new thing
    key must be used to execute AMT commands.

Currently, the meshcmd tool and cira setup and cleanup scripts are
packaged in an OTA package.  This might change to a download link that
is handled by the OTA helper script (TBD).

OTA Package For AMT
-------------------
Requires:
  * setup_amp.py
  * meshcmd.exe
  * cira_setup.mescript
  * cira_cleanup.mescript

An example OTA package is provided in
  * share/example-ota-packages/amt-ota-windows

The install scripts therein reference 'setup_amt.py' which lives in
share and  must be copied into the OTA package.  The meshcmd.exe and
cira scripts must be provided by the MPS server TBD.

