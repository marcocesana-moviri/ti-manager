# Splunk Threat Intelligence (TI) Manager

This repository contains a high-performance Splunk app/add-on designed to ingest, aggregate, and synchronize Threat Intelligence (TI) IP feeds into Splunk KV Store collections. The synchronized lists are then utilized by network security devices like **F5** and **Palo Alto Networks** firewalls.

## 🚀 Key Features

- **Multi-Target Architecture:** Declarative `TargetProfile` configurations allow managing different firewalls (F5, Palo Alto) with distinct synchronization rules, frequencies, and target KV Store collections using a single unified core engine.
- **Ultra-Fast Network Math:** Leverages C-level primitive functions (`socket.inet_pton`) for IPv4 parsing, achieving up to 20x faster processing compared to native Python `ipaddress` object instantiation.
- **Two-Tier State Management:** Zero-I/O execution when feeds are unchanged, combined with effective CIDR hashing to prevent unnecessary API calls to Splunk.
- **Differential KV Store Sync:** Computes exact delta (added/removed IPs) and applies changes via parallel chunked batch operations, drastically reducing Splunk Search Head CPU/Memory load.
- **Smart Feed Ingestion:** Supports HTTP Conditional Requests (`ETag` / `Last-Modified`) to avoid downloading and parsing unchanged external feeds.
- **Self-Healing:** Periodically (e.g., every 6 hours) cross-references the local computed state with the actual remote Splunk KV Store state to automatically fix manual unauthorized alterations or drift.

---

## 🏗️ Architecture

The app is built around three main phases: **Feed Ingestion**, **Core Orchestration & Math**, and **Target Synchronization**.

### 1. Feed Ingestion (`get_ti_helper.py`)

This modular input is responsible for fetching external threat feeds (e.g., Abuse.ch, Emerging Threats) and saving them as local CSV files.

- **Streaming & Regex:** Downloads large files in memory-efficient chunks (`stream=True`) and extracts IPs/CIDRs using user-defined regular expressions.
- **HTTP Cache Support:** Saves `ETag` and `Last-Modified` headers in a `.meta.json` sidecar file. If the remote server responds with `304 Not Modified`, it gracefully skips processing.
- **Atomic Writes:** Updates local `.csv` files using temporary files and `os.replace`. If the newly parsed IP list is identical to the existing CSV, it skips the write operation entirely, preserving the OS `mtime` (Modification Time).

### 2. Core Engine (`ti_sync_core.py`)

The heavy-lifter shared library. It abstracts the KV Store client, handles network mathematics, audits event generation, and manages the state tracking.

### 3. Target Profiles (`merge_ti_f5_helper.py`, `merge_ti_paloalto_helper.py`)

These are lightweight modular inputs acting as wrappers around `ti_sync_core.py`. They define a `TargetProfile` dataclass specifying:

- Target collections (`denylist_f5`, `denylist_paloalto`, `allowlist`).
- Which manual/dependency lists to fetch before processing.
- Whether to synchronize the allowlist or trigger a remote SPL CSV export (`| outputlookup`).

---

## 🧠 Deep Dive: Two-Tier State Management

To minimize resource utilization, the sync engine uses a highly optimized two-tier caching mechanism saved in a `state_<target>.json` file.

### Tier 1: OS-Level Metadata (Zero-I/O Check)

Before opening any of the potentially massive `.csv` feeds, the engine stats all required files and collects their size and modification time (`st_mtime_ns`, `st_size`).

- **If metadata matches the previous run:** The engine immediately stops (execution time `< 0.2s`). No files are opened, and no API calls are made to Splunk.

### Tier 2: Effective CIDR Hash

If a file _was_ updated (Tier-1 missed), the engine parses the IPs, merges overlapping ranges, and subtracts the whitelists. It then hashes the **final aggregated CIDR set**.

- **Why?** An external feed might add an IP that is _already covered_ by an existing `/16` subnet, or an IP that falls inside your Whitelist. In both cases, the final enforcement boundaries haven't changed.
- **Action:** If the `effective_bl_hash` remains identical, the engine updates the local state file but **skips the KV Store diff and push completely**, saving significant API overhead.

