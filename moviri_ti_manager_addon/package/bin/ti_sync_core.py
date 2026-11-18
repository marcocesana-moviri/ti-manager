from __future__ import annotations

import glob
import hashlib
import ipaddress
import itertools
import json
import logging
import os
import socket
import struct
import tempfile
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator, Iterable, Iterator, List, Optional, Set, Tuple, Union

import requests
from requests.adapters import HTTPAdapter
import urllib3

# Disabilita i warning InsecureRequestWarning dovuti a verify=False verso la Search Head
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from solnlib import conf_manager, credentials, log
from splunklib import modularinput as smi

from configs import (
    ACCOUNT_CONF_FILE_NAME,
    ADDON_NAME,
    COLLECTION_ALLOWLIST,
    COLLECTION_MANUAL_ALLOWLIST,
    COLLECTION_MANUAL_DENYLIST,
    CONF_FILE_NAME,
    CONNECT_TIMEOUT_SECONDS,
    CSV_HEADERS,
    DEFAULT_APP_NAME,
    EVENTS_PER_SECOND_BUCKET,
    KVSTORE_ADDITION_CHUNK_SIZE,
    KVSTORE_DELETION_CHUNK_SIZE,
    KVSTORE_READ_PAGE_SIZE,
    LOG_DEBUG_TAG,
    LOG_ERROR_TAG,
    LOG_INFO_TAG,
    LOG_WARNING_TAG,
    MAX_KVSTORE_WORKERS,
    READ_TIMEOUT_SECONDS,
    REQUEST_RETRIES,
    RETRY_BACKOFF_SECONDS,
    SELF_HEALING_INTERVAL_SECONDS,
    SPL_EXPORT_READ_TIMEOUT_SECONDS,
    STATIC_PRIVATE_NETWORKS,
)

# Primitive C-level e type alias interni
_UNPACK_IPV4 = struct.Struct("!I").unpack
_INET_PTON = socket.inet_pton
_AF_INET = socket.AF_INET

IpRange = Tuple[int, int]
NetworkInput = Union[str, ipaddress.IPv4Network, ipaddress.IPv6Network]


# ==============================================================================
# MODELLI DI CONFIGURAZIONE E PROFILO TARGET
# ==============================================================================

@dataclass(frozen=True)
class TargetProfile:
    """Definisce dichiarativamente il comportamento di sincronizzazione per un firewall target."""
    target_name: str
    state_filename: str
    denylist_collection: str
    manual_collections_to_fetch: Tuple[str, ...]
    blacklist_patterns: Tuple[str, ...]
    whitelist_patterns: Tuple[str, ...] = ("*.csv",)
    allowlist_collection: str = COLLECTION_ALLOWLIST
    sync_allowlist: bool = False
    export_csv_lookup: bool = False


@dataclass(frozen=True)
class InputConfig:
    """Parametri risolti per una stanza del modular input Splunk."""
    raw_name: str
    normalized_name: str
    index: str
    sourcetype: str
    account_name: str
    search_head: str
    search_head_port: int
    app_name: str = DEFAULT_APP_NAME

    @classmethod
    def from_stanza(cls, raw_name: str, stanza: Dict[str, Any]) -> InputConfig:
        return cls(
            raw_name=raw_name,
            normalized_name=raw_name.split("/")[-1],
            index=stanza.get("index") or "default",
            sourcetype=stanza.get("sourcetype") or "stash",
            account_name=(stanza.get("account") or "").strip(),
            search_head=(stanza.get("search_head") or "").strip(),
            search_head_port=int(stanza.get("search_head_port") or 8089),
        )


@dataclass(frozen=True)
class LookupDirs:
    """Percorsi delle directory locali di lavoro per feed CSV e file di stato."""
    base: str
    blacklists: str
    whitelists: str
    master: str

    @classmethod
    def initialize(cls) -> LookupDirs:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.abspath(os.path.join(script_dir, "..", "lookups"))
        dirs = cls(
            base=base_dir,
            blacklists=os.path.join(base_dir, "blacklists"),
            whitelists=os.path.join(base_dir, "whitelists"),
            master=os.path.join(base_dir, "master"),
        )
        for path in (dirs.base, dirs.blacklists, dirs.whitelists, dirs.master):
            os.makedirs(path, exist_ok=True)
        return dirs

    def resolve_files(self, folder: str, patterns: Tuple[str, ...]) -> List[str]:
        matched: Set[str] = set()
        for pattern in patterns:
            matched.update(glob.glob(os.path.join(folder, pattern)))
        return sorted(p for p in matched if os.path.isfile(p))


