# A Comparative Analysis of Centralized and Distributed Load Balancing in a Software-defined Networking Environment

Performance comparison of centralized load balancing in a star-topology centralized network and distributed load balancing in a Clos network model distributed network.

### Technology Used

This study uses these following tools:

* [Ryu] - component-based SDN framework
* [Python 2.7.6] - programming language used in Ryu controller
* [iPerf 2.0.10] - network performance benchmarking tool
* [Mininet 2.3.0] - network emulator

### Installation

##### Quick Install
* Run install.sh

##### Mininet

* Download Mininet VM image in this link: https://github.com/mininet/mininet/wiki/Mininet-VM-Images
* Run .ovf file using VMWare or VirtualBox

##### Ryu Controller
* Clone Ryu Git repository with this command: git clone git://github.com/osrg/ryu.git
* Open "ryu" folder 
* python ./setup.py install 

##### Modified iPerf
* Open "modified-iperf-2.0.10" folder
* ./configure
* make
* make install

### Testing
* Run main_lb.py: ryu-manager main_lb.py --observe-links
* Set the number of servers, clients and spine switches in topo.py (Line 19-21)
* Run topo.py: sudo mn --custom topo.py --topo mytopo --link tc --controller=remote,port=6633 --mac
* Inside Mininet terminal execute xTerms for servers and clients: xterm h1 h2 ... hn
* Inside xTerm
    * For each server, type: iperf -s -e | tee h<num>.txt for TCP or iperf -s -u -e| tee h<num>.txt for UDP
    * For each client, type ./start_batch_iperf_client h<num> t <parallel> for TCP or ./start_batch_iperf_client h<num> u <parallel> for UDP
* Run get_results.py to get the needed results: python get_results.py

[Ryu]: <https://osrg.github.io/ryu/>
[Python 2.7.6]: <https://www.python.org/download/releases/2.7.6/>
[iPerf 2.0.10]: <https://iperf.fr/iperf-download.php>
[Mininet 2.3.0]: <http://mininet.org/>

