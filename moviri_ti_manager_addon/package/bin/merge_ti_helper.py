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
import bisect
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List, Set

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
    """Crea e restituisce i percorsi per la nuova struttura a cartelle."""
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


def _read_networks_from_files(logger: logging.Logger, filepaths: List[str]) -> Tuple[List[ipaddress.IPv4Network], List[ipaddress.IPv6Network]]:
    """Reads IPs/CIDRs from a list of file paths and returns IPv4 and IPv6 network objects."""
    ipv4_nets = []
    ipv6_nets = []
    
    for filepath in filepaths:
        if not os.path.exists(filepath):
            continue
            
        filename = os.path.basename(filepath)
        logger.debug(f"{LOG_DEBUG_TAG} Reading source CSV: {filename}")
        try:
            with open(filepath, mode="r", encoding="utf-8") as f:
                # Fast block read for millions of lines instead of csv module
                lines = f.read().splitlines()
                
            for line in lines:
                candidate = line.strip()
                # Skip headers and empty lines
                if not candidate or candidate.lower() in ("ip", "ip_address", "cidr"):
                    continue
                    
                try:
                    # strict=False converts host bits safely into correct subnets
                    net = ipaddress.ip_network(candidate, strict=False)
                    if net.version == 4:
                        ipv4_nets.append(net)
                    else:
                        ipv6_nets.append(net)
                except ValueError:
                    pass
        except Exception as e:
            logger.warning(f"{LOG_WARNING_TAG} Error reading {filename}: {e}")
            
    return ipv4_nets, ipv6_nets


def _build_merged_ranges(networks: List) -> List[Tuple[int, int]]:
    """Converts IP networks to integer intervals and merges overlapping ones for fast O(log N) lookup."""
    if not networks:
        return []
    
    # Convert subnets into start and end integers
    ranges = [(int(net.network_address), int(net.broadcast_address)) for net in networks]
    ranges.sort()
    
    merged = []
    for r in ranges:
        if not merged:
            merged.append(r)
        else:
            last = merged[-1]
            if r[0] <= last[1] + 1:
                # Overlapping or adjacent ranges are merged
                merged[-1] = (last[0], max(last[1], r[1]))
            else:
                merged.append(r)
    return merged


def _is_overlapping(net_start: int, net_end: int, merged_ranges: List[Tuple[int, int]]) -> bool:
    """Checks if a given integer network range overlaps with any merged whitelist ranges using Binary Search."""
    if not merged_ranges:
        return False
        
    idx = bisect.bisect_right(merged_ranges, (net_start, float('inf')))
    
    # Check range directly before insertion point
    if idx > 0:
        _, wl_end = merged_ranges[idx - 1]
        if wl_end >= net_start:
            return True
            
    # Check range at insertion point
    if idx < len(merged_ranges):
        wl_start, _ = merged_ranges[idx]
        if wl_start <= net_end:
            return True
            
    return False


def extract_and_filter_networks(
    logger: logging.Logger, 
    lookups_dirs: dict[str, str]
) -> Tuple[List[ipaddress.IPv4Network], List[ipaddress.IPv6Network]]:
    """
    Legge tutte le blacklist dalla rispettiva cartella, le whitelist dalla loro, 
    ed esclude le subnet blacklistate che si sovrappongono alle whitelist.
    """
    # 1. Lettura dinamica di TUTTE le whitelist
    wl_files = glob.glob(os.path.join(lookups_dirs["whitelists"], "*.csv"))
    wl_v4, wl_v6 = _read_networks_from_files(logger, wl_files)

    # Considera SEMPRE in whitelist gli ip/subnet privati
    wl_v4.extend(STATIC_PRIVATE_NETWORKS)
    
    # Pre-calcolo degli intervalli per le whitelist
    wl_v4_ranges = _build_merged_ranges(wl_v4)
    wl_v6_ranges = _build_merged_ranges(wl_v6)
    
    # 2. Lettura dinamica di TUTTE le blacklist
    bl_files = glob.glob(os.path.join(lookups_dirs["blacklists"], "*.csv"))
    raw_bl_v4, raw_bl_v6 = _read_networks_from_files(logger, bl_files)
    
    # 3. Filtraggio delle blacklist (rimane invariato)
    filtered_v4 = []
    for net in raw_bl_v4:
        if not _is_overlapping(int(net.network_address), int(net.broadcast_address), wl_v4_ranges):
            filtered_v4.append(net)
            
    filtered_v6 = []
    for net in raw_bl_v6:
        if not _is_overlapping(int(net.network_address), int(net.broadcast_address), wl_v6_ranges):
            filtered_v6.append(net)

    return filtered_v4, filtered_v6


