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

from setuptools import setup
import sys, os

pyver = sys.version_info
ret = []

def addDir(filedir):
    abspath = os.path.dirname(os.path.abspath(__file__))+os.sep+filedir
    for filename in os.listdir(abspath):
        if os.path.isdir(abspath+os.sep+filename):
            addDir(filedir+os.sep+filename)
        else:
           path = filedir+os.sep+filename
           key = ("share/device_cloud/"+filedir, [path])
           ret.append(key)
    return ret

if pyver < (2,7,9) or (pyver > (3,0,0) and pyver < (3,4,0)):
    print("Sorry, your Python version ({}.{}.{}) is not supported by device_cloud!".format(pyver[0], pyver[1], pyver[2]))
    sys.exit('Please upgrade to Python 2.7.9 or 3.4 and try again.')

setup(
    name='device_cloud',
    version='18.06.19',
    description='Python library for Wind River\'s Helix Device Cloud',
    author='Wind River Systems',
    author_email='',
    packages=['device_cloud','device_cloud._core','device_cloud.test'],
    data_files = [('share/device_cloud/docs', ['docs/paho-mqtt-QOS.md']),
                  ('share/device_cloud/demo', ['demo/action.bat',
                                               'demo/action.sh',
                                               'demo/iot-simple-actions.py',
                                               'demo/iot-simple-location.py',
                                               'demo/iot-simple-telemetry.py']),
                  ('share/device_cloud', ['generate_config.py',
                                          'device_manager.py',
                                          'iot.cfg',
                                          'COPYING.txt',
                                          'README.md',
                                          'README.macOSX.md',
                                          'README.style.md',
                                          'validate_app.py',
                                          'validate_device_manager.py',
                                          'validate_script.py'])] + addDir("share"),
    install_requires=[
        'certifi==2017.11.5',
        'paho-mqtt==1.3.1',
        'PySocks==1.6.8',
        'queues==0.6.3',
        'requests==2.18.4',
        'simplejson==3.8.1',
        'urllib3==1.22',
        'websocket-client==0.47.0'
        ],
    maintainer='Paul Barrette',
    maintainer_email='paul.barrette@windriver.com',
    url='http://www.windriver.com/products/helix/',
    license='Apache License, Version 2.0',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.4',
        'Operating System :: Microsoft :: Windows :: Windows 7',
        'Operating System :: Microsoft :: Windows :: Windows 10',
        'Operating System :: POSIX :: Linux',
        'Topic :: Software Development :: Libraries :: Python Modules'
        ]
    )
