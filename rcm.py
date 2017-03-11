#!/usr/bin/env python
#
# This work is licensed under the Creative Commons Attribution-ShareAlike
# 3.0 Unported License.To view a copy of this license, visit
# http://creativecommons.org/licenses/by-sa/3.0/ or send a letter to
# Creative Commons, 444 Castro Street, Suite 900, Mountain View,
# California, 94041, USA.

# This is a sample application that uses the Repeater Call Monitor packets to display events in the IPSC
# NOTE: dmrlink.py MUST BE CONFIGURED TO CONNECT AS A "REPEATER CALL MONITOR" PEER!!!
# ALSO NOTE, I'M NOT DONE MAKING THIS WORK, SO UNTIL THIS MESSAGE IS GONE, DON'T EXPECT GREAT THINGS.

from __future__ import print_function
from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
from twisted.internet import task
from binascii import b2a_hex as h

import datetime
import binascii
import dmrlink
from dmrlink import IPSC, NETWORK, networks, get_info, int_id, subscriber_ids, peer_ids, talkgroup_ids, logger

__author__ = 'Cortney T. Buffington, N0MJS'
__copyright__ = 'Copyright (c) 2013, 2014 Cortney T. Buffington, N0MJS and the K0USY Group'
__credits__ = 'Adam Fast, KC0YLK, Dave K, and he who wishes not to be named'
__license__ = 'Creative Commons Attribution-ShareAlike 3.0 Unported'
__version__ = '0.2a'
__maintainer__ = 'Cort Buffington, N0MJS'
__email__ = 'n0mjs@me.com'
__status__ = 'Production'

try:
    from ipsc.ipsc_message_types import *
except ImportError:
    sys.exit('IPSC message types file not found or invalid')

status = True
rpt = False
nack = False

class rcmIPSC(IPSC):
    
    def __init__(self, *args, **kwargs):
        IPSC.__init__(self, *args, **kwargs)

    #************************************************
    #     CALLBACK FUNCTIONS FOR USER PACKET TYPES
    #************************************************
    #
    def call_mon_status(self, _network, _data):
        if not status:
            return
        _source =   _data[1:5]
        _ipsc_src = _data[5:9]
        _seq_num =  _data[9:13]
        _ts =       _data[13]
        _status =   _data[15] # suspect [14:16] but nothing in leading byte?
        _rf_src =   _data[16:19]
        _rf_tgt =   _data[19:22]
        _type =     _data[22]
        _prio =     _data[23]
        _sec =      _data[24]
        
        _source = get_info(int_id(_source), peer_ids)
        _ipsc_src = get_info(int_id(_ipsc_src), peer_ids)
        _rf_src = get_info(int_id(_rf_src), subscriber_ids)
        
        if _type == '\x4F' or '\x51':
            _rf_tgt = get_info(int_id(_rf_tgt), talkgroup_ids)
        else:
            _rf_tgt = get_info(int_id(_rf_tgt), subscriber_ids)
        
        printAndLog('Call Monitor - Call Status')
        printAndLog('TIME:        ', datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        printAndLog('DATA SOURCE: ', _source)
        printAndLog('IPSC:        ', _network)
        printAndLog('IPSC Source: ', _ipsc_src)
        printAndLog('Timeslot:    ', TS[_ts])
        try:
            printAndLog('Status:      ', STATUS[_status])
        except KeyError:
            printAndLog('Status (unknown): ', h(status))
        try:
            printAndLog('Type:        ', TYPE[_type])
        except KeyError:
            printAndLog('Type (unknown): ', h(_type))
        printAndLog('Source Sub:  ', _rf_src)
        printAndLog('Target Sub:  ', _rf_tgt)
        printAndLog()
    
    def call_mon_rpt(self, _network, _data):
        if not rpt:
            return
        _source    = _data[1:5]
        _ts1_state = _data[5]
        _ts2_state = _data[6]
        
        _source = get_info(int_id(_source), peer_ids)
        
        printAndLog('Call Monitor - Repeater State')
        printAndLog('TIME:         ', datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        printAndLog('DATA SOURCE:  ', _source)
     
        try:
            printAndLog('TS1 State:    ', REPEAT[_ts1_state])
        except KeyError:
            printAndLog('TS1 State (unknown): ', h(_ts1_state))
        try:
            printAndLog('TS2 State:    ', REPEAT[_ts2_state])
        except KeyError:
            printAndLog('TS2 State (unknown): ', h(_ts2_state))
        printAndLog()
            
    def call_mon_nack(self, _network, _data):
        if not nack:
            return
        _source = _data[1:5]
        _nack =   _data[5]
        
        _source = get_info(int_id(_source), peer_ids)
        
        printAndLog('Call Monitor - Transmission NACK')
        printAndLog('TIME:        ', datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        printAndLog('DATA SOURCE: ', _source)
        try:
            printAndLog('NACK Cause:  ', NACK[_nack])
        except KeyError:
            printAndLog('NACK Cause (unknown): ', h(_nack))
        printAndLog()
    
    def repeater_wake_up(self, _network, _data):
        _source = _data[1:5]
        _source_dec = int_id(_source)
        _source_name = get_info(_source_dec, peer_ids)
        #printAndLog('({}) Repeater Wake-Up Packet Received: {} ({})' .format(_network, _source_name, _source_dec))


if __name__ == '__main__':
    logger.info('DMRlink \'rcm.py\' (c) 2013, 2014 N0MJS & the K0USY Group - SYSTEM STARTING...')
    for ipsc_network in NETWORK:
        if NETWORK[ipsc_network]['LOCAL']['ENABLED']:
            networks[ipsc_network] = rcmIPSC(ipsc_network)
            reactor.listenUDP(NETWORK[ipsc_network]['LOCAL']['PORT'], networks[ipsc_network])
    reactor.run()
