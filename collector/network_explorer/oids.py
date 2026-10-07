"""Numeric OIDs: IF-MIB, EtherLike-MIB, LLDP-MIB, IEEE8023-LAG-MIB.

Runtime MIB downloading is deliberately disabled. No vendor-specific capability
is implied by the presence of a standard OID in this module.
"""

UPTIME = "1.3.6.1.2.1.1.3.0"
IF_NUMBER = "1.3.6.1.2.1.2.1.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
IF = {
    "index": "1.3.6.1.2.1.2.2.1.1",
    "description": "1.3.6.1.2.1.2.2.1.2",
    "type": "1.3.6.1.2.1.2.2.1.3",
    "mtu": "1.3.6.1.2.1.2.2.1.4",
    "speed": "1.3.6.1.2.1.2.2.1.5",
    "mac": "1.3.6.1.2.1.2.2.1.6",
    "admin": "1.3.6.1.2.1.2.2.1.7",
    "oper": "1.3.6.1.2.1.2.2.1.8",
    "name": "1.3.6.1.2.1.31.1.1.1.1",
    "high_speed": "1.3.6.1.2.1.31.1.1.1.15",
    "connector": "1.3.6.1.2.1.31.1.1.1.17",
    "alias": "1.3.6.1.2.1.31.1.1.1.18",
    "duplex": "1.3.6.1.2.1.10.7.2.1.19",
}
IF_REQUIRED = {"index", "description", "type", "admin", "oper"}
LLDP_LOCAL_CHASSIS_SUBTYPE = "1.0.8802.1.1.2.1.3.1.0"
LLDP_LOCAL_CHASSIS_ID = "1.0.8802.1.1.2.1.3.2.0"
LLDP_LOCAL = {
    "subtype": "1.0.8802.1.1.2.1.3.7.1.2",
    "id": "1.0.8802.1.1.2.1.3.7.1.3",
    "description": "1.0.8802.1.1.2.1.3.7.1.4",
}
LLDP_REMOTE = {
    "chassis_subtype": "1.0.8802.1.1.2.1.4.1.1.4",
    "chassis_id": "1.0.8802.1.1.2.1.4.1.1.5",
    "port_subtype": "1.0.8802.1.1.2.1.4.1.1.6",
    "port_id": "1.0.8802.1.1.2.1.4.1.1.7",
    "port_description": "1.0.8802.1.1.2.1.4.1.1.8",
    "system_name": "1.0.8802.1.1.2.1.4.1.1.9",
    "management": "1.0.8802.1.1.2.1.4.2.1.3",
}
LAG = {
    # dot3adAggIndex (.1) is not-accessible; derive it from readable row suffixes.
    "individual": "1.2.840.10006.300.43.1.1.1.1.5",
    "actor": "1.2.840.10006.300.43.1.1.1.1.4",
    "partner": "1.2.840.10006.300.43.1.1.1.1.8",
    "attached": "1.2.840.10006.300.43.1.2.1.1.13",
}
