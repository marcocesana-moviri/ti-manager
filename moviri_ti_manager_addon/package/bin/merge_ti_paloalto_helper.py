import hashlib
import glob
import ipaddress
import logging
import os
import tempfile
import json
import urllib.parse
import requests
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List, Set, Iterable, Generator

# Disabilita i warning di InsecureRequestWarning dovuti a verify=False
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from solnlib import conf_manager, credentials, log
from splunklib import modularinput as smi

from configs import (
    ADDON_NAME,
    CONF_FILE_NAME,
    LOG_INFO_TAG,
    LOG_DEBUG_TAG,
    LOG_ERROR_TAG,
    LOG_WARNING_TAG,
    ACCOUNT_CONF_FILE_NAME,
    KVSTORE_LIMIT,
    KVSTORE_ADDITION_CHUNK_SIZE,
    KVSTORE_DELETION_CHUNK_SIZE,
    REQUEST_TIMEOUT,
    REQUEST_RETRIES,
    RETRY_BACKOFF_SECONDS,
    STATIC_PRIVATE_NETWORKS
)

def logger_for_input(input_name: str) -> logging.Logger:
    return log.Logs().get_logger(f"{ADDON_NAME.lower()}_{input_name}")


def _get_conf_manager(session_key: str, conf_file_name: str) -> conf_manager.ConfManager:
    return conf_manager.ConfManager(
        session_key,
        ADDON_NAME,
        realm=f"__REST_CREDENTIAL__#{ADDON_NAME}#configs/conf-{conf_file_name}",
    )


def _get_credential_manager(session_key: str, conf_file_name: str) -> credentials.CredentialManager:
    return credentials.CredentialManager(
        session_key,
        ADDON_NAME,
        realm=f"__REST_CREDENTIAL__#{ADDON_NAME}#configs/conf-{conf_file_name}",
    )


def get_lookups_dirs() -> dict[str, str]:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.abspath(os.path.join(script_dir, "..", "lookups"))
    dirs = {
        "base": base_dir,
        "blacklists": os.path.join(base_dir, "blacklists"),
        "whitelists": os.path.join(base_dir, "whitelists"),
        "master": os.path.join(base_dir, "master"),
    }
    for dir_path in dirs.values():
        os.makedirs(dir_path, exist_ok=True)      
    return dirs


def _calculate_state_hash(lookups_dirs: dict[str, str]) -> str:
    hasher = hashlib.md5()
    files_to_hash = []
    
    bl_dir = lookups_dirs["blacklists"]
    for target_file in ["manual_denylist.csv", "es_automatic_detection.csv"]:
        file_path = os.path.join(bl_dir, target_file)
        if os.path.exists(file_path):
            files_to_hash.append(file_path)
            
    wl_dir = lookups_dirs["whitelists"]
    files_to_hash.extend(glob.glob(os.path.join(wl_dir, "*.csv")))
    
    files_to_hash.sort()
    
    for filepath in files_to_hash:
        filename = os.path.basename(filepath)
        hasher.update(filename.encode('utf-8'))
        
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
                
    return hasher.hexdigest()


