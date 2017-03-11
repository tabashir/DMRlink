#!/usr/bin/env python
#
# This work is licensed under the Creative Commons Attribution-ShareAlike
# 3.0 Unported License.To view a copy of this license, visit
# http://creativecommons.org/licenses/by-sa/3.0/ or send a letter to
# Creative Commons, 444 Castro Street, Suite 900, Mountain View,
# California, 94041, USA.

#NOTE: This program uses a configuration file specified on the command line
#      if none is specified, then dmrlink.cfg in the same directory as this
#      file will be tried. Finally, if that does not exist, this process
#      will terminate

from __future__ import print_function

import ConfigParser
import argparse
import sys
import binascii
import csv
import os
import logging
import time
import signal

from logging.config import dictConfig
from hmac import new as hmac_new
from binascii import b2a_hex as h
from hashlib import sha1
from socket import inet_ntoa as IPAddr
from socket import inet_aton as IPHexStr
from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
from twisted.internet import task

__author__ = 'Cortney T. Buffington, N0MJS'
__copyright__ = 'Copyright (c) 2013, 2014 Cortney T. Buffington, N0MJS and the K0USY Group'
__credits__ = 'Adam Fast, KC0YLK, Dave K, and he who wishes not to be named'
__license__ = 'Creative Commons Attribution-ShareAlike 3.0 Unported'
__version__ = '0.3'
__maintainer__ = 'Cort Buffington, N0MJS'
__email__ = 'n0mjs@me.com'
__status__ = 'Production'


parser = argparse.ArgumentParser()
parser.add_argument('-c', '--config', action='store', dest='CFG_FILE', help='/full/path/to/config.file (usually dmrlink.cfg)')

cli_args = parser.parse_args()


#************************************************
#     PARSE THE CONFIG FILE AND BUILD STRUCTURE
#************************************************

NETWORK = {}
networks = {}
config = ConfigParser.ConfigParser()

if not cli_args.CFG_FILE:
    cli_args.CFG_FILE = os.path.dirname(os.path.abspath(__file__))+'/dmrlink.cfg'
try:
    if not config.read(cli_args.CFG_FILE):
        sys.exit('Configuration file \''+cli_args.CFG_FILE+'\' is not a valid configuration file! Exiting...')        
except:    
    sys.exit('Configuration file \''+cli_args.CFG_FILE+'\' is not a valid configuration file! Exiting...')

try:
    for section in config.sections():
        if section == 'GLOBAL':
            # Process GLOBAL items in the configuration
            PATH = config.get(section, 'PATH')

        elif section == 'REPORTS':
            # Process REPORTS items in the configuration
            REPORTS = {
                'REPORT_PEERS': config.getboolean(section, 'REPORT_PEERS'),
                'PEER_REPORT_INC_MODE': config.getboolean(section, 'PEER_REPORT_INC_MODE'),
                'PEER_REPORT_INC_FLAGS': config.getboolean(section, 'PEER_REPORT_INC_FLAGS')
            }

        elif section == 'LOGGER':
            # Process LOGGER items in the configuration
            LOGGER = {
                'LOG_FILE': config.get(section, 'LOG_FILE'),
                'LOG_HANDLERS': config.get(section, 'LOG_HANDLERS'),
                'LOG_LEVEL': config.get(section, 'LOG_LEVEL'),
                'LOG_ROTATE_SIZE_FORMATTER': config.get(section, 'LOG_ROTATE_SIZE_FORMATTER'),
                'LOG_ROTATE_SIZE_BYTES': config.get(section, 'LOG_ROTATE_SIZE_BYTES'),
                'LOG_ROTATE_SIZE_BACKUP_COUNT': config.get(section, 'LOG_ROTATE_SIZE_BACKUP_COUNT'),
                'LOG_ROTATE_TIMER_FORMATTER': config.get(section, 'LOG_ROTATE_TIMER_FORMATTER'),
                'LOG_ROTATE_TIMER_SECONDS': config.get(section, 'LOG_ROTATE_TIMER_SECONDS'),
                'LOG_ROTATE_TIMER_BACKUP_COUNT': config.get(section, 'LOG_ROTATE_TIMER_BACKUP_COUNT')
            }
        else:
            # All other sections define indiviual IPSC Networks we connect to
            # Each IPSC network config will contain the following three sections
            NETWORK.update({section: {'LOCAL': {}, 'MASTER': {}, 'PEERS': {}}})
            # LOCAL means we need to know this stuff to be a peer in the network
            NETWORK[section]['LOCAL'].update({
                # In case we want to keep config, but not actually connect to the network
                'ENABLED':      config.getboolean(section, 'ENABLED'),
                
                # These items are used to create the MODE byte
                'PEER_OPER':    config.getboolean(section, 'PEER_OPER'),
                'IPSC_MODE':    config.get(section, 'IPSC_MODE'),
                'TS1_LINK':     config.getboolean(section, 'TS1_LINK'),
                'TS2_LINK':     config.getboolean(section, 'TS2_LINK'),
                'MODE': '',
                
                # These items are used to create the multi-byte FLAGS field
                'AUTH_ENABLED': config.getboolean(section, 'AUTH_ENABLED'),
                'CSBK_CALL':    config.getboolean(section, 'CSBK_CALL'),
                'RCM':          config.getboolean(section, 'RCM'),
                'CON_APP':      config.getboolean(section, 'CON_APP'),
                'XNL_CALL':     config.getboolean(section, 'XNL_CALL'),
                'XNL_MASTER':   config.getboolean(section, 'XNL_MASTER'),
                'DATA_CALL':    config.getboolean(section, 'DATA_CALL'),
                'VOICE_CALL':   config.getboolean(section, 'VOICE_CALL'),
                'MASTER_PEER':  config.getboolean(section, 'MASTER_PEER'),
                'FLAGS': '',
                
                # Things we need to know to connect and be a peer in this IPSC
                'RADIO_ID':     hex(int(config.get(section, 'RADIO_ID')))[2:].rjust(8,'0').decode('hex'),
                'PORT':         config.getint(section, 'PORT'),
                'ALIVE_TIMER':  config.getint(section, 'ALIVE_TIMER'),
                'MAX_MISSED':   config.getint(section, 'MAX_MISSED'),
                'AUTH_KEY':     (config.get(section, 'AUTH_KEY').rjust(40,'0')).decode('hex'),
                'NUM_PEERS': 0,
                })
            # Master means things we need to know about the master peer of the network
            NETWORK[section]['MASTER'].update({
                'RADIO_ID': '\x00\x00\x00\x00',
                'MODE': '\x00',
                'MODE_DECODE': '',
                'FLAGS': '\x00\x00\x00\x00',
                'FLAGS_DECODE': '',
                'STATUS': {
                    'CONNECTED':               False,
                    'PEER_LIST':               False,
                    'KEEP_ALIVES_SENT':        0,
                    'KEEP_ALIVES_MISSED':      0,
                    'KEEP_ALIVES_OUTSTANDING': 0,
                    'KEEP_ALIVES_RECEIVED':    0,
                    'KEEP_ALIVE_RX_TIME':      0
                    },
                'IP': '',
                'PORT': ''
                })
            if not NETWORK[section]['LOCAL']['MASTER_PEER']:
                NETWORK[section]['MASTER'].update({
                    'IP': config.get(section, 'MASTER_IP'),
                    'PORT': config.getint(section, 'MASTER_PORT')
                })
            
            # Temporary locations for building MODE and FLAG data
            MODE_BYTE = 0
            FLAG_1 = 0
            FLAG_2 = 0
            
            # Construct and store the MODE field
            if NETWORK[section]['LOCAL']['PEER_OPER']:
                MODE_BYTE |= 1 << 6
            if NETWORK[section]['LOCAL']['IPSC_MODE'] == 'ANALOG':
                MODE_BYTE |= 1 << 4
            elif NETWORK[section]['LOCAL']['IPSC_MODE'] == 'DIGITAL':
                MODE_BYTE |= 1 << 5
            if NETWORK[section]['LOCAL']['TS1_LINK']:
                MODE_BYTE |= 1 << 3
            else:
                MODE_BYTE |= 1 << 2
            if NETWORK[section]['LOCAL']['TS2_LINK']:
                MODE_BYTE |= 1 << 1
            else:
                MODE_BYTE |= 1 << 0
            NETWORK[section]['LOCAL']['MODE'] = chr(MODE_BYTE)

            # Construct and store the FLAGS field
            if NETWORK[section]['LOCAL']['CSBK_CALL']:
                FLAG_1 |= 1 << 7  
            if NETWORK[section]['LOCAL']['RCM']:
                FLAG_1 |= 1 << 6
            if NETWORK[section]['LOCAL']['CON_APP']:
                FLAG_1 |= 1 << 5
            if NETWORK[section]['LOCAL']['XNL_CALL']:
                FLAG_2 |= 1 << 7    
            if NETWORK[section]['LOCAL']['XNL_CALL'] and NETWORK[section]['LOCAL']['XNL_MASTER']:
                FLAG_2 |= 1 << 6
            elif NETWORK[section]['LOCAL']['XNL_CALL'] and not NETWORK[section]['LOCAL']['XNL_MASTER']:
                FLAG_2 |= 1 << 5
            if NETWORK[section]['LOCAL']['AUTH_ENABLED']:
                FLAG_2 |= 1 << 4
            if NETWORK[section]['LOCAL']['DATA_CALL']:
                FLAG_2 |= 1 << 3
            if NETWORK[section]['LOCAL']['VOICE_CALL']:
                FLAG_2 |= 1 << 2
            if NETWORK[section]['LOCAL']['MASTER_PEER']:
                FLAG_2 |= 1 << 0
            NETWORK[section]['LOCAL']['FLAGS'] = '\x00\x00'+chr(FLAG_1)+chr(FLAG_2)
