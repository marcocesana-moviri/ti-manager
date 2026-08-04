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


def _calculate_state_hash(lookups_dirs: dict[str, str]) -> str:
    """
    Calcola un hash MD5 cumulativo del contenuto di tutti i file CSV 
    presenti nelle cartelle blacklists e whitelists.
    """
    hasher = hashlib.md5()
    
    # Ordiniamo le cartelle e i file per garantire che l'hash sia deterministico
    for folder in ["blacklists", "whitelists"]:
        folder_path = lookups_dirs[folder]
        csv_files = sorted(glob.glob(os.path.join(folder_path, "*.csv")))
        
        for filepath in csv_files:
            # Aggiungiamo il nome del file all'hash
            hasher.update(os.path.basename(filepath).encode('utf-8'))
            
            # Leggiamo il contenuto a blocchi (veloce e memory-safe) per generare l'hash
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
                    
    return hasher.hexdigest()


def _read_previous_state_hash(hash_path: str) -> str:
    """Legge l'hash salvato dall'esecuzione precedente."""
    if os.path.exists(hash_path):
        with open(hash_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return ""


def _write_current_state_hash(hash_path: str, state_hash: str) -> None:
    """Salva il nuovo hash di stato."""
    with open(hash_path, 'w', encoding='utf-8') as f:
        f.write(state_hash)


def _read_networks_from_files(logger: logging.Logger, filepaths: List[str], list_type: str) -> Tuple[List[ipaddress.IPv4Network], List[ipaddress.IPv6Network]]:
    """Reads IPs/CIDRs from a list of files."""
    ipv4_nets, ipv6_nets = [], []
    start_time = time.time()
    
    for filepath in filepaths:
        if not os.path.exists(filepath):
            continue
        try:
            with open(filepath, mode="r", encoding="utf-8") as f:
                for line in f.read().splitlines():
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
    """
    Sottrae chirurgicamente gli intervalli Whitelist dagli intervalli Blacklist.
    Algoritmo a doppio puntatore con complessità temporale lineare O(N + M).
    """
    result = []
    wl_idx = 0
    wl_len = len(wl_ranges)
    
    for b_start, b_end in bl_ranges:
        current_start = b_start
        
        # Avanza l'indice whitelist finché non troviamo un range potenzialmente intersecante
        while wl_idx < wl_len and wl_ranges[wl_idx][1] < current_start:
            wl_idx += 1
            
        temp_wl_idx = wl_idx
        
        # Scorri tutte le whitelist che si sovrappongono a questo specifico range della blacklist
        while temp_wl_idx < wl_len and wl_ranges[temp_wl_idx][0] <= b_end:
            w_start, w_end = wl_ranges[temp_wl_idx]
            
            # Se c'è uno spazio prima dell'intersezione whitelist, conservalo
            if current_start < w_start:
                result.append((current_start, w_start - 1))
                
            # Salta la parte coperta dalla whitelist
            current_start = max(current_start, w_end + 1)
            
            if current_start > b_end:
                break
                
            temp_wl_idx += 1
            
        # Se dopo tutte le intersezioni avanza ancora spazio nella blacklist, conservalo
        if current_start <= b_end:
            result.append((current_start, b_end))
            
    return result


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


def extract_and_filter_networks(logger: logging.Logger, lookups_dirs: dict[str, str]) -> Tuple[Set[str], Set[str]]:
    """
    Main Logic: Reads raw feeds, maps them to interval trees, and applies 
    mathematical subtraction (O(N+M)) to surgically separate whitelist exceptions.
    """
    # 1. RAW READ
    wl_files = glob.glob(os.path.join(lookups_dirs["whitelists"], "*.csv"))
    wl_v4, wl_v6 = _read_networks_from_files(logger, wl_files, "Whitelist")
    wl_v4.extend(STATIC_PRIVATE_NETWORKS)
    
    bl_files = glob.glob(os.path.join(lookups_dirs["blacklists"], "*.csv"))
    raw_bl_v4, raw_bl_v6 = _read_networks_from_files(logger, bl_files, "Blacklist")
    
    # 2. INTERVAL CREATION (This step also acts as a native "collapse")
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
    
    # 4. CIDR RECONVERSION (summarize_address_range converts integers back to optimal CIDR blocks)
    t_start = time.time()
    final_bl_set = set()
    final_wl_set = set()
    
    for start, end in filtered_v4_ranges:
        for net in ipaddress.summarize_address_range(ipaddress.IPv4Address(start), ipaddress.IPv4Address(end)):
            final_bl_set.add(str(net))
            
    for start, end in filtered_v6_ranges:
        for net in ipaddress.summarize_address_range(ipaddress.IPv6Address(start), ipaddress.IPv6Address(end)):
            final_bl_set.add(str(net))
            
    # Rebuild the clean and collapsed whitelist similarly
    for start, end in wl_v4_ranges:
        for net in ipaddress.summarize_address_range(ipaddress.IPv4Address(start), ipaddress.IPv4Address(end)):
            final_wl_set.add(str(net))
            
    for start, end in wl_v6_ranges:
        for net in ipaddress.summarize_address_range(ipaddress.IPv6Address(start), ipaddress.IPv6Address(end)):
            final_wl_set.add(str(net))
            
    logger.info(
        f"{LOG_INFO_TAG} [CIDR REBUILD] Final lists rebuilt. Blacklist: {len(final_bl_set)} subnet(s), Whitelist: {len(final_wl_set)} subnet(s). (Elapsed: {time.time() - t_start:.2f}s)"
    )
    
    return final_bl_set, final_wl_set


def optimize_ips(logger: logging.Logger, ipv4_nets: List, ipv6_nets: List, action: str) -> Set[str]:
    """
    Uses collapse_addresses to eliminate duplicate or overlapping IPs/subnets.
    Returns an optimized set of strings.
    """
    logger.debug(f"{LOG_DEBUG_TAG} Collapsing {len(ipv4_nets)} IPv4 and {len(ipv6_nets)} IPv6 {action} raw entries...")
    
    collapsed_v4 = list(ipaddress.collapse_addresses(ipv4_nets))
    collapsed_v6 = list(ipaddress.collapse_addresses(ipv6_nets))
    
    optimized_set = {str(net) for net in (collapsed_v4 + collapsed_v6)}
    logger.debug(f"{LOG_DEBUG_TAG} Collapsed to {len(optimized_set)} unique optimized {action} subnets/IPs.")
    
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
                if val and val.lower() not in ("ip", "ip_address", "cidr"):
                    existing.add(val)
    except Exception as e:
        # Return empty set if failure reading to force a full rewrite
        pass
        
    return existing


def write_merged_csv(merged_path: str, ip_set: Set[str], header: str = "ip") -> None:
    """Writes the new merged lookup atomically using optimized block writing."""
    directory = os.path.dirname(merged_path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, mode="w", newline="", encoding="utf-8") as f:
            # Fast block write
            f.write(f"{header}\n")
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


def push_master_whitelist_to_kvstore(
    logger: logging.Logger,
    splunk_username: str,
    splunk_password: str,
    whitelist_ips: Set[str],
    search_head: str,
    search_head_port: int,
    app_name: str,
    collection_name: str,
) -> None:
    """
    Overwrites the remote Splunk KV Store collection with the new whitelist.
    It unconditionally deletes all existing records and performs a batched POST.
    """
    base_url = f"https://{search_head}:{search_head_port}/servicesNS/nobody/{app_name}/storage/collections/data/{collection_name}"
    auth_tuple = (splunk_username, splunk_password)
    
    # 1. DELETE ALL RECORDS
    logger.debug(f"{LOG_DEBUG_TAG} Clearing all existing records from KV Store {collection_name}")
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = requests.delete(
                base_url,
                auth=auth_tuple,
                verify=False,
                timeout=REQUEST_TIMEOUT
            )
            if response.status_code not in (200, 404):
                response.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed deleting all records from KV Store {collection_name}: {e}")
            if attempt < REQUEST_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            else:
                logger.error(f"{LOG_ERROR_TAG} Giving up on clearing KV Store {collection_name}. Whitelist push aborted.")
                raise # Solleviamo un'eccezione per bloccare il push ed evitare duplicati

    # 2. INSERT NEW RECORDS (POST via batch_save)
    if whitelist_ips:
        logger.debug(f"{LOG_DEBUG_TAG} Pushing {len(whitelist_ips)} IPs to KV Store {collection_name}")
        batch_url = f"{base_url}/batch_save"
        headers = {"Content-Type": "application/json"}
        
        # Mapping _key via MD5 and ip for batch saving.
        payload = [{"_key": hashlib.md5(ip.encode('utf-8')).hexdigest(), "ip": ip} for ip in whitelist_ips]
        
        # Chunking payload to safely adhere to Splunk REST batch limits[cite: 4]
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
                    break
                except requests.exceptions.RequestException as e:
                    logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed during batch push ({len(chunk)} items) to KV Store {collection_name}: {e}")
                    if hasattr(e, 'response') and e.response is not None:
                        logger.error(f"{LOG_ERROR_TAG} Splunk response detail: {e.response.text}")
                        
                    if attempt < REQUEST_RETRIES:
                        time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                    else:
                        logger.error(f"{LOG_ERROR_TAG} Giving up on batch push after {REQUEST_RETRIES} attempts.")
                        raise
        logger.debug(f"{LOG_DEBUG_TAG} Successfully added {len(whitelist_ips)} IPs to KV Store {collection_name}")


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
        
        keys_to_remove = [hashlib.md5(ip.encode('utf-8')).hexdigest() for ip in removed_ips]
        
        for i in range(0, len(keys_to_remove), KVSTORE_DELETION_CHUNK_SIZE):
            chunk = keys_to_remove[i:i + KVSTORE_DELETION_CHUNK_SIZE]
            query = {"_key": {"$in": chunk}}
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
                    if response.status_code not in (200, 404):
                        response.raise_for_status()
                    break
                except requests.exceptions.RequestException as e:
                    logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed batch deleting IPs from KV Store: {e}")
                    if hasattr(e, 'response') and e.response is not None:
                        logger.error(f"{LOG_ERROR_TAG} Splunk response detail: {e.response.text}")
                    if attempt < REQUEST_RETRIES:
                        time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                    else:
                        logger.error(f"{LOG_ERROR_TAG} Giving up on batch delete after {REQUEST_RETRIES} attempts.")
        logger.debug(f"{LOG_DEBUG_TAG} Successfully removed {len(removed_ips)} IPs from KV Store {collection_name}")

    # 2. Handle ADDITIONS (POST via batch_save)
    if added_ips:
        logger.debug(f"{LOG_DEBUG_TAG} Adding {len(added_ips)} IPs to KV Store {collection_name}")
        batch_url = f"{base_url}/batch_save"
        headers = {"Content-Type": "application/json"}
        
        payload = [{"_key": hashlib.md5(ip.encode('utf-8')).hexdigest(), "ip": ip} for ip in added_ips]
        
        # Chunking payload to safely adhere to Splunk REST batch limits
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
                    break
                except requests.exceptions.RequestException as e:
                    logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed during batch push ({len(chunk)} items) to KV Store: {e}")
                    if hasattr(e, 'response') and e.response is not None:
                        logger.error(f"{LOG_ERROR_TAG} Splunk response detail: {e.response.text}")
                        
                    if attempt < REQUEST_RETRIES:
                        time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                    else:
                        logger.error(f"{LOG_ERROR_TAG} Giving up on batch push after {REQUEST_RETRIES} attempts.")
        logger.debug(f"{LOG_DEBUG_TAG} Successfully added {len(added_ips)} IPs to KV Store {collection_name}")


def update_remote_csv_lookup(
    logger: logging.Logger,
    splunk_username: str,
    splunk_password: str,
    search_head: str,
    search_head_port: int,
    app_name: str,
    collection_name: str
) -> None:
    """
    Executes a remote SPL search to dump the KV Store collection into a CSV lookup.
    SPL: | inputlookup <collection> | outputlookup <collection>_csv.csv
    """
    url = f"https://{search_head}:{search_head_port}/servicesNS/nobody/{app_name}/search/jobs"
    auth_tuple = (splunk_username, splunk_password)

    # AGGIUNTO IL SUFFISSO .csv OBBLIGATORIO PER OUTPUTLOOKUP
    csv_name = f"{collection_name}_csv"
    spl_query = f"| inputlookup {collection_name} | outputlookup {csv_name}"

    payload = {
        "search": spl_query,
        "exec_mode": "oneshot",
        "output_mode": "json"  # Richiediamo esplicitamente l'output in JSON per leggere i warning
    }

    logger.debug(f"{LOG_DEBUG_TAG} Executing remote search to update CSV lookup: {spl_query}")

    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = requests.post(
                url,
                auth=auth_tuple,
                data=payload,
                verify=False,
                timeout=REQUEST_TIMEOUT * 2
            )
            response.raise_for_status()
            
            # PARSING DEGLI ERRORI SILENZIOSI DI SPLUNK
            try:
                response_data = response.json()
                messages = response_data.get("messages", [])
                
                # Controlliamo se Splunk ci ha restituito un errore FATAL o ERROR 
                # (es. problemi di permessi, lookup inesistente, quote superate)
                for msg in messages:
                    msg_type = msg.get("type", "").upper()
                    if msg_type in ("FATAL", "ERROR"):
                        logger.error(f"{LOG_ERROR_TAG} [CSV EXPORT] SPL Search failed internally: {msg.get('text')}")
                        return # Usciamo senza stampare il messaggio di successo
            except ValueError:
                # Se la risposta non è in JSON per qualche anomalia, passiamo oltre
                pass
                
            logger.info(f"{LOG_INFO_TAG} [CSV EXPORT] Successfully updated remote CSV lookup '{csv_name}' via SPL.")
            break
            
        except requests.exceptions.RequestException as e:
            logger.error(f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed to execute remote search: {e}")
            
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"{LOG_ERROR_TAG} Splunk response detail: {e.response.text}")
                
            if attempt < REQUEST_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            else:
                logger.error(f"{LOG_ERROR_TAG} Giving up on updating remote CSV lookup after {REQUEST_RETRIES} attempts.")


def _generate_logs(ip_iterable: Set[str], action: str, list_name: str) -> List[str]:
    """Generates standard Splunk event strings, spreading timestamps to avoid Splunk limits."""
    base_time = datetime.now(timezone.utc)
    logs = []
    
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
    master_threatlist_collection: str,
    master_whitelist_collection: str,
    manual_blacklist_collection: str,
    manual_whitelist_collection: str,
    event_writer: smi.EventWriter,
) -> None:
    
    lookups_dirs = get_lookups_dirs()
    merged_path = os.path.join(lookups_dirs["master"], f"{master_threatlist_collection}.csv")
    state_hash_path = os.path.join(lookups_dirs["master"], "state.hash")

    logger.info(f"{LOG_INFO_TAG} [SYNC START] Beginning synchronization cycle for {input_name}")

    # 1. RETRIEVE MANUAL LISTS
    get_manual_list_from_search_head(logger, lookups_dirs["blacklists"], search_head, search_head_port, splunk_username, splunk_password, app_name, manual_blacklist_collection)
    get_manual_list_from_search_head(logger, lookups_dirs["whitelists"], search_head, search_head_port, splunk_username, splunk_password, app_name, manual_whitelist_collection)

    # 2. STATE HASH CHECK
    current_state_hash = _calculate_state_hash(lookups_dirs)
    previous_state_hash = _read_previous_state_hash(state_hash_path)

    if current_state_hash == previous_state_hash and os.path.exists(merged_path):
        logger.info(f"{LOG_INFO_TAG} [SYNC SKIP] No changes detected in source feeds (Hash: {current_state_hash}). Skipping intensive processing.")
        return
    
    logger.info(f"{LOG_INFO_TAG} [SYNC PROCEED] Changes detected. Proceeding with network optimization...")

    # 3. EXTRACTION & FILTERING
    # Grazie all'ottimizzazione, le reti escono già convertite in SET di stringhe pronte all'uso.
    new_merged_bl, new_merged_wl = extract_and_filter_networks(logger, lookups_dirs)
    
    # 4. WHITELIST PUSH (Unconditional)
    whitelist_filename = f"{master_whitelist_collection}.csv"
    whitelist_path = os.path.join(lookups_dirs["master"], whitelist_filename)
    try:
        write_merged_csv(whitelist_path, new_merged_wl, header="ip")
        push_master_whitelist_to_kvstore(logger, splunk_username, splunk_password, new_merged_wl, search_head, search_head_port, app_name, master_whitelist_collection)
    except Exception as e:
        logger.error(f"{LOG_ERROR_TAG} [SYNC ERROR] Whitelist synchronization failed: {e}")
    
    # 5. BLACKLIST DIFF CALCULATION
    existing_bl = read_existing_merged(merged_path)
    added_ips, removed_ips = diff_ip_lists(logger, new_merged_bl, existing_bl)

    # 6. BLACKLIST PUSH (Conditional)
    if added_ips or removed_ips or not os.path.exists(merged_path):
        try:
            # PUSH REMOTO
            logger.info(f"{LOG_INFO_TAG} [KVSTORE PUSH] Propagating Threatlist diffs to Splunk...")
            push_master_threatlist(logger, splunk_username, splunk_password, added_ips, removed_ips, search_head, search_head_port, app_name, master_threatlist_collection)
            
            # COMMIT LOCALE
            write_merged_csv(merged_path, new_merged_bl, header="ip")

            # AUDIT EVENTS
            if added_ips:
                logs_added = _generate_logs(added_ips, "added", master_threatlist_collection)
                write_events(index, sourcetype, logs_added, input_name, event_writer, logger)
            if removed_ips:
                logs_removed = _generate_logs(removed_ips, "removed", master_threatlist_collection)
                write_events(index, sourcetype, logs_removed, input_name, event_writer, logger)
                
            log.events_ingested(logger, input_name, sourcetype, len(added_ips) + len(removed_ips), index)

            logger.info(f"{LOG_INFO_TAG} [KVSTORE PUSH] Changes pushed. Triggering remote CSV export via SPL...")
            update_remote_csv_lookup(
                logger, 
                splunk_username, 
                splunk_password, 
                search_head, 
                search_head_port, 
                app_name, 
                master_threatlist_collection
            )
            logger.info(f"{LOG_INFO_TAG} [SYNC SUCCESS] Synchronization cycle completed successfully.")

        except Exception as e:
            logger.error(f"{LOG_ERROR_TAG} [CRITICAL] Blacklist Sync failed. Rolling back local state. Error: {e}")
            return # Ferma qui, non aggiornare l'hash.
            
    # Alla fine, solo se tutto è andato bene, aggiorniamo l'hash
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
            app_name = input_item.get("app_name")
            
            master_threatlist_collection = input_item.get("master_threatlist_collection")
            master_whitelist_collection = input_item.get("master_whitelist_collection")
            manual_blacklist_collection = input_item.get("manual_blacklist_collection")
            manual_whitelist_collection = input_item.get("manual_whitelist_collection")

            splunk_username, splunk_password = get_account_settings(session_key, account_name, logger)

            logger.debug(f"{LOG_DEBUG_TAG} Starting merge and push process for master threatlist: {master_threatlist_collection}")

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
                master_threatlist_collection,
                master_whitelist_collection,
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