# ==============================================================================
# LOGGING, CREDENZIALI E I/O ATOMICO SU DISCO
# ==============================================================================

def logger_for_input(input_name: str) -> logging.Logger:
    return log.Logs().get_logger(f"{ADDON_NAME.lower()}_{input_name}")


def get_account_settings(
    session_key: str, account_name: str, logger: logging.Logger
) -> Tuple[Optional[str], Optional[str]]:
    realm = f"__REST_CREDENTIAL__#{ADDON_NAME}#configs/conf-{ACCOUNT_CONF_FILE_NAME}"
    try:
        cfm = conf_manager.ConfManager(session_key, ADDON_NAME, realm=realm)
        account_data = cfm.get_conf(ACCOUNT_CONF_FILE_NAME).get(account_name)
        username = account_data.get("splunk_username") if account_data else None

        cm = credentials.CredentialManager(session_key, ADDON_NAME, realm=realm)
        raw_secret = cm.get_password(account_name)
        password = json.loads(raw_secret).get("splunk_password") if raw_secret else None

        return username, password
    except Exception as exc:
        logger.error(
            f"{LOG_ERROR_TAG} [AUTH] Failed retrieving credentials account={account_name} error={exc!r}"
        )
        return None, None


def atomic_write_if_changed(target_path: str, content: str) -> bool:
    """
    Scrive `content` su `target_path` in modo atomico (mkstemp + os.replace)
    solo se il contenuto differisce da quello già presente su disco.
    """
    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as existing:
                if existing.read() == content:
                    return False
        except OSError:
            pass

    target_dir = os.path.dirname(target_path)
    prefix = f".{os.path.basename(target_path)}_"
    fd, tmp_path = tempfile.mkstemp(dir=target_dir, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, mode="w", newline="", encoding="utf-8") as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, target_path)
        return True
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _chunked(iterable: Iterable[Any], chunk_size: int) -> Iterator[List[Any]]:
    iterator = iter(iterable)
    while True:
        batch = list(itertools.islice(iterator, chunk_size))
        if not batch:
            break
        yield batch


