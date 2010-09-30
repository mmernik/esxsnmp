#!/usr/bin/env python

import os
import sys
import socket
import time

from esxsnmp.util import get_ESDB_client
from esxsnmp.config get_opt_parser, get_config
from esxsnmp.api import ESxSNMPAPI

def gen_ma_storefile():
    """Translated from the original Perl by jdugan"""
    params = {}
    params['hostname'] = socket.gethostname()
    params['date'] = time.asctime()
    params['user'] = os.getlogin()
    params['args'] = " ".join(sys.argv)

    debug = False

    AUTHREALM = "ESnet-Public"
    DOMAIN = "es.net"
    HEADER = """<?xml version="1.0" encoding="UTF-8"?>


<!-- ===================================================================
<description>
   MA RRD configuration file

   $Id$
   project: perfSONAR

Notes:
   This is the configuration file which contains the information 
   about RRD files from ESnet.

   It was generated by %(user)s on %(hostname)s using %(args)s
   at %(date)s


    -Joe Metzger


</description>
==================================================================== -->
<nmwg:store
         xmlns:nmwg="http://ggf.org/ns/nmwg/base/2.0/"
         xmlns:netutil="http://ggf.org/ns/nmwg/characteristic/utilization/2.0/"
         xmlns:nmwgt="http://ggf.org/ns/nmwg/topology/2.0/" 
         xmlns:nmwgt3="http://ggf.org/ns/nmwg/topology/3.0/" >

     <!-- Note: The URNs and the nmwgt3 namespace are possible implementations, and not standard.
          The URNs should not be meta-data IDs. But maybe they should be idRefs. But this seems
          to be expanding the scope of a reference significantly...  Joe
      -->

     <!--  metadata section  -->

""" % params


    bogusIP = "BOGUS1"

    print HEADER

    (transport, client) = get_ESDB_client(server='snmp-west.es.net', port=9090)
    transport.open()

    oidset_rtr_map = {}
    interfaces = []

    for device in client.list_devices(1):
        if debug:
            print >>sys.stderr, "starting %s" % device

        for iface in client.get_interfaces(device, 0):
            if iface.ipaddr:
                try:
                    iface.dns = socket.gethostbyaddr(iface.ipaddr)[0]
                except socket.herror:
                    iface.dns = ''
            else:
                iface.dns = ''

            try:
                oidset = oidset_rtr_map[iface.device.name]
            except KeyError:
                for oidset in iface.device.oidsets:
                    if oidset.name == 'FastPoll':
                        oidset_rtr_map[iface.device.name] = oidset
                        break
                    elif oidset.name == 'FastPollHC':
                        oidset_rtr_map[iface.device.name] = oidset
                        break
      
            if oidset.name == 'FastPollHC':
                prefix = 'ifHC'
            elif oidset.name == 'FastPoll':
                prefix = 'if'
            else:
                print "<!-- No OIDSet for %s %s -->" % (iface.device.name,
                        iface.ifdescr)
                print >>sys.stderr, "No OIDSet for %s %s: %s" % (iface.device.name,
                        iface.ifdescr, ",".join([o.name for o in iface.device.oidsets]))

            iface.intpath = iface.ifdescr;
            iface.intpath = iface.intpath.replace("/","_")
            iface.intpath = iface.intpath.replace(" ","_")
            iface.key = '%s:%s' % (iface.device.name, iface.ifdescr)

            rtr = iface.device.name
            
            if iface.ifhighspeed == 0:
                speed = iface.ifspeed
            else:
                speed = iface.ifhighspeed * int(1e6)

            d = dict(
                    intname=iface.ifdescr,
                    namein='%s/%s/%sInOctets/%s' % (rtr, oidset.name, prefix,
                        iface.intpath),
                    nameout='%s/%s/%sOutOctets/%s' % (rtr, oidset.name, prefix,
                        iface.intpath),
                    intdesc=iface.ifalias,
                    device=rtr,
                    dns=iface.dns,
                    speed=speed,
                    ipaddr=iface.ipaddr,
                    domain=DOMAIN,
                    authrealm=AUTHREALM)

            interfaces.append(d)

        if debug:
            print >>sys.stderr, "done with %s" % (device)

    #
    # Now need to generate XML name spaces/rnc info
    #

    META = [] # Contains the Meta Data
    DATA = [] # Contains the data

    i = 0

    for iface in interfaces:
        if not iface['intname']:
            continue

        if iface['ipaddr']:
            iface['ipaddr_line'] = """
\t\t\t\t<nmwgt:ifAddress type="ipv4">%s</nmwgt:ifAddress>""" % iface['ipaddr']
        else:
            iface['ipaddr_line'] = ''

        for dir in ('in', 'out'):
            i += 1
            iface['i'] = i
            iface['dir'] = dir
            if dir == 'in':
                iface['name'] = iface['namein']
            else:
                iface['name'] = iface['nameout']

            m = """
\t<nmwg:metadata  xmlns:nmwg="http://ggf.org/ns/nmwg/base/2.0/" id="meta%(i)d">
\t\t<netutil:subject  xmlns:netutil="http://ggf.org/ns/nmwg/characteristic/utilization/2.0/" id="subj%(i)d">
\t\t\t<nmwgt:interface xmlns:nmwgt="http://ggf.org/ns/nmwg/topology/2.0/">
\t\t\t\t<nmwgt3:urn xmlns:nmwgt3="http://ggf.org/ns/nmwg/topology/base/3.0/">urn:ogf:network:domain=%(domain)s:node=%(device)s:port=%(intname)s</nmwgt3:urn>%(ipaddr_line)s
\t\t\t\t<nmwgt:hostName>%(device)s</nmwgt:hostName>
\t\t\t\t<nmwgt:ifName>%(intname)s</nmwgt:ifName>
\t\t\t\t<nmwgt:ifDescription>%(intdesc)s</nmwgt:ifDescription>
\t\t\t\t<nmwgt:capacity>%(speed)s</nmwgt:capacity>
\t\t\t\t<nmwgt:direction>%(dir)s</nmwgt:direction>
\t\t\t\t<nmwgt:authRealm>%(authrealm)s</nmwgt:authRealm>
\t\t\t</nmwgt:interface>
\t\t</netutil:subject>
\t\t<nmwg:eventType>http://ggf.org/ns/nmwg/characteristic/utilization/2.0</nmwg:eventType>
\t\t<nmwg:parameters id="metaparam%(i)d">
\t\t\t<nmwg:parameter name="supportedEventType">http://ggf.org/ns/nmwg/characteristic/utilization/2.0</nmwg:parameter>
\t\t\t<nmwg:parameter name="supportedEventType">http://ggf.org/ns/nmwg/tools/snmp/2.0</nmwg:parameter>
\t\t</nmwg:parameters>
\t</nmwg:metadata>""" % iface

            META.append(m)

            d = """
\t<nmwg:data  xmlns:nmwg="http://ggf.org/ns/nmwg/base/2.0/" id="data%(i)d" metadataIdRef="meta%(i)d">
\t\t<nmwg:key id="keyid%(i)d">
\t\t\t<nmwg:parameters id="dataparam%(i)d">
\t\t\t\t<nmwg:parameter name="type">esxsnmp</nmwg:parameter>
\t\t\t\t<nmwg:parameter name="valueUnits">Bps</nmwg:parameter>
\t\t\t\t<nmwg:parameter name="name">%(name)s</nmwg:parameter>
\t\t\t\t<nmwg:parameter name="eventType">http://ggf.org/ns/nmwg/characteristic/utilization/2.0</nmwg:parameter>
\t\t\t</nmwg:parameters>
\t\t</nmwg:key>
\t</nmwg:data>""" % iface

            DATA.append(d)



    print ''.join(META)
    print ''.join(DATA)
    print '</nmwg:store>'
           
