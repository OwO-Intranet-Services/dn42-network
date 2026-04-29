from __future__ import annotations

import ipaddress
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

PEER_KEY_ORDER = ("comment", "wg", "bgp", "removed")
WG_KEY_ORDER = ("port", "endpoint", "wg_pubkey", "psk", "peer4", "peer6", "own6", "keepalive", "mtu")
DEFAULT_PEERING_STRATEGY = "full_table"
PEERING_STRATEGIES = (DEFAULT_PEERING_STRATEGY, "transit", "peer", "downstream")
VALID_MP_BGP_TRANSPORTS = ("ipv4", "ipv6")
BGP_KEY_ORDER = (
    "asn",
    "ipv4",
    "ipv6",
    "extended_next_hop",
    "mp_bgp",
    "mp_bgp_transport",
    "peering_strategy",
)
BASE64_LIKE_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
HOSTNAME_LABEL_RE = re.compile(r"^[A-Za-z0-9-]{1,63}$")
DEFAULT_INVENTORY = Path(__file__).resolve().parents[1] / "inventory.yaml"


@lru_cache(maxsize=1)
def _shared_default_link_local_ipv6() -> ipaddress.IPv6Address | None:
    try:
        with DEFAULT_INVENTORY.open(encoding="utf-8") as handle:
            inventory = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError):
        return None

    hosts = (
        ((inventory or {}).get("all") or {})
        .get("children", {})
        .get("nodes", {})
        .get("hosts", {})
    )
    if not isinstance(hosts, dict):
        return None

    values: set[ipaddress.IPv6Address] = set()
    for host_data in hosts.values():
        if not isinstance(host_data, dict):
            continue
        raw_value = host_data.get("link_local_ipv6")
        if raw_value in (None, ""):
            continue
        try:
            address = ipaddress.IPv6Address(str(raw_value))
        except ValueError:
            return None
        if not address.is_link_local:
            return None
        values.add(address)

    if len(values) != 1:
        return None
    return next(iter(values))


class TaggedScalar(str):
    """Scalar string that remembers its original YAML tag."""

    yaml_tag: str

    def __new__(cls, value: str, yaml_tag: str) -> "TaggedScalar":
        instance = super().__new__(cls, value)
        instance.yaml_tag = yaml_tag
        return instance


class PeerConfigLoader(yaml.SafeLoader):
    """Safe YAML loader that preserves tagged scalars such as !vault."""


class PeerConfigDumper(yaml.SafeDumper):
    """Deterministic YAML dumper for peer configuration files."""

    _representing_key = False

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> Any:
        return super().increase_indent(flow, False)

    def ignore_aliases(self, data: Any) -> bool:
        return True

    def represent_mapping(self, tag: str, mapping: Any, flow_style: bool | None = None) -> MappingNode:
        value: list[tuple[yaml.Node, yaml.Node]] = []
        node = MappingNode(tag, value, flow_style=flow_style)
        if self.alias_key is not None:
            self.represented_objects[self.alias_key] = node

        best_style = True
        if hasattr(mapping, "items"):
            mapping = list(mapping.items())
            if self.sort_keys:
                try:
                    mapping = sorted(mapping)
                except TypeError:
                    pass

        for item_key, item_value in mapping:
            self._representing_key = True
            node_key = self.represent_data(item_key)
            self._representing_key = False
            node_value = self.represent_data(item_value)
            if not (isinstance(node_key, ScalarNode) and node_key.style is None):
                best_style = False
            if not (isinstance(node_value, ScalarNode) and node_value.style is None):
                best_style = False
            value.append((node_key, node_value))

        if flow_style is None:
            if self.default_flow_style is not None:
                node.flow_style = self.default_flow_style
            else:
                node.flow_style = best_style
        return node


def _construct_unknown_tag(loader: PeerConfigLoader, node: yaml.Node) -> Any:
    if isinstance(node, ScalarNode):
        value = loader.construct_scalar(node)
        if node.tag.startswith("!"):
            return TaggedScalar(value, node.tag)
        return value
    if isinstance(node, SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, MappingNode):
        return loader.construct_mapping(node)
    raise TypeError(f"Unsupported YAML node: {type(node)!r}")


def _represent_tagged_scalar(dumper: PeerConfigDumper, data: TaggedScalar) -> yaml.Node:
    style = "|" if "\n" in str(data) or data.yaml_tag == "!vault" else None
    return dumper.represent_scalar(data.yaml_tag, str(data), style=style)


