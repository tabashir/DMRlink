Setup:
From this folder:

sudo aptitude install daemontools
sudo aptitude install pip
sudo pip install virtualenv

virtualenv dmr_libs
source dmr_libs/bin/activate

pip install twisted
pip install supervisor

check/make config file
check supervisord.conf

check you have csv files
check you have a log folder if you have configured a file logger


run start_server.sh
