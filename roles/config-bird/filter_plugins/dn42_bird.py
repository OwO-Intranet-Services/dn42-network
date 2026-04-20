from __future__ import annotations

from typing import Any

try:
    from ansible.errors import AnsibleFilterError
except ModuleNotFoundError:  # pragma: no cover - unit tests may run without ansible installed
    class AnsibleFilterError(ValueError):
        """Fallback error used when Ansible is unavailable."""


VALID_MP_BGP_TRANSPORTS = ("ipv4", "ipv6")


def _peer_label(peer: dict[str, Any]) -> str:
    bgp = peer.get("bgp") or {}
    asn = bgp.get("asn")
    return f"peer AS{asn}" if asn is not None else "peer"


def _bgp_bool(bgp: dict[str, Any], key: str, default: bool) -> bool:
    value = bgp.get(key)
    return default if value is None else bool(value)


def _resolve_mp_bgp_transport(peer: dict[str, Any]) -> str:
    bgp = peer.get("bgp") or {}
    wg = peer.get("wg") or {}

    configured = bgp.get("mp_bgp_transport")
    if configured is not None:
        normalized = str(configured).strip()
        if normalized not in VALID_MP_BGP_TRANSPORTS:
            raise AnsibleFilterError(
                f"{_peer_label(peer)} has invalid bgp.mp_bgp_transport: "
                f"expected one of {', '.join(VALID_MP_BGP_TRANSPORTS)}"
            )
        return normalized

    if wg.get("peer6"):
        return "ipv6"
    if wg.get("peer4"):
        return "ipv4"

    raise AnsibleFilterError(
        f"{_peer_label(peer)} requires wg.peer4 or wg.peer6 to infer bgp.mp_bgp_transport"
    )


def _validate_extended_next_hop(
    peer: dict[str, Any], *, ipv4: bool, mp_bgp: bool, transport: str, extended_next_hop: bool
) -> None:
    if not extended_next_hop:
        return
    if not mp_bgp:
        raise AnsibleFilterError(
            f"{_peer_label(peer)} cannot enable bgp.extended_next_hop without bgp.mp_bgp"
        )
    if transport != "ipv6":
        raise AnsibleFilterError(
            f"{_peer_label(peer)} can only enable bgp.extended_next_hop with bgp.mp_bgp_transport=ipv6"
        )
    if not ipv4:
        raise AnsibleFilterError(
            f"{_peer_label(peer)} can only enable bgp.extended_next_hop when bgp.ipv4 is enabled"
        )


def _family_entry(peer: dict[str, Any], family: str, transport: str, extended_next_hop: bool) -> dict[str, Any]:
    wg = peer.get("wg") or {}
    native_neighbor_key = "peer4" if family == "ipv4" else "peer6"
    native_neighbor = wg.get(native_neighbor_key)

    if family == transport:
        return {"name": family, "extended_next_hop": None}

    if family == "ipv4" and transport == "ipv6":
        if not native_neighbor and not extended_next_hop:
            raise AnsibleFilterError(
                f"{_peer_label(peer)} requires bgp.extended_next_hop for ipv4 routes over ipv6 "
                f"transport when wg.peer4 is absent"
            )
        return {"name": family, "extended_next_hop": extended_next_hop}

    if family == "ipv6" and transport == "ipv4":
        return {"name": family, "extended_next_hop": None}

    if not native_neighbor:
        raise AnsibleFilterError(
            f"{_peer_label(peer)} requires wg.{native_neighbor_key} for {family} routes over {transport} "
            f"transport"
        )

    return {"name": family, "extended_next_hop": None}


def dn42_bird_sessions(peer: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(peer, dict):
        raise AnsibleFilterError("dn42_bird_sessions expects a peer mapping")

    bgp = peer.get("bgp") or {}
    wg = peer.get("wg") or {}

    ipv4 = _bgp_bool(bgp, "ipv4", True)
    ipv6 = _bgp_bool(bgp, "ipv6", True)
    mp_bgp = _bgp_bool(bgp, "mp_bgp", True)
    extended_next_hop = _bgp_bool(bgp, "extended_next_hop", True)

    if not ipv4 and not ipv6:
        raise AnsibleFilterError(f"{_peer_label(peer)} must enable at least one address family")

    if not mp_bgp:
        _validate_extended_next_hop(
            peer, ipv4=ipv4, mp_bgp=mp_bgp, transport="ipv6", extended_next_hop=extended_next_hop
        )
        sessions: list[dict[str, Any]] = []
        if ipv4:
            neighbor = wg.get("peer4")
            if not neighbor:
                raise AnsibleFilterError(
                    f"{_peer_label(peer)} requires wg.peer4 for split IPv4 BGP rendering"
                )
            sessions.append(
                {
                    "name_suffix": "_v4",
                    "transport": "ipv4",
                    "neighbor": neighbor,
                    "families": [{"name": "ipv4", "extended_next_hop": None}],
                }
            )
        if ipv6:
            neighbor = wg.get("peer6")
            if not neighbor:
                raise AnsibleFilterError(
                    f"{_peer_label(peer)} requires wg.peer6 for split IPv6 BGP rendering"
                )
            sessions.append(
                {
                    "name_suffix": "_v6",
                    "transport": "ipv6",
                    "neighbor": neighbor,
                    "families": [{"name": "ipv6", "extended_next_hop": None}],
                }
            )
        return sessions

    transport = _resolve_mp_bgp_transport(peer)
    _validate_extended_next_hop(
        peer,
        ipv4=ipv4,
        mp_bgp=mp_bgp,
        transport=transport,
        extended_next_hop=extended_next_hop,
    )
    neighbor_key = "peer4" if transport == "ipv4" else "peer6"
    neighbor = wg.get(neighbor_key)
    if not neighbor:
        raise AnsibleFilterError(
            f"{_peer_label(peer)} requires wg.{neighbor_key} for bgp.mp_bgp_transport={transport}"
        )

    families = []
    if ipv4:
        families.append(_family_entry(peer, "ipv4", transport, extended_next_hop))
    if ipv6:
        families.append(_family_entry(peer, "ipv6", transport, extended_next_hop))

    return [
        {
            "name_suffix": "",
            "transport": transport,
            "neighbor": neighbor,
            "families": families,
        }
    ]


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {"dn42_bird_sessions": dn42_bird_sessions}
