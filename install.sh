#!/bin/bash

sudo apt-get update
sudo apt-get install htop
git clone git://github.com/mininet/mininet
git clone git://github.com/osrg/ryu.git

sudo mininet/util/install.sh -nfv
cd ryu
sudo python ./setup.py install
cd ..

sudo apt-get install python-pip -y
sudo pip install webob
sudo pip install tinyrpc
sudo pip install routes
sudo pip install ovs
sudo pip install oslo.config
sudo pip install msgpack
sudo pip install eventlet==0.18.2

cd modified-iperf-2.0.10
sudo apt-get remove iperf -y
sudo ./configure
sudo make
sudo make install