def gen_ma_storefile_http():
    """Translated from the original Perl by jdugan"""

    argv = sys.argv
    oparse = get_opt_parser(default_config_file=get_config_path())
    (opts, args) = oparse.parse_args(args=argv)

    try:
        config = get_config(opts.config_file, opts)
    except ConfigError, e:
        print >>sys.stderr, e
        sys.exit(1)

    if not config.db_uri:
        print >>sys.stderr, "error: db_uri not specified in config"
        sys.exit(1)

    params = {}
    params['hostname'] = socket.gethostname()
    params['date'] = time.asctime()
    params['user'] = os.getlogin()
    params['args'] = " ".join(sys.argv)

    debug = False

    AUTHREALM = "ESnet-Public"
    DOMAIN = "es.net"
    HEADER = """<?xml version="1.0" encoding="UTF-8"?>


<!-- ===================================================================
<description>
   MA RRD configuration file

   $Id$
   project: perfSONAR

Notes:
   This is the configuration file which contains the information 
   about RRD files from ESnet.

   It was generated by %(user)s on %(hostname)s using %(args)s
   at %(date)s


    -Joe Metzger


</description>
==================================================================== -->
<nmwg:store
         xmlns:nmwg="http://ggf.org/ns/nmwg/base/2.0/"
         xmlns:netutil="http://ggf.org/ns/nmwg/characteristic/utilization/2.0/"
         xmlns:nmwgt="http://ggf.org/ns/nmwg/topology/2.0/" 
         xmlns:nmwgt3="http://ggf.org/ns/nmwg/topology/3.0/" >

     <!-- Note: The URNs and the nmwgt3 namespace are possible implementations, and not standard.
          The URNs should not be meta-data IDs. But maybe they should be idRefs. But this seems
          to be expanding the scope of a reference significantly...  Joe
      -->

     <!--  metadata section  -->

""" % params


    bogusIP = "BOGUS1"

    print HEADER

    client = ESxSNMPAPI(config.db_uri)

    oidset_rtr_map = {}
    interfaces = []

    debug = True
    rtrs = client.get_routers()
    devices = [ x['name'] for x in rtrs['children']]

    for device in devices:
        if device.startswith('wifi'):
            continue

        try:
            device_fqdn = socket.gethostbyaddr(device)[0]
        except socket.herror:
            device_fqdn = device

        if debug:
            print >>sys.stderr, "starting %s" % device

        ifaces = filter(lambda x: x['descr'] != '',
                client.get_interfaces(device)['children'])

        l = []
        for iface in ifaces:
            l.append(dict(id=iface['uri'], uri=iface['uri']))

        ifaces = client.get_bulk(l)

        for k, iface in ifaces.iteritems():
            iface = iface['result'][0]
            if debug:
                print >>sys.stderr, iface

            if iface['ipAddr']:
                try:
                    iface['dns'] = socket.gethostbyaddr(iface['ipAddr'])[0]
                except socket.herror:
                    iface['dns'] = ''
            else:
                iface['dns'] = ''

            iface['key'] = '%s:%s' % (device, iface['ifDescr'])

            iface['device'] = device
            iface['device_fqdn'] = device_fqdn
            
            if iface['ifHighSpeed'] == 0:
                iface['speed'] = iface['ifSpeed']
            else:
                iface['speed'] = iface['ifHighSpeed'] * int(1e6)

            iface['domain'] = DOMAIN
            iface['authrealm'] = AUTHREALM
            iface['namein'] = iface['uri'] + '/in'
            iface['nameout'] = iface['uri'] + '/out'
            iface['ifAlias'] = iface['ifAlias'].replace('&','')

            """
            d = dict(
                    intname=iface.ifdescr,
                    namein='%s/%s/%sInOctets/%s' % (rtr, oidset.name, prefix,
                        iface.intpath),
                    nameout='%s/%s/%sOutOctets/%s' % (rtr, oidset.name, prefix,
                        iface.intpath),
                    intdesc=iface.ifalias,
                    device=rtr,
                    dns=iface.dns,
                    speed=speed,
                    ipaddr=iface.ipaddr,
                    domain=DOMAIN,
                    authrealm=AUTHREALM)
            """

            interfaces.append(iface)

        if debug:
            print >>sys.stderr, "done with %s" % (device)

    #
    # Now need to generate XML name spaces/rnc info
    #

    META = [] # Contains the Meta Data
    DATA = [] # Contains the data

    i = 0

    for iface in interfaces:
        if not iface['ifDescr']:
            continue

        if iface['ipAddr']:
            iface['ipaddr_line'] = """
\t\t\t\t<nmwgt:ifAddress type="ipv4">%s</nmwgt:ifAddress>""" % iface['ipAddr']
        else:
            iface['ipaddr_line'] = ''

        for dir in ('in', 'out'):
            i += 1
            iface['i'] = i
            iface['dir'] = dir
            if dir == 'in':
                iface['name'] = iface['namein']
            else:
                iface['name'] = iface['nameout']

            m = """
\t<nmwg:metadata  xmlns:nmwg="http://ggf.org/ns/nmwg/base/2.0/" id="meta%(i)d">
\t\t<netutil:subject  xmlns:netutil="http://ggf.org/ns/nmwg/characteristic/utilization/2.0/" id="subj%(i)d">
\t\t\t<nmwgt:interface xmlns:nmwgt="http://ggf.org/ns/nmwg/topology/2.0/">
\t\t\t\t<nmwgt3:urn xmlns:nmwgt3="http://ggf.org/ns/nmwg/topology/base/3.0/">urn:ogf:network:domain=%(domain)s:node=%(device)s:port=%(ifDescr)s</nmwgt3:urn>%(ipaddr_line)s
\t\t\t\t<nmwgt:hostName>%(device_fqdn)s</nmwgt:hostName>
\t\t\t\t<nmwgt:ifName>%(ifDescr)s</nmwgt:ifName>
\t\t\t\t<nmwgt:ifDescription>%(ifAlias)s</nmwgt:ifDescription>
\t\t\t\t<nmwgt:capacity>%(speed)s</nmwgt:capacity>
\t\t\t\t<nmwgt:direction>%(dir)s</nmwgt:direction>
\t\t\t\t<nmwgt:authRealm>%(authrealm)s</nmwgt:authRealm>
\t\t\t</nmwgt:interface>
\t\t</netutil:subject>
\t\t<nmwg:eventType>http://ggf.org/ns/nmwg/characteristic/utilization/2.0</nmwg:eventType>
\t\t<nmwg:parameters id="metaparam%(i)d">
\t\t\t<nmwg:parameter name="supportedEventType">http://ggf.org/ns/nmwg/characteristic/utilization/2.0</nmwg:parameter>
\t\t\t<nmwg:parameter name="supportedEventType">http://ggf.org/ns/nmwg/tools/snmp/2.0</nmwg:parameter>
\t\t</nmwg:parameters>
\t</nmwg:metadata>""" % iface

            META.append(m)

            d = """
\t<nmwg:data  xmlns:nmwg="http://ggf.org/ns/nmwg/base/2.0/" id="data%(i)d" metadataIdRef="meta%(i)d">
\t\t<nmwg:key id="keyid%(i)d">
\t\t\t<nmwg:parameters id="dataparam%(i)d">
\t\t\t\t<nmwg:parameter name="type">esxsnmp</nmwg:parameter>
\t\t\t\t<nmwg:parameter name="valueUnits">Bps</nmwg:parameter>
\t\t\t\t<nmwg:parameter name="name">%(name)s</nmwg:parameter>
\t\t\t\t<nmwg:parameter name="eventType">http://ggf.org/ns/nmwg/characteristic/utilization/2.0</nmwg:parameter>
\t\t\t</nmwg:parameters>
\t\t</nmwg:key>
\t</nmwg:data>""" % iface

            DATA.append(d)



    print ''.join(META)
    print ''.join(DATA)
    print '</nmwg:store>'
           
