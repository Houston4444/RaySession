#!/usr/bin/python3
import liblo
import sys
from PyQt5.QtXml import QDomDocument

def noGoodArg():
    strerror = "%s currently only recognizes the following options:\n" \
                    % sys.argv[0]
    strerror += "save close abort\n"
    sys.stderr.write(strerror)
    sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) <= 1:
        noGoodArg()
        
    option = sys.argv[1]
    if not option in ('save', 'close', 'abort'):
        noGoodArg()
        
    multi_daemon_file = '/tmp/RaySession/multi-daemon.xml'
    file = open(multi_daemon_file, 'r')
    xml = QDomDocument()
    xml.setContent(file.read())
    
    daemons_root = xml.documentElement()
    nodes = daemons_root.childNodes()
    for i in range(nodes.count()):
        node = nodes.at(i)
        node_el = node.toElement()
        port = node_el.attribute('port')
        liblo.send(liblo.Address(port), '/ray/session/%s' % option)
    