def _represent_string(dumper: PeerConfigDumper, data: str) -> yaml.Node:
    style = None if dumper._representing_key else "'"
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


PeerConfigLoader.add_constructor(None, _construct_unknown_tag)
PeerConfigDumper.add_representer(TaggedScalar, _represent_tagged_scalar)
PeerConfigDumper.add_representer(str, _represent_string)


def load_peer_yaml_text(text: str) -> Any:
    return yaml.load(text, Loader=PeerConfigLoader)


def load_peer_yaml_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return load_peer_yaml_text(handle.read())


def dump_peer_yaml(data: Any) -> str:
    return yaml.dump(
        data,
        Dumper=PeerConfigDumper,
        default_flow_style=False,
        sort_keys=False,
        width=4096,
    ).rstrip() + "\n"


def default_peer_port(asn: int) -> int:
    return int(str(asn)[-5:])


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_generic(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, child in value.items():
            normalized_child = _normalize_generic(child)
            if normalized_child is None:
                continue
            normalized[str(key)] = normalized_child
        return normalized

    if isinstance(value, list):
        return [_normalize_generic(item) for item in value]

    return value


def _ordered_items(mapping: dict[str, Any], preferred_keys: tuple[str, ...]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    for key in preferred_keys:
        if key in mapping:
            ordered[key] = mapping[key]
    for key, value in mapping.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def _normalize_known_value(mapping: dict[str, Any], key: str, default: Any) -> Any:
    normalized_value = _normalize_generic(mapping.get(key, default))
    if normalized_value is None:
        return default
    return normalized_value


def _peer_label(asn: int) -> str:
    return f"peer AS{asn}"


def _require_bool(value: Any, *, field: str, peer_label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{peer_label} has invalid {field}: expected boolean")
    return value


def _normalize_peering_strategy(value: Any, *, field: str, peer_label: str) -> str:
    if value is None:
        return DEFAULT_PEERING_STRATEGY
    if not isinstance(value, str):
        raise ValueError(
            f"{peer_label} has invalid {field}: expected one of {', '.join(PEERING_STRATEGIES)}"
        )
    strategy = value.strip()
    if strategy not in PEERING_STRATEGIES:
        raise ValueError(
            f"{peer_label} has invalid {field}: expected one of {', '.join(PEERING_STRATEGIES)}"
        )
    return strategy


def _normalize_mp_bgp_transport(value: Any, *, field: str, peer_label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"{peer_label} has invalid {field}: expected one of {', '.join(VALID_MP_BGP_TRANSPORTS)}"
        )
    transport = value.strip()
    if transport not in VALID_MP_BGP_TRANSPORTS:
        raise ValueError(
            f"{peer_label} has invalid {field}: expected one of {', '.join(VALID_MP_BGP_TRANSPORTS)}"
        )
    return transport


def _resolve_mp_bgp_transport(
    bgp: dict[str, Any],
    wg: dict[str, Any],
    *,
    field: str,
    peer_label: str,
) -> str | None:
    configured = _normalize_mp_bgp_transport(bgp.get(field), field=field, peer_label=peer_label)
    if configured is not None:
        return configured
    if wg.get("peer6") is not None:
        return "ipv6"
    if wg.get("peer4") is not None:
        return "ipv4"
    return None


def _require_port(value: Any, *, field: str, peer_label: str) -> int:
    port = _coerce_int(value)
    if port is None or not 1 <= port <= 65535:
        raise ValueError(f"{peer_label} has invalid {field}: expected integer in range 1-65535")
    return port


def _require_optional_port(value: Any, *, field: str, peer_label: str) -> None:
    if value is None:
        return
    _require_port(value, field=field, peer_label=peer_label)


def _require_endpoint(value: Any, *, peer_label: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, TaggedScalar) and value.yaml_tag == "!vault":
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{peer_label} has invalid wg.endpoint: expected host:port string or null")

    endpoint = value.strip()
    if endpoint.startswith("["):
        closing = endpoint.find("]")
        if closing == -1 or closing == 1 or closing + 2 > len(endpoint) or endpoint[closing + 1] != ":":
            raise ValueError(f"{peer_label} has invalid wg.endpoint: expected [ipv6]:port")
        host = endpoint[1:closing]
        port_text = endpoint[closing + 2 :]
    else:
        if endpoint.count(":") != 1:
            raise ValueError(f"{peer_label} has invalid wg.endpoint: expected host:port")
        host, port_text = endpoint.rsplit(":", 1)

    _require_port(port_text, field="wg.endpoint port", peer_label=peer_label)
    _require_endpoint_host(host, peer_label=peer_label)
    return endpoint


def _require_endpoint_host(host: str, *, peer_label: str) -> None:
    if not host:
        raise ValueError(f"{peer_label} has invalid wg.endpoint: missing host")

    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass

    labels = host.split(".")
    if len(labels) < 2:
        raise ValueError(
            f"{peer_label} has invalid wg.endpoint: host must be an IP address or dotted hostname"
        )
    if len(host) > 253:
        raise ValueError(f"{peer_label} has invalid wg.endpoint: hostname is too long")

    for label in labels:
        if not HOSTNAME_LABEL_RE.fullmatch(label) or label.startswith("-") or label.endswith("-"):
            raise ValueError(f"{peer_label} has invalid wg.endpoint: malformed hostname label {label!r}")


def _require_wg_public_key(value: Any, *, peer_label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{peer_label} has invalid wg.wg_pubkey: expected non-empty string")

    key = value.strip()
    if not BASE64_LIKE_RE.fullmatch(key):
        raise ValueError(f"{peer_label} has invalid wg.wg_pubkey: expected base64-like string")
    return key


def _require_optional_ipv4(value: Any, *, field: str, peer_label: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{peer_label} has invalid {field}: expected IPv4 string")

    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"{peer_label} has invalid {field}: not a valid IPv4 address") from exc

    if address.is_unspecified:
        raise ValueError(f"{peer_label} has invalid {field}: unspecified IPv4 address is not allowed")


def _require_ipv6(value: Any, *, field: str, peer_label: str) -> ipaddress.IPv6Address:
    if not isinstance(value, str):
        raise ValueError(f"{peer_label} has invalid {field}: expected IPv6 string")

    try:
        address = ipaddress.IPv6Address(value)
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"{peer_label} has invalid {field}: not a valid IPv6 address") from exc

    if address.is_unspecified:
        raise ValueError(f"{peer_label} has invalid {field}: unspecified IPv6 address is not allowed")
    if address.is_multicast:
        raise ValueError(f"{peer_label} has invalid {field}: multicast IPv6 address is not allowed")
    return address


def _require_optional_link_local_ipv6(value: Any, *, field: str, peer_label: str) -> ipaddress.IPv6Address | None:
    if value is None:
        return None
    address = _require_ipv6(value, field=field, peer_label=peer_label)
    if not address.is_link_local:
        raise ValueError(f"{peer_label} has invalid {field}: expected link-local IPv6 address")
    return address


def _validate_wg_settings(
    wg: dict[str, Any],
    *,
    asn: int,
    removed: bool,
    ipv4: bool,
    ipv6: bool,
    mp_bgp: bool,
    mp_bgp_transport: str,
    extended_next_hop: bool,
) -> None:
    peer_label = _peer_label(asn)
    peer4 = wg.get("peer4")
    peer6 = wg.get("peer6")
    own6 = wg.get("own6")

    if not removed:
        _require_port(wg.get("port", default_peer_port(asn)), field="wg.port", peer_label=peer_label)
        _require_endpoint(wg.get("endpoint"), peer_label=peer_label)
        _require_wg_public_key(wg.get("wg_pubkey"), peer_label=peer_label)
        if mp_bgp and mp_bgp_transport == "ipv6" and peer6 is None:
            raise ValueError(f"{peer_label} requires wg.peer6 for bgp.mp_bgp_transport=ipv6")
        if mp_bgp and mp_bgp_transport == "ipv4" and peer4 is None:
            raise ValueError(f"{peer_label} requires wg.peer4 for bgp.mp_bgp_transport=ipv4")
        if ipv6 and ((not mp_bgp) or mp_bgp_transport == "ipv6") and peer6 is None:
            raise ValueError(f"{peer_label} requires wg.peer6 for bgp.ipv6")
        if mp_bgp and ipv4 and mp_bgp_transport == "ipv6" and peer4 is None and not extended_next_hop:
            raise ValueError(
                f"{peer_label} requires bgp.extended_next_hop for bgp.ipv4 over bgp.mp_bgp_transport=ipv6 when wg.peer4 is absent"
            )
        if ipv4 and not mp_bgp and peer4 is None:
            raise ValueError(f"{peer_label} requires wg.peer4 for bgp.ipv4 when bgp.mp_bgp is disabled")

    _require_optional_ipv4(peer4, field="wg.peer4", peer_label=peer_label)
    peer6_address = None
    if peer6 is not None:
        peer6_address = _require_ipv6(peer6, field="wg.peer6", peer_label=peer_label)
    own6_address = _require_optional_link_local_ipv6(own6, field="wg.own6", peer_label=peer_label)
    if own6_address is not None:
        if peer6_address is None:
            raise ValueError(f"{peer_label} requires wg.peer6 when wg.own6 is set")
        if not peer6_address.is_link_local:
            raise ValueError(f"{peer_label} can only set wg.own6 when wg.peer6 is link-local")
    effective_own6_address = own6_address or _shared_default_link_local_ipv6()
    if (
        peer6_address is not None
        and peer6_address.is_link_local
        and effective_own6_address is not None
        and peer6_address == effective_own6_address
    ):
        raise ValueError(f"{peer_label} requires wg.peer6 to differ from our link-local IPv6")
    _require_optional_port(wg.get("keepalive"), field="wg.keepalive", peer_label=peer_label)

    mtu = wg.get("mtu")
    if mtu is not None:
        mtu_value = _coerce_int(mtu)
        if mtu_value is None or not 576 <= mtu_value <= 65535:
            raise ValueError(f"{peer_label} has invalid wg.mtu: expected integer in range 576-65535")


def _validate_bgp_settings(
    bgp: dict[str, Any], wg: dict[str, Any], *, asn: int, removed: bool
) -> tuple[bool, bool, bool, bool, str | None]:
    peer_label = _peer_label(asn)
    ipv4 = _require_bool(bgp.get("ipv4", True), field="bgp.ipv4", peer_label=peer_label)
    ipv6 = _require_bool(bgp.get("ipv6", True), field="bgp.ipv6", peer_label=peer_label)
    extended_next_hop = _require_bool(
        bgp.get("extended_next_hop", True),
        field="bgp.extended_next_hop",
        peer_label=peer_label,
    )
    mp_bgp = _require_bool(bgp.get("mp_bgp", True), field="bgp.mp_bgp", peer_label=peer_label)
    mp_bgp_transport = _resolve_mp_bgp_transport(
        bgp,
        wg,
        field="mp_bgp_transport",
        peer_label=peer_label,
    )
    _normalize_peering_strategy(
        bgp.get("peering_strategy", DEFAULT_PEERING_STRATEGY),
        field="bgp.peering_strategy",
        peer_label=peer_label,
    )
    if not ipv4 and not ipv6:
        raise ValueError(f"{peer_label} must enable at least one address family")
    if mp_bgp and not removed and mp_bgp_transport is None:
        raise ValueError(
            f"{peer_label} has invalid bgp.mp_bgp_transport: requires wg.peer4 or wg.peer6 to infer MP-BGP transport"
        )
    if extended_next_hop and not mp_bgp:
        raise ValueError(f"{peer_label} cannot enable bgp.extended_next_hop without bgp.mp_bgp")
    if extended_next_hop and mp_bgp_transport not in (None, "ipv6"):
        raise ValueError(
            f"{peer_label} can only enable bgp.extended_next_hop with bgp.mp_bgp_transport=ipv6"
        )
    if extended_next_hop and not ipv4:
        raise ValueError(f"{peer_label} can only enable bgp.extended_next_hop when bgp.ipv4 is enabled")
    return ipv4, ipv6, extended_next_hop, mp_bgp, mp_bgp_transport


def normalize_peer_entry(peer: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(peer, dict):
        raise ValueError("peer entry must be a mapping")

    bgp = peer.get("bgp")
    if not isinstance(bgp, dict):
        raise ValueError("peer entry is missing bgp mapping")

    asn = _coerce_int(bgp.get("asn"))
    if asn is None:
        raise ValueError("peer entry is missing valid bgp.asn")

    removed = bool(peer.get("removed", False))
    wg = peer.get("wg")
    if not isinstance(wg, dict) and not removed:
        raise ValueError(f"active peer AS{asn} is missing wg mapping")
    raw_wg = wg if isinstance(wg, dict) else {}

    ipv4, ipv6, extended_next_hop, mp_bgp, mp_bgp_transport = _validate_bgp_settings(
        bgp,
        raw_wg,
        asn=asn,
        removed=removed,
    )
    _validate_wg_settings(
        raw_wg,
        asn=asn,
        removed=removed,
        ipv4=ipv4,
        ipv6=ipv6,
        mp_bgp=mp_bgp,
        mp_bgp_transport=mp_bgp_transport or "ipv6",
        extended_next_hop=extended_next_hop,
    )

    normalized_peer: dict[str, Any] = {}

    comment = _normalize_generic(peer.get("comment"))
    if comment is not None:
        normalized_peer["comment"] = comment

    raw_port = _normalize_known_value(raw_wg, "port", default_peer_port(asn))
    normalized_port = _coerce_int(raw_port)
    normalized_wg: dict[str, Any] = {
        "port": normalized_port if normalized_port is not None else raw_port,
        "endpoint": _normalize_known_value(raw_wg, "endpoint", None),
        "wg_pubkey": _normalize_known_value(raw_wg, "wg_pubkey", None),
        "psk": _normalize_known_value(raw_wg, "psk", None),
        "peer4": _normalize_known_value(raw_wg, "peer4", None),
        "peer6": _normalize_known_value(raw_wg, "peer6", None),
        "own6": _normalize_known_value(raw_wg, "own6", None),
        "keepalive": _normalize_known_value(raw_wg, "keepalive", None),
        "mtu": _normalize_known_value(raw_wg, "mtu", None),
    }
    for key, value in raw_wg.items():
        if key in WG_KEY_ORDER:
            continue
        normalized_value = _normalize_generic(value)
        if normalized_value is None:
            continue
        normalized_wg[str(key)] = normalized_value
    if normalized_wg:
        normalized_peer["wg"] = _ordered_items(normalized_wg, WG_KEY_ORDER)

    normalized_bgp: dict[str, Any] = {
        "asn": asn,
        "ipv4": _normalize_known_value(bgp, "ipv4", True),
        "ipv6": _normalize_known_value(bgp, "ipv6", True),
        "extended_next_hop": _normalize_known_value(bgp, "extended_next_hop", True),
        "mp_bgp": _normalize_known_value(bgp, "mp_bgp", True),
    }
    normalized_mp_bgp_transport = _normalize_mp_bgp_transport(
        _normalize_generic(bgp.get("mp_bgp_transport")),
        field="bgp.mp_bgp_transport",
        peer_label=_peer_label(asn),
    )
    if normalized_mp_bgp_transport is not None:
        normalized_bgp["mp_bgp_transport"] = normalized_mp_bgp_transport
    peering_strategy = _normalize_peering_strategy(
        _normalize_generic(bgp.get("peering_strategy")),
        field="bgp.peering_strategy",
        peer_label=_peer_label(asn),
    )
    if peering_strategy != DEFAULT_PEERING_STRATEGY:
        normalized_bgp["peering_strategy"] = peering_strategy
    for key, value in bgp.items():
        if key in BGP_KEY_ORDER:
            continue
        normalized_value = _normalize_generic(value)
        if normalized_value is None:
            continue
        normalized_bgp[str(key)] = normalized_value
    normalized_peer["bgp"] = normalized_bgp

    if removed:
        normalized_peer["removed"] = True

    for key, value in peer.items():
        if key in PEER_KEY_ORDER:
            continue
        normalized_value = _normalize_generic(value)
        if normalized_value is None:
            continue
        normalized_peer[str(key)] = normalized_value

    return _ordered_items(normalized_peer, PEER_KEY_ORDER)


def normalize_peer_entry_for_compare(peer: dict[str, Any]) -> dict[str, Any]:
    normalized_peer = normalize_peer_entry(peer)
    if normalized_peer.get("removed"):
        asn = int(normalized_peer["bgp"]["asn"])
        return {"bgp": {"asn": asn}, "removed": True}
    return normalized_peer


def normalize_peer_file_data(data: Any) -> dict[str, Any]:
    if data is None:
        data = {}

    if not isinstance(data, dict):
        raise ValueError("peer file must contain a mapping at the top level")

    peers = data.get("peers")
    if peers is None:
        peers = []
    if not isinstance(peers, list):
        raise ValueError("peer file must contain a top-level peers list")

    normalized_peers = [normalize_peer_entry(peer) for peer in peers]
    return {"peers": normalized_peers}