except:
    sys.exit('Could not parse configuration file, exiting...')


#************************************************
#     CONFIGURE THE SYSTEM LOGGER
#************************************************

dictConfig({
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
    },
    'formatters': {
        'verbose': {
            'format': '%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s'
        },
        'timed': {
            'format': '%(levelname)s %(asctime)s %(message)s'
        },
        'simple': {
            'format': '%(levelname)s %(message)s'
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple'
        },
        'console-timed': {
            'class': 'logging.StreamHandler',
            'formatter': 'timed'
        },
        'file': {
            'class': 'logging.FileHandler',
            'formatter': 'simple',
            'filename': LOGGER['LOG_FILE'],
        },
        'file-timed': {
            'class': 'logging.FileHandler',
            'formatter': 'timed',
            'filename': LOGGER['LOG_FILE'],
        },
        'rotate-size': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOGGER['LOG_FILE'],
            'formatter': LOGGER['LOG_ROTATE_SIZE_FORMATTER'],
            'maxBytes': LOGGER['LOG_ROTATE_SIZE_BYTES'],
            'backupCount': LOGGER['LOG_ROTATE_SIZE_BACKUP_COUNT'],
        },
        'rotate-timer': {
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': LOGGER['LOG_FILE'],
            'formatter': LOGGER['LOG_ROTATE_TIMER_FORMATTER'],
            'when': 'S',
            'interval': int(LOGGER['LOG_ROTATE_TIMER_SECONDS']),
            'backupCount': LOGGER['LOG_ROTATE_TIMER_BACKUP_COUNT'],
        },
        'syslog': {
            'class': 'logging.handlers.SysLogHandler',
            'formatter': 'verbose',
        }
    },
    'loggers': {
        'dmrlink': {
            'handlers': LOGGER['LOG_HANDLERS'].split(','),
            'level': LOGGER['LOG_LEVEL'],
            'propagate': True,
        }
    }
})
logger = logging.getLogger('dmrlink')


#************************************************
#     IMPORTING OTHER FILES - '#include'
#************************************************

# Import IPSC message types and version information
#
try:
    from ipsc.ipsc_message_types import *
except ImportError:
    sys.exit('IPSC message types file not found or invalid')

# Import IPSC flag mask values
#
try:
    from ipsc.ipsc_mask import *
except ImportError:
    sys.exit('IPSC mask values file not found or invalid')

# Import the Alias files for numeric ids. This is split to save
# time making lookups in one huge dictionary
#
curdir= os.path.dirname(__file__)
subscriber_ids = {}
peer_ids = {}
talkgroup_ids = {}

try:
    with open(PATH+'subscriber_ids.csv', 'rU') as subscriber_ids_csv:
        subscribers = csv.reader(subscriber_ids_csv, dialect='excel', delimiter=',')
        for row in subscribers:
            subscriber_ids[int(row[1])] = (row[0])
except ImportError:
    logger.warning('subscriber_ids.csv not found: Subscriber aliases will not be available')
    
try:
    with open(PATH+'peer_ids.csv', 'rU') as peer_ids_csv:
        peers = csv.reader(peer_ids_csv, dialect='excel', delimiter=',')
        for row in peers:
            peer_ids[int(row[1])] = (row[0])
except ImportError:
    logger.warning('peer_ids.csv not found: Peer aliases will not be available')

try:
    with open(PATH+'talkgroup_ids.csv', 'rU') as talkgroup_ids_csv:
        talkgroups = csv.reader(talkgroup_ids_csv, dialect='excel', delimiter=',')
        for row in talkgroups:
            talkgroup_ids[int(row[1])] = (row[0])
except ImportError:
    logger.warning('talkgroup_ids.csv not found: Talkgroup aliases will not be available')


#************************************************
#     UTILITY FUNCTIONS FOR INTERNAL USE
#************************************************

# Create a 2 byte hex string from an integer
#
def hex_str_2(_int_id):
    try:
        return hex(_int_id)[2:].rjust(4,'0').decode('hex')
    except TypeError:
        logger.error('hex_str_2: invalid integer length')
     
# Create a 3 byte hex string from an integer
#
def hex_str_3(_int_id):
    try:
        return hex(_int_id)[2:].rjust(6,'0').decode('hex')
    except TypeError:
        logger.error('hex_str_3: invalid integer length')

