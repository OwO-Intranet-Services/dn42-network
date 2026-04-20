# Autopeer Follow-Up: MP-BGP Transport Logic

The Ansible roles now derive BIRD sessions from two independent decisions:

- Transport: split sessions, or one MP-BGP session over `ipv4` or `ipv6`
- Families carried: `ipv4`, `ipv6`, or both

Role-side behavior:

- `mp_bgp: false` still renders separate `_v4` / `_v6` protocols.
- `mp_bgp: true` now renders one protocol, with transport chosen by `bgp.mp_bgp_transport`.
- If `bgp.mp_bgp_transport` is omitted, the role infers it from the tunnel addresses:
  - prefer `ipv6` when `wg.peer6` exists
  - otherwise fall back to `ipv4` when `wg.peer4` exists
- `extended_next_hop` is now treated as the RFC 8950-style IPv4-over-IPv6 knob only:
  - it is only valid with `mp_bgp: true`
  - it is only valid with `mp_bgp_transport: ipv6`
  - it is only meaningful when `ipv4: true`
  - it is only emitted in the `ipv4 {}` channel
- IPv4 routes over IPv6 transport now require one of:
  - `wg.peer4`, so BIRD can use a native IPv4 next hop
  - `extended_next_hop: true`, so BIRD can use an IPv6 next hop
- IPv6 routes over IPv4 transport are now allowed without `wg.peer6`; the repo relies on BIRD's existing IPv6-over-IPv4 next-hop handling for that case, and `extended_next_hop` is still not involved.

Autopeer-side changes still needed:

- Add `mp_bgp_transport` to the session models in both Rust and worker TypeScript.
- Preserve the field in worker normalization and round-tripping:
  - `autopeer-worker/src/types.ts`
  - `autopeer-worker/src/network.ts`
  - `autopeer-worker/src/index.ts`
  - `autopeer/src/models.rs`
  - `autopeer/src/store.rs`
- Update worker validation so MP-BGP no longer implies IPv6 transport. Validation should instead check the chosen transport and only require `peer4` / `peer6` when that transport or a native-family next hop is actually needed; in particular, IPv6 over IPv4 transport should no longer require `peer6`.
- Update the autopeer UI copy. The current text says MP-BGP uses the IPv6 address for a single session; that is no longer always true, but `extended_next_hop` should still be described as the IPv4-over-IPv6 option rather than a generic mixed-family toggle.
- Add a transport selector in the advanced BGP section, defaulting to the current behavior (`ipv6` when available) for backward compatibility.
- Extend worker and Rust tests to cover:
  - MP-BGP over IPv4 transport
  - MP-BGP over IPv6 transport
  - cross-family carriage with and without `extended_next_hop`
  - legacy entries with no explicit `mp_bgp_transport`
