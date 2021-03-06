#!/usr/bin/env python

#
# test_msdp_mesh_topo1.py
# Part of NetDEF Topology Tests
#
# Copyright (C) 2021 by
# Network Device Education Foundation, Inc. ("NetDEF")
#
# Permission to use, copy, modify, and/or distribute this software
# for any purpose with or without fee is hereby granted, provided
# that the above copyright notice and this permission notice appear
# in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND NETDEF DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL NETDEF BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY
# DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
# WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS
# ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE
# OF THIS SOFTWARE.
#

"""
test_msdp_mesh_topo1.py: Test the FRR PIM MSDP mesh groups.
"""

import os
import sys
import json
from functools import partial
import pytest
import socket

# Save the Current Working Directory to find configuration files.
CWD = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(CWD, "../"))

# pylint: disable=C0413
# Import topogen and topotest helpers
from lib import topotest
from lib.topogen import Topogen, TopoRouter, get_topogen
from lib.topolog import logger

# Required to instantiate the topology builder class.
from mininet.topo import Topo

pytestmark = [pytest.mark.bgpd, pytest.mark.ospfd, pytest.mark.pimd]

#
# Test global variables:
# They are used to handle communicating with external application.
#
APP_SOCK_PATH = '/tmp/topotests/apps.sock'
HELPER_APP_PATH = os.path.join(CWD, "../lib/mcast-tester.py")
app_listener = None
app_clients = {}

def listen_to_applications():
    "Start listening socket to connect with applications."
    # Remove old socket.
    try:
        os.unlink(APP_SOCK_PATH)
    except OSError:
        pass

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM, 0)
    sock.bind(APP_SOCK_PATH)
    sock.listen(10)
    global app_listener
    app_listener = sock

def accept_host(host):
    "Accept connection from application running in hosts."
    global app_listener, app_clients
    conn = app_listener.accept()
    app_clients[host] = {
        'fd': conn[0],
        'address': conn[1]
    }

def close_applications():
    "Signal applications to stop and close all sockets."
    global app_listener, app_clients

    # Close listening socket.
    app_listener.close()

    # Remove old socket.
    try:
        os.unlink(APP_SOCK_PATH)
    except OSError:
        pass

    # Close all host connections.
    for host in ["h1", "h2"]:
        if app_clients.get(host) is None:
            continue
        app_clients["h1"]["fd"].close()


class MSDPMeshTopo1(Topo):
    "Test topology builder"

    def build(self, *_args, **_opts):
        "Build function"
        tgen = get_topogen(self)

        # Create 3 routers
        for routern in range(1, 4):
            tgen.add_router("r{}".format(routern))

        switch = tgen.add_switch("s1")
        switch.add_link(tgen.gears["r1"])
        switch.add_link(tgen.gears["r2"])

        switch = tgen.add_switch("s2")
        switch.add_link(tgen.gears["r2"])
        switch.add_link(tgen.gears["r3"])

        # Create stub networks for multicast traffic.
        tgen.add_host("h1", "192.168.10.2/24", "192.168.10.1")
        switch = tgen.add_switch("s3")
        switch.add_link(tgen.gears["r1"])
        switch.add_link(tgen.gears["h1"])

        tgen.add_host("h2", "192.168.30.2/24", "192.168.30.1")
        switch = tgen.add_switch("s4")
        switch.add_link(tgen.gears["r3"])
        switch.add_link(tgen.gears["h2"])


def setup_module(mod):
    "Sets up the pytest environment"
    tgen = Topogen(MSDPMeshTopo1, mod.__name__)
    tgen.start_topology()

    router_list = tgen.routers()
    for rname, router in router_list.items():
        daemon_file = "{}/{}/zebra.conf".format(CWD, rname)
        if os.path.isfile(daemon_file):
            router.load_config(TopoRouter.RD_ZEBRA, daemon_file)

        daemon_file = "{}/{}/bgpd.conf".format(CWD, rname)
        if os.path.isfile(daemon_file):
            router.load_config(TopoRouter.RD_BGP, daemon_file)

        daemon_file = "{}/{}/ospfd.conf".format(CWD, rname)
        if os.path.isfile(daemon_file):
            router.load_config(TopoRouter.RD_OSPF, daemon_file)

        daemon_file = "{}/{}/pimd.conf".format(CWD, rname)
        if os.path.isfile(daemon_file):
            router.load_config(TopoRouter.RD_PIM, daemon_file)

    # Initialize all routers.
    tgen.start_router()

    # Start applications socket.
    listen_to_applications()