# Create a 4 byte hex string from an integer
#
def hex_str_4(_int_id):
    try:
        return hex(_int_id)[2:].rjust(8,'0').decode('hex')
    except TypeError:
        logger.error('hex_str_4: invalid integer length')

# Convert a hex string to an int (radio ID, etc.)
#
def int_id(_hex_string):
    return int(h(_hex_string), 16)

# Re-Write Source Radio-ID (DMR NAT)
#
def dmr_nat(_data, _src_id, _nat_id):
    _data = _data.replace(_src_id, _nat_id)
    return _data

# Lookup text data for numeric IDs
#
def get_info(_id, _dict):
    if _id in _dict:
        return _dict[_id]
    return _id

# Determine if the provided peer ID is valid for the provided network 
#
def valid_peer(_peer_list, _peerid):
    if _peerid in _peer_list:
        return True        
    return False


# Determine if the provided master ID is valid for the provided network
#
def valid_master(_network, _peerid):
    if NETWORK[_network]['MASTER']['RADIO_ID'] == _peerid:
        return True     
    else:
        return False
        
            
# Accept a complete packet, ready to be sent, and send it to all active peers + master in an IPSC
#
def send_to_ipsc(_target, _packet):
    _network = NETWORK[_target]
    _network_instance = networks[_target]
    _peers = _network['PEERS']
    
    # Send to the Master
    if _network['MASTER']['STATUS']['CONNECTED']:
        _network_instance.transport.write(_packet, (_network['MASTER']['IP'], _network['MASTER']['PORT']))
    # Send to each connected Peer
    for peer in _peers.keys():
        if _peers[peer]['STATUS']['CONNECTED']:
            _network_instance.transport.write(_packet, (_peers[peer]['IP'], _peers[peer]['PORT']))

    
# De-register a peer from an IPSC by removing it's information
#
def de_register_peer(_network, _peerid):
    # Iterate for the peer in our data
    if _peerid in NETWORK[_network]['PEERS'].keys():
        del NETWORK[_network]['PEERS'][_peerid]
        logger.info('(%s) Peer De-Registration Requested for: %s', _network, h(_peerid))
        return
    else:
        logger.warning('(%s) Peer De-Registration Requested for: %s, but we don\'t have a listing for this peer', _network, h(_peerid))
        pass


# Process the MODE byte in registration/peer list packets for determining master and peer capabilities
#
def process_mode_byte(_hex_mode):
    _mode = int(h(_hex_mode), 16)
    
    # Determine whether or not the peer is operational
    _peer_op = bool(_mode & PEER_OP_MSK)    
    # Determine whether or not timeslot 1 is linked
    _ts1 = bool(_mode & IPSC_TS1_MSK)  
    # Determine whether or not timeslot 2 is linked
    _ts2 = bool(_mode & IPSC_TS2_MSK)
     
    # Determine the operational mode of the peer
    if _mode & PEER_MODE_MSK == PEER_MODE_MSK:
        _peer_mode = 'UNKNOWN'
    elif not _mode & PEER_MODE_MSK:
        _peer_mode = 'NO_RADIO'
    elif _mode & PEER_MODE_ANALOG:
        _peer_mode = 'ANALOG'
    elif _mode & PEER_MODE_DIGITAL:
        _peer_mode = 'DIGITAL'
    
    return {
        'PEER_OP': _peer_op,
        'PEER_MODE': _peer_mode,
        'TS_1': _ts1,
        'TS_2': _ts2
        }


# Process the FLAGS bytes in registration replies for determining what services are available
#
def process_flags_bytes(_hex_flags):
    _byte3 = int(h(_hex_flags[2]), 16)
    _byte4 = int(h(_hex_flags[3]), 16)
    
    _csbk       = bool(_byte3 & CSBK_MSK)
    _rpt_mon    = bool(_byte3 & RPT_MON_MSK)
    _con_app    = bool(_byte3 & CON_APP_MSK)
    _xnl_con    = bool(_byte4 & XNL_STAT_MSK)
    _xnl_master = bool(_byte4 & XNL_MSTR_MSK)
    _xnl_slave  = bool(_byte4 & XNL_SLAVE_MSK)
    _auth       = bool(_byte4 & PKT_AUTH_MSK)
    _data       = bool(_byte4 & DATA_CALL_MSK)
    _voice      = bool(_byte4 & VOICE_CALL_MSK)
    _master     = bool(_byte4 & MSTR_PEER_MSK)
    
    return {
        'CSBK': _csbk,
        'RCM': _rpt_mon,
        'CON_APP': _con_app,
        'XNL_CON': _xnl_con,
        'XNL_MASTER': _xnl_master,
        'XNL_SLAVE': _xnl_slave,
        'AUTH': _auth,
        'DATA': _data,
        'VOICE': _voice,
        'MASTER': _master
        } 
        
        
# Take a received peer list and the network it belongs to, process and populate the
# data structure in my_ipsc_config with the results, and return a simple list of peers.
#
def process_peer_list(_data, _network):
    # Create a temporary peer list to track who we should have in our list -- used to find old peers we should remove.
    _temp_peers = []
    # Determine the length of the peer list for the parsing iterator
    _peer_list_length = int(h(_data[5:7]), 16)
    # Record the number of peers in the data structure... we'll use it later (11 bytes per peer entry)
    NETWORK[_network]['LOCAL']['NUM_PEERS'] = _peer_list_length/11
    logger.info('(%s) Peer List Received from Master: %s peers in this IPSC', _network, NETWORK[_network]['LOCAL']['NUM_PEERS'])
    
    # Iterate each peer entry in the peer list. Skip the header, then pull the next peer, the next, etc.
    for i in range(7, _peer_list_length +7, 11):
        # Extract various elements from each entry...
        _hex_radio_id = (_data[i:i+4])
        _hex_address  = (_data[i+4:i+8])
        _ip_address   = IPAddr(_hex_address)
        _hex_port     = (_data[i+8:i+10])
        _port         = int(h(_hex_port), 16)
        _hex_mode     = (_data[i+10:i+11])
     
        # Add this peer to a temporary PeerID list - used to remove any old peers no longer with us
        _temp_peers.append(_hex_radio_id)
        
        # This is done elsewhere for the master too, so we use a separate function
        _decoded_mode = process_mode_byte(_hex_mode)

        # If this entry was NOT already in our list, add it.
        if _hex_radio_id not in NETWORK[_network]['PEERS'].keys():
            NETWORK[_network]['PEERS'][_hex_radio_id] = {
                'IP':          _ip_address, 
                'PORT':        _port, 
                'MODE':        _hex_mode,            
                'MODE_DECODE': _decoded_mode,
                'FLAGS': '',
                'FLAGS_DECODE': '',
                'STATUS': {
                    'CONNECTED':               False,
                    'KEEP_ALIVES_SENT':        0,
                    'KEEP_ALIVES_MISSED':      0,
                    'KEEP_ALIVES_OUTSTANDING': 0,
                    'KEEP_ALIVES_RECEIVED':    0,
                    'KEEP_ALIVE_RX_TIME':      0
                    }
                }
        logger.debug('(%s) Peer Added: %s', _network, NETWORK[_network]['PEERS'][_hex_radio_id])
    
    # Finally, check to see if there's a peer already in our list that was not in this peer list
    # and if so, delete it.
    for peer in NETWORK[_network]['PEERS'].keys():
        if peer not in _temp_peers:
            de_register_peer(_network, peer)
            logger.warning('(%s) Peer Deleted (not in new peer list): %s', _network, h(peer))

