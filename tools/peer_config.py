from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

PEER_KEY_ORDER = ("comment", "wg", "bgp", "removed")
WG_KEY_ORDER = ("port", "endpoint", "wg_pubkey", "psk", "peer4", "peer6", "own6", "keepalive", "mtu")
BGP_KEY_ORDER = ("asn", "ipv4", "ipv6", "extended_next_hop", "mp_bgp")
BASE64_LIKE_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
HOSTNAME_LABEL_RE = re.compile(r"^[A-Za-z0-9-]{1,63}$")


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


def _require_port(value: Any, *, field: str, peer_label: str) -> int:
    port = _coerce_int(value)
    if port is None or not 1 <= port <= 65535:
        raise ValueError(f"{peer_label} has invalid {field}: expected integer in range 1-65535")
    return port


def _require_optional_port(value: Any, *, field: str, peer_label: str) -> None:
    if value is None:
        return
    _require_port(value, field=field, peer_label=peer_label)


def _require_endpoint(value: Any, *, peer_label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{peer_label} has invalid wg.endpoint: expected host:port string")

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


def _require_optional_link_local_ipv6(value: Any, *, field: str, peer_label: str) -> None:
    if value is None:
        return
    address = _require_ipv6(value, field=field, peer_label=peer_label)
    if not address.is_link_local:
        raise ValueError(f"{peer_label} has invalid {field}: expected link-local IPv6 address")


def _validate_wg_settings(wg: dict[str, Any], *, asn: int, removed: bool) -> None:
    peer_label = _peer_label(asn)

    if not removed:
        _require_port(wg.get("port", default_peer_port(asn)), field="wg.port", peer_label=peer_label)
        _require_endpoint(wg.get("endpoint"), peer_label=peer_label)
        _require_wg_public_key(wg.get("wg_pubkey"), peer_label=peer_label)
        _require_ipv6(wg.get("peer6"), field="wg.peer6", peer_label=peer_label)

    _require_optional_ipv4(wg.get("peer4"), field="wg.peer4", peer_label=peer_label)
    _require_optional_link_local_ipv6(wg.get("own6"), field="wg.own6", peer_label=peer_label)
    _require_optional_port(wg.get("keepalive"), field="wg.keepalive", peer_label=peer_label)

    mtu = wg.get("mtu")
    if mtu is not None:
        mtu_value = _coerce_int(mtu)
        if mtu_value is None or not 576 <= mtu_value <= 65535:
            raise ValueError(f"{peer_label} has invalid wg.mtu: expected integer in range 576-65535")


def _validate_bgp_settings(bgp: dict[str, Any], *, asn: int) -> None:
    peer_label = _peer_label(asn)
    ipv4 = _require_bool(bgp.get("ipv4", True), field="bgp.ipv4", peer_label=peer_label)
    ipv6 = _require_bool(bgp.get("ipv6", True), field="bgp.ipv6", peer_label=peer_label)
    _require_bool(
        bgp.get("extended_next_hop", True),
        field="bgp.extended_next_hop",
        peer_label=peer_label,
    )
    _require_bool(bgp.get("mp_bgp", True), field="bgp.mp_bgp", peer_label=peer_label)
    if not ipv4 and not ipv6:
        raise ValueError(f"{peer_label} must enable at least one address family")


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

    _validate_wg_settings(raw_wg, asn=asn, removed=removed)
    _validate_bgp_settings(bgp, asn=asn)

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
    if not isinstance(peers, list):
        raise ValueError("peer file must contain a top-level peers list")

    normalized_peers = [normalize_peer_entry(peer) for peer in peers]
    return {"peers": normalized_peers}