---

## 🧮 Deep Dive: Network Optimization

Merging hundreds of thousands of IPs and CIDRs is computationally expensive. The engine approaches this by transforming IP objects into flat numeric intervals (Integers):

1. **Fast-Path Parsing:** Individual IPv4 addresses are converted to 32-bit integers via `struct.unpack("!I", socket.inet_pton(socket.AF_INET, ip))`. IPv6 and CIDRs use the standard `ipaddress` library.
2. **Interval Merging (O(N log N)):** `[(start_int, end_int), ...]` tuples are sorted and overlapping/adjacent intervals are collapsed into contiguous blocks.
3. **Whitelist Subtraction (O(N + M)):** The engine walks through the merged Blacklist and Whitelist intervals simultaneously, carving out exceptions and splitting blacklist ranges where they overlap with whitelists.
4. **CIDR Rebuilding:** The final disjoint integer intervals are converted back to the minimum number of exact CIDR subnets using `ipaddress.summarize_address_range`.

---

## 🔌 Splunk KV Store Interaction Optimizations

The `SplunkKVStoreClient` class includes several defenses against Splunk Search Head overload and network timeouts:

- **Explicit Field Projection:** Fetching the existing state utilizes `fields=ip,_key:0,_user:0`. By explicitly dropping `_key` (32-char MD5) and `_user` (`nobody`), the JSON payload and Splunk's serialization CPU cost are reduced by **over 70%**.
- **Parallel Pagination & Batching:** Pages are downloaded concurrently using a `ThreadPoolExecutor` with a conservative worker limit (`MAX_KVSTORE_WORKERS=2`). Insertions and Deletions use the `batch_save` and `$in` JSON query endpoints in chunks of 1,000 to 2,000 records.
- **Resilient Retries:** Employs decoupled timeouts (`connect=10s`, `read=90s`). If a `ReadTimeout` occurs (meaning Splunk is struggling to generate the response), it backs off exponentially up to 30 seconds per attempt, preventing compounding stress on the `splunkd` daemon.
- **Continuous SPL Export:** For targets that require it (e.g., F5), `| inputlookup ... | eval time=now() | outputlookup` runs at the end of every cycle, even if no IPs changed, to ensure Splunk consumers know the list is fresh and actively managed.

---

## 📂 Project Structure

```text
├── bin/
│   ├── configs.py                    # Global constants, chunk sizes, timeouts
│   ├── get_ti_helper.py              # Ingests external feeds -> CSV
│   ├── ti_sync_core.py               # Core Engine (Math, KV Store, State, Audit)
│   ├── merge_ti_f5_helper.py         # Mod Input wrapping core for F5
│   └── merge_ti_paloalto_helper.py   # Mod Input wrapping core for Palo Alto
│
└── lookups/
    ├── blacklists/                   # Downloaded raw threat feeds (CSV)
    ├── whitelists/                   # Downloaded allowlists & manual exclusions (CSV)
    └── master/
        ├── state_f5.json             # Two-tier cache state for F5
        └── state_paloalto.json       # Two-tier cache state for Palo Alto
```

## 🛠️ Troubleshooting & Logs

All scripts log natively to Splunk `splunkd.log` (or internal indexes) using a unified `key=value` structured format, making it extremely easy to build dashboards on top of the add-on's performance.

Look for the `[TI MANAGER ...]` tags:

- `[SYNC]` - State transitions, Tier-1/Tier-2 skips, self-healing events.
- `[NETWORK]` - Time taken to read CSVs, merge intervals, and compute final CIDRs.
- `[KVSTORE]` - Batch operations, API retries, and pagination times.
- `[AUDIT]` - Number of events written to the Splunk index indicating added/removed IPs.

Example query to check synchronization times:

```spl
index=_internal "TI MANAGER INFO" "Cycle completed successfully"
| rex field=_raw "target=(?<target>\w+) .* total_elapsed=(?<elapsed_sec>[\d\.]+)s"
| timechart max(elapsed_sec) by target
```