# Build a peer list - used when a peer registers, re-regiseters or times out
#
def build_peer_list(_peers):
    concatenated_peers = ''
    for peer in _peers:
        hex_ip = IPHexStr(_peers[peer]['IP'])
        hex_port = hex_str_2(_peers[peer]['PORT'])
        mode = _peers[peer]['MODE']        
        concatenated_peers += peer + hex_ip + hex_port + mode
    
    peer_list = hex_str_2(len(concatenated_peers)) + concatenated_peers
    return peer_list

# Gratuitous print-out of the peer list.. Pretty much debug stuff.
#
def print_peer_list(_network):
    _peers = NETWORK[_network]['PEERS']
    
    _status = NETWORK[_network]['MASTER']['STATUS']['PEER_LIST']
    #print('Peer List Status for {}: {}' .format(_network, _status))
    
    if _status and not NETWORK[_network]['PEERS']:
        print('We are the only peer for: %s' % _network)
        print('')
        return
             
    print('Peer List for: %s' % _network)
    for peer in _peers.keys():
        _this_peer = _peers[peer]
        _this_peer_stat = _this_peer['STATUS']
        
        if peer == NETWORK[_network]['LOCAL']['RADIO_ID']:
            me = '(self)'
        else:
            me = ''
             
        print('\tRADIO ID: {} {}' .format(int(h(peer), 16), me))
        print('\t\tIP Address: {}:{}' .format(_this_peer['IP'], _this_peer['PORT']))
        if _this_peer['MODE_DECODE'] and REPORTS['PEER_REPORT_INC_MODE']:
            print('\t\tMode Values:')
            for name, value in _this_peer['MODE_DECODE'].items():
                print('\t\t\t{}: {}' .format(name, value))
        if _this_peer['FLAGS_DECODE'] and REPORTS['PEER_REPORT_INC_FLAGS']:
            print('\t\tService Flags:')
            for name, value in _this_peer['FLAGS_DECODE'].items():
                print('\t\t\t{}: {}' .format(name, value))
        print('\t\tStatus: {},  KeepAlives Sent: {},  KeepAlives Outstanding: {},  KeepAlives Missed: {}' .format(_this_peer_stat['CONNECTED'], _this_peer_stat['KEEP_ALIVES_SENT'], _this_peer_stat['KEEP_ALIVES_OUTSTANDING'], _this_peer_stat['KEEP_ALIVES_MISSED']))
        print('\t\t                KeepAlives Received: {},  Last KeepAlive Received at: {}' .format(_this_peer_stat['KEEP_ALIVES_RECEIVED'], _this_peer_stat['KEEP_ALIVE_RX_TIME']))
        
    print('')
 
# Gratuitous print-out of Master info.. Pretty much debug stuff.
#
def print_master(_network):
    if NETWORK[_network]['LOCAL']['MASTER_PEER']:
        print('DMRlink is the Master for %s' % _network)
    else:
        _master = NETWORK[_network]['MASTER']
        print('Master for %s' % _network)
        print('\tRADIO ID: {}' .format(int(h(_master['RADIO_ID']), 16)))
        if _master['MODE_DECODE'] and REPORTS['PEER_REPORT_INC_MODE']:
            print('\t\tMode Values:')
            for name, value in _master['MODE_DECODE'].items():
                print('\t\t\t{}: {}' .format(name, value))
        if _master['FLAGS_DECODE'] and REPORTS['PEER_REPORT_INC_FLAGS']:
            print('\t\tService Flags:')
            for name, value in _master['FLAGS_DECODE'].items():
                print('\t\t\t{}: {}' .format(name, value))
        print('\t\tStatus: {},  KeepAlives Sent: {},  KeepAlives Outstanding: {},  KeepAlives Missed: {}' .format(_master['STATUS']['CONNECTED'], _master['STATUS']['KEEP_ALIVES_SENT'], _master['STATUS']['KEEP_ALIVES_OUTSTANDING'], _master['STATUS']['KEEP_ALIVES_MISSED']))
        print('\t\t                KeepAlives Received: {},  Last KeepAlive Received at: {}' .format(_master['STATUS']['KEEP_ALIVES_RECEIVED'], _master['STATUS']['KEEP_ALIVE_RX_TIME']))

# Shut ourselves down gracefully with the IPSC peers.
#
def handler(_signal, _frame):
    logger.info('*** DMRLINK IS TERMINATING WITH SIGNAL %s ***', str(_signal))
    
    for network in networks:
        this_ipsc = networks[network]
        logger.info('De-Registering from IPSC %s', network)
        de_reg_req_pkt = this_ipsc.hashed_packet(this_ipsc._local['AUTH_KEY'], this_ipsc.DE_REG_REQ_PKT)
        send_to_ipsc(network, de_reg_req_pkt)
    
    reactor.stop()

#************************************************
#********                             ***********
#********    IPSC Network 'Engine'    ***********
#********                             ***********
#************************************************

#************************************************
#     Base Class (used nearly all of the time)
#************************************************