def _md5_key(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _hash_cidr_set(cidrs: Set[str]) -> str:
    hasher = hashlib.sha256()
    for cidr in sorted(cidrs):
        hasher.update(cidr.encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


# ==============================================================================
# GESTIONE STATO A DOPPIO LIVELLO (METADATA OS + HASH CIDR EFFETTIVI)
# ==============================================================================

def _collect_files_metadata(dirs: LookupDirs, filepaths: List[str]) -> Dict[str, List[int]]:
    """Raccoglie [mtime_ns, size] per ciascun file sorgente senza leggerne il contenuto."""
    metadata: Dict[str, List[int]] = {}
    for path in filepaths:
        try:
            st = os.stat(path)
            rel_path = os.path.relpath(path, dirs.base).replace("\\", "/")
            metadata[rel_path] = [st.st_mtime_ns, st.st_size]
        except OSError:
            continue
    return metadata


def _load_state(state_path: str) -> Dict[str, Any]:
    if not os.path.exists(state_path):
        return {}
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state_path: str, state_data: Dict[str, Any]) -> None:
    serialized = json.dumps(state_data, indent=2, sort_keys=True) + "\n"
    atomic_write_if_changed(state_path, serialized)


# ==============================================================================
# MOTORE DI PARSING, MERGE E SOTTRAZIONE INTERVALLI IP/CIDR
# ==============================================================================

def parse_network_to_range(candidate: NetworkInput) -> Optional[Tuple[int, int, int]]:
    """
    Converte un IP o CIDR nella tupla (ip_version, start_int, end_int).
    Usa socket.inet_pton come fast-path C-level per singoli indirizzi IPv4.
    """
    if isinstance(candidate, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
        return (
            candidate.version,
            int(candidate.network_address),
            int(candidate.broadcast_address),
        )

    if "/" not in candidate and ":" not in candidate:
        try:
            ip_int = _UNPACK_IPV4(_INET_PTON(_AF_INET, candidate))[0]
            return 4, ip_int, ip_int
        except OSError:
            pass

    try:
        net = ipaddress.ip_network(candidate, strict=False)
        return net.version, int(net.network_address), int(net.broadcast_address)
    except ValueError:
        return None


def _read_ranges_from_files(
    logger: logging.Logger, filepaths: List[str], list_label: str
) -> Tuple[List[IpRange], List[IpRange]]:
    ipv4_ranges: List[IpRange] = []
    ipv6_ranges: List[IpRange] = []
    start_time = time.perf_counter()

    for filepath in filepaths:
        if not os.path.exists(filepath):
            continue
        try:
            with open(filepath, mode="r", encoding="utf-8-sig") as f:
                for line in f:
                    candidate = line.split(",", 1)[0].strip()
                    if not candidate or candidate.lower() in CSV_HEADERS:
                        continue

                    parsed = parse_network_to_range(candidate)
                    if parsed is None:
                        continue

                    if parsed[0] == 4:
                        ipv4_ranges.append((parsed[1], parsed[2]))
                    else:
                        ipv6_ranges.append((parsed[1], parsed[2]))
        except Exception as exc:
            logger.warning(
                f"{LOG_WARNING_TAG} [NETWORK] Failed reading CSV file={filepath} error={exc!r}"
            )

    elapsed = time.perf_counter() - start_time
    logger.debug(
        f"{LOG_DEBUG_TAG} [NETWORK] Loaded CSV feeds type={list_label} files={len(filepaths)} "
        f"ipv4_entries={len(ipv4_ranges)} ipv6_entries={len(ipv6_ranges)} elapsed={elapsed:.2f}s"
    )
    return ipv4_ranges, ipv6_ranges


def _merge_ranges(ranges: List[IpRange]) -> List[IpRange]:
    if not ranges:
        return []

    ranges.sort()
    merged: List[IpRange] = [ranges[0]]

    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            if end > last_end:
                merged[-1] = (last_start, end)
        else:
            merged.append((start, end))

    return merged


def _subtract_ranges(bl_ranges: List[IpRange], wl_ranges: List[IpRange]) -> List[IpRange]:
    if not bl_ranges:
        return []
    if not wl_ranges:
        return list(bl_ranges)

    result: List[IpRange] = []
    wl_idx = 0
    wl_len = len(wl_ranges)

    for b_start, b_end in bl_ranges:
        current_start = b_start

        while wl_idx < wl_len and wl_ranges[wl_idx][1] < current_start:
            wl_idx += 1

        scan_idx = wl_idx
        while scan_idx < wl_len and wl_ranges[scan_idx][0] <= b_end:
            w_start, w_end = wl_ranges[scan_idx]
            if current_start < w_start:
                result.append((current_start, w_start - 1))
            if w_end + 1 > current_start:
                current_start = w_end + 1
            if current_start > b_end:
                break
            scan_idx += 1

        if current_start <= b_end:
            result.append((current_start, b_end))

    return result


def _ranges_to_cidr_set(v4_ranges: List[IpRange], v6_ranges: List[IpRange]) -> Set[str]:
    summarize = ipaddress.summarize_address_range
    ipv4 = ipaddress.IPv4Address
    ipv6 = ipaddress.IPv6Address

    return {
        *(str(net) for s, e in v4_ranges for net in summarize(ipv4(s), ipv4(e))),
        *(str(net) for s, e in v6_ranges for net in summarize(ipv6(s), ipv6(e))),
    }


def compute_effective_networks(
    logger: logging.Logger,
    bl_files: List[str],
    wl_files: List[str],
) -> Tuple[Set[str], Set[str]]:
    """Aggrega blacklist e whitelist, sottrae gli intervalli esclusi e ricostruisce i set CIDR."""
    wl_v4_raw, wl_v6_raw = _read_ranges_from_files(logger, wl_files, "whitelist")

    for static_net in STATIC_PRIVATE_NETWORKS:
        parsed = parse_network_to_range(static_net)
        if parsed is not None:
            if parsed[0] == 4:
                wl_v4_raw.append((parsed[1], parsed[2]))
            else:
                wl_v6_raw.append((parsed[1], parsed[2]))

    bl_v4_raw, bl_v6_raw = _read_ranges_from_files(logger, bl_files, "blacklist")

    t_start = time.perf_counter()
    wl_v4_merged = _merge_ranges(wl_v4_raw)
    wl_v6_merged = _merge_ranges(wl_v6_raw)
    bl_v4_merged = _merge_ranges(bl_v4_raw)
    bl_v6_merged = _merge_ranges(bl_v6_raw)

    filtered_v4 = _subtract_ranges(bl_v4_merged, wl_v4_merged)
    filtered_v6 = _subtract_ranges(bl_v6_merged, wl_v6_merged)

    final_bl = _ranges_to_cidr_set(filtered_v4, filtered_v6)
    final_wl = _ranges_to_cidr_set(wl_v4_merged, wl_v6_merged)

    logger.info(
        f"{LOG_INFO_TAG} [NETWORK] CIDR optimization completed "
        f"blacklist_subnets={len(final_bl)} whitelist_subnets={len(final_wl)} "
        f"elapsed={time.perf_counter() - t_start:.2f}s"
    )
    return final_bl, final_wl


def diff_ip_lists(
    logger: logging.Logger, desired_ips: Set[str], current_remote_ips: Set[str]
) -> Tuple[Set[str], Set[str]]:
    added_ips = desired_ips - current_remote_ips
    removed_ips = current_remote_ips - desired_ips

    logger.info(
        f"{LOG_INFO_TAG} [DIFF] Computed KV Store delta "
        f"added={len(added_ips)} removed={len(removed_ips)} unchanged={len(desired_ips) - len(added_ips)}"
    )
    return added_ips, removed_ips


# ==============================================================================
# CLIENT HTTP VERSO SPLUNK KV STORE E SEARCH JOBS
# ==============================================================================

class SplunkKVStoreClient:
    """Gestisce tutte le chiamate REST verso Splunk KV Store e Search Jobs."""

    def __init__(
        self,
        logger: logging.Logger,
        search_head: str,
        search_head_port: int,
        app_name: str,
        username: str,
        password: str,
    ) -> None:
        self.logger = logger
        self.base_ns_url = f"https://{search_head}:{search_head_port}/servicesNS/nobody/{app_name}"
        self.session = self._create_session(username, password)

    @staticmethod
    def _create_session(username: str, password: str) -> requests.Session:
        session = requests.Session()
        session.auth = (username, password)
        session.verify = False
        pool_size = MAX_KVSTORE_WORKERS * 2
        adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> SplunkKVStoreClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _collection_url(self, collection_name: str) -> str:
        return f"{self.base_ns_url}/storage/collections/data/{collection_name}"

    def _request(
        self,
        method: str,
        url: str,
        operation: str,
        allow_404: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        kwargs.setdefault("timeout", (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS))
        for attempt in range(1, REQUEST_RETRIES + 1):
            try:
                response = self.session.request(method, url, **kwargs)
                if allow_404 and response.status_code == 404:
                    return response
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as exc:
                detail = ""
                if getattr(exc, "response", None) is not None:
                    detail = f" response_body={exc.response.text!r}"

                if attempt < REQUEST_RETRIES:
                    if isinstance(exc, requests.exceptions.ReadTimeout):
                        backoff = min(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)), 30)
                    else:
                        backoff = RETRY_BACKOFF_SECONDS * attempt

                    self.logger.warning(
                        f"{LOG_WARNING_TAG} [KVSTORE] Retryable error operation={operation} "
                        f"attempt={attempt}/{REQUEST_RETRIES} backoff={backoff}s error={exc!r}{detail}"
                    )
                    time.sleep(backoff)
                else:
                    self.logger.error(
                        f"{LOG_ERROR_TAG} [KVSTORE] Request failed permanently operation={operation} "
                        f"attempts={REQUEST_RETRIES} error={exc!r}{detail}"
                    )
                    raise
        raise RuntimeError(f"Unexpected retry exit for operation={operation}")

    def _iter_pages(self, collection_name: str, fields: str) -> Generator[List[Dict[str, Any]], None, None]:
        """Paginazione con dimensione pagina controllata e proiezione esplicita dei campi."""
        url = self._collection_url(collection_name)

        def fetch_page(skip_offset: int) -> List[Dict[str, Any]]:
            resp = self._request(
                "GET",
                url,
                operation=f"fetch_page(collection={collection_name}, skip={skip_offset})",
                params={"limit": KVSTORE_READ_PAGE_SIZE, "skip": skip_offset, "fields": fields},
            )
            return resp.json() or []

        first_page = fetch_page(0)
        if not first_page:
            return
        yield first_page
        if len(first_page) < KVSTORE_READ_PAGE_SIZE:
            return

        next_skip = KVSTORE_READ_PAGE_SIZE
        with ThreadPoolExecutor(max_workers=MAX_KVSTORE_WORKERS) as executor:
            while True:
                skips = [next_skip + i * KVSTORE_READ_PAGE_SIZE for i in range(MAX_KVSTORE_WORKERS)]
                futures = [executor.submit(fetch_page, offset) for offset in skips]
                reached_end = False

                for idx, future in enumerate(futures):
                    page = future.result()
                    if page:
                        yield page
                    if len(page) < KVSTORE_READ_PAGE_SIZE:
                        for remaining in futures[idx + 1 :]:
                            remaining.cancel()
                        reached_end = True
                        break

                if reached_end:
                    break
                next_skip += MAX_KVSTORE_WORKERS * KVSTORE_READ_PAGE_SIZE

    def _batch_insert_ips(self, collection_name: str, ips: Set[str]) -> None:
        if not ips:
            return

        batch_url = f"{self._collection_url(collection_name)}/batch_save"
        headers = {"Content-Type": "application/json"}
        records = ({"_key": _md5_key(ip), "ip": ip} for ip in ips)
        chunks = list(_chunked(records, KVSTORE_ADDITION_CHUNK_SIZE))

        def push_chunk(chunk: List[Dict[str, str]]) -> None:
            self._request(
                "POST",
                batch_url,
                operation=f"batch_save(collection={collection_name}, count={len(chunk)})",
                headers=headers,
                json=chunk,
            )

        if len(chunks) == 1:
            push_chunk(chunks[0])
        else:
            with ThreadPoolExecutor(max_workers=MAX_KVSTORE_WORKERS) as executor:
                for future in [executor.submit(push_chunk, c) for c in chunks]:
                    future.result()

    def download_manual_list(self, collection_name: str, dirs: LookupDirs) -> None:
        """
        Scarica una collection sorgente dal KV Store.
        Aggiorna il file su disco solo se il contenuto differisce, preservando i timestamp OS
        quando non ci sono variazioni reali.
        """
        start_time = time.perf_counter()
        is_manual_denylist = collection_name == COLLECTION_MANUAL_DENYLIST
        fields = "ip,target" if is_manual_denylist else "ip"
        save_dir = dirs.whitelists if collection_name == COLLECTION_MANUAL_ALLOWLIST else dirs.blacklists

        total_records = 0
        updated_files = 0

        if is_manual_denylist:
            ips_both: List[str] = []
            ips_f5: List[str] = []

            for page in self._iter_pages(collection_name, fields):
                total_records += len(page)
                for item in page:
                    ip = item.get("ip")
                    if not ip:
                        continue
                    target = item.get("target")
                    if target == "Both (F5+PaloAlto)":
                        ips_both.append(ip)
                    elif target == "F5":
                        ips_f5.append(ip)

            both_content = "ip\n" + ("\n".join(ips_both) + "\n" if ips_both else "")
            f5_content = "ip\n" + ("\n".join(ips_f5) + "\n" if ips_f5 else "")

            if atomic_write_if_changed(
                os.path.join(save_dir, f"{collection_name}_f5_paloalto.csv"), both_content
            ):
                updated_files += 1
            if atomic_write_if_changed(
                os.path.join(save_dir, f"{collection_name}_f5.csv"), f5_content
            ):
                updated_files += 1
        else:
            ips_all: List[str] = []
            for page in self._iter_pages(collection_name, fields):
                total_records += len(page)
                ips_all.extend(item["ip"] for item in page if item.get("ip"))

            content = "ip\n" + ("\n".join(ips_all) + "\n" if ips_all else "")
            if atomic_write_if_changed(os.path.join(save_dir, f"{collection_name}.csv"), content):
                updated_files += 1

        elapsed = time.perf_counter() - start_time
        self.logger.info(
            f"{LOG_INFO_TAG} [DOWNLOAD] Collection synced collection={collection_name} "
            f"records={total_records} files_updated={updated_files} elapsed={elapsed:.2f}s"
        )

    def fetch_collection_ips(self, collection_name: str) -> Set[str]:
        start_time = time.perf_counter()
        existing_ips: Set[str] = set()

        for page in self._iter_pages(collection_name, fields="ip"):
            existing_ips.update(item["ip"] for item in page if item.get("ip"))

        elapsed = time.perf_counter() - start_time
        self.logger.info(
            f"{LOG_INFO_TAG} [KVSTORE] Remote state loaded collection={collection_name} "
            f"records={len(existing_ips)} elapsed={elapsed:.2f}s"
        )
        return existing_ips

    def replace_collection_ips(self, collection_name: str, whitelist_ips: Set[str]) -> None:
        start_time = time.perf_counter()
        self._request(
            "DELETE",
            self._collection_url(collection_name),
            operation=f"truncate_collection(collection={collection_name})",
            allow_404=True,
        )
        self._batch_insert_ips(collection_name, whitelist_ips)

        elapsed = time.perf_counter() - start_time
        self.logger.info(
            f"{LOG_INFO_TAG} [KVSTORE] Allowlist synchronized collection={collection_name} "
            f"records={len(whitelist_ips)} elapsed={elapsed:.2f}s"
        )

    def sync_collection_diff(
        self, collection_name: str, added_ips: Set[str], removed_ips: Set[str]
    ) -> None:
        start_time = time.perf_counter()
        base_url = self._collection_url(collection_name)

        if removed_ips:
            keys_gen = (_md5_key(ip) for ip in removed_ips)
            delete_chunks = list(_chunked(keys_gen, KVSTORE_DELETION_CHUNK_SIZE))

            def delete_chunk(keys: List[str]) -> None:
                encoded_query = urllib.parse.quote(json.dumps({"_key": {"$in": keys}}))
                self._request(
                    "DELETE",
                    f"{base_url}?query={encoded_query}",
                    operation=f"batch_delete(collection={collection_name}, count={len(keys)})",
                    allow_404=True,
                )

            if len(delete_chunks) == 1:
                delete_chunk(delete_chunks[0])
            else:
                with ThreadPoolExecutor(max_workers=MAX_KVSTORE_WORKERS) as executor:
                    for future in [executor.submit(delete_chunk, c) for c in delete_chunks]:
                        future.result()

        if added_ips:
            self._batch_insert_ips(collection_name, added_ips)

        elapsed = time.perf_counter() - start_time
        self.logger.info(
            f"{LOG_INFO_TAG} [KVSTORE] Denylist diff applied collection={collection_name} "
            f"added={len(added_ips)} removed={len(removed_ips)} elapsed={elapsed:.2f}s"
        )

    def export_collection_to_csv(self, collection_name: str) -> None:
        start_time = time.perf_counter()
        csv_name = f"{collection_name}_managedlookup.csv"
        spl_query = f"| inputlookup {collection_name} | eval time=now() | table ip time | outputlookup {csv_name}"

        self.logger.debug(
            f"{LOG_DEBUG_TAG} [SPL_EXPORT] Triggering remote CSV lookup export target={csv_name}"
        )
        response = self._request(
            "POST",
            f"{self.base_ns_url}/search/jobs",
            operation=f"spl_csv_export(target={csv_name})",
            data={"search": spl_query, "exec_mode": "oneshot", "output_mode": "json"},
            timeout=(CONNECT_TIMEOUT_SECONDS, SPL_EXPORT_READ_TIMEOUT_SECONDS),
        )

        try:
            payload = response.json()
            for msg in payload.get("messages", []):
                if msg.get("type", "").upper() in ("FATAL", "ERROR"):
                    err_text = msg.get("text", "Unknown SPL execution error")
                    self.logger.error(
                        f"{LOG_ERROR_TAG} [SPL_EXPORT] SPL search error target={csv_name} message={err_text!r}"
                    )
                    raise RuntimeError(f"SPL export failed for {csv_name}: {err_text}")
        except ValueError:
            pass

        elapsed = time.perf_counter() - start_time
        self.logger.info(
            f"{LOG_INFO_TAG} [SPL_EXPORT] Remote CSV lookup updated target={csv_name} elapsed={elapsed:.2f}s"
        )


# ==============================================================================
# EMISSIONE EVENTI DI AUDIT IN SPLUNK
# ==============================================================================

def _generate_audit_events(
    ips: Iterable[str], action: str, list_name: str
) -> Generator[str, None, None]:
    base_time = datetime.now(timezone.utc)
    cached_bucket = -1
    cached_timestamp = ""

    for idx, ip in enumerate(ips):
        bucket = idx // EVENTS_PER_SECOND_BUCKET
        if bucket != cached_bucket:
            cached_bucket = bucket
            cached_timestamp = (base_time + timedelta(seconds=bucket)).isoformat()
        yield f'{cached_timestamp} action="{action}", ip="{ip}", list_name="{list_name}"'


def _write_events(
    index: str,
    sourcetype: str,
    logs: Iterable[str],
    input_name: str,
    event_writer: smi.EventWriter,
    logger: logging.Logger,
) -> int:
    written = 0
    for event_data in logs:
        try:
            event_writer.write_event(smi.Event(data=event_data, index=index, sourcetype=sourcetype))
            written += 1
        except Exception as exc:
            logger.error(
                f"{LOG_ERROR_TAG} [AUDIT] Failed writing event input={input_name} error={exc!r}"
            )
    return written


# ==============================================================================
# ORCHESTRAZIONE PIPELINE DI SINCRONIZZAZIONE E ENTRYPOINT MODULAR INPUT
# ==============================================================================

def _sync_kvstore_if_needed(
    logger: logging.Logger,
    config: InputConfig,
    profile: TargetProfile,
    dirs: LookupDirs,
    state_path: str,
    prev_state: Dict[str, Any],
    kv_client: SplunkKVStoreClient,
    event_writer: smi.EventWriter,
    now_ts: float,
    force_reconcile: bool,
) -> None:
    """Esegue la sincronizzazione differenziale verso il KV Store solo in presenza di variazioni."""
    last_reconcile_ts = float(prev_state.get("last_reconcile_ts", 0.0))

    # 1. Scarica autonomamente le collection manuali/ES richieste dal profilo target
    for collection in profile.manual_collections_to_fetch:
        kv_client.download_manual_list(collection, dirs)

    # 2. LIVELLO 1: Verifica rapida su metadati OS (mtime_ns + size) senza aprire i CSV
    bl_files = dirs.resolve_files(dirs.blacklists, profile.blacklist_patterns)
    wl_files = dirs.resolve_files(dirs.whitelists, profile.whitelist_patterns)
    current_files_meta = _collect_files_metadata(dirs, bl_files + wl_files)

    if not force_reconcile and current_files_meta == prev_state.get("files_meta"):
        logger.info(
            f"{LOG_INFO_TAG} [SYNC] Tier-1 metadata unchanged; skipping CIDR rebuild "
            f"target={profile.target_name} tracked_files={len(current_files_meta)}"
        )
        return

    # 3. Estrazione, fusione intervalli e sottrazione whitelist
    new_blacklist, new_whitelist = compute_effective_networks(logger, bl_files, wl_files)
    bl_hash = _hash_cidr_set(new_blacklist)
    wl_hash = _hash_cidr_set(new_whitelist)

    bl_changed = force_reconcile or (bl_hash != prev_state.get("effective_bl_hash"))
    wl_changed = profile.sync_allowlist and (
        force_reconcile or (wl_hash != prev_state.get("effective_wl_hash"))
    )

    # 4. LIVELLO 2: Se i file sono cambiati ma i CIDR effettivi sono identici, evita query KV Store
    if not bl_changed and not wl_changed:
        _save_state(
            state_path,
            {
                "last_reconcile_ts": last_reconcile_ts,
                "files_meta": current_files_meta,
                "effective_bl_hash": bl_hash,
                "effective_wl_hash": wl_hash,
            },
        )
        logger.info(
            f"{LOG_INFO_TAG} [SYNC] Tier-2 effective CIDR set unchanged; skipping KV Store push "
            f"target={profile.target_name} bl_hash={bl_hash[:12]}"
        )
        return

    # 5. Sincronizzazione Allowlist (se prevista dal profilo)
    if wl_changed:
        kv_client.replace_collection_ips(profile.allowlist_collection, new_whitelist)

    # 6. Calcolo delta contro lo stato reale KV Store e push incrementale
    if bl_changed:
        remote_blacklist = kv_client.fetch_collection_ips(profile.denylist_collection)
        added_ips, removed_ips = diff_ip_lists(logger, new_blacklist, remote_blacklist)

        if added_ips or removed_ips:
            kv_client.sync_collection_diff(profile.denylist_collection, added_ips, removed_ips)

            written_count = 0
            if added_ips:
                written_count += _write_events(
                    config.index,
                    config.sourcetype,
                    _generate_audit_events(added_ips, "added", profile.denylist_collection),
                    config.raw_name,
                    event_writer,
                    logger,
                )
            if removed_ips:
                written_count += _write_events(
                    config.index,
                    config.sourcetype,
                    _generate_audit_events(removed_ips, "removed", profile.denylist_collection),
                    config.raw_name,
                    event_writer,
                    logger,
                )

            log.events_ingested(
                logger, config.raw_name, config.sourcetype, written_count, config.index
            )
            logger.info(
                f"{LOG_INFO_TAG} [AUDIT] Ingested audit events target={profile.target_name} "
                f"count={written_count} index={config.index}"
            )

    # 7. Salvataggio atomico del nuovo stato solo a sincronizzazione KV Store completata
    _save_state(
        state_path,
        {
            "last_reconcile_ts": now_ts if force_reconcile else last_reconcile_ts,
            "files_meta": current_files_meta,
            "effective_bl_hash": bl_hash,
            "effective_wl_hash": wl_hash,
        },
    )


def _synchronize_target(
    logger: logging.Logger,
    config: InputConfig,
    profile: TargetProfile,
    username: str,
    password: str,
    event_writer: smi.EventWriter,
) -> None:
    cycle_start = time.perf_counter()
    now_ts = time.time()
    dirs = LookupDirs.initialize()
    state_path = os.path.join(dirs.master, profile.state_filename)
    prev_state = _load_state(state_path)

    last_reconcile_ts = float(prev_state.get("last_reconcile_ts", 0.0))
    force_reconcile = (now_ts - last_reconcile_ts) >= SELF_HEALING_INTERVAL_SECONDS

    logger.info(
        f"{LOG_INFO_TAG} [SYNC] Starting cycle target={profile.target_name} "
        f"input={config.normalized_name} self_healing_reconcile={force_reconcile}"
    )

    with SplunkKVStoreClient(
        logger=logger,
        search_head=config.search_head,
        search_head_port=config.search_head_port,
        app_name=config.app_name,
        username=username,
        password=password,
    ) as kv_client:
        _sync_kvstore_if_needed(
            logger=logger,
            config=config,
            profile=profile,
            dirs=dirs,
            state_path=state_path,
            prev_state=prev_state,
            kv_client=kv_client,
            event_writer=event_writer,
            now_ts=now_ts,
            force_reconcile=force_reconcile,
        )

        # Eseguito ad ogni ciclo per i profili che richiedono l'aggiornamento continuo di time=now()
        if profile.export_csv_lookup:
            kv_client.export_collection_to_csv(profile.denylist_collection)

    total_elapsed = time.perf_counter() - cycle_start
    logger.info(
        f"{LOG_INFO_TAG} [SYNC] Cycle completed successfully target={profile.target_name} "
        f"total_elapsed={total_elapsed:.2f}s"
    )


def execute_modular_input(
    inputs: smi.InputDefinition,
    event_writer: smi.EventWriter,
    profile: TargetProfile,
) -> None:
    """Entrypoint comune per l'esecuzione delle stanze di un modular input di merge."""
    session_key = inputs.metadata["session_key"]

    for raw_input_name, stanza in inputs.inputs.items():
        config = InputConfig.from_stanza(raw_input_name, stanza)
        logger = logger_for_input(config.normalized_name)

        try:
            log_level = conf_manager.get_log_level(
                logger=logger,
                session_key=session_key,
                app_name=ADDON_NAME,
                conf_name=CONF_FILE_NAME,
            )
            logger.setLevel(log_level)
            log.modular_input_start(logger, config.normalized_name)

            if not config.search_head or not config.account_name:
                logger.error(
                    f"{LOG_ERROR_TAG} [CONFIG] Missing required settings input={config.normalized_name} "
                    f"search_head={config.search_head!r} account={config.account_name!r}"
                )
                continue

            username, password = get_account_settings(session_key, config.account_name, logger)
            if not username or not password:
                logger.error(
                    f"{LOG_ERROR_TAG} [AUTH] Missing or invalid credentials input={config.normalized_name} "
                    f"account={config.account_name}"
                )
                continue

            _synchronize_target(logger, config, profile, username, password, event_writer)

        except Exception as exc:
            log.log_exception(
                logger,
                exc,
                LOG_ERROR_TAG,
                msg_before=(
                    f"[SYNC] Unhandled exception target={profile.target_name} "
                    f"input={config.normalized_name}: {exc}"
                ),
            )
        finally:
            log.modular_input_end(logger, config.normalized_name)