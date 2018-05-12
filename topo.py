#!/usr/bin/python

# sudo mn --custom centralized_topo.py --topo mytopo --link tc,bw=1000,delay=10ms --controller=remote,ip=10.0.1.1,port=6633
# sudo mn --custom centralized_topo.py --topo mytopo --link tc,bw=1000,delay=10ms --controller=remote,port=6633
# sudo mn --custom centralized_topo.py --topo mytopo --link tc --controller=remote,port=6633 --mac

from mininet.topo import Topo
from mininet.node import OVSKernelSwitch

class MyTopo( Topo ):

  def __init__( self ):

    # Initialize topology
    Topo.__init__( self )

    # Only change servers and clients

    servers = 3
    clients = 3
    spine_switches = 2

    hosts = []
    switches = []

    hosts_cnt = 0

    # Add Hosts
    for h in range(servers):
      hosts.append(self.addHost('h%s' % (h+1)))
      hosts_cnt += 1

    for h in range(clients):
      hosts.append(self.addHost('h%s' % (h+1+servers)))
      hosts_cnt += 1

    # Add Switches
    # s6 is the load balancer
    for s in range(servers + clients + spine_switches * 2):
      switches.append(self.addSwitch('s%s' % (s+1), cls=OVSKernelSwitch, protocols='OpenFlow13'))

    # Add links
    for x in range(servers + clients):
        self.addLink(hosts[x], switches[x])

    for x in range(servers):
        for y in range (spine_switches):
            self.addLink(switches[servers + clients + y], switches[x])

    for x in range(clients):
        for y in range (spine_switches):
            self.addLink(switches[servers + clients + spine_switches + y], switches[x + servers])

    for x in range(spine_switches):
        self.addLink(switches[servers + clients + x], switches[servers + clients + spine_switches + x], bw=100)

    

topos = { 'mytopo': ( lambda: MyTopo() ) }
