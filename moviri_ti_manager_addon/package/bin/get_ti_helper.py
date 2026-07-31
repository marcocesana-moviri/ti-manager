import csv
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
    Downloads the feed from `ti_url` implementing retry and backoff logic.
    
    Extracts the IP and CIDR (if present) using `ip_regex`.
    Each line is validated using the ipaddress library: invalid lines or those 
    not matching the regex are skipped and counted. The result is deduplicated and sorted.
    """
    if isinstance(ip_regex, str):
        ip_regex = re.compile(ip_regex)
        
    logger.debug(f"{LOG_DEBUG_TAG} Fetching threat intelligence data from: {ti_url}")
    
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            response = requests.get(ti_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            
            valid_ips = []
            invalid_count = 0
            
            for line in response.text.splitlines():
                candidate = line.strip()
                if not candidate or candidate.startswith("#"):
                    continue
                    
                # Apply the regex passed as a parameter
                match = ip_regex.search(candidate)
                if not match:
                    invalid_count += 1
                    continue
                    
                groups = match.groups()   
                if len(groups) >= 1:
                    ip = match.group(1)
                    cidr = match.group(2) if len(groups) >= 2 and match.group(2) else "32"
                else:
                    # Fallback: regex matched but has no capturing groups.
                    # Take the full match (group 0) and try to split IP and CIDR manually.
                    full_match = match.group(0)
                    if "/" in full_match:
                        ip, cidr = full_match.split("/", 1)
                    else:
                        ip = full_match
                        cidr = "32"
                        
                ip_cidr_str = f"{ip}/{cidr}"
                
                try:
                    network = ipaddress.ip_network(ip_cidr_str, strict=False)
                    valid_ips.append(str(network))
                except ValueError:
                    invalid_count += 1
                    
            deduped_ips = sorted(set(valid_ips))
            logger.debug(
                f"{LOG_DEBUG_TAG} Fetched {len(deduped_ips)} valid IP(s) ({invalid_count} invalid line(s) skipped) from {ti_url}"
            )
            return deduped_ips
            
        except requests.RequestException as e:
            logger.error(
                f"{LOG_ERROR_TAG} Attempt {attempt}/{REQUEST_RETRIES} failed for {ti_url}: {e}"
            )
            
        if attempt < REQUEST_RETRIES:
            delay = RETRY_BACKOFF_SECONDS * attempt
            logger.debug(
                f"{LOG_DEBUG_TAG} Retrying in {delay}s (attempt {attempt + 1}/{REQUEST_RETRIES})"
            )
            time.sleep(delay)
            
    logger.error(f"{LOG_ERROR_TAG} Giving up fetching {ti_url} after {REQUEST_RETRIES} attempts.")
    return []


def get_lookups_dir(list_type: str) -> str:
    """
    Creates and returns the specific lookups subdirectory based on the list type.
    Defaults to 'blacklists' if the type is not explicitly 'whitelist'.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    safe_type = "whitelists" if str(list_type).strip().lower() == "whitelist" else "blacklists"
    
    target_dir = os.path.abspath(os.path.join(script_dir, "..", "lookups", safe_type))
    os.makedirs(target_dir, exist_ok=True)
    
    return target_dir


def write_ip_csv(csv_path: str, ip_list: list[str]) -> None:
    """Writes the IP lookup CSV atomically using fast block I/O operations."""
    directory = os.path.dirname(csv_path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    
    try:
        with os.fdopen(fd, mode="w", newline="", encoding="utf-8") as csv_file:
            # Block write optimization for large datasets
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
    """Downloads the feed and updates the local CSV in the correct target folder."""
    ti_data = get_threat_list(logger, ti_url, ti_matching_regex)
    if not ti_data:
        logger.warning(f"{LOG_WARNING_TAG} No data fetched from URL: {ti_url}. Skipping CSV update.")
        return

    # Route the CSV to the correct directory based on list_type
    target_dir = get_lookups_dir(list_type)
    
    # Name the file exactly as the modular input name
    csv_name = f"{input_name}.csv"
    csv_path = os.path.join(target_dir, csv_name)

    write_ip_csv(csv_path, ti_data)
    logger.debug(f"{LOG_DEBUG_TAG} CSV {csv_name} successfully refreshed with {len(ti_data)} IP(s) in {target_dir}.")


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

            # Retrieve parameters from Splunk configuration
            list_type = input_item.get("list_type")
            ti_url = input_item.get("ti_url")
            ti_matching_regex = input_item.get("ti_matching_regex")

            logger.debug(
                f"{LOG_DEBUG_TAG} Input parameters: list_type={list_type}, ti_url={ti_url}, ti_matching_regex={ti_matching_regex}"
            )

            _process_ti_updates(logger, ti_url, ti_matching_regex, list_type, normalized_input_name)

        except Exception as e:
            log.log_exception(
                logger,
                e,
                LOG_ERROR_TAG,
                msg_before=f"Exception raised while ingesting data for {normalized_input_name}: {e}",
            )
        finally:
            log.modular_input_end(logger, normalized_input_name)