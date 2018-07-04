#!/usr/bin/env python

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

import argparse
import json
import os
import sys
import stat

if sys.version_info.major == 2:
    input = raw_input

file_desc = "\nName of config file to write (eg. appname-connect.cfg) (Required)"
cloud_desc = "\nCloud host address (Required)"
port_desc = "\nCloud port (eg. 1883/8883/443) (Required)"
token_desc = "\nCloud token (Required)"
proxy_desc = "\nRoute all traffic through a proxy (default false) (Optional)"
proxy_type_desc = "\nProxy type (eg. SOCKS4/SOCKS5/HTTP)"
proxy_host_desc = "\nProxy host address"
proxy_port_desc = "\nProxy port"
proxy_username_desc = "\nProxy username (Optional)"
proxy_password_desc = "\nProxy password (Optional)"
onprem_desc = "\nSet on-prem special configuration? (default false) (Optional)"
onprem_file_xfer_host_desc = "\nOn-prem set a different host for file transfer? (Optional)"
onprem_file_xfer_port_desc = "\nOn-prem set a different port for file transfer (Optional)"

negatives = ["false", "f", "no", "n"]
positives = ["true", "t", "yes", "y"]

def generate():
    parser = argparse.ArgumentParser(description="Generate a connection config file. Give no arguments to run with prompt.")
    parser.add_argument("-f", "--file", help=file_desc)
    parser.add_argument("-c", "--cloud", help=cloud_desc)
    parser.add_argument("-p", "--port", type=int, help=port_desc)
    parser.add_argument("-t", "--token", help=token_desc)
    parser.add_argument("--proxy-type", help=proxy_type_desc)
    parser.add_argument("--proxy-host", help=proxy_host_desc)
    parser.add_argument("--proxy-port", type=int, help=proxy_port_desc)
    parser.add_argument("--proxy-username", help=proxy_username_desc)
    parser.add_argument("--proxy-password", help=proxy_password_desc)
    parser.add_argument("--onprem-file-xfer-host", help=onprem_file_xfer_host_desc)
    parser.add_argument("--onprem-file-xfer-port", help=onprem_file_xfer_port_desc)

    args = parser.parse_args(sys.argv[1:])
    file_name = ""
    config = {"cloud":{}}

    if len(sys.argv) > 1:
        # Arguments given. Attempt to use these arguments.
        missing = []
        if args.file:
            file_name = args.file
        else:
            missing.append("file name")
        if args.cloud:
            config["cloud"]["host"] = args.cloud
        else:
            missing.append("cloud address")
        if args.port:
            config["cloud"]["port"] = args.port
        else:
            missing.append("port")
        if args.token:
            config["cloud"]["token"] = args.token
        else:
            missing.append("token")

        if (args.proxy_type):
            config["proxy"] = {}
            if args.proxy_type:
                config["proxy"]["type"] = args.proxy_type
            else:
                missing.append("proxy type")
            if args.proxy_host:
                config["proxy"]["host"] = args.proxy_host
            else:
                missing.append("proxy host")
            if args.proxy_port:
                config["proxy"]["port"] = args.proxy_port
            else:
                missing.append("proxy port")

            if args.proxy_username:
                config["proxy"]["username"] = args.proxy_username
            if args.proxy_password:
                config["proxy"]["password"] = args.proxy_password

        # On Prem config options
        if (args.onprem_file_xfer_host):
            config["cloud"]["file_xfer_host"] = args.onprem_file_xfer_host
        if (args.onprem_file_xfer_port):
            config["cloud"]["file_xfer_port"] = args.onprem_file_xfer_port

        if missing:
            print("Missing {}. Try again.".format(", ".join(missing)))
            return 1

        config["qos_level"] = 1
        config["validate_cloud_cert"] = True

    else:
        # No arguments. Use prompt to gather information.
        print("Generating config. Please enter connection information for the config file.")
        print(file_desc)
        file_name = input("# ").strip()
        if not file_name:
            print("File name is required.")
            return 1

        print(cloud_desc)
        temp = input("# ").strip()
        if temp:
            config["cloud"]["host"] = temp
        else:
            print("Cloud address is required.")
            return 1

        print(port_desc)
        temp = input("# ").strip()
        if temp:
            if temp.isdigit():
                config["cloud"]["port"] = int(temp)
            else:
                print("Cloud port must be an integer.")
                return 1
        else:
            print("Cloud port is required.")
            return 1

        print(token_desc)
        temp = input("# ").strip()
        if temp:
            config["cloud"]["token"] = temp
        else:
            print("Cloud token is required.")
            return 1

        config["qos_level"] = 1
        config["validate_cloud_cert"] = True

        print(proxy_desc)
        temp = input("# ").strip()
        if temp and temp.lower() in positives:
            config["proxy"] = {}

            print(proxy_type_desc)
            temp = input("# ").strip()
            if temp:
                config["proxy"]["type"] = temp
            else:
                print("Proxy type is required.")
                return 1

            print(proxy_host_desc)
            temp = input("# ").strip()
            if temp:
                config["proxy"]["host"] = temp
            else:
                print("Proxy address is required.")
                return 1

            print(proxy_port_desc)
            temp = input("# ").strip()
            if temp:
                if temp.isdigit():
                    config["proxy"]["port"] = int(temp)
                else:
                    print("Proxy port must be an integer.")
                    return 1
            else:
                print("Proxy port is required.")
                return 1

            print(proxy_username_desc)
            temp = input("# ").strip()
            if temp:
                config["proxy"]["username"] = temp

            print(proxy_password_desc)
            temp = input("# ").strip()
            if temp:
                config["proxy"]["password"] = temp

        print(onprem_desc)
        temp = input("# ").strip()
        if temp:
            print(onprem_file_xfer_host_desc)
            temp = input("# ").strip()
            if temp:
                config["cloud"]["file_xfer_host"] = temp

            print(onprem_file_xfer_port_desc)
            temp = input("# ").strip()
            if temp:
                config["cloud"]["file_xfer_port"] = temp

    if not os.path.splitext(file_name)[1]:
        file_name += ".cfg"

    with open(file_name, "w+b") as config_file:
        config_file.write(json.dumps(config, indent=2, sort_keys=True).encode())
    os.chmod(file_name, stat.S_IRWXU | stat.S_IROTH | stat.S_IRGRP)
    print("\nConfiguration:")
    print(json.dumps(config, indent=2, sort_keys=True))
    print("")
    if len(sys.argv) == 1:
        input("Press enter to finish...")
    return 0


if __name__ == "__main__":
    status = generate()
    sys.exit(status)