def test_wait_ospf_convergence():
    "Wait for OSPF to converge"
    tgen = get_topogen()
    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)

    logger.info("waiting for protocols to converge")

    def expect_loopback_route(router, iptype, route, proto):
        "Wait until route is present on RIB for protocol."
        logger.info("waiting route {} in {}".format(route, router))
        test_func = partial(
            topotest.router_json_cmp,
            tgen.gears[router],
            "show {} route json".format(iptype),
            {route: [{"protocol": proto}]}
        )
        _, result = topotest.run_and_expect(test_func, None, count=40, wait=1)
        assertmsg = '"{}" OSPF convergence failure'.format(router)
        assert result is None, assertmsg

    # Wait for R1 <-> R2 convergence.
    expect_loopback_route("r1", "ip", "10.254.254.2/32", "ospf")
    # Wait for R1 <-> R3 convergence.
    expect_loopback_route("r1", "ip", "10.254.254.3/32", "ospf")

    # Wait for R2 <-> R1 convergence.
    expect_loopback_route("r2", "ip", "10.254.254.1/32", "ospf")
    # Wait for R2 <-> R3 convergence.
    expect_loopback_route("r2", "ip", "10.254.254.3/32", "ospf")

    # Wait for R3 <-> R1 convergence.
    expect_loopback_route("r3", "ip", "10.254.254.1/32", "ospf")
    # Wait for R3 <-> R2 convergence.
    expect_loopback_route("r3", "ip", "10.254.254.2/32", "ospf")


def test_wait_msdp_convergence():
    "Wait for MSDP to converge"
    tgen = get_topogen()
    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)

    logger.info("test MSDP convergence")

    tgen.gears["h1"].run("{} --send='0.7' '{}' '{}' '{}' &".format(
        HELPER_APP_PATH, APP_SOCK_PATH, '229.0.1.10', 'h1-eth0'))
    accept_host("h1")

    tgen.gears["h2"].run("{} '{}' '{}' '{}' &".format(
        HELPER_APP_PATH, APP_SOCK_PATH, '229.0.1.10', 'h2-eth0'))
    accept_host("h2")

    def expect_msdp_peer(router, peer, sa_count=0):
        "Expect MSDP peer connection to be established with SA amount."
        logger.info("waiting MSDP connection from peer {} on router {}".format(peer, router))
        test_func = partial(
            topotest.router_json_cmp,
            tgen.gears[router],
            "show ip msdp peer json",
            {peer: {"state": "established", "saCount": sa_count}}
        )
        _, result = topotest.run_and_expect(test_func, None, count=30, wait=1)
        assertmsg = '"{}" MSDP connection failure'.format(router)
        assert result is None, assertmsg

    # R1 peers.
    expect_msdp_peer("r1", "10.254.254.2")
    expect_msdp_peer("r1", "10.254.254.3")

    # R2 peers.
    expect_msdp_peer("r2", "10.254.254.1", 1)
    expect_msdp_peer("r2", "10.254.254.3")

    # R3 peers.
    expect_msdp_peer("r3", "10.254.254.1", 1)
    expect_msdp_peer("r3", "10.254.254.2")


def test_msdp_sa_configuration():
    "Expect the multicast traffic SA to be created"
    tgen = get_topogen()
    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)

    logger.info("test MSDP SA")

    def expect_msdp_sa(router, source, group, local, rp, spt_setup):
        "Expect MSDP SA."
        logger.info("waiting MSDP SA on router {}".format(router))
        test_func = partial(
            topotest.router_json_cmp,
            tgen.gears[router],
            "show ip msdp sa json",
            {group: {source: {"local": local, "rp": rp, "sptSetup": spt_setup}}}
        )
        _, result = topotest.run_and_expect(test_func, None, count=30, wait=1)
        assertmsg = '"{}" MSDP SA failure'.format(router)
        assert result is None, assertmsg

    source = "192.168.10.2"
    group = "229.0.1.10"
    rp = "10.254.254.1"

    # R1 SA.
    expect_msdp_sa("r1", source, group, "yes", "-", "-")

    # R2 SA.
    expect_msdp_sa("r2", source, group, "no", rp, "no")

    # R3 peers.
    expect_msdp_sa("r3", source, group, "no", rp, "yes")


def teardown_module(_mod):
    "Teardown the pytest environment"
    tgen = get_topogen()
    close_applications()
    tgen.stop_topology()


def test_memory_leak():
    "Run the memory leak test and report results."
    tgen = get_topogen()
    if not tgen.is_memleak_enabled():
        pytest.skip("Memory leak test/report is disabled")

    tgen.report_memory_leaks()


if __name__ == "__main__":
    args = ["-s"] + sys.argv[1:]
    sys.exit(pytest.main(args))