def optimize_ips(logger: logging.Logger, ipv4_nets: List, ipv6_nets: List) -> Set[str]:
    """
    Uses collapse_addresses to eliminate duplicate or overlapping IPs/subnets.
    Returns an optimized set of strings.
    """
    logger.debug(f"{LOG_DEBUG_TAG} Collapsing {len(ipv4_nets)} IPv4 and {len(ipv6_nets)} IPv6 raw entries...")
    
    collapsed_v4 = list(ipaddress.collapse_addresses(ipv4_nets))
    collapsed_v6 = list(ipaddress.collapse_addresses(ipv6_nets))
    
    optimized_set = {str(net) for net in (collapsed_v4 + collapsed_v6)}
    logger.debug(f"{LOG_DEBUG_TAG} Collapsed to {len(optimized_set)} unique optimized subnets/IPs.")
    
    return set(optimized_set)


def read_existing_merged(merged_path: str) -> Set[str]:
    """Reads the previously generated merged file to calculate differences."""
    if not os.path.exists(merged_path):
        return set()

    existing = set()
    try:
        with open(merged_path, mode="r", encoding="utf-8") as f:
            lines = f.read().splitlines()
            for line in lines:
                val = line.strip()
                if val and val.lower() not in ("ip_address", "ip", "cidr"):
                    existing.add(val)
    except Exception as e:
        # Return empty set if failure reading to force a full rewrite
        pass
        
    return existing


