Running Device Cloud Python Over Proxy Server
=============================================

Tested with:
  * tinyproxy (HTTP)
  * danted (SOCKS 5)

Tiny Proxy
==========
https://github.com/tinyproxy/tinyproxy.git

Configuration: /etc/tinyproxy.conf
-----------------------------
Example tinyproxy configuration for testing only:

```
User root
Group root
Port 8888
Timeout 600
DefaultErrorFile "/usr/share/tinyproxy/default.html"
StatFile "/usr/share/tinyproxy/stats.html"
Logfile "/var/log/tinyproxy/tinyproxy.log"
LogLevel Info
PidFile "/var/run/tinyproxy/tinyproxy.pid"
MaxClients 100
MinSpareServers 5
MaxSpareServers 20
StartServers 10
MaxRequestsPerChild 0
ViaProxyName "tinyproxy"
```

HTTP Proxy Device Configuration
--------------------------------
Run "generate_config.py" and answer the questions for your setup.
Example configuration:
```
{
  "cloud": {
    "host": "CLOUDADDRESS",
    "port": 443,
    "token": "TOKEN"
  },
  "proxy": {
    "host": "PROXYIP",
    "port": PROXYPORT,
    "type": "http"
  },
  "qos_level": 1,
  "validate_cloud_cert": true
}
```

Testing HTTP Proxy
------------------
Run tinyproxy:
```sh
# as root
tinyproxy -d
```

Watch connections:
In a new shell run:
```sh
watch -n 1 'netstat -tn | grep EST | grep 8888'
```

Dante SOCKS 5 Server
--------------------
https://www.binarytides.com/setup-dante-socks5-server-on-ubuntu/

Configuration: /etc/danted.conf
--------------------------
Example configuration for testing only:

```
logoutput: syslog
user.privileged: root
user.unprivileged: nobody

# The listening network interface or address.
internal: 0.0.0.0 port=1080

# The proxying network interface or address.
external: eth0

# socks-rules determine what is proxied through the external
# interface.
# The default of "none" permits anonymous access.
socksmethod: none

# client-rules determine who can connect to the internal interface.
# The default of "none" permits anonymous access.
clientmethod: none

client pass {
        from: 0.0.0.0/0 to: 0.0.0.0/0
        log: connect disconnect error
}

socks pass {
        from: 0.0.0.0/0 to: 0.0.0.0/0
        log: connect disconnect error
}
```

Start the server:

```sh
service danted start
```

Verify it is running:

```sh
netstat -nlpt | grep dant
tcp        0      0 0.0.0.0:1080            0.0.0.0:*               LISTEN      6342/danted
```



Force all traffic through proxy server
======================================
On a Linux host, e.g. ubuntu, an iptables rule can be used to force
all external traffic through a proxy server.  This is useful for
testing purposes. Note: this rule will allow only the internal WR
network access out, e.g. to reach the proxy server on the network.
DNS queries are allowed. Here are the rules:
```sh
# Proxy only traffic and internal wr traffic
# allow only a range of ips out
iptables -F
iptables -X
iptables -P INPUT DROP

# accept the wr internal network only
iptables -A INPUT -i eth0 -s 128.224.0.0/16 -j ACCEPT
iptables -A OUTPUT -i eth0 -s 128.224.0.0/16 -j ACCEPT

#accept lo input output
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -i lo -j ACCEPT

# allow dns queries
iptables -A INPUT -p udp -m udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p udp -m udp --sport 53 -j ACCEPT
```


Issues with a proxy server
--------------------------
If a call back wants to make a requests call to localhost, i.e. do not
go over the proxy server, then it will not work because the
socket.socket has been overridden in the parent by PySocks to support
the proxy.  However, there is a work around.  In the call back where
requests is being used, restore socket.socket before calling requests:

```
socket.socket = client.handler.original_socket
r = requests.get('https://localhost:443', verify=False)
```