def _read_previous_state_hash(hash_path: str) -> str:
    if os.path.exists(hash_path):
        with open(hash_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return ""


def _write_current_state_hash(hash_path: str, state_hash: str) -> None:
    with open(hash_path, 'w', encoding='utf-8') as f:
        f.write(state_hash)


def _read_networks_from_files(logger: logging.Logger, filepaths: List[str], list_type: str) -> Tuple[List[ipaddress.IPv4Network], List[ipaddress.IPv6Network]]:
    ipv4_nets, ipv6_nets = [], []
    start_time = time.time()
    
    for filepath in filepaths:
        if not os.path.exists(filepath):
            continue
        try:
            with open(filepath, mode="r", encoding="utf-8") as f:
                # OTTIMIZZAZIONE: Streaming I/O
                for line in f:
                    candidate = line.strip()
                    if not candidate or candidate.lower() in ("ip", "ip_address", "cidr"):
                        continue
                    try:
                        net = ipaddress.ip_network(candidate, strict=False)
                        if net.version == 4: ipv4_nets.append(net)
                        else: ipv6_nets.append(net)
                    except ValueError:
                        pass
        except Exception as e:
            logger.warning(f"{LOG_WARNING_TAG} [READ ERROR] File {filepath}: {e}")
            
    logger.debug(f"{LOG_DEBUG_TAG} [I/O] Read {len(filepaths)} {list_type} files. Loaded {len(ipv4_nets)+len(ipv6_nets)} total raw networks. (Elapsed: {time.time() - start_time:.2f}s)")
    return ipv4_nets, ipv6_nets


def _subtract_ranges(bl_ranges: List[Tuple[int, int]], wl_ranges: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    result = []
    wl_idx = 0
    wl_len = len(wl_ranges)
    
    for b_start, b_end in bl_ranges:
        current_start = b_start
        
        while wl_idx < wl_len and wl_ranges[wl_idx][1] < current_start:
            wl_idx += 1
            
        temp_wl_idx = wl_idx
        
        while temp_wl_idx < wl_len and wl_ranges[temp_wl_idx][0] <= b_end:
            w_start, w_end = wl_ranges[temp_wl_idx]
            if current_start < w_start:
                result.append((current_start, w_start - 1))
            current_start = max(current_start, w_end + 1)
            
            if current_start > b_end:
                break
            temp_wl_idx += 1
            
        if current_start <= b_end:
            result.append((current_start, b_end))
            
    return result


def _build_merged_ranges(networks: List) -> List[Tuple[int, int]]:
    if not networks:
        return []
    
    ranges = [(int(net.network_address), int(net.broadcast_address)) for net in networks]
    ranges.sort()
    
    merged = []
    for r in ranges:
        if not merged:
            merged.append(r)
        else:
            last = merged[-1]
            if r[0] <= last[1] + 1:
                merged[-1] = (last[0], max(last[1], r[1]))
            else:
                merged.append(r)
    return merged


def extract_and_filter_networks(logger: logging.Logger, lookups_dirs: dict[str, str]) -> Tuple[Set[str], Set[str]]:
    # 1. RAW READ
    wl_files = glob.glob(os.path.join(lookups_dirs["whitelists"], "*.csv"))
    wl_v4, wl_v6 = _read_networks_from_files(logger, wl_files, "Whitelist")
    wl_v4.extend(STATIC_PRIVATE_NETWORKS)
    
    bl_files = []
    bl_dir = lookups_dirs["blacklists"]
    for target_file in ["manual_denylist_f5_paloalto.csv", "es_automatic_detection.csv"]:
        file_path = os.path.join(bl_dir, target_file)
        if os.path.exists(file_path):
            bl_files.append(file_path)
            
    raw_bl_v4, raw_bl_v6 = _read_networks_from_files(logger, bl_files, "Blacklist")
    
    # 2. INTERVAL CREATION
    t_start = time.time()
    wl_v4_ranges = _build_merged_ranges(wl_v4)
    wl_v6_ranges = _build_merged_ranges(wl_v6)
    bl_v4_ranges = _build_merged_ranges(raw_bl_v4)
    bl_v6_ranges = _build_merged_ranges(raw_bl_v6)
    logger.debug(f"{LOG_DEBUG_TAG} [INTERVALS] Continuous intervals generated and collapsed in {time.time() - t_start:.2f}s")
    
    # 3. SURGICAL MATHEMATICAL SUBTRACTION
    t_start = time.time()
    filtered_v4_ranges = _subtract_ranges(bl_v4_ranges, wl_v4_ranges)
    filtered_v6_ranges = _subtract_ranges(bl_v6_ranges, wl_v6_ranges)
    logger.debug(f"{LOG_DEBUG_TAG} [SUBTRACTION] Overlaps removed in {time.time() - t_start:.2f}s")
    
    # 4. CIDR RECONVERSION
    t_start = time.time()
    final_bl_set = set()
    final_wl_set = set()
    
    for start, end in filtered_v4_ranges:
        for net in ipaddress.summarize_address_range(ipaddress.IPv4Address(start), ipaddress.IPv4Address(end)):
            final_bl_set.add(str(net))
            
    for start, end in filtered_v6_ranges:
        for net in ipaddress.summarize_address_range(ipaddress.IPv6Address(start), ipaddress.IPv6Address(end)):
            final_bl_set.add(str(net))
            
    # OTTIMIZZAZIONE: Collasso nativo per la whitelist senza riconversioni matematiche superflue
    for net in ipaddress.collapse_addresses(wl_v4 + wl_v6):
        final_wl_set.add(str(net))
            
    logger.info(
        f"{LOG_INFO_TAG} [CIDR REBUILD] Final lists rebuilt. Blacklist: {len(final_bl_set)} subnet(s), Whitelist: {len(final_wl_set)} subnet(s). (Elapsed: {time.time() - t_start:.2f}s)"
    )
    
    return final_bl_set, final_wl_set


def read_existing_merged(merged_path: str) -> Set[str]:
    if not os.path.exists(merged_path):
        return set()

    existing = set()
    try:
        with open(merged_path, mode="r", encoding="utf-8") as f:
            # OTTIMIZZAZIONE: Streaming I/O
            for line in f:
                val = line.strip()
                if val and val.lower() not in ("ip", "ip_address", "cidr"):
                    existing.add(val)
    except Exception:
        pass
        
    return existing


def write_merged_csv(merged_path: str, ip_set: Set[str], header: str = "ip") -> None:
    directory = os.path.dirname(merged_path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, mode="w", newline="", encoding="utf-8") as f:
            f.write(f"{header}\n")
            f.write("\n".join(sorted(ip_set)))
            f.write("\n")
        os.replace(tmp_path, merged_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def diff_ip_lists(logger: logging.Logger, new_ips: Set[str], existing_ips: Set[str]) -> Tuple[Set[str], Set[str]]:
    added_ips = new_ips - existing_ips
    removed_ips = existing_ips - new_ips

    if added_ips:
        logger.debug(f"{LOG_DEBUG_TAG} {len(added_ips)} new IP(s)/Subnet(s) to add.")
    if removed_ips:
        logger.debug(f"{LOG_DEBUG_TAG} {len(removed_ips)} IP(s)/Subnet(s) to remove.")
    if not added_ips and not removed_ips:
        logger.debug(f"{LOG_DEBUG_TAG} No differences found since the last run.")

    return added_ips, removed_ips


def get_account_settings(
    session_key: str, account_name: str, logger: logging.Logger
) -> Tuple[Optional[str], Optional[str]]:
    splunk_username = None
    splunk_password = None
    try:
        cfm = _get_conf_manager(session_key, ACCOUNT_CONF_FILE_NAME)
        account_conf_file = cfm.get_conf(ACCOUNT_CONF_FILE_NAME)
        account_data = account_conf_file.get(account_name)
        splunk_username = account_data.get("splunk_username") if account_data else None

        cm = _get_credential_manager(session_key, ACCOUNT_CONF_FILE_NAME)
        credential_data = cm.get_password(account_name)
        splunk_password = json.loads(credential_data).get("splunk_password") if credential_data else None
    except Exception as err:
        logger.error(f"{LOG_ERROR_TAG} Failed to retrieve account settings for {account_name}, error: {err}")

    return splunk_username, splunk_password


def get_list_from_search_head(
    logger: logging.Logger, 
    save_dir: str, 
    search_head: str,
    search_head_port: int,
    session: requests.Session,
    app_name: str,
    collection_name: str,
) -> None:
    url = f"https://{search_head}:{search_head_port}/servicesNS/nobody/{app_name}/storage/collections/data/{collection_name}"
    skip = 0
    total_downloaded = 0
    csv_path = os.path.join(save_dir, f"{collection_name}.csv")

    logger.debug(f"{LOG_DEBUG_TAG} Starting download of list '{collection_name}' from KV Store: {url}")

    try:
        with open(csv_path, mode="w", newline="", encoding="utf-8") as csv_file:
            csv_file.write("ip\n")
            
            while True:
                params = {"limit": KVSTORE_LIMIT, "skip": skip}
                data = None
                
                for attempt in range(1, REQUEST_RETRIES + 1):
                    try:
                        # OTTIMIZZAZIONE: Utilizzo di Session
                        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                        response.raise_for_status()
                        data = response.json()
                        break
                    except requests.exceptions.RequestException as e:
                        logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed for KV Store (collection={collection_name}, skip={skip}): {e}")
                        if attempt < REQUEST_RETRIES:
                            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                        else:
                            raise

                if not data:
                    break
                
                valid_ips = [item.get("ip") for item in data if item.get("ip")]
                if valid_ips:
                    csv_file.write("\n".join(valid_ips) + "\n")
                
                chunk_size = len(data)
                total_downloaded += chunk_size
                
                if chunk_size < KVSTORE_LIMIT:
                    break
                skip += KVSTORE_LIMIT

        logger.info(f"{LOG_INFO_TAG} Download complete: {total_downloaded} records saved for list '{collection_name}'.")

    except requests.exceptions.RequestException as e:
        logger.error(f"{LOG_ERROR_TAG} Irreversible error retrieving list '{collection_name}' from KV Store: {e}")


def push_allowlist_to_kvstore(
    logger: logging.Logger,
    session: requests.Session,
    whitelist_ips: Set[str],
    search_head: str,
    search_head_port: int,
    app_name: str,
    collection_name: str,
) -> None:
    base_url = f"https://{search_head}:{search_head_port}/servicesNS/nobody/{app_name}/storage/collections/data/{collection_name}"
    
    logger.debug(f"{LOG_DEBUG_TAG} Clearing all existing records from KV Store {collection_name}")
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = session.delete(base_url, timeout=REQUEST_TIMEOUT)
            if response.status_code not in (200, 404):
                response.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed deleting all records: {e}")
            if attempt < REQUEST_RETRIES: time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            else: raise

    if whitelist_ips:
        logger.debug(f"{LOG_DEBUG_TAG} Pushing {len(whitelist_ips)} IPs to KV Store {collection_name}")
        batch_url = f"{base_url}/batch_save"
        headers = {"Content-Type": "application/json"}
        payload = [{"_key": hashlib.md5(ip.encode('utf-8')).hexdigest(), "ip": ip} for ip in whitelist_ips]
        
        for i in range(0, len(payload), KVSTORE_ADDITION_CHUNK_SIZE):
            chunk = payload[i:i + KVSTORE_ADDITION_CHUNK_SIZE]
            for attempt in range(1, REQUEST_RETRIES + 1):
                try:
                    response = session.post(batch_url, headers=headers, json=chunk, timeout=REQUEST_TIMEOUT)
                    response.raise_for_status()
                    break
                except requests.exceptions.RequestException as e:
                    logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed batch push: {e}")
                    if attempt < REQUEST_RETRIES: time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                    else: raise
        logger.debug(f"{LOG_DEBUG_TAG} Successfully added {len(whitelist_ips)} IPs to KV Store")


def push_denylist_paloalto(
    logger: logging.Logger,
    session: requests.Session,
    added_ips: Set[str],
    removed_ips: Set[str],
    search_head: str,
    search_head_port: int,
    app_name: str,
    collection_name: str,
) -> None:
    base_url = f"https://{search_head}:{search_head_port}/servicesNS/nobody/{app_name}/storage/collections/data/{collection_name}"
    
    if removed_ips:
        logger.debug(f"{LOG_DEBUG_TAG} Removing {len(removed_ips)} IPs from KV Store {collection_name} via batch query")
        keys_to_remove = [hashlib.md5(ip.encode('utf-8')).hexdigest() for ip in removed_ips]
        
        for i in range(0, len(keys_to_remove), KVSTORE_DELETION_CHUNK_SIZE):
            chunk = keys_to_remove[i:i + KVSTORE_DELETION_CHUNK_SIZE]
            query = {"_key": {"$in": chunk}}
            encoded_query = urllib.parse.quote(json.dumps(query))
            delete_url = f"{base_url}?query={encoded_query}"
            
            for attempt in range(1, REQUEST_RETRIES + 1):
                try:
                    response = session.delete(delete_url, timeout=REQUEST_TIMEOUT)
                    if response.status_code not in (200, 404):
                        response.raise_for_status()
                    break
                except requests.exceptions.RequestException as e:
                    logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed batch deleting IPs: {e}")
                    if attempt < REQUEST_RETRIES: time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        logger.debug(f"{LOG_DEBUG_TAG} Successfully removed {len(removed_ips)} IPs from KV Store {collection_name}")

    if added_ips:
        logger.debug(f"{LOG_DEBUG_TAG} Adding {len(added_ips)} IPs to KV Store {collection_name}")
        batch_url = f"{base_url}/batch_save"
        headers = {"Content-Type": "application/json"}
        payload = [{"_key": hashlib.md5(ip.encode('utf-8')).hexdigest(), "ip": ip} for ip in added_ips]
        
        for i in range(0, len(payload), KVSTORE_ADDITION_CHUNK_SIZE):
            chunk = payload[i:i + KVSTORE_ADDITION_CHUNK_SIZE]
            for attempt in range(1, REQUEST_RETRIES + 1):
                try:
                    response = session.post(batch_url, headers=headers, json=chunk, timeout=REQUEST_TIMEOUT)
                    response.raise_for_status()
                    break
                except requests.exceptions.RequestException as e:
                    logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed batch push: {e}")
                    if attempt < REQUEST_RETRIES: time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        logger.debug(f"{LOG_DEBUG_TAG} Successfully added {len(added_ips)} IPs to KV Store {collection_name}")


def update_remote_csv_lookup(
    logger: logging.Logger,
    session: requests.Session,
    search_head: str,
    search_head_port: int,
    app_name: str,
    collection_name: str
) -> None:
    url = f"https://{search_head}:{search_head_port}/servicesNS/nobody/{app_name}/search/jobs"
    csv_name = f"{collection_name}_managedlookup.csv"
    spl_query = f"| inputlookup {collection_name} | eval time=now() | table ip time | outputlookup {csv_name}"

    payload = {"search": spl_query, "exec_mode": "oneshot", "output_mode": "json"}
    logger.debug(f"{LOG_DEBUG_TAG} Executing remote search to update CSV lookup: {spl_query}")

    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = session.post(url, data=payload, timeout=REQUEST_TIMEOUT * 2)
            response.raise_for_status()
            try:
                response_data = response.json()
                messages = response_data.get("messages", [])
                for msg in messages:
                    msg_type = msg.get("type", "").upper()
                    if msg_type in ("FATAL", "ERROR"):
                        logger.error(f"{LOG_ERROR_TAG} [CSV EXPORT] SPL Search failed internally: {msg.get('text')}")
                        return
            except ValueError:
                pass
                
            logger.info(f"{LOG_INFO_TAG} [CSV EXPORT] Successfully updated remote CSV lookup '{csv_name}'.")
            break
        except requests.exceptions.RequestException as e:
            logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed to execute remote search: {e}")
            if attempt < REQUEST_RETRIES: time.sleep(RETRY_BACKOFF_SECONDS * attempt)


def _generate_logs(ip_iterable: Iterable[str], action: str, list_name: str) -> Generator[str, None, None]:
    # OTTIMIZZAZIONE: Yield generator
    base_time = datetime.now(timezone.utc)
    for i, ip in enumerate(ip_iterable):
        event_time = base_time + timedelta(seconds=(i // 50000))
        yield f'{event_time.isoformat()} action="{action}", ip="{ip}", list_name="{list_name}"'


def write_events(
    index: str,
    sourcetype: str,
    logs: Iterable[str],
    input_name: str,
    event_writer: smi.EventWriter,
    logger: logging.Logger,
) -> None:
    for event_data in logs:
        try:
            event = smi.Event(data=event_data, index=index, sourcetype=sourcetype)
            event_writer.write_event(event)
        except Exception as err:
            logger.error(f"{LOG_ERROR_TAG} Failed to write event for input '{input_name}': {err}")


def validate_input(definition: smi.ValidationDefinition):
    return


def _process_lists(
    logger: logging.Logger,
    input_name: str,
    index: str,
    sourcetype: str,
    splunk_username: str,
    splunk_password: str,
    search_head: str,
    search_head_port: int,
    app_name: str,
    denylist_paloalto_collection: str,
    es_automatic_detection_collection: str,
    event_writer: smi.EventWriter,
) -> None:
    
    lookups_dirs = get_lookups_dirs()
    merged_path = os.path.join(lookups_dirs["master"], f"{denylist_paloalto_collection}.csv")
    state_hash_path = os.path.join(lookups_dirs["master"], "state_paloalto.hash")

    logger.info(f"{LOG_INFO_TAG} [SYNC START] Beginning synchronization cycle for {input_name}")

    # OTTIMIZZAZIONE: Sessione HTTP persistente
    with requests.Session() as session:
        session.auth = (splunk_username, splunk_password)
        session.verify = False
        
        # 1. RETRIEVE MANUAL AND ES LISTS
        get_list_from_search_head(logger, lookups_dirs["blacklists"], search_head, search_head_port, session, app_name, es_automatic_detection_collection)

        # 2. STATE HASH CHECK
        current_state_hash = _calculate_state_hash(lookups_dirs)
        previous_state_hash = _read_previous_state_hash(state_hash_path)

        if current_state_hash == previous_state_hash and os.path.exists(merged_path):
            logger.info(f"{LOG_INFO_TAG} [SYNC SKIP] No changes detected in source feeds. Skipping intensive processing.")
            return
        
        logger.info(f"{LOG_INFO_TAG} [SYNC PROCEED] Changes detected. Proceeding with network optimization...")

        # 3. EXTRACTION & FILTERING
        new_merged_bl, new_merged_wl = extract_and_filter_networks(logger, lookups_dirs)
        
        # 4. BLACKLIST DIFF CALCULATION (Self-Healing Mode)
        # Invece di fidarci del file master locale (che potrebbe essere perso o disallineato),
        # scarichiamo lo stato REALE del KV Store in questo esatto momento.
        
        # Riutilizziamo get_list_from_search_head per salvare il KV store attuale in master/
        get_list_from_search_head(
            logger, 
            lookups_dirs["master"], 
            search_head, 
            search_head_port, 
            session, 
            app_name, 
            denylist_paloalto_collection
        )
        
        # Ora il file scaricato rappresenta la vera 'existing_bl' remota
        remote_state_path = os.path.join(lookups_dirs["master"], f"{denylist_paloalto_collection}.csv")
        existing_bl = read_existing_merged(remote_state_path)
        
        added_ips, removed_ips = diff_ip_lists(logger, new_merged_bl, existing_bl)

        # 5. BLACKLIST PUSH (Conditional)
        if added_ips or removed_ips or not os.path.exists(merged_path):
            try:
                # PUSH REMOTO
                logger.info(f"{LOG_INFO_TAG} [KVSTORE PUSH] Propagating {denylist_paloalto_collection} diffs to Splunk...")
                push_denylist_paloalto(logger, session, added_ips, removed_ips, search_head, search_head_port, app_name, denylist_paloalto_collection)
                
                # COMMIT LOCALE
                write_merged_csv(merged_path, new_merged_bl, header="ip")

                # AUDIT EVENTS tramite yield logs
                if added_ips:
                    write_events(index, sourcetype, _generate_logs(added_ips, "added", denylist_paloalto_collection), input_name, event_writer, logger)
                if removed_ips:
                    write_events(index, sourcetype, _generate_logs(removed_ips, "removed", denylist_paloalto_collection), input_name, event_writer, logger)
                    
                log.events_ingested(logger, input_name, sourcetype, len(added_ips) + len(removed_ips), index)

                logger.info(f"{LOG_INFO_TAG} [KVSTORE PUSH] Changes pushed.")
                logger.info(f"{LOG_INFO_TAG} [SYNC SUCCESS] Synchronization cycle completed successfully.")

            except Exception as e:
                logger.error(f"{LOG_ERROR_TAG} [CRITICAL] DenyList Palo Alto Sync failed. Rolling back local state. Error: {e}")
                return
                
        _write_current_state_hash(state_hash_path, current_state_hash)
        logger.debug(f"{LOG_DEBUG_TAG} [STATE] State hash updated successfully.")


def stream_events(inputs: smi.InputDefinition, event_writer: smi.EventWriter):
    for input_name, input_item in inputs.inputs.items():
        normalized_input_name = input_name.split("/")[-1]
        logger = logger_for_input(normalized_input_name)
        try:
            session_key = inputs.metadata["session_key"]
            log_level = conf_manager.get_log_level(
                logger=logger,
                session_key=session_key,
                app_name=ADDON_NAME,
                conf_name=CONF_FILE_NAME,
            )
            logger.setLevel(log_level)
            log.modular_input_start(logger, normalized_input_name)

            index = input_item.get("index")
            sourcetype = input_item.get("sourcetype")
            account_name = input_item.get("account")
            search_head = input_item.get("search_head")
            search_head_port = input_item.get("search_head_port")
            app_name = "moviri_ti_manager_app"
            denylist_paloalto_collection = "denylist_paloalto"
            es_automatic_detection_collection = "es_automatic_detection"

            splunk_username, splunk_password = get_account_settings(session_key, account_name, logger)

            logger.debug(f"{LOG_DEBUG_TAG} Starting merge and push process for DenyList Palo Alto: {denylist_paloalto_collection}")

            _process_lists(
                logger, 
                input_name, 
                index, 
                sourcetype, 
                splunk_username, 
                splunk_password,
                search_head, 
                search_head_port, 
                app_name, 
                denylist_paloalto_collection,
                es_automatic_detection_collection,
                event_writer
            )

        except Exception as e:
            log.log_exception(
                logger,
                e,
                LOG_ERROR_TAG,
                msg_before=f"Exception raised while executing modular input {normalized_input_name}: {e}",
            )
        finally:
            log.modular_input_end(logger, normalized_input_name)