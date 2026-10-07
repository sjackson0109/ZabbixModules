# LLDP capability: observations, mapping and privacy

LLDP is required for the initial release. Templates collect per-host observations; they do not perform privileged cross-host peer resolution or create hosts.

## Candidate standard objects and indices

LLDP-MIB root `.1.0.8802.1.1.2.1`. Local system `.3` includes chassis subtype `.1.0`, chassis ID `.2.0`, sysName `.3.0`; local port entry `.3.7.1` columns local port number1, ID subtype2, ID3, description4. Remote entry `.4.1.1` columns chassis subtype4/ID5, port subtype6/ID7, description8, system name9. Remote rows are indexed by `(timeMark, localPortNum, remoteIndex)`. Preserve the compound suffix; reducing it to localPortNum loses multiple peers and time transitions.

Remote management address entry `.4.2.1` is indexed by the remote-row triple then address subtype, address length and address octets. Relevant readable columns include interface subtype3/interface ID4/object ID5. Decode IPv4 and IPv6 with explicit subtype and exact length; keep multiple addresses and unknown address families as source evidence. Management address is not globally unique and never grants visibility.

These are standard object candidates, confirmed against named LLDP-MIB definitions but not a device-support claim. Capture local/remote tables together with IF-MIB identity columns, sysUpTime and counters/time evidence where exposed. Include `lldpStatsRemTablesLastChangeTime` as change evidence where usable; it is not a per-peer observation timestamp. The envelope observation time is acquisition time, and must not be presented as the exact neighbour insertion time.

## Local and remote port identity

lldpLocPortNum need not equal ifIndex. Match subtype5 interfaceName to unique ifName; subtype1 interfaceAlias to unique ifAlias; subtype3 macAddress to unique canonical MAC; subtype7 local IDs only through explicit unique name/description evidence or a qualified adapter rule. Subtype4 networkAddress requires a demonstrated interface-address join. Keep unresolved `local_interface_uid=null` and mapping reason; no numeric guess. Description can corroborate a match, not override a conflicting subtype.

Normalised rows preserve local/remote `{subtype,value}` identifiers, local UID when resolved, remote system name/port description, all management addresses, compound source index where schema extension permits it, and observed_at. Binary MAC/network-address encodings must not be decoded blindly as text. Preserve multiple peers, one-sided observations and reused timeMark/index rows. Deduplication uses observation identity, not just neighbour name.

## Completeness, health and privacy

Completed supported walks with no remote rows can emit complete empty data; denied/timed-out/absent LLDP tables cannot. Determine capability using local agent evidence plus completed remote subtree queries. An empty table alone does not establish `unsupported`. Missing required columns makes a partial attempt and leaves last complete snapshot retained; unresolved local mapping is quality evidence and must not be silently dropped.

Store only local-source metadata in the source-host snapshot. Cross-host matches occur under user permissions and stable network-domain scope. Strict boundary deployments must explicitly assess raw LLDP item/history disclosure, not just widget output. A profile may redact remote name/address fields while retaining safe adjacency evidence; fixture/export policy follows the same rule.

## Qualification

Test all relevant identifier subtypes, binary/text encodings, local port numbers unrelated to ifIndex, multiple neighbours on one port, multiple addresses/IPv6, empty supported table, LLDP-disabled/denied view, partial remote rows, stale/delayed delivery and two opposite observations disagreeing. Frontend tests cover permission-hidden neighbours, duplicated names/IPs in different domains, unknown peers and ambiguity. Version imports, canonical values, observation ages and proxy load must pass before profile support is claimed.
