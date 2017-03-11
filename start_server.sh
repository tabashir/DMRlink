#!/usr/bin/env bash

DEBUG=true


function debug_echo {
  if [ "$DEBUG" == 'true' ]; then
	echo "DEBUG: " $1
  fi
}

function check_progs {
  for name in $1; do
    if [ ! `which $name` ]; then
      echo -e "ERROR: $name - is not installed correctly, refer to README" 
      exit 1
    fi
  done
}

# System packages
check_progs "python2 pip virtualenv multilog"

# Python packages
source dmr_libs/bin/activate
check_progs "supervisord "

set -e
ABS_PATH=$(readlink -f $0)
BASE_PATH=$(dirname "$ABS_PATH")

debug_echo "ABS_PATH: $ABS_PATH"
debug_echo "BASE_PATH: $BASE_PATH"

cd $BASE_PATH
supervisord -c supervisord.conf -n