def write_merged_csv(merged_path: str, ip_set: Set[str]) -> None:
    """Writes the new merged lookup atomically using optimized block writing."""
    directory = os.path.dirname(merged_path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, mode="w", newline="", encoding="utf-8") as f:
            # Fast block write
            f.write("ip_address\n")
            f.write("\n".join(sorted(ip_set)))
            f.write("\n")
        os.replace(tmp_path, merged_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def diff_ip_lists(logger: logging.Logger, new_ips: Set[str], existing_ips: Set[str]) -> Tuple[Set[str], Set[str]]:
    """Calculates added and removed IPs between two sets."""
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
    """Retrieves Splunk account credentials from the conf manager."""
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


def get_manual_list_from_search_head(
    logger: logging.Logger, 
    save_dir: str, 
    search_head: str,
    search_head_port: int,
    splunk_username: str, 
    splunk_password: str,
    app_name: str,
    collection_name: str,
) -> None:
    """
    Downloads a generic manual list (e.g. blacklist, whitelist) from Splunk KV Store in blocks (pagination) 
    and saves it as a single-column 'ip' CSV.
    Implements retry and backoff in case of network errors.
    """    
    url = f"https://{search_head}:{search_head_port}/servicesNS/nobody/{app_name}/storage/collections/data/{collection_name}"
    
    skip = 0
    total_downloaded = 0
    csv_path = os.path.join(save_dir, f"{collection_name}.csv")

    logger.debug(f"{LOG_DEBUG_TAG} Starting download of list '{collection_name}' from KV Store: {url}")

    try:
        with open(csv_path, mode="w", newline="", encoding="utf-8") as csv_file:
            # Using basic write for streaming large API responses
            csv_file.write("ip\n")
            
            while True:
                params = {"limit": KVSTORE_LIMIT, "skip": skip}
                data = None
                
                for attempt in range(1, REQUEST_RETRIES + 1):
                    try:
                        response = requests.get(
                            url,
                            auth=(splunk_username, splunk_password),
                            params=params,
                            verify=False,
                            timeout=REQUEST_TIMEOUT
                        )
                        response.raise_for_status()
                        data = response.json()
                        break
                        
                    except requests.exceptions.RequestException as e:
                        logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed for KV Store (collection={collection_name}, skip={skip}): {e}")
                        
                        if attempt < REQUEST_RETRIES:
                            delay = RETRY_BACKOFF_SECONDS * attempt
                            time.sleep(delay)
                        else:
                            logger.error(f"{LOG_ERROR_TAG} Giving up on KV Store request after {REQUEST_RETRIES} attempts for '{collection_name}'.")
                            raise

                if not data:
                    break
                
                # Stream write items avoiding csv.writer overhead
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


def push_master_threatlist(
    logger: logging.Logger,
    splunk_username: str,
    splunk_password: str,
    added_ips: Set[str],
    removed_ips: Set[str],
    search_head: str,
    search_head_port: int,
    app_name: str,
    collection_name: str,
) -> None:
    """
    Synchronizes the newly calculated Master Threatlist differences to the remote Splunk KV Store.
    Implements retry and backoff in case of network errors. Uses MD5 for safe _key generation.
    """
    base_url = f"https://{search_head}:{search_head_port}/servicesNS/nobody/{app_name}/storage/collections/data/{collection_name}"
    auth_tuple = (splunk_username, splunk_password)
    
    # 1. Handle REMOVALS (DELETE via Query Batching)
    if removed_ips:
        logger.debug(f"{LOG_DEBUG_TAG} Removing {len(removed_ips)} IPs from KV Store {collection_name} via batch query")
        
        # Converte tutti gli IP da rimuovere nei rispettivi hash MD5
        keys_to_remove = [hashlib.md5(ip.encode('utf-8')).hexdigest() for ip in removed_ips]
        
        # Usa un chunk size minore (es. 50-100) per evitare l'errore HTTP 414 (URI Too Long)
        # Un chunk di 100 MD5 genera una query URL di circa 4000 caratteri, che è un limite sicuro.
        
        for i in range(0, len(keys_to_remove), KVSTORE_DELETION_CHUNK_SIZE):
            chunk = keys_to_remove[i:i + KVSTORE_DELETION_CHUNK_SIZE]
            
            # Crea la query in stile MongoDB: {"_key": {"$in": ["hash1", "hash2", ...]}}
            query = {"_key": {"$in": chunk}}
            
            # Converte il dizionario JSON in stringa e ne fa l'URL encoding
            encoded_query = urllib.parse.quote(json.dumps(query))
            delete_url = f"{base_url}?query={encoded_query}"
            
            for attempt in range(1, REQUEST_RETRIES + 1):
                try:
                    response = requests.delete(
                        delete_url, 
                        auth=auth_tuple, 
                        verify=False, 
                        timeout=REQUEST_TIMEOUT
                    )
                    # Ignore 404 error: if the IP is already gone, the goal is achieved
                    if response.status_code not in (200, 404):
                        response.raise_for_status()
                    break  # Success, exit the retry loop
                    
                except requests.exceptions.RequestException as e:
                    logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed batch deleting IPs from KV Store: {e}")
                    
                    if hasattr(e, 'response') and e.response is not None:
                        logger.error(f"{LOG_ERROR_TAG} Splunk response detail: {e.response.text}")
                    
                    if attempt < REQUEST_RETRIES:
                        delay = RETRY_BACKOFF_SECONDS * attempt
                        time.sleep(delay)
                    else:
                        logger.error(f"{LOG_ERROR_TAG} Giving up on batch delete after {REQUEST_RETRIES} attempts.")
        logger.debug(f"{LOG_DEBUG_TAG} Successfully removed {len(removed_ips)} IPs from KV Store {collection_name}")

    # 2. Handle ADDITIONS (POST via batch_save)
    if added_ips:
        logger.debug(f"{LOG_DEBUG_TAG} Adding {len(added_ips)} IPs to KV Store {collection_name}")
        batch_url = f"{base_url}/batch_save"
        headers = {"Content-Type": "application/json"}
        
        # Mapping _key and ip for batch saving.
        payload = [{"_key": hashlib.md5(ip.encode('utf-8')).hexdigest(), "ip": ip} for ip in added_ips]
        
        # Chunking payload to safely adhere to Splunk REST batch limits[cite: 3]
        for i in range(0, len(payload), KVSTORE_ADDITION_CHUNK_SIZE):
            chunk = payload[i:i + KVSTORE_ADDITION_CHUNK_SIZE]
            
            for attempt in range(1, REQUEST_RETRIES + 1):
                try:
                    response = requests.post(
                        batch_url,
                        auth=auth_tuple,
                        headers=headers,
                        json=chunk,
                        verify=False,
                        timeout=REQUEST_TIMEOUT
                    )
                    response.raise_for_status()
                    break  # Success, exit the retry loop
                    
                except requests.exceptions.RequestException as e:
                    logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed during batch push ({len(chunk)} items) to KV Store: {e}")
                    
                    if hasattr(e, 'response') and e.response is not None:
                        logger.error(f"{LOG_ERROR_TAG} Splunk response detail: {e.response.text}")
                        
                    if attempt < REQUEST_RETRIES:
                        delay = RETRY_BACKOFF_SECONDS * attempt
                        time.sleep(delay)
                    else:
                        logger.error(f"{LOG_ERROR_TAG} Giving up on batch push after {REQUEST_RETRIES} attempts.")
        logger.debug(f"{LOG_DEBUG_TAG} Successfully added {len(added_ips)} IPs to KV Store {collection_name}")


def _generate_logs(ip_iterable: Set[str], action: str, list_name: str) -> List[str]:
    """Generates standard Splunk event strings, spreading timestamps to avoid Splunk limits."""
    base_time = datetime.now(timezone.utc)
    logs = []
    
    # Aggiungiamo 1 secondo al timestamp ogni 50.000 eventi.
    # Questo evita il limite hardcoded di Splunk (max 1.000.000 di eventi nello stesso secondo).
    for i, ip in enumerate(ip_iterable):
        event_time = base_time + timedelta(seconds=(i // 50000))
        logs.append(
            f'{event_time.isoformat()} action="{action}", ip="{ip}", list_name="{list_name}"'
        )
        
    return logs


def write_events(
    index: str,
    sourcetype: str,
    logs: List[str],
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


def _process_local_lookups(
    logger: logging.Logger,
    input_name: str,
    index: str,
    sourcetype: str,
    splunk_username: str,
    splunk_password: str,
    search_head: str,
    search_head_port: int,
    app_name: str,
    master_threatlist_collection: str,
    manual_blacklist_collection: str,
    manual_whitelist_collection: str,
    event_writer: smi.EventWriter,
) -> None:
    
    lookups_dirs = get_lookups_dirs()
    merged_csv_filename = f"{master_threatlist_collection}.csv"
    merged_path = os.path.join(lookups_dirs["master"], merged_csv_filename)

    # 1. Retrieve manual blacklist collection from Splunk KV Store
    get_manual_list_from_search_head(
        logger, lookups_dirs["blacklists"], search_head, search_head_port, 
        splunk_username, splunk_password, app_name, manual_blacklist_collection
    )
    
    # 2. Retrieve manual whitelist collection from Splunk KV Store
    get_manual_list_from_search_head(
        logger, lookups_dirs["whitelists"], search_head, search_head_port, 
        splunk_username, splunk_password, app_name, manual_whitelist_collection
    )

    # 3. Parse and filter networks (excludes whitelists dynamically)
    ipv4_nets, ipv6_nets = extract_and_filter_networks(logger, lookups_dirs)
    
    # 4. Collapse and optimize resulting valid subnets
    new_merged_ips = optimize_ips(logger, ipv4_nets, ipv6_nets)
    
    # 5. Read existing state to calculate diff
    existing_ips = read_existing_merged(merged_path)
    added_ips, removed_ips = diff_ip_lists(logger, new_merged_ips, existing_ips)

    # 6 & 7. Pseudo-Atomic Synchronization (KV Store -> Local CSV -> Splunk Events)
    if added_ips or removed_ips or not os.path.exists(merged_path):
        try:
            logger.debug(f"{LOG_DEBUG_TAG} Pushing updated differences to remote KV Store first...")
            
            # 1. PUSH REMOTO (Punto di rottura più probabile)
            push_master_threatlist(
                logger,
                splunk_username,
                splunk_password,
                added_ips,
                removed_ips,
                search_head,
                search_head_port,
                app_name,
                master_threatlist_collection
            )
            
            # 2. COMMIT LOCALE (Atomico via OS file replace)
            # Viene eseguito SOLO se il push remoto non ha sollevato eccezioni
            logger.debug(f"{LOG_DEBUG_TAG} Remote push successful. Writing updated merged CSV to {merged_path}")
            write_merged_csv(merged_path, new_merged_ips)

            # 3. SCRITTURA EVENTI DI AUDIT (Solo se la transazione è completata)
            logger.debug(f"{LOG_DEBUG_TAG} State committed. Writing audit events to Splunk...")
            if added_ips:
                logs_added = _generate_logs(added_ips, "added", master_threatlist_collection)
                write_events(index, sourcetype, logs_added, input_name, event_writer, logger)
                log.events_ingested(logger, input_name, sourcetype, len(logs_added), index)

            if removed_ips:
                logs_removed = _generate_logs(removed_ips, "removed", master_threatlist_collection)
                write_events(index, sourcetype, logs_removed, input_name, event_writer, logger)
                log.events_ingested(logger, input_name, sourcetype, len(logs_removed), index)

        except Exception as e:
            # Intercettiamo l'errore e usciamo in modo pulito. 
            # Il CSV locale non viene aggiornato, quindi al prossimo avvio lo script 
            # rileverà nuovamente lo stesso diff e riproverà l'intera operazione.
            logger.error(
                f"{LOG_ERROR_TAG} Synchronization failed! Aborting local CSV update and event generation to maintain state consistency. Error: {e}"
            )
            logger.info(
                f"{LOG_INFO_TAG} Will retry the synchronization on the next scheduled execution."
            )


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
            app_name = input_item.get("app_name")
            
            master_threatlist_collection = input_item.get("master_threatlist_collection")
            manual_blacklist_collection = input_item.get("manual_blacklist_collection")
            manual_whitelist_collection = input_item.get("manual_whitelist_collection")

            splunk_username, splunk_password = get_account_settings(session_key, account_name, logger)

            logger.debug(f"{LOG_DEBUG_TAG} Starting merge and push process for master threatlist: {master_threatlist_collection}")

            _process_local_lookups(
                logger, 
                input_name, 
                index, 
                sourcetype, 
                splunk_username, 
                splunk_password,
                search_head, 
                search_head_port, 
                app_name, 
                master_threatlist_collection,
                manual_blacklist_collection,
                manual_whitelist_collection,
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