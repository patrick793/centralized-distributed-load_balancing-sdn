# Copyright (C) 2011 Nippon Telegraph and Telephone Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

__author__  = "Patrick Atienza"

# from operator import attrgetter
# import os

import sys
import ctypes
 
import random
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import arp, ipv4, tcp, udp
from ryu.lib.packet import ether_types, in_proto

from ryu.topology import event, switches
from ryu.topology.api import get_switch, get_link, get_host, get_all_host

from ryu.lib import hub

from random import randint

# import time

# Datapath Types
DT_SERVER_LEAF = 1
DT_SPINE = 2
DT_CLIENT_LEAF = 3

class SimpleSwitch13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(SimpleSwitch13, self).__init__(*args, **kwargs)

        # os.system('clear')

        self.client_cnt = 3
        self.server_cnt = 3


        self.is_rr = True  # Round-robin
        self.is_ih = False # IP Hashing
        self.is_rb = False # Weighted Random
        self.is_lc = False  # Least connections
        self.is_lb = False   # Least bandwidth
        self.is_lp = False   # Least packets

        self.is_tcp = True
        self.is_udp = False

        self.mac_to_port = {}
        self.port_to_mac = {}
        self.mac_to_ip = {}

        self.l4_port_to_ip = {}

        self.get_topology_data_success = False

        # Virtual Load Balancer IP
        self.controller_ip = "10.0.0.100"

        # Virtual Load Balancer MAC Address
        self.controller_mac = "11:22:33:ab:cd:ef"

        self.total_hosts = 0
       
        self.server_ips = []
        for x in range(self.server_cnt):
            self.server_ips.append("10.0.0.%s" % (x+1))
            self.total_hosts += 1

        self.client_ips = []
        for x in range(self.client_cnt):
            self.total_hosts += 1
            self.client_ips.append("10.0.0.%s" % (self.total_hosts))

        self.datapaths = {}
        self.dpid_type = {} # DT_SERVER_LEAF = 1, DT_SPINE = 2, DT_CLIENT_LEAF = 3

        self.spine_dpids = []
        self.server_leaf_dpids = []
        self.client_leaf_dpids = []
        self.dpid_to_mac = {}

        self.is_init = True
        self.init_thread = hub.spawn(self.init_delay)

        # Test
        self.target_mac = "00:00:00:00:00:01"
        self.target_ip = "10.0.0.1"

        if self.is_rr or self.is_ih:
            self.cur_spine_index = 0
            self.cur_server_leaf_index = 0

        if self.is_rb:
            self.max_weight = 1
            while self.max_weight * 2 < sys.maxsize:
                self.max_weight*=2
            self.spine_weights = []
            self.server_leaf_weights = []

        if self.is_lc or self.is_lb or self.is_lp:
            self.spine_active_ports = {}
            self.server_leaf_active_ports = {}

        if self.is_lb or self.is_lp:
            if self.is_lb:
                self.spine_prev_total_transmitted_bytes = {}
                self.spine_cur_total_transmitted_bytes = {}
                self.server_leaf_prev_total_transmitted_bytes = {}
                self.server_leaf_cur_total_transmitted_bytes = {}
            if self.is_lp:
                self.spine_prev_total_transmitted_packets = {}
                self.spine_cur_total_transmitted_packets = {}
                self.server_leaf_prev_total_transmitted_packets = {}
                self.server_leaf_cur_total_transmitted_packets = {}
            
            self.spine_prev_time_sec = {}
            self.spine_prev_time_nsec = {}
            self.spine_cur_time_sec = {}
            self.spine_cur_time_nsec = {}
            self.server_leaf_prev_time_sec = {}
            self.server_leaf_prev_time_nsec = {}
            self.server_leaf_cur_time_sec = {}
            self.server_leaf_cur_time_nsec = {}

            self.ports_to_check_per_dpid = {}
        if self.is_ih == True:
            self.ip_hash_to_spine_dpid = {}
            self.ip_hash_to_server_leaf_dpid = {}

        self.count_in = 0

    def init_delay(self):
        hub.sleep(1.5)
        # time.sleep(5)

        self.is_init = False

        # Final Initializations
        for x,_ in self.datapaths.items():
            if x in self.server_leaf_dpids:
                self.dpid_type[x] = DT_SERVER_LEAF
            elif x in self.client_leaf_dpids:
                self.dpid_type[x] = DT_CLIENT_LEAF
            else:
                self.dpid_type[x] = DT_SPINE
                self.spine_dpids.append(x)


        self.server_leaf_dpids.sort()
        self.client_leaf_dpids.sort()

        # Set meters for spine switches
        # for dpid in self.spine_dpids:
        #     datapath = self.datapaths[dpid]
        #     ofproto = datapath.ofproto
        #     parser = datapath.ofproto_parser

        #     bands = [parser.OFPMeterBandDrop(type_=ofproto.OFPMBT_DROP, len_=0, rate=1000, burst_size=10)]
        #     req=parser.OFPMeterMod(datapath=datapath, command=ofproto.OFPMC_ADD, flags=ofproto.OFPMF_KBPS, meter_id=99, bands=bands)
        #     datapath.send_msg(req)

        if self.is_rb:
            for x in range(len(self.spine_dpids) / 2):
                self.spine_weights.append({"w" : self.max_weight, "i" : x})
            for x in self.server_leaf_dpids:
                self.server_leaf_weights.append({"w" : self.max_weight, "i" : x})

        if self.is_lc or self.is_lb or self.is_lp:
            for x in range(len(self.spine_dpids) / 2):
                self.spine_active_ports[self.spine_dpids[x]] = []
            for x in self.server_leaf_dpids:
                self.server_leaf_active_ports[x] = []

            if self.is_lb or self.is_lp:
                for x in range(len(self.spine_dpids) / 2):
                    if self.is_lb:
                        self.spine_prev_total_transmitted_bytes[self.spine_dpids[x]] = 0
                        self.spine_cur_total_transmitted_bytes[self.spine_dpids[x]] = 0
                    elif self.is_lp:
                        self.spine_prev_total_transmitted_packets[self.spine_dpids[x]] = 0
                        self.spine_cur_total_transmitted_packets[self.spine_dpids[x]] = 0
                    self.spine_prev_time_sec[self.spine_dpids[x]] = 0
                    self.spine_prev_time_nsec[self.spine_dpids[x]] = 0
                    self.spine_cur_time_sec[self.spine_dpids[x]] = 0
                    self.spine_cur_time_nsec[self.spine_dpids[x]] = 0
                    self.ports_to_check_per_dpid[self.spine_dpids[x]] = []
                for dpid in self.server_leaf_dpids:
                    if self.is_lb:
                        self.server_leaf_prev_total_transmitted_bytes[dpid] = 0
                        self.server_leaf_cur_total_transmitted_bytes[dpid] = 0
                    elif self.is_lp:
                        self.server_leaf_prev_total_transmitted_packets[dpid] = 0
                        self.server_leaf_cur_total_transmitted_packets[dpid] = 0
                    self.server_leaf_prev_time_sec[dpid] = 0
                    self.server_leaf_prev_time_nsec[dpid] = 0
                    self.server_leaf_cur_time_sec[dpid] = 0
                    self.server_leaf_cur_time_nsec[dpid] = 0
                    self.ports_to_check_per_dpid[dpid] = []
                self.monitor_thread = hub.spawn(self.monitor)

        
        self.logger.info("dpid_types" + str(self.dpid_type))
        self.logger.info("mac_to_port" + str(self.mac_to_port))
        self.logger.info("port_to_mac" + str(self.port_to_mac))
        self.logger.info("spine_dpids: " + str(self.spine_dpids))
        self.logger.info("server_leaf_dpids: " + str(self.server_leaf_dpids))
        self.logger.info("client_leaf_dpids: " + str(self.client_leaf_dpids))

        self.logger.info("Initialization complete!")
        if self.is_rr:
            self.logger.info("Round-robin Load Balancing is activated!")
        elif self.is_lc:
            self.logger.info("Least Connections Load Balancing is activated!")
        elif self.is_lb:
            self.logger.info("Least Bandwidth Load Balancing is activated!")
        elif self.is_lp:
            self.logger.info("Least Packets Load Balancing is activated!")
        elif self.is_rb:
            self.logger.info("Random Load Balancing is activated!")
        elif self.is_ih:
            self.logger.info("IP Hashing Load Balancing is activated!")

        if self.is_tcp:
            self.logger.info("TCP-only mode! (Note: Establishing UDP connections may cause inconsistencies)")
        if self.is_udp:
            self.logger.info("UDP-only mode! (Note: Establishing TCP connections may cause inconsistencies)")

    def monitor(self):
        while True:
            # os.system('clear')
            for x in range(len(self.spine_dpids) / 2):
                self.request_stats(self.datapaths[self.spine_dpids[x]])
            for dpid in self.server_leaf_dpids:
                self.request_stats(self.datapaths[dpid])
            hub.sleep(.1)

    def request_stats(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        req = parser.OFPPortStatsRequest(datapath)
        datapath.send_msg(req)

    def calculate_speed(self, dpid, active_connections):
        if self.dpid_type[dpid] == DT_SPINE:
            if self.is_lb:
                transmit_diff = self.spine_cur_total_transmitted_bytes[dpid] - self.spine_prev_total_transmitted_bytes[dpid]
            elif self.is_lp:
                transmit_diff = self.spine_cur_total_transmitted_packets[dpid] - self.spine_prev_total_transmitted_packets[dpid]
            cur_sec = self.spine_cur_time_sec[dpid] - self.spine_prev_time_sec[dpid]
            cur_nsec = self.spine_cur_time_nsec[dpid] - self.spine_prev_time_nsec[dpid]
            if cur_sec < 0 or (cur_sec == 0 and cur_nsec <= 0):
                self.logger.info("ERROR: prev_time larger or equal than cur_time")
                return
            if cur_nsec < 0:
                cur_sec -= 1
                cur_nsec = (self.spine_cur_time_nsec[dpid] + 1000000000) - self.spine_prev_time_nsec[dpid]

            time_diff = float(cur_sec) + float(cur_nsec) / float(1000000000)
            speed = transmit_diff / time_diff
            if active_connections == 0:
                return float(0)
            else:
                return speed / float(active_connections)
        elif self.dpid_type[dpid] == DT_SERVER_LEAF:

            if self.is_lb:
                transmit_diff = self.server_leaf_cur_total_transmitted_bytes[dpid] - self.server_leaf_prev_total_transmitted_bytes[dpid]
            elif self.is_lp:
                transmit_diff = self.server_leaf_cur_total_transmitted_packets[dpid] - self.server_leaf_prev_total_transmitted_packets[dpid]
            cur_sec = self.server_leaf_cur_time_sec[dpid] - self.server_leaf_prev_time_sec[dpid]
            cur_nsec = self.server_leaf_cur_time_nsec[dpid] - self.server_leaf_prev_time_nsec[dpid]
            if cur_sec < 0 or (cur_sec == 0 and cur_nsec <= 0):
                self.logger.info("ERROR: prev_time larger or equal than cur_time")
                return
            if cur_nsec < 0:
                cur_sec -= 1
                cur_nsec = (self.server_leaf_cur_time_nsec[dpid] + 1000000000) - self.server_leaf_prev_time_nsec[dpid]
            time_diff = float(cur_sec) + float(cur_nsec) / float(1000000000)
            speed = transmit_diff / time_diff
            if active_connections == 0:
                return float(0)
            else:
                return speed / float(active_connections)
        return None


    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply_handler(self, ev):
        body = ev.msg.body
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        dpid = datapath.id
        
        if self.dpid_type[dpid] == DT_SPINE:
            if not self.ports_to_check_per_dpid[dpid]:
                if self.is_lb:
                    total_transmitted_bytes = 0
                elif self.is_lp:
                    total_transmitted_packets = 0
                for i in range(len(body)):
                    x = body[i]
                    try:
                        if self.dpid_type[self.port_to_mac[dpid][x.port_no]] == DT_SERVER_LEAF:
                            self.ports_to_check_per_dpid[dpid].append([i, x.port_no])
                            if self.is_lb:
                                total_transmitted_bytes += x.tx_bytes
                            elif self.is_lp:
                                total_transmitted_packets += x.tx_packets
                            # if i == len(body) - 1:
                            self.spine_cur_time_sec[dpid] = x.duration_sec
                            self.spine_cur_time_nsec[dpid] = x.duration_nsec
                    except KeyError:
                        pass
                if self.is_lb:
                    self.spine_cur_total_transmitted_bytes[dpid] = total_transmitted_bytes
                elif self.is_lp:
                    self.spine_cur_total_transmitted_packets[dpid] = total_transmitted_packets
            else:
                if self.is_lb:
                    self.spine_prev_total_transmitted_bytes[dpid] = self.spine_cur_total_transmitted_bytes[dpid]
                elif self.is_lp:
                    self.spine_prev_total_transmitted_packets[dpid] = self.spine_cur_total_transmitted_packets[dpid]
                self.spine_prev_time_sec[dpid] = self.spine_cur_time_sec[dpid]
                self.spine_prev_time_nsec[dpid] = self.spine_cur_time_nsec[dpid]
                if self.is_lb:
                    total_transmitted_bytes = 0
                elif self.is_lp:
                    total_transmitted_packets = 0
                for i in range(len(self.ports_to_check_per_dpid[dpid])):
                    x = body[self.ports_to_check_per_dpid[dpid][i][0]]
                    if x.port_no != self.ports_to_check_per_dpid[dpid][i][1]:
                        self.logger.info("ERROR: Spine index and port mismatch! " + str(self.ports_to_check_per_dpid[dpid][i][1]) + ":" + str(x.port_no))
                        return
                    if self.is_lb:
                        total_transmitted_bytes += x.tx_bytes
                    elif self.is_lp:
                        total_transmitted_packets += x.tx_packets
                    if i == len(self.ports_to_check_per_dpid[dpid]) - 1:
                        self.spine_cur_time_sec[dpid] = x.duration_sec
                        self.spine_cur_time_nsec[dpid] = x.duration_nsec
                if self.is_lb:
                    self.spine_cur_total_transmitted_bytes[dpid] = total_transmitted_bytes
                elif self.is_lp:
                    self.spine_cur_total_transmitted_packets[dpid] = total_transmitted_packets
            # self.logger.info(str(self.spine_prev_total_transmitted_bytes[dpid]) + " " + str(self.spine_cur_total_transmitted_bytes[dpid]))
            # self.logger.info(str(self.spine_prev_time_sec[dpid]) + " " + str(self.spine_cur_time_sec[dpid]))
            # self.logger.info(str(self.spine_prev_time_nsec[dpid]) + " " + str(self.spine_cur_time_nsec[dpid]))
        elif self.dpid_type[dpid] == DT_SERVER_LEAF:
            if not self.ports_to_check_per_dpid[dpid]:
                if self.is_lb:
                    total_transmitted_bytes = 0
                elif self.is_lp:
                    total_transmitted_packets = 0
                for i in range(len(body)):
                    x = body[i]
                    try:
                        if self.mac_to_ip[self.port_to_mac[dpid][x.port_no]] in self.server_ips:
                            self.ports_to_check_per_dpid[dpid].append([i, x.port_no])
                            if self.is_lb:
                                total_transmitted_bytes += x.tx_bytes
                            elif self.is_lp:
                                total_transmitted_packets += x.tx_packets
                            # if i == len(body) - 1:
                            self.server_leaf_cur_time_sec[dpid] = x.duration_sec
                            self.server_leaf_cur_time_nsec[dpid] = x.duration_nsec
                    except KeyError:
                        pass
                if self.is_lb:
                    self.server_leaf_cur_total_transmitted_bytes[dpid] = total_transmitted_bytes
                elif self.is_lp:
                    self.server_leaf_cur_total_transmitted_packets[dpid] = total_transmitted_packets
            else:
                if self.is_lb:
                    self.server_leaf_prev_total_transmitted_bytes[dpid] = self.server_leaf_cur_total_transmitted_bytes[dpid]
                elif self.is_lp:
                    self.server_leaf_prev_total_transmitted_packets[dpid] = self.server_leaf_cur_total_transmitted_packets[dpid]
                self.server_leaf_prev_time_sec[dpid] = self.server_leaf_cur_time_sec[dpid]
                self.server_leaf_prev_time_nsec[dpid] = self.server_leaf_cur_time_nsec[dpid]
                if self.is_lb:
                    total_transmitted_bytes = 0
                elif self.is_lp:
                    total_transmitted_packets = 0
                for i in range(len(self.ports_to_check_per_dpid[dpid])):
                    x = body[self.ports_to_check_per_dpid[dpid][i][0]]
                    if x.port_no != self.ports_to_check_per_dpid[dpid][i][1]:
                        self.logger.info("ERROR: Server leaf index and port mismatch! " + str(self.ports_to_check_per_dpid[dpid][i][1]) + ":" + str(x.port_no))
                        return
                    if self.is_lb:
                        total_transmitted_bytes += x.tx_bytes
                    elif self.is_lp:
                        total_transmitted_packets += x.tx_packets
                    if i == len(self.ports_to_check_per_dpid[dpid]) - 1:
                        self.server_leaf_cur_time_sec[dpid] = x.duration_sec
                        self.server_leaf_cur_time_nsec[dpid] = x.duration_nsec
                if self.is_lb:
                    self.server_leaf_cur_total_transmitted_bytes[dpid] = total_transmitted_bytes
                elif self.is_lp:
                    self.server_leaf_cur_total_transmitted_packets[dpid] = total_transmitted_packets 
            # self.logger.info(str(self.server_leaf_prev_total_transmitted_bytes[dpid]) + " " + str(self.server_leaf_cur_total_transmitted_bytes [dpid]))
            # self.logger.info(str(self.server_leaf_prev_time_sec[dpid]) + " " + str(self.server_leaf_cur_time_sec[dpid]))
            # self.logger.info(str(self.server_leaf_prev_time_nsec[dpid]) + " " + str(self.server_leaf_cur_time_nsec[dpid]))
            # print(body)


                # for x in ports_to_check_per_dpid[dpid]:
                #     cur_total



        # self.logger.info('datapath         port     '
        #                  'rx-pkts  rx-bytes rx-error '
        #                  'tx-pkts  tx-bytes tx-error')
        # self.logger.info('---------------- -------- '
        #                  '-------- -------- -------- '
        #                  '-------- -------- --------')
        # for stat in sorted(body, key=attrgetter('port_no')):
        #     self.logger.info('%016x %8x %8d %8d %8d %8d %8d %8d',
        #                      ev.msg.datapath.id, stat.port_no,
        #                      stat.rx_packets, stat.rx_bytes, stat.rx_errors,
        #                      stat.tx_packets, stat.tx_bytes, stat.tx_errors)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        dpid = datapath.id

        # install table-miss flow entry
        #
        # We specify NO BUFFER to max_len of the output action due to
        # OVS bug. At this moment, if we specify a lesser number, e.g.,
        # 128, OVS will send Packet-In with invalid buffer_id and
        # truncated packet data. In that case, we cannot output packets
        # correctly.  The bug has been fixed in OVS v2.1.0.
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, match, actions, 0)

        self.datapaths[datapath.id] = datapath

        links_list = get_link(self, None)
        # links=[(link.src.dpid,link.dst.dpid,{'port':link.src.port_no}) for link in links_list]
        
        for link in links_list:
            self.mac_to_port.setdefault(link.src.dpid, {})
            self.port_to_mac.setdefault(link.src.dpid, {})
            self.mac_to_port[link.src.dpid][link.dst.dpid] = link.src.port_no
            self.port_to_mac[link.src.dpid][link.src.port_no] = link.dst.dpid

        self.logger.info("Successful getting topology data!")

        for x in self.server_ips:
            self.send_arp(datapath, x)
        for x in self.client_ips:
            self.send_arp(datapath, x)

    def send_arp(self, datapath, dst_ip, dst_mac=None, out_port=None, opcode=arp.ARP_REQUEST):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        if out_port == None:
            out_port = datapath.ofproto.OFPP_FLOOD
        if dst_mac == None:
            dst_mac = 'ff:ff:ff:ff:ff:ff'

        pkt = packet.Packet()
        e = ethernet.ethernet(
            dst_mac,
            self.controller_mac,
            ether_types.ETH_TYPE_ARP)
        r = arp.arp(
            opcode=opcode,
            src_mac=self.controller_mac,
            src_ip=self.controller_ip,
            dst_mac=dst_mac,
            dst_ip=dst_ip)
        pkt.add_protocol(e)
        pkt.add_protocol(r)
        pkt.serialize()

        actions = [parser.OFPActionOutput(out_port)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=0xffffffff,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=pkt.data)
        datapath.send_msg(out)


    def add_flow(self, datapath, match, actions, priority=ofproto_v1_3.OFP_DEFAULT_PRIORITY, idle_timeout=0, buffer_id=None, cookie=0, meter_id=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = []
        inst.append(parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions))
        if meter_id != 0:
            inst.append(parser.OFPInstructionMeter(meter_id,ofproto.OFPIT_METER))

        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    instructions=inst, idle_timeout=idle_timeout,
                                    cookie=cookie, flags=ofproto.OFPFF_SEND_FLOW_REM)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                    match=match, instructions=inst,
                                    idle_timeout=idle_timeout, cookie=cookie,
                                    flags=ofproto.OFPFF_SEND_FLOW_REM)
        datapath.send_msg(mod)

    def arp_init(self, datapath, arp_header, in_port):
        dpid = datapath.id

        if arp_header.dst_ip == self.controller_ip and arp_header.opcode == arp.ARP_REPLY:
            # print(arp_header)
            if arp_header.src_ip in self.server_ips:
                self.server_leaf_dpids.append(dpid)
                self.dpid_to_mac[dpid] = arp_header.src_mac
                self.mac_to_ip[arp_header.src_mac] = arp_header.src_ip
            elif arp_header.src_ip in self.client_ips:
                self.client_leaf_dpids.append(dpid)
                self.dpid_to_mac[dpid] = arp_header.src_mac
                self.mac_to_ip[arp_header.src_mac] = arp_header.src_ip

    def select_next_dpids(self, src_ip = None):
        
        if self.is_rr:
            cur_spine_dpid_upper = self.spine_dpids[self.cur_spine_index + len(self.spine_dpids) / 2]
            cur_spine_dpid_lower = self.spine_dpids[self.cur_spine_index]
            cur_server_leaf_dpid = self.server_leaf_dpids[self.cur_server_leaf_index]

            self.cur_server_leaf_index += 1
            if self.cur_server_leaf_index == len(self.server_leaf_dpids):
                self.cur_server_leaf_index = 0

            self.cur_spine_index += 1
            if self.cur_spine_index == len(self.spine_dpids) / 2:
                self.cur_spine_index = 0

            return cur_spine_dpid_upper, cur_spine_dpid_lower, cur_server_leaf_dpid
        elif self.is_lc:
            cur_spine_dpid_upper = -1
            cur_spine_dpid_lower = -1
            cur_server_leaf_dpid = -1

            min_spine_active_ports = 9999999999
            min_server_leaf_active_ports = 9999999999
            for x in range(len(self.spine_dpids) / 2 ):
                if min_spine_active_ports > len(self.spine_active_ports[self.spine_dpids[x]]):
                    min_spine_active_ports = len(self.spine_active_ports[self.spine_dpids[x]])
                    cur_spine_dpid_upper = self.spine_dpids[x + len(self.spine_dpids) / 2]
                    cur_spine_dpid_lower = self.spine_dpids[x]

            for x in range(len(self.server_leaf_dpids)):
                if min_server_leaf_active_ports > len(self.server_leaf_active_ports[self.server_leaf_dpids[x]]):
                    min_server_leaf_active_ports = len(self.server_leaf_active_ports[self.server_leaf_dpids[x]])
                    cur_server_leaf_dpid = self.server_leaf_dpids[x]

            return cur_spine_dpid_upper, cur_spine_dpid_lower, cur_server_leaf_dpid
        elif self.is_lb:
            cur_spine_dpid_upper = -1
            cur_spine_dpid_lower = -1
            cur_server_leaf_dpid = -1

            max_spine_bytes_per_sec = 0
            max_server_leaf_bytes_per_sec = 0
            
            for x in range(len(self.spine_dpids) / 2 ):
                spine_active_ports_len = len(self.spine_active_ports[self.spine_dpids[x]])
                if  spine_active_ports_len == 0:
                    cur_spine_dpid_upper = self.spine_dpids[x + len(self.spine_dpids) / 2]
                    cur_spine_dpid_lower = self.spine_dpids[x]
                    break
                else:
                    bytes_per_sec = self.calculate_speed(self.spine_dpids[x], spine_active_ports_len)
                    if max_spine_bytes_per_sec <= bytes_per_sec:
                        max_spine_bytes_per_sec = bytes_per_sec
                        cur_spine_dpid_upper = self.spine_dpids[x + len(self.spine_dpids) / 2]
                        cur_spine_dpid_lower = self.spine_dpids[x]

            for x in range(len(self.server_leaf_dpids)):
                server_leaf_active_ports_len = len(self.server_leaf_active_ports[self.server_leaf_dpids[x]])
                if  server_leaf_active_ports_len == 0:
                    cur_server_leaf_dpid = self.server_leaf_dpids[x]
                    break
                else:
                    bytes_per_sec = self.calculate_speed(self.server_leaf_dpids[x], server_leaf_active_ports_len)
                    if max_server_leaf_bytes_per_sec <= bytes_per_sec:
                        max_server_leaf_bytes_per_sec = bytes_per_sec
                        cur_server_leaf_dpid = self.server_leaf_dpids[x]
                
            return cur_spine_dpid_upper, cur_spine_dpid_lower, cur_server_leaf_dpid
        elif self.is_lp:
            cur_spine_dpid_upper = -1
            cur_spine_dpid_lower = -1
            cur_server_leaf_dpid = -1

            max_spine_packets_per_sec = 0.0
            max_server_leaf_packets_per_sec = 0.0
            # self.logger.info("PASS")
            for x in range(len(self.spine_dpids) / 2 ):
                spine_active_ports_len = len(self.spine_active_ports[self.spine_dpids[x]])
                # self.logger.info("SPINE")
                # self.logger.info(spine_active_ports_len)
                if spine_active_ports_len == 0:
                    cur_spine_dpid_upper = self.spine_dpids[x + len(self.spine_dpids) / 2]
                    cur_spine_dpid_lower = self.spine_dpids[x]
                    break
                else:                    
                    packets_per_sec = self.calculate_speed(self.spine_dpids[x], spine_active_ports_len)
                    # self.logger.info(packets_per_sec)
                    if max_spine_packets_per_sec <= packets_per_sec:
                        max_spine_packets_per_sec = packets_per_sec
                        cur_spine_dpid_upper = self.spine_dpids[x + len(self.spine_dpids) / 2]
                        cur_spine_dpid_lower = self.spine_dpids[x]

            for x in range(len(self.server_leaf_dpids)):
                # self.logger.info("SERVER")
                server_leaf_active_ports_len = len(self.server_leaf_active_ports[self.server_leaf_dpids[x]])
                # self.logger.info(server_leaf_active_ports_len)
                if server_leaf_active_ports_len == 0:
                    cur_server_leaf_dpid = self.server_leaf_dpids[x]
                    break
                else:
                    packets_per_sec = self.calculate_speed(self.server_leaf_dpids[x], server_leaf_active_ports_len)
                    # self.logger.info(packets_per_sec)
                    if max_server_leaf_packets_per_sec <= packets_per_sec:
                        max_server_leaf_packets_per_sec = packets_per_sec
                        cur_server_leaf_dpid = self.server_leaf_dpids[x]
                
            return cur_spine_dpid_upper, cur_spine_dpid_lower, cur_server_leaf_dpid
        elif self.is_rb:
            r = randint(0, self.max_weight)
            for i, x in enumerate(self.spine_weights):
                if r <= x["w"]:
                    cur_spine_dpid_upper = self.spine_dpids[x["i"] + len(self.spine_dpids) / 2]
                    cur_spine_dpid_lower = self.spine_dpids[x["i"]]
                    self.spine_weights[i]["w"] /= 2
                    if self.spine_weights[i]["w"] == 1:
                        for w in range(len(self.spine_weights)):
                            self.spine_weights[w]["w"] *= self.max_weight
                    break
            r = randint(0, self.max_weight)
            for i, x in enumerate(self.server_leaf_weights):
                if r <= x["w"]:
                    cur_server_leaf_dpid = self.server_leaf_dpids[x["i"]]
                    self.server_leaf_weights[i]["w"] /= 2
                    if self.server_leaf_weights[i]["w"] == 1:
                        for w in range(len(self.server_leaf_weights)):
                            self.server_leaf_weights[w]["w"] *= self.server_leaf_weights
                    break
            self.spine_weights.sort(reverse=True)
            self.server_leaf_weights.sort(reverse=True)
            return cur_spine_dpid_upper, cur_spine_dpid_lower, cur_server_leaf_dpid
        elif self.is_ih:
            if src_ip == None:
                self.logger.info("ERROR: Source IP not available!")
            # Java's hashCode() method implementation
            hash_code = 0
            for x in src_ip:
                char_code = ord(x)
                hash_code = ((hash_code << 5) - hash_code) + char_code
                # hash_code = hash_code & 0xFFFFFFFF # Converting to 32-bit unsigned integer
                hash_code = ctypes.c_int32(hash_code).value

            if self.ip_hash_to_spine_dpid.get(hash_code, None) == None:
                # Round-robin
                self.ip_hash_to_spine_dpid[hash_code] = self.spine_dpids[self.cur_spine_index]
                self.ip_hash_to_server_leaf_dpid[hash_code] = self.server_leaf_dpids[self.cur_server_leaf_index]

                self.cur_server_leaf_index += 1
                if self.cur_server_leaf_index == len(self.server_leaf_dpids):
                    self.cur_server_leaf_index = 0

                self.cur_spine_index += 1
                if self.cur_spine_index == len(self.spine_dpids) / 2:
                    self.cur_spine_index = 0
                self.logger.info("IP hash added!")

            cur_spine_dpid_upper = self.  ip_hash_to_spine_dpid[hash_code] + len(self.spine_dpids) / 2
            cur_spine_dpid_lower = self.ip_hash_to_spine_dpid[hash_code]
            cur_server_leaf_dpid = self.ip_hash_to_server_leaf_dpid[hash_code]

            return cur_spine_dpid_upper, cur_spine_dpid_lower, cur_server_leaf_dpid

        return None, None, None

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        # If you hit this you might want to increase
        # the "miss_send_length" of your switch
        if ev.msg.msg_len < ev.msg.total_len:
            self.logger.debug("packet truncated: only %s of %s bytes",
                              ev.msg.msg_len, ev.msg.total_len)
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            # ignore lldp packet
            return
        dst = eth.dst
        src = eth.src

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
        self.port_to_mac.setdefault(dpid, {})

        # self.logger.info("packet in %s %s %s %s %s", dpid, src, dst, in_port, eth.ethertype)

        # learn a mac address to avoid FLOOD next time.
        if src != self.controller_mac:
            self.mac_to_port[dpid][src] = in_port
            self.port_to_mac[dpid][in_port] = src

        if eth.ethertype == ether_types.ETH_TYPE_ARP:
            # print("It's ARP")           
            arp_header = pkt.get_protocols(arp.arp)[0]
            if self.is_init:
                self.arp_init(datapath, arp_header, in_port)
                return
            if arp_header.dst_ip == self.controller_ip and arp_header.opcode == arp.ARP_REQUEST:
                self.send_arp(datapath, arp_header.src_ip, arp_header.src_mac, in_port, arp.ARP_REPLY)
            return

        if eth.ethertype == ether_types.ETH_TYPE_IP:
            ip_header = pkt.get_protocols(ipv4.ipv4)[0]

            # print(str(dpid) + " " + str(ip_header.proto))

            cookie = random.randint(0, 0xffffffffffffffff)
            idle_timeout = 10
            if self.is_lp or self.is_lb:
                idle_timeout = 10

            if ip_header.dst == self.controller_ip and ip_header.proto == in_proto.IPPROTO_TCP:
                tcp_header = pkt.get_protocols(tcp.tcp)[0]

                if ip_header.src in self.client_ips:

                    if self.l4_port_to_ip.get(tcp_header.src_port, None) != None:
                        return
                
                    if self.is_ih:
                        cur_spine_dpid_upper, cur_spine_dpid_lower, cur_server_leaf_dpid = self.select_next_dpids(ip_header.src)
                    else:
                        cur_spine_dpid_upper, cur_spine_dpid_lower, cur_server_leaf_dpid = self.select_next_dpids()
                    
                    if cur_spine_dpid_upper == None or cur_spine_dpid_lower == None or cur_server_leaf_dpid == None:
                        self.logger.info("ERROR: dpids not collected while installing flow")
                        return

                    if self.is_lc or self.is_lb or self.is_lp:
                        self.spine_active_ports[cur_spine_dpid_lower].append(tcp_header.src_port)
                        self.server_leaf_active_ports[cur_server_leaf_dpid].append(tcp_header.src_port)
                        # print(self.spine_active_ports)

                    self.l4_port_to_ip[tcp_header.src_port] = []
                    self.l4_port_to_ip[tcp_header.src_port].append(cur_spine_dpid_upper)
                    self.l4_port_to_ip[tcp_header.src_port].append(cur_spine_dpid_lower)
                    self.l4_port_to_ip[tcp_header.src_port].append(dpid)

                    # print(self.l4_port_to_ip)

                    cur_target_server_mac =  self.dpid_to_mac[cur_server_leaf_dpid]

                    # Datapaths to use
                    spine_datapath_upper = self.datapaths[cur_spine_dpid_upper]
                    spine_datapath_lower = self.datapaths[cur_spine_dpid_lower]
                    server_leaf_datapath = self.datapaths[cur_server_leaf_dpid]

                    # Ports from datapaths to use
                    out_port_client_leaf_to_spine_upper = self.mac_to_port[dpid][cur_spine_dpid_upper]
                    out_port_spine_lower_to_server_leaf = self.mac_to_port[cur_spine_dpid_lower][cur_server_leaf_dpid]
                    out_port_server_leaf_to_server = self.mac_to_port[cur_server_leaf_dpid][cur_target_server_mac]
                    out_port_spine_upper_to_spine_lower = self.mac_to_port[cur_spine_dpid_upper][cur_spine_dpid_lower]

                    self.logger.info("Current Path: " + src + " -> " + str(dpid) + " -> " + str(cur_spine_dpid_upper) +
                        " -> " + str(cur_spine_dpid_lower) + " -> " + str(cur_server_leaf_dpid) + " -> " + self.dpid_to_mac[cur_server_leaf_dpid])

                    # Client Switch -> Spine Switch Upper

                    match_send = parser.OFPMatch(
                        # in_port=in_port,
                        eth_type=eth.ethertype,
                        eth_src=src,
                        eth_dst=dst,
                        ip_proto=ip_header.proto,
                        ipv4_src=ip_header.src,
                        ipv4_dst=ip_header.dst,
                        tcp_src=tcp_header.src_port,
                        tcp_dst=tcp_header.dst_port
                    )

                    actions = [parser.OFPActionOutput(out_port_client_leaf_to_spine_upper)]
                    self.add_flow(datapath, match_send, actions, idle_timeout=idle_timeout, cookie=cookie)

                    # Spine Switch Upper -> Spine Switch Lower

                    actions = [parser.OFPActionOutput(out_port_spine_upper_to_spine_lower)]
                    self.add_flow(spine_datapath_upper, match_send, actions, idle_timeout=idle_timeout, cookie=cookie)

                    # Spine Switch Lower -> Server Switch

                    actions = [parser.OFPActionOutput(out_port_spine_lower_to_server_leaf)]
                    self.add_flow(spine_datapath_lower, match_send, actions, idle_timeout=idle_timeout, cookie=cookie)

                    # Server Switch -> Server Host

                    actions = [
                        parser.OFPActionSetField(ipv4_src=self.controller_ip),
                        parser.OFPActionSetField(eth_dst=cur_target_server_mac),
                        parser.OFPActionSetField(ipv4_dst=self.mac_to_ip[cur_target_server_mac]),
                        parser.OFPActionOutput(out_port_server_leaf_to_server)
                    ]
                    self.add_flow(server_leaf_datapath, match_send, actions, idle_timeout=idle_timeout, cookie=cookie)

                elif ip_header.src in self.server_ips:

                    cur_spine_dpid_upper = self.l4_port_to_ip[tcp_header.dst_port][0]
                    cur_spine_dpid_lower = self.l4_port_to_ip[tcp_header.dst_port][1]
                    cur_client_leaf_dpid = self.l4_port_to_ip[tcp_header.dst_port][2]

                    del self.l4_port_to_ip[tcp_header.dst_port]

                    cur_target_client_mac =  self.dpid_to_mac[cur_client_leaf_dpid]

                    # Datapaths to use
                    spine_datapath_upper = self.datapaths[cur_spine_dpid_upper]
                    spine_datapath_lower = self.datapaths[cur_spine_dpid_lower]
                    client_leaf_datapath = self.datapaths[cur_client_leaf_dpid]

                    # Ports from datapaths to use
                    out_port_server_leaf_to_spine_lower = self.mac_to_port[dpid][cur_spine_dpid_lower]
                    out_port_spine_lower_to_spine_upper = self.mac_to_port[cur_spine_dpid_lower][cur_spine_dpid_upper]
                    out_port_spine_upper_to_client_leaf = self.mac_to_port[cur_spine_dpid_upper][cur_client_leaf_dpid]
                    out_port_client_leaf_to_client = self.mac_to_port[cur_client_leaf_dpid][cur_target_client_mac]

                    match_receive = parser.OFPMatch(
                        eth_type=eth.ethertype,
                        eth_src=src,
                        eth_dst=dst,
                        ip_proto=ip_header.proto,
                        ipv4_src=ip_header.src,
                        ipv4_dst=ip_header.dst,
                        tcp_src=tcp_header.src_port,
                        tcp_dst=tcp_header.dst_port
                    )

                    # Server Switch -> Spine Switch Lower (Reverse)

                    actions = [parser.OFPActionOutput(out_port_server_leaf_to_spine_lower)]
                    self.add_flow(datapath, match_receive, actions, idle_timeout=idle_timeout, cookie=cookie)

                    # Spine Switch Lower -> Spine Switch Upper (Reverse)

                    actions = [parser.OFPActionOutput(out_port_spine_lower_to_spine_upper)]
                    self.add_flow(spine_datapath_lower, match_receive, actions, idle_timeout=idle_timeout, cookie=cookie)

                    # Spine Switch Upper -> Client Switch (Reverse)

                    actions = [parser.OFPActionOutput(out_port_spine_upper_to_client_leaf)]
                    self.add_flow(spine_datapath_upper, match_receive, actions, idle_timeout=idle_timeout, cookie=cookie)

                    # Client Switch -> Client Host (Reverse)

                    actions = [                        
                        parser.OFPActionSetField(ipv4_src=self.controller_ip),
                        parser.OFPActionSetField(eth_dst=cur_target_client_mac),
                        parser.OFPActionSetField(ipv4_dst=self.mac_to_ip[cur_target_client_mac]),
                        # parser.OFPActionSetField(eth_src=self.controller_mac),
                        parser.OFPActionOutput(out_port_client_leaf_to_client)
                    ]

                    self.add_flow(client_leaf_datapath, match_receive, actions, idle_timeout=idle_timeout, cookie=cookie)



            if ip_header.dst == self.controller_ip and ip_header.proto == in_proto.IPPROTO_UDP:

                udp_header = pkt.get_protocols(udp.udp)[0]

                if ip_header.src in self.client_ips:

                    if self.l4_port_to_ip.get(udp_header.src_port, None) != None:
                        return
                
                    if self.is_ih:
                        cur_spine_dpid_upper, cur_spine_dpid_lower, cur_server_leaf_dpid = self.select_next_dpids(ip_header.src)
                    else:
                        cur_spine_dpid_upper, cur_spine_dpid_lower, cur_server_leaf_dpid = self.select_next_dpids()
                    
                    if cur_spine_dpid_upper == None or cur_spine_dpid_lower == None or cur_server_leaf_dpid == None:
                        self.logger.info("ERROR: dpids not collected while installing flow")
                        return

                    if self.is_lc or self.is_lb or self.is_lp:
                        self.spine_active_ports[cur_spine_dpid_lower].append(udp_header.src_port)
                        # print("cur_server_leaf_dpid: " + str(cur_server_leaf_dpid))
                        self.server_leaf_active_ports[cur_server_leaf_dpid].append(udp_header.src_port)
                        # print(self.spine_active_ports)

                    self.l4_port_to_ip[udp_header.src_port] = []
                    self.l4_port_to_ip[udp_header.src_port].append(cur_spine_dpid_upper)
                    self.l4_port_to_ip[udp_header.src_port].append(cur_spine_dpid_lower)
                    self.l4_port_to_ip[udp_header.src_port].append(dpid)

                    cur_target_server_mac =  self.dpid_to_mac[cur_server_leaf_dpid]

                    # Datapaths to use
                    spine_datapath_upper = self.datapaths[cur_spine_dpid_upper]
                    spine_datapath_lower = self.datapaths[cur_spine_dpid_lower]
                    server_leaf_datapath = self.datapaths[cur_server_leaf_dpid]

                    # Ports from datapaths to use
                    out_port_client_leaf_to_spine_upper = self.mac_to_port[dpid][cur_spine_dpid_upper]
                    out_port_spine_lower_to_server_leaf = self.mac_to_port[cur_spine_dpid_lower][cur_server_leaf_dpid]
                    out_port_server_leaf_to_server = self.mac_to_port[cur_server_leaf_dpid][cur_target_server_mac]
                    out_port_spine_upper_to_spine_lower = self.mac_to_port[cur_spine_dpid_upper][cur_spine_dpid_lower]

                    # self.logger.info(str(dpid) + " udp_port: " + str(udp_header.src_port))
                    # self.logger.info(str(dpid) + " : " + str(eth.ethertype) + ", " + str(src) + ", " + str(dst) + ", " + str(ip_header.proto) +
                    #     ", " + str(ip_header.src) + ", " + str(ip_header.dst) + ", " + str(udp_header.src_port) + ", " + str(udp_header.dst_port))
                    
                    self.count_in += 1
                    self.logger.info(str(self.count_in) + " Current Path: " + src + " -> " + str(dpid) + " -> " + str(cur_spine_dpid_upper) +
                        " -> " + str(cur_spine_dpid_lower) + " -> " + str(cur_server_leaf_dpid) + " -> " + self.dpid_to_mac[cur_server_leaf_dpid])

                    

                    match_send = parser.OFPMatch(
                        # in_port=in_port,
                        eth_type=eth.ethertype,
                        eth_src=src,
                        eth_dst=dst,
                        ip_proto=ip_header.proto,
                        ipv4_src=ip_header.src,
                        ipv4_dst=ip_header.dst,
                        udp_src=udp_header.src_port,
                        udp_dst=udp_header.dst_port
                    )

                    # Client Switch -> Spine Switch Upper
                    actions = [parser.OFPActionOutput(out_port_client_leaf_to_spine_upper)]
                    self.add_flow(datapath, match_send, actions, idle_timeout=idle_timeout, cookie=cookie)

                    # Spine Switch Upper -> Spine Switch Lower

                    actions = [parser.OFPActionOutput(out_port_spine_upper_to_spine_lower)]
                    self.add_flow(spine_datapath_upper, match_send, actions, idle_timeout=idle_timeout, cookie=cookie)

                    # Spine Switch Lower -> Server Switch

                    actions = [parser.OFPActionOutput(out_port_spine_lower_to_server_leaf)]
                    self.add_flow(spine_datapath_lower, match_send, actions, idle_timeout=idle_timeout, cookie=cookie)

                    # Server Switch -> Server Host

                    actions = [
                        parser.OFPActionSetField(ipv4_src=self.controller_ip),
                        parser.OFPActionSetField(eth_dst=cur_target_server_mac),
                        parser.OFPActionSetField(ipv4_dst=self.mac_to_ip[cur_target_server_mac]),
                        parser.OFPActionOutput(out_port_server_leaf_to_server)
                    ]
                    self.add_flow(server_leaf_datapath, match_send, actions, idle_timeout=idle_timeout, cookie=cookie)

                elif ip_header.src in self.server_ips:

                    cur_spine_dpid_upper = self.l4_port_to_ip[udp_header.dst_port][0]
                    cur_spine_dpid_lower = self.l4_port_to_ip[udp_header.dst_port][1]
                    cur_client_leaf_dpid = self.l4_port_to_ip[udp_header.dst_port][2]

                    # del self.l4_port_to_ip[udp_header.dst_port]

                    cur_target_client_mac =  self.dpid_to_mac[cur_client_leaf_dpid]

                    # Datapaths to use
                    spine_datapath_upper = self.datapaths[cur_spine_dpid_upper]
                    spine_datapath_lower = self.datapaths[cur_spine_dpid_lower]
                    client_leaf_datapath = self.datapaths[cur_client_leaf_dpid]

                    # Ports from datapaths to use
                    out_port_server_leaf_to_spine_lower = self.mac_to_port[dpid][cur_spine_dpid_lower]
                    out_port_spine_lower_to_spine_upper = self.mac_to_port[cur_spine_dpid_lower][cur_spine_dpid_upper]
                    out_port_spine_upper_to_client_leaf = self.mac_to_port[cur_spine_dpid_upper][cur_client_leaf_dpid]
                    out_port_client_leaf_to_client = self.mac_to_port[cur_client_leaf_dpid][cur_target_client_mac]

                    match_receive = parser.OFPMatch(
                        eth_type=eth.ethertype,
                        eth_src=src,
                        eth_dst=dst,
                        ip_proto=ip_header.proto,
                        ipv4_src=ip_header.src,
                        ipv4_dst=ip_header.dst,
                        udp_src=udp_header.src_port,
                        udp_dst=udp_header.dst_port
                    )

                    # Server Switch -> Spine Switch Lower (Reverse)

                    actions = [parser.OFPActionOutput(out_port_server_leaf_to_spine_lower)]
                    self.add_flow(datapath, match_receive, actions, idle_timeout=idle_timeout, cookie=cookie)

                    # Spine Switch Lower -> Spine Switch Upper (Reverse)

                    actions = [parser.OFPActionOutput(out_port_spine_lower_to_spine_upper)]
                    self.add_flow(spine_datapath_lower, match_receive, actions, idle_timeout=idle_timeout, cookie=cookie)

                    # Spine Switch Upper -> Client Switch (Reverse)

                    actions = [parser.OFPActionOutput(out_port_spine_upper_to_client_leaf)]
                    self.add_flow(spine_datapath_upper, match_receive, actions, idle_timeout=idle_timeout, cookie=cookie)

                    # Client Switch -> Client Host (Reverse)

                    actions = [
                        parser.OFPActionSetField(ipv4_src=self.controller_ip),
                        parser.OFPActionSetField(eth_dst=cur_target_client_mac),  
                        parser.OFPActionSetField(ipv4_dst=self.mac_to_ip[cur_target_client_mac]),
                        # parser.OFPActionSetField(eth_src=self.controller_mac),
                        parser.OFPActionOutput(out_port_client_leaf_to_client)
                    ]

                    self.add_flow(client_leaf_datapath, match_receive, actions, idle_timeout=idle_timeout, cookie=cookie)
            return
           



        # if dst in self.mac_to_port[dpid]:
        #     out_port = self.mac_to_port[dpid][dst]
        # else:
        #     out_port = ofproto.OFPP_FLOOD

        # actions = [parser.OFPActionOutput(out_port)]

        # # install a flow to avoid packet_in next time
        # if out_port != ofproto.OFPP_FLOOD:
        #     match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
        #     # verify if we have a valid buffer_id, if yes avoid to send both
        #     # flow_mod & packet_out
        #     if msg.buffer_id != ofproto.OFP_NO_BUFFER:
        #         self.add_flow(datapath, 1, match, actions, msg.buffer_id)
        #         return
        #     else:
        #         self.add_flow(datapath, 1, match, actions)
        # data = None
        # if msg.buffer_id == ofproto.OFP_NO_BUFFER:
        #     data = msg.data

        # out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
        #                           in_port=in_port, actions=actions, data=data)
        # datapath.send_msg(out)

    # @set_ev_cls(event.EventSwitchEnter)
    # def get_topology_data(self, ev):

        # hosts_list = get_host(self,None)
        # switch_list = get_switch(self, None)
        # switches=[switch.dp.id for switch in switch_list]

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def flow_removed_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto

        dpid = datapath.id

        if self.is_lc or self.is_lb or self.is_lp:

            if self.is_tcp:
                tcp_src = msg.match.get('tcp_src')
            elif self.is_udp:
                udp_src = msg.match.get('udp_src')

            if dpid in self.spine_dpids:
                if self.spine_active_ports.get(dpid, None) != None:
                    try:
                        if self.is_tcp:
                            self.spine_active_ports[dpid].remove(tcp_src)
                        elif self.is_udp:
                            self.spine_active_ports[dpid].remove(udp_src)
                    except ValueError:
                        return
                else:
                    return
            elif dpid in self.server_leaf_dpids:
                if self.server_leaf_active_ports.get(dpid, None) != None:
                    try:
                        if self.is_tcp:
                            self.server_leaf_active_ports[dpid].remove(tcp_src)
                        elif self.is_udp:
                            self.server_leaf_active_ports[dpid].remove(udp_src)
                    except ValueError:
                        return
                else:
                    return


            # self.logger.info(self.spine_active_ports)
            # self.logger.info(self.server_leaf_active_ports)

        # if msg.reason == ofproto.OFPRR_IDLE_TIMEOUT:
        #     reason = 'IDLE TIMEOUT'
        # elif msg.reason == ofproto.OFPRR_HARD_TIMEOUT:
        #     reason = 'HARD TIMEOUT'
        # elif msg.reason == ofproto.OFPRR_DELETE:
        #     reason = 'DELETE'
        # elif msg.reason == ofproto.OFPRR_GROUP_DELETE:
        #     reason = 'GROUP DELETE'
        # else:
        #     reason = 'unknown'

        # self.logger.info('OFPFlowRemoved received: '
        #                   'cookie=%d priority=%d reason=%s table_id=%d '
        #                   'duration_sec=%d duration_nsec=%d '
        #                   'idle_timeout=%d hard_timeout=%d '
        #                   'packet_count=%d byte_count=%d match.fields=%s',
        #                   msg.cookie, msg.priority, reason, msg.table_id,
        #                   msg.duration_sec, msg.duration_nsec,
        #                   msg.idle_timeout, msg.hard_timeout,
        #                   msg.packet_count, msg.byte_count, msg.match)
