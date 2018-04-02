Device Cloud REST API
=====================
The device cloud API now supports a subset of REST APIs for
interaction with the cloud.  The goal of the REST APIs is to
standardize on how REST actions are performed from the device point of
view.

Why REST?
---------
Today, REST is used for validation and sys admin tasks for cloud
setup.  The plan is that number of APIs supported will grow as
required.  The APIs are implemented in Python for ease of use by current
application writers on the device.

How To Get REST APIs
--------------------
The new REST APIs will be shipped along with the device_cloud module.
So, an update to device_cloud is all that is required.

Usage
-----
The REST APIs are a device_cloud class.  Import the REST class as
usual in python.
```
from device_cloud.rest import Rest

r = Rest(cloud=cloud, username=username, password=password)
r.method_exec(thing_key, "ping")

```

See a full example in demos/iot-rest.py
