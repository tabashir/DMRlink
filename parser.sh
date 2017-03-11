#!/usr/bin/env bash

while true; do

  find logs -name dmr.* |xargs cat > webroot/current.log
  cat webroot/current.log |grep Regist | sort |uniq > webroot/system.log
  cat webroot/current.log |grep --no-group-separator -A1 'RADIO ID' |grep --no-group-separator -B1 'IP Address' |sed 'N;s/\n/ /' |sort |uniq > webroot/dmrs.log

  sleep 10

done
