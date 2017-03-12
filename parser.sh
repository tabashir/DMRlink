#!/usr/bin/env bash

while true; do
  ls -1t logs/dmr.log.* |head -n1 | xargs cat > webroot/current.log
  cat logs/dmr.log >> webroot/current.log
  cat webroot/current.log |grep Regist | sort |uniq > webroot/registrations.log
  cat webroot/current.log |grep --no-group-separator -A1 'RADIO ID' |grep --no-group-separator -B1 'IP Address' |sed 'N;s/\n/ /' |sort |uniq > webroot/dmrs.log
  tail -n 50 webroot/current.log > webroot/system.log

  sleep 3

done
