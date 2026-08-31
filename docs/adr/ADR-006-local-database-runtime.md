# ADR-006: Docker runs Postgres and Redis only; Neon stays configured but optional

**Status:** Accepted

## Context

Development happens on a 7.4 GB Windows laptop, typically under 1 GB free. Four separate
constraints surfaced, each uncovered by fixing the previous one.

**1. Memory.** Docker Desktop's WSL VM ballooned far beyond what the containers used,
OOM-killing them (exit 137) and eventually corrupting its own storage layer
(`buildkit/metadata_v2.db: read-only file system`). Capping the VM in `.wslconfig`
(3 GB, 4 CPUs, `autoMemoryReclaim`) brought vmmemWSL from ~10 GB to ~1.75 GB and stopped
Docker from destabilising Windows, but did not remove the underlying pressure.

**2. Managed Postgres worked, then became unreachable.** A Neon project
(`COMPAIP_Postgres`, branch `development`) was provisioned, migrated and loaded
successfully on Postgres 18 with pgvector 0.8.6. Then **outbound TCP/5432 stopped
working on this network**. Verified: 5432 times out from both Windows and WSL, while
port 443 to the same internet succeeds in ~142 ms, DNS resolves correctly, and Windows
Firewall's outbound default is unconfigured (allow). The block is upstream, at the ISP.

Neon's only 443 transport is the `@neondatabase/serverless` driver, which is
JavaScript-only. There is no psycopg-compatible equivalent, so Python cannot reach Neon
from a network that blocks 5432.

**3. Latency, found while Neon was still reachable.** 298 ms per round trip to
`us-east-2`, which exposed that the row-by-row CDC path had silently assumed a local
database. Addressed separately in ADR-007.

**4. Hosting the databases in WSL did not work.** Postgres 16 + pgvector and Redis were
installed in WSL under systemd and ran correctly *inside* the VM (`redis-cli ping` →
`PONG`, `psql` fine, both listening on `0.0.0.0`). They could not be reached from
Windows. Attempted, in order:

- NAT mode with `localhostForwarding=true` — `localhost` refused
- the VM's NAT IP directly — connected once, then refused intermittently
- `networkingMode=mirrored` — VM correctly shared the host NIC (192.168.1.13), still
  unreachable on `localhost`, `127.0.0.1`, or the shared IP
- targeted Hyper-V firewall rules for 5432/6379 (`New-NetFirewallHyperVRule`) — added
  successfully, connections still refused

The host adapter is named `vEthernet (WSL (Hyper-V firewall))`, and connections were
actively *refused* rather than timing out, which points at the Hyper-V firewall layer.
Rather than keep chasing it, the option that had demonstrably worked for Phases 0–2 was
taken.

## Decision

**Docker Compose runs the two stateful services -- Postgres (pgvector) and Redis -- and
nothing else.** Publishing a container port to Windows `localhost` is the one path that
has consistently worked on this machine.

- Application code, Celery worker, Beat and Flower all run from the **local venv**
  (`make worker`, `make beat`, `make flower`), so the container count stays at two.
- `worker` and `beat` remain in `docker-compose.yml` behind a `workers` profile, for
  exercising the production image on demand:
  `docker compose --profile workers up -d`.
- Neon stays fully configured in `.env` behind `DATABASE_URL_OVERRIDE`, commented out.
  Re-enabling it is uncommenting one line, once the network permits.

## Consequences

- Fewest moving parts that are known to work here: two containers, everything else
  native. Memory stays low because the worker processes are not containerised.
- Docker remains the least reliable component on this machine (five failures in one
  session). The mitigation is that **nothing irreplaceable lives in it**: every raw
  payload is in bronze, and `cpi replay <source> <day>` rebuilds the entire warehouse
  with no upstream traffic and no quota spend. This was not theoretical -- the Postgres
  volume was lost to Docker's storage corruption and rebuilt from bronze in 30 seconds
  (3,420 events, 1,309 products, 111 partitions).
- The Neon exercise was still worth it: it proved the schema is portable (ran unmodified
  on Postgres 18), it is the natural Phase 6 target, and the per-day replay figures on
  Neon (2,996 then 255 inserts) matched the local rebuild exactly, which is good
  evidence the bulk CDC path is deterministic across Postgres versions.
- The Hyper-V firewall rules added during investigation (`scripts/setup-wsl-firewall.ps1`)
  are inert under this decision. They are harmless and left in place, with the script
  retained as documentation of what was tried.
- The WSL Postgres/Redis services are installed but `systemctl disable`d, so they do not
  compete for memory. They are a working offline fallback if Docker fails again *and*
  the boundary problem is ever solved.
