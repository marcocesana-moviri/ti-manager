import ipaddress
import logging
import os
import tempfile
import time
import re
from typing import Union

import requests
from solnlib import conf_manager, log
from splunklib import modularinput as smi

from configs import (
    ADDON_NAME,
    CONF_FILE_NAME,
    LOG_INFO_TAG,
    LOG_DEBUG_TAG,
    LOG_ERROR_TAG,
    LOG_WARNING_TAG,
    REQUEST_TIMEOUT,
    REQUEST_RETRIES,
    RETRY_BACKOFF_SECONDS
)

def logger_for_input(input_name: str) -> logging.Logger:
    return log.Logs().get_logger(f"{ADDON_NAME.lower()}_{input_name}")

def get_threat_list(logger: logging.Logger, ti_url: str, ip_regex: Union[str, re.Pattern]) -> list[str]:
    """
    Downloads the feed using memory-efficient streaming and regex parsing.
    Safely handles both string and byte responses.
    """
    if isinstance(ip_regex, str):
        ip_regex = re.compile(ip_regex)
        
    logger.info(f"{LOG_INFO_TAG} [FEED DOWNLOAD] Starting fetch for URL: {ti_url}")
    start_time = time.time()
    
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            # stream=True ensures we don't load huge files entirely in memory
            response = requests.get(ti_url, timeout=REQUEST_TIMEOUT, stream=True)
            response.raise_for_status()
            
            valid_ips = set()
            total_lines = 0
            regex_fails = 0
            invalid_ips = 0
            
            for chunk in response.iter_lines():
                if not chunk:
                    continue
                
                if isinstance(chunk, bytes):
                    line = chunk.decode('utf-8', errors='ignore')
                else:
                    line = chunk
                
                total_lines += 1
                candidate = line.strip()
                
                if candidate.startswith("#"):
                    continue
                    
                match = ip_regex.search(candidate)
                if not match:
                    regex_fails += 1
                    continue
                    
                groups = match.groups()   
                if len(groups) >= 1:
                    ip = match.group(1)
                    cidr = match.group(2) if len(groups) >= 2 and match.group(2) else "32"
                else:
                    full_match = match.group(0)
                    if "/" in full_match:
                        ip, cidr = full_match.split("/", 1)
                    else:
                        ip = full_match
                        cidr = "32"
                        
                ip_cidr_str = f"{ip}/{cidr}"
                
                try:
                    # strict=False safely transforms host bits to subnets
                    network = ipaddress.ip_network(ip_cidr_str, strict=False)
                    valid_ips.add(str(network))
                except ValueError:
                    invalid_ips += 1
                    
            elapsed = time.time() - start_time
            logger.info(
                f"{LOG_INFO_TAG} [FEED PARSING] Success for {ti_url} (Attempt {attempt}). Extracted {len(valid_ips)} unique IPs in {elapsed:.2f}s. Stats: Total Lines: {total_lines}, Regex Fails: {regex_fails}, Invalid IPs: {invalid_ips}."
            )
            return sorted(valid_ips)
            
        except requests.RequestException as e:
            logger.error(
                f"{LOG_ERROR_TAG} [FEED ERROR] Attempt {attempt}/{REQUEST_RETRIES} failed for {ti_url}: {e}"
            )
            
        if attempt < REQUEST_RETRIES:
            delay = RETRY_BACKOFF_SECONDS * attempt
            logger.debug(f"{LOG_DEBUG_TAG} Retrying in {delay}s...")
            time.sleep(delay)
            
    logger.error(f"{LOG_ERROR_TAG} [FEED ABORTED] Max retries reached for {ti_url}.")
    return []

def get_lookups_dir(list_type: str) -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    safe_type = "whitelists" if str(list_type).strip().lower() == "whitelist" else "blacklists"
    target_dir = os.path.abspath(os.path.join(script_dir, "..", "lookups", safe_type))
    os.makedirs(target_dir, exist_ok=True)
    return target_dir

def write_ip_csv(csv_path: str, ip_list: list[str]) -> None:
    directory = os.path.dirname(csv_path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    
    try:
        with os.fdopen(fd, mode="w", newline="", encoding="utf-8") as csv_file:
            csv_file.write("ip\n")
            if ip_list:
                csv_file.write("\n".join(ip_list) + "\n")
        os.replace(tmp_path, csv_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

def validate_input(definition: smi.ValidationDefinition):
    return

def _process_ti_updates(
    logger: logging.Logger,
    ti_url: str,
    ti_matching_regex: str,
    list_type: str,
    input_name: str
) -> None:
    ti_data = get_threat_list(logger, ti_url, ti_matching_regex)
    if not ti_data:
        logger.warning(f"{LOG_WARNING_TAG} [FILE SKIP] No data returned for {input_name}. Skipping local file write.")
        return

    target_dir = get_lookups_dir(list_type)
    csv_name = f"{input_name}.csv"
    csv_path = os.path.join(target_dir, csv_name)

    write_ip_csv(csv_path, ti_data)
    logger.debug(f"{LOG_DEBUG_TAG} [FILE COMMIT] Successfully wrote {len(ti_data)} IPs to {csv_path}")

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

            list_type = input_item.get("list_type", "blacklist")
            ti_url = input_item.get("ti_url")
            ti_matching_regex = input_item.get("ti_matching_regex")

            logger.info(f"{LOG_INFO_TAG} Starting TI processing for input: {normalized_input_name} (Type: {list_type})")

            _process_ti_updates(logger, ti_url, ti_matching_regex, list_type, normalized_input_name)

        except Exception as e:
            log.log_exception(logger, e, LOG_ERROR_TAG, msg_before=f"Exception in input {normalized_input_name}: {e}")
        finally:
            log.modular_input_end(logger, normalized_input_name)