class IPSC(DatagramProtocol):
    
    #************************************************
    #     IPSC INSTANCE INSTANTIATION
    #************************************************
    
    # Modify the initializer to set up our environment and build the packets
    # we need to maintain connections
    #
    def __init__(self, *args, **kwargs):
        if len(args) == 1:
            # Housekeeping: create references to the configuration and status data for this IPSC instance.
            # Some configuration objects that are used frequently and have lengthy names are shortened
            # such as (self._master_sock) expands to (self._config['MASTER']['IP'], self._config['MASTER']['PORT']).
            # Note that many of them reference each other... this is the Pythonic way.
            #
            self._network = args[0]
            self._config = NETWORK[self._network]
            #
            self._local = self._config['LOCAL']
            self._local_id = self._local['RADIO_ID']
            #
            self._master = self._config['MASTER']
            self._master_stat = self._master['STATUS']
            self._master_sock = self._master['IP'], self._master['PORT']
            #
            self._peers = self._config['PEERS']
            #
            # This is a regular list to store peers for the IPSC. At times, parsing a simple list is much less
            # Spendy than iterating a list of dictionaries... Maybe I'll find a better way in the future. Also
            # We have to know when we have a new peer list, so a variable to indicate we do (or don't)
            #
            args = ()
            
            # Packet 'constructors' - builds the necessary control packets for this IPSC instance.
            # This isn't really necessary for anything other than readability (reduction of code golf)
            #
            # General Items
            self.TS_FLAGS               = (self._local['MODE'] + self._local['FLAGS'])
            #
            # Peer Link Maintenance Packets 
            self.MASTER_REG_REQ_PKT     = (MASTER_REG_REQ + self._local_id + self.TS_FLAGS + IPSC_VER)
            self.MASTER_ALIVE_PKT       = (MASTER_ALIVE_REQ + self._local_id + self.TS_FLAGS + IPSC_VER)
            self.PEER_LIST_REQ_PKT      = (PEER_LIST_REQ + self._local_id)
            self.PEER_REG_REQ_PKT       = (PEER_REG_REQ + self._local_id + IPSC_VER)
            self.PEER_REG_REPLY_PKT     = (PEER_REG_REPLY + self._local_id + IPSC_VER)
            self.PEER_ALIVE_REQ_PKT     = (PEER_ALIVE_REQ + self._local_id + self.TS_FLAGS)
            self.PEER_ALIVE_REPLY_PKT   = (PEER_ALIVE_REPLY + self._local_id + self.TS_FLAGS)
            #
            # Master Link Maintenance Packets
            # self.MASTER_REG_REPLY_PKT   is not static and must be generated when it is sent
            self.MASTER_ALIVE_REPLY_PKT = (MASTER_ALIVE_REPLY + self._local_id + self.TS_FLAGS + IPSC_VER)
            self.PEER_LIST_REPLY_PKT    = (PEER_LIST_REPLY + self._local_id)
            #
            # General Link Maintenance Packets
            self.DE_REG_REQ_PKT         = (DE_REG_REQ + self._local_id)
            self.DE_REG_REPLY_PKT       = (DE_REG_REPLY + self._local_id)
            #
            logger.info('(%s) IPSC Instance Created', self._network)
        else:
            # If we didn't get called correctly, log it!
            #
            logger.error('(%s) IPSC Instance Could Not be Created... Exiting', self._network)
            sys.exit()
        
        # Choose which set of fucntions to use - authenticated or not
        if self._local['AUTH_ENABLED']:
            self.hashed_packet = self.auth_hashed_packet
            self.strip_hash = self.auth_strip_hash
            self.validate_auth = self.auth_validate_auth
        else:
            self.hashed_packet = self.unauth_hashed_packet
            self.strip_hash = self.unauth_strip_hash
            self.validate_auth = self.unauth_validate_auth


    #************************************************
    #     CALLBACK FUNCTIONS FOR USER PACKET TYPES
    #************************************************

    def call_mon_status(self, _network, _data):
        logger.debug('(%s) Repeater Call Monitor Origin Packet Received: %s',_network, h(_data))
    
    def call_mon_rpt(self, _network, _data):
        logger.debug('(%s) Repeater Call Monitor Repeating Packet Received: %s', _network, h(_data))
    
    def call_mon_nack(self, _network, _data):
        logger.debug('(%s) Repeater Call Monitor NACK Packet Received: %s', _network, h(_data))
    
    def xcmp_xnl(self, _network, _data):
        logger.debug('(%s) XCMP/XNL Packet Received: %s', _network, h(_data))
        
    def repeater_wake_up(self, _network, _data):
        logger.debug('(%s) Repeater Wake-Up Packet Received: %s', _network, h(_data))
        
    def group_voice(self, _network, _src_sub, _dst_sub, _ts, _end, _peerid, _data):
        logger.debug('(%s) Group Voice Packet Received From: %s, IPSC Peer %s, Destination %s', _network, h(_src_sub), h(_peerid), h(_dst_sub))
    
    def private_voice(self, _network, _src_sub, _dst_sub, _ts, _end, _peerid, _data):
        logger.debug('(%s) Private Voice Packet Received From: %s, IPSC Peer %s, Destination %s', _network, h(_src_sub), h(_peerid), h(_dst_sub))
    
    def group_data(self, _network, _src_sub, _dst_sub, _ts, _end, _peerid, _data):    
        logger.debug('(%s) Group Data Packet Received From: %s, IPSC Peer %s, Destination %s', _network, h(_src_sub), h(_peerid), h(_dst_sub))
    
    def private_data(self, _network, _src_sub, _dst_sub, _ts, _end, _peerid, _data):    
        logger.debug('(%s) Private Data Packet Received From: %s, IPSC Peer %s, Destination %s', _network, h(_src_sub), h(_peerid), h(_dst_sub))

    def unknown_message(self, _network, _packettype, _peerid, _data):
        _packettype = h(_packettype)
        logger.error('(%s) Unknown message type encountered\n\tPacket Type: %s\n\tFrom: %s\n\tPacket: %s', _network, h(_packettype), h(_peerid), h(_data))


    #************************************************
    #     IPSC SPECIFIC MAINTENANCE FUNCTIONS
    #************************************************

    # Reset the outstanding keep-alive counter for _peerid...
    # Used when receiving acks OR when we see traffic from a repeater, since they ignore keep-alives when transmitting
    #
    def reset_keep_alive(self, _peerid):
        if _peerid in self._peers.keys():
            self._peers[_peerid]['STATUS']['KEEP_ALIVES_OUTSTANDING'] = 0
            self._peers[_peerid]['STATUS']['KEEP_ALIVE_RX_TIME'] = int(time.time())
        if _peerid == self._master['RADIO_ID']:
            self._master_stat['KEEP_ALIVES_OUTSTANDING'] = 0

    #
    # NEXT THREE FUNCITONS ARE FOR AUTHENTICATED PACKETS
    #

    # Take a packet to be SENT, calculate auth hash and return the whole thing
    #
    def auth_hashed_packet(self, _key, _data):
        _hash = binascii.a2b_hex((hmac_new(_key,_data,sha1)).hexdigest()[:20])
        return _data + _hash
    
    # Remove the hash from a packet and return the payload
    #
    def auth_strip_hash(self, _data):
        return _data[:-10]
    
    # Take a RECEIVED packet, calculate the auth hash and verify authenticity
    #
    def auth_validate_auth(self, _key, _data):
        _payload = self.strip_hash(_data)
        _hash = _data[-10:]
        _chk_hash = binascii.a2b_hex((hmac_new(_key,_payload,sha1)).hexdigest()[:20])   

        if _chk_hash == _hash:
            return True
        else:
            return False
    
    #
    # NEXT THREE FUNCITONS ARE FOR UN-AUTHENTICATED PACKETS
    #
    
    # There isn't a hash to build, so just return the data
    #
    def unauth_hashed_packet(self, _key, _data):
        return _data
    
    # Remove the hash from a packet and return the payload... except don't
    #
    def unauth_strip_hash(self, _data):
        return _data
    
    # Everything is validated, so just return True
    #
    def unauth_validate_auth(self, _key, _data):
        return True


    #************************************************
    #     TIMED LOOP - CONNECTION MAINTENANCE
    #************************************************

    # Timed loop initialization (called by the twisted reactor)
    #       
    def startProtocol(self):
        # Timed loops for:
        #   IPSC connection establishment and maintenance
        #   Reporting/Housekeeping
        #
        if not self._local['MASTER_PEER']:
            self._peer_maintenance = task.LoopingCall(self.peer_maintenance_loop)
            self._peer_maintenance_loop = self._peer_maintenance.start(self._local['ALIVE_TIMER'])
        #
        if self._local['MASTER_PEER']:
            self._master_maintenance = task.LoopingCall(self.master_maintenance_loop)
            self._master_maintenance_loop = self._master_maintenance.start(self._local['ALIVE_TIMER'])
        #
        self._reporting = task.LoopingCall(self.reporting_loop)
        self._reporting_loop = self._reporting.start(10)
    
    
    # Timed loop used for reporting IPSC status
    #
    def reporting_loop(self):
        # Right now, without this, we really don't know anything is happening.
        logger.debug('(%s) Periodic Reporting Loop Started', self._network)
        if REPORTS['REPORT_PEERS']:
            print_master(self._network)
            print_peer_list(self._network)
    
    # Timed loop used for IPSC connection Maintenance when we are the MASTER
    #    
    def master_maintenance_loop(self):
        logger.debug('(%s) MASTER Connection Maintenance Loop Started', self._network)
        update_time = int(time.time())
        
        for peer in self._peers.keys():
            keep_alive_delta = update_time - self._peers[peer]['STATUS']['KEEP_ALIVE_RX_TIME']
            logger.debug('(%s) Time Since Last KeepAlive Request from Peer %s: %s seconds', self._network, h(peer), keep_alive_delta)
          
            if keep_alive_delta > 120:
                de_register_peer(self._network, peer)
                peer_list_packet = self.PEER_LIST_REPLY_PKT + build_peer_list(self._peers)
                peer_list_packet = self.hashed_packet(self._local['AUTH_KEY'], peer_list_packet)
                send_to_ipsc(self._network, peer_list_packet)
                logger.warning('(%s) Timeout Exceeded for Peer %s, De-registering', self._network, h(peer))
    
    
    # Timed loop used for IPSC connection Maintenance when we are a PEER
    #
    def peer_maintenance_loop(self):
        logger.debug('(%s) PEER Connection Maintenance Loop Started', self._network)

        # If the master isn't connected, we have to do that before we can do anything else!
        #
        if not self._master_stat['CONNECTED']:
            reg_packet = self.hashed_packet(self._local['AUTH_KEY'], self.MASTER_REG_REQ_PKT)
            self.transport.write(reg_packet, self._master_sock)
            logger.info('(%s) Registering with the Master', self._network)
        
        # Once the master is connected, we have to send keep-alives.. and make sure we get them back
        elif self._master_stat['CONNECTED']:
            # Send keep-alive to the master
            master_alive_packet = self.hashed_packet(self._local['AUTH_KEY'], self.MASTER_ALIVE_PKT)
            self.transport.write(master_alive_packet, self._master_sock)
            logger.debug('(%s) Keep Alive Sent to the Master', self._network)
            
            # If we had a keep-alive outstanding by the time we send another, mark it missed.
            if (self._master_stat['KEEP_ALIVES_OUTSTANDING']) > 0:
                self._master_stat['KEEP_ALIVES_MISSED'] += 1
                logger.info('(%s) Master Keep-Alive Missed', self._network)
            
            # If we have missed too many keep-alives, de-register the master and start over.
            if self._master_stat['KEEP_ALIVES_OUTSTANDING'] >= self._local['MAX_MISSED']:
                self._master_stat['CONNECTED'] = False
                self._master_stat['KEEP_ALIVES_OUTSTANDING'] = 0
                logger.error('(%s) Maximum Master Keep-Alives Missed -- De-registering the Master', self._network)
            
            # Update our stats before we move on...
            self._master_stat['KEEP_ALIVES_SENT'] += 1
            self._master_stat['KEEP_ALIVES_OUTSTANDING'] += 1
            
        else:
            # This is bad. If we get this message, we need to reset the state and try again
            logger.error('->> (%s) Master in UNKOWN STATE:%s:%s', self._network, self._master_sock)
            self._master_stat['CONNECTED'] = False
        
        
        # If the master is connected and we don't have a peer-list yet....
        #
        if (self._master_stat['CONNECTED'] == True) and (self._master_stat['PEER_LIST'] == False):
            # Ask the master for a peer-list
            if self._local['NUM_PEERS']:
                peer_list_req_packet = self.hashed_packet(self._local['AUTH_KEY'], self.PEER_LIST_REQ_PKT)
                self.transport.write(peer_list_req_packet, self._master_sock)
                logger.info('(%s), No Peer List - Requesting One From the Master', self._network)
            else:
                self._master_stat['PEER_LIST'] = True
                logger.debug('(%s), Skip asking for a Peer List, we are the only Peer', self._network)


        # If we do have a peer-list, we need to register with the peers and send keep-alives...
        #
        if self._master_stat['PEER_LIST']:
            # Iterate the list of peers... so we do this for each one.
            for peer in self._peers.keys():

                # We will show up in the peer list, but shouldn't try to talk to ourselves.
                if peer == self._local_id:
                    continue

                # If we haven't registered to a peer, send a registration
                if not self._peers[peer]['STATUS']['CONNECTED']:
                    peer_reg_packet = self.hashed_packet(self._local['AUTH_KEY'], self.PEER_REG_REQ_PKT)
                    self.transport.write(peer_reg_packet, (self._peers[peer]['IP'], self._peers[peer]['PORT']))
                    logger.info('(%s) Registering with Peer %s', self._network, int_id(peer))

                # If we have registered with the peer, then send a keep-alive
                elif self._peers[peer]['STATUS']['CONNECTED']:
                    peer_alive_req_packet = self.hashed_packet(self._local['AUTH_KEY'], self.PEER_ALIVE_REQ_PKT)
                    self.transport.write(peer_alive_req_packet, (self._peers[peer]['IP'], self._peers[peer]['PORT']))
                    logger.debug('(%s) Keep-Alive Sent to the Peer %s', self._network, int_id(peer))

                    # If we have a keep-alive outstanding by the time we send another, mark it missed.
                    if self._peers[peer]['STATUS']['KEEP_ALIVES_OUTSTANDING'] > 0:
                        self._peers[peer]['STATUS']['KEEP_ALIVES_MISSED'] += 1
                        logger.info('(%s) Peer Keep-Alive Missed for %s', self._network, int_id(peer))

                    # If we have missed too many keep-alives, de-register the peer and start over.
                    if self._peers[peer]['STATUS']['KEEP_ALIVES_OUTSTANDING'] >= self._local['MAX_MISSED']:
                        self._peers[peer]['STATUS']['CONNECTED'] = False
                        #del peer   # Becuase once it's out of the dictionary, you can't use it for anything else.
                        logger.warning('(%s) Maximum Peer Keep-Alives Missed -- De-registering the Peer: %s', self._network, int_id(peer))
                    
                    # Update our stats before moving on...
                    self._peers[peer]['STATUS']['KEEP_ALIVES_SENT'] += 1
                    self._peers[peer]['STATUS']['KEEP_ALIVES_OUTSTANDING'] += 1
    
    
    # For public display of information, etc. - anything not part of internal logging/diagnostics
    #
    def _notify_event(self, network, event, info):
        """
            Used internally whenever an event happens that may be useful to notify the outside world about.
            Arguments:
                network: string, network name to look up in config
                event:   string, basic description
                info:    dict, in the interest of accomplishing as much as possible without code changes.
                         The dict will typically contain the ID of a peer so the origin of the event is known.
        """
        pass
    


    #************************************************
    #     MESSAGE RECEIVED - TAKE ACTION
    #************************************************

    # Actions for received packets by type: For every packet received, there are some things that we need to do:
    #   Decode some of the info
    #   Check for auth and authenticate the packet
    #   Strip the hash from the end... we don't need it anymore
    #
    # Once they're done, we move on to the processing or callbacks for each packet type.
    #
    # Callbacks are iterated in the order of "more likely" to "less likely" to reduce processing time
    #
    def datagramReceived(self, data, (host, port)):
        _packettype = data[0:1]
        _peerid     = data[1:5]
        
        # AUTHENTICATE THE PACKET
        if not self.validate_auth(self._local['AUTH_KEY'], data):
            logger.warning('(%s) AuthError: IPSC packet failed authentication. Type %s: Peer ID: %s', self._network, h(_packettype), int_id(_peerid))
            return
            
        # REMOVE SHA-1 AUTHENTICATION HASH: WE NO LONGER NEED IT
        data = self.strip_hash(data)

        # PACKETS THAT WE RECEIVE FROM ANY VALID PEER OR VALID MASTER
        if _packettype in ANY_PEER_REQUIRED:
            if not(valid_master(self._network, _peerid) == False or valid_peer(self._peers.keys(), _peerid) == False):
                logger.warning('(%s) PeerError: Peer not in peer-list: %s', self._network, int_id(_peerid))
                return
                
            # ORIGINATED BY SUBSCRIBER UNITS - a.k.a someone transmitted
            if _packettype in USER_PACKETS:
                # Extract commonly used items from the packet header
                _src_sub    = data[6:9]
                _dst_sub    = data[9:12]
                _call       = int_id(data[17:18])
                _ts         = bool(_call & TS_CALL_MSK)
                _end        = bool(_call & END_MSK)

                # User Voice and Data Call Types:
                if _packettype == GROUP_VOICE:
                    self.reset_keep_alive(_peerid)
                    self.group_voice(self._network, _src_sub, _dst_sub, _ts, _end, _peerid, data)
                    self._notify_event(self._network, 'group_voice', {'peer': int_id(_peerid)})
                    return
            
                elif _packettype == PVT_VOICE:
                    self.reset_keep_alive(_peerid)
                    self.private_voice(self._network, _src_sub, _dst_sub, _ts, _end, _peerid, data)
                    self._notify_event(self._network, 'private_voice', {'peer': int_id(_peerid)})
                    return
                    
                elif _packettype == GROUP_DATA:
                    self.reset_keep_alive(_peerid)
                    self.group_data(self._network, _src_sub, _dst_sub, _ts, _end, _peerid, data)
                    self._notify_event(self._network, 'group_data', {'peer': int_id(_peerid)})
                    return
                    
                elif _packettype == PVT_DATA:
                    self.reset_keep_alive(_peerid)
                    self.private_data(self._network, _src_sub, _dst_sub, _ts, _end, _peerid, data)
                    self._notify_event(self._network, 'private_voice', {'peer': int_id(_peerid)})
                    return
                return
                
            # MOTOROLA XCMP/XNL CONTROL PROTOCOL: We don't process these (yet)   
            elif _packettype == XCMP_XNL:
                self.xcmp_xnl(self._network, data)
                return
            
            # ORIGINATED BY PEERS, NOT IPSC MAINTENANCE: Call monitoring is all we've found here so far 
            elif _packettype == CALL_MON_STATUS:
                self.call_mon_status(self._network, data)
                return
                
            elif _packettype == CALL_MON_RPT:
                self.call_mon_rpt(self._network, data)
                return
                
            elif _packettype == CALL_MON_NACK:
                self.call_mon_nack(self._network, data)
                return
                
            # IPSC CONNECTION MAINTENANCE MESSAGES
            elif _packettype == DE_REG_REQ:
                de_register_peer(self._network, _peerid)
                logger.warning('(%s) Peer De-Registration Request From: %s', self._network, int_id(_peerid))
                return
            
            elif _packettype == DE_REG_REPLY:
                logger.warning('(%s) Peer De-Registration Reply From: %s', self._network, int_id(_peerid))
                return
                
            elif _packettype == RPT_WAKE_UP:
                self.repeater_wake_up(self._network, data)
                logger.debug('(%s) Repeater Wake-Up Packet From: %s', self._network, int_id(_peerid))
                return
            return

        #
        # THE FOLLOWING PACKETS ARE RECEIVED ONLY IF WE ARE OPERATING AS A PEER
        #
        
        # ONLY ACCEPT FROM A PREVIOUSLY VALIDATED PEER
        if _packettype in PEER_REQUIRED:
            if not valid_peer(self._peers.keys(), _peerid):
                logger.warning('(%s) PeerError: Peer %s not in peer-list', self._network, int_id(_peerid))
                return
            
            # REQUESTS FROM PEERS: WE MUST REPLY IMMEDIATELY FOR IPSC MAINTENANCE
            if _packettype == PEER_ALIVE_REQ:
                _hex_mode      = (data[5])
                _hex_flags     = (data[6:10])
                _decoded_mode  = process_mode_byte(_hex_mode)
                _decoded_flags = process_flags_bytes(_hex_flags)
                
                self._peers[_peerid]['MODE'] = _hex_mode
                self._peers[_peerid]['MODE_DECODE'] = _decoded_mode
                self._peers[_peerid]['FLAGS'] = _hex_flags
                self._peers[_peerid]['FLAGS_DECODE'] = _decoded_flags
                # Generate a hashed packet from our template and send it.
                peer_alive_reply_packet = self.hashed_packet(self._local['AUTH_KEY'], self.PEER_ALIVE_REPLY_PKT)
                self.transport.write(peer_alive_reply_packet, (host, port))
                self.reset_keep_alive(_peerid)  # Might as well reset our own counter, we know it's out there...
                logger.debug('(%s) Keep-Alive reply sent to Peer %s', self._network, int_id(_peerid))
                return
                                
            elif _packettype == PEER_REG_REQ:
                peer_reg_reply_packet = self.hashed_packet(self._local['AUTH_KEY'], self.PEER_REG_REPLY_PKT)
                self.transport.write(peer_reg_reply_packet, (host, port))
                logger.info('(%s) Peer Registration Request From: %s', self._network, int_id(_peerid))
                return
                
            # ANSWERS FROM REQUESTS WE SENT TO PEERS: WE DO NOT REPLY
            elif _packettype == PEER_ALIVE_REPLY:
                self.reset_keep_alive(_peerid)
                self._peers[_peerid]['STATUS']['KEEP_ALIVES_RECEIVED'] += 1
                self._peers[_peerid]['STATUS']['KEEP_ALIVE_RX_TIME'] = int(time.time())
                logger.debug('(%s) Keep-Alive Reply (we sent the request) Received from Peer %s', self._network, int_id(_peerid))
                return                

            elif _packettype == PEER_REG_REPLY:
                if _peerid in self._peers.keys():
                    self._peers[_peerid]['STATUS']['CONNECTED'] = True
                    logger.info('(%s) Registration Reply From: %s', self._network, int_id(_peerid))
                return
            return
            
        
        # PACKETS ONLY ACCEPTED FROM OUR MASTER
        
        # PACKETS WE ONLY ACCEPT IF WE HAVE FINISHED REGISTERING WITH OUR MASTER
        if _packettype in MASTER_REQUIRED:
            if not valid_master(self._network, _peerid):
                logger.warning('(%s) MasterError: %s is not the master peer', self._network, int_id(_peerid))
                return
            
            # ANSWERS FROM REQUESTS WE SENT TO THE MASTER: WE DO NOT REPLY    
            if _packettype == MASTER_ALIVE_REPLY:
                self.reset_keep_alive(_peerid)
                self._master['STATUS']['KEEP_ALIVES_RECEIVED'] += 1
                self._master['STATUS']['KEEP_ALIVE_RX_TIME'] = int(time.time())
                logger.debug('(%s) Keep-Alive Reply (we sent the request) Received from the Master %s', self._network, int_id(_peerid))
                return
            
            elif _packettype == PEER_LIST_REPLY:
                NETWORK[self._network]['MASTER']['STATUS']['PEER_LIST'] = True
                if len(data) > 18:
                    process_peer_list(data, self._network)
                logger.debug('(%s) Peer List Reply Recieved From Master %s', self._network, int_id(_peerid))
                return
            return
            
        
        # THIS MEANS WE HAVE SUCCESSFULLY REGISTERED TO OUR MASTER - RECORD MASTER INFORMATION
        elif _packettype == MASTER_REG_REPLY:
            
            _hex_mode      = data[5]
            _hex_flags     = data[6:10]
            _num_peers     = data[10:12]
            _decoded_mode  = process_mode_byte(_hex_mode)
            _decoded_flags = process_flags_bytes(_hex_flags)
            
            self._local['NUM_PEERS'] = int(h(_num_peers), 16)
            self._master['RADIO_ID'] = _peerid
            self._master['MODE'] = _hex_mode
            self._master['MODE_DECODE'] = _decoded_mode
            self._master['FLAGS'] = _hex_flags
            self._master['FLAGS_DECODE'] = _decoded_flags
            self._master_stat['CONNECTED'] = True
            self._master_stat['KEEP_ALIVES_OUTSTANDING'] = 0
            logger.warning('(%s) Registration response (we requested reg) from the Master %s (%s peers)', self._network, int_id(_peerid), self._local['NUM_PEERS'])
            return
        

        # THE FOLLOWING PACKETS ARE RECEIVED ONLLY IF WE ARE OPERATING AS A MASTER
        
        # REQUESTS FROM PEERS: WE MUST REPLY IMMEDIATELY FOR IPSC MAINTENANCE
        
        # REQUEST TO REGISTER TO THE IPSC
        elif _packettype == MASTER_REG_REQ:
            
            _ip_address    = host
            _port          = port
            _hex_mode      = data[5]
            _hex_flags     = data[6:10]
            _decoded_mode  = process_mode_byte(_hex_mode)
            _decoded_flags = process_flags_bytes(_hex_flags)
            
            self.MASTER_REG_REPLY_PKT = (MASTER_REG_REPLY + self._local_id + self.TS_FLAGS + hex_str_2(self._local['NUM_PEERS']) + IPSC_VER)
            
            master_reg_reply_packet = self.hashed_packet(self._local['AUTH_KEY'], self.MASTER_REG_REPLY_PKT)
            self.transport.write(master_reg_reply_packet, (host, port))
            logger.debug('(%s) Master Registration Packet Received from peer %s', self._network, int_id(_peerid))

            # If this entry was NOT already in our list, add it.
            if _peerid not in self._peers.keys():
                self._peers[_peerid] = {
                    'IP':          _ip_address, 
                    'PORT':        _port, 
                    'MODE':        _hex_mode,            
                    'MODE_DECODE': _decoded_mode,
                    'FLAGS':       _hex_flags,
                    'FLAGS_DECODE': _decoded_flags,
                    'STATUS': {
                        'CONNECTED':               True,
                        'KEEP_ALIVES_SENT':        0,
                        'KEEP_ALIVES_MISSED':      0,
                        'KEEP_ALIVES_OUTSTANDING': 0,
                        'KEEP_ALIVES_RECEIVED':    0,
                        'KEEP_ALIVE_RX_TIME':      int(time.time())
                        }
                    }
            self._local['NUM_PEERS'] = len(self._peers)       
            logger.debug('(%s) Peer Added To Peer List: %s (IPSC now has %s Peers)', self._network, self._peers[_peerid], self._local['NUM_PEERS'])            
            return
          
        # REQUEST FOR A KEEP-ALIVE REPLY (WE KNOW THE PEER IS STILL ALIVE TOO) 
        elif _packettype == MASTER_ALIVE_REQ:
            if _peerid in self._peers.keys():
                self._peers[_peerid]['STATUS']['KEEP_ALIVES_RECEIVED'] += 1
                self._peers[_peerid]['STATUS']['KEEP_ALIVE_RX_TIME'] = int(time.time())
                
                master_alive_reply_packet = self.hashed_packet(self._local['AUTH_KEY'], self.MASTER_ALIVE_REPLY_PKT)
                self.transport.write(master_alive_reply_packet, (host, port))
                
                logger.debug('(%s) Master Keep-Alive Request Received from peer %s', self._network, int_id(_peerid))
            else:
                logger.warning('(%s) Master Keep-Alive Request Received from *UNREGISTERED* peer %s', self._network, int_id(_peerid))
            return
            
        # REQUEST FOR A PEER LIST
        elif _packettype == PEER_LIST_REQ:
            
            if _peerid in self._peers.keys():
                logger.debug('(%s) Peer List Request from peer %s', self._network, int_id(_peerid))
                peer_list_packet = self.PEER_LIST_REPLY_PKT + build_peer_list(self._peers)
                peer_list_packet = self.hashed_packet(self._local['AUTH_KEY'], peer_list_packet)
                send_to_ipsc(self._network, peer_list_packet)
            else:
                logger.warning('(%s) Peer List Request Received from *UNREGISTERED* peer %s', self._network, int_id(_peerid))
            return
            
        
        
        
        # PACKET IS OF AN UNKNOWN TYPE. LOG IT AND IDENTTIFY IT!
        else:
            self.unknown_message(self._network, _packettype, _peerid, data)
            return

    

#************************************************
#      MAIN PROGRAM LOOP STARTS HERE
#************************************************

if __name__ == '__main__':
    logger.info('DMRlink \'dmrlink.py\' (c) 2013, 2014 N0MJS & the K0USY Group - SYSTEM STARTING...')
    
    # Set signal handers so that we can gracefully exit if need be
    for sig in [signal.SIGTERM, signal.SIGINT, signal.SIGQUIT]:
        signal.signal(sig, handler)
    
    networks = {}
    for ipsc_network in NETWORK:
        if NETWORK[ipsc_network]['LOCAL']['ENABLED']:
            networks[ipsc_network] = IPSC(ipsc_network)
            reactor.listenUDP(NETWORK[ipsc_network]['LOCAL']['PORT'], networks[ipsc_network])
    reactor.run()
