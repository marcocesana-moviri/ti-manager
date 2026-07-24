import json
import logging
import ipaddress
import os
import csv

import requests
from solnlib import conf_manager, log
from splunklib import modularinput as smi
from urllib.parse import urlparse
from datetime import datetime, timezone
from configs import (ADDON_NAME, LOG_DEBUG_TAG, LOG_INFO_TAG, LOG_ERROR_TAG, LOG_WARNING_TAG, LOG_CRITICAL_TAG, REQUEST_TIMEOUT, REQUEST_RETRIES)


def logger_for_input(input_name: str) -> logging.Logger:
    return log.Logs().get_logger(f"{ADDON_NAME.lower()}_{input_name}")


def get_threat_list(logger: logging.Logger, ti_url: str):
    logger.debug(f"{LOG_DEBUG_TAG} Starting to fetch threat intelligence data from URL: {ti_url}")
    for attempt in range(REQUEST_RETRIES):
        try:
            response = requests.get(ti_url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                logger.debug(f"{LOG_DEBUG_TAG} Successfully fetched threat intelligence data from URL: {ti_url}")
                lines = response.text.splitlines()
                valid_ips = [
                    line.strip()
                    for line in lines
                    if line.strip() and not line.strip().startswith('#')
                ]
                logger.debug(f"{LOG_DEBUG_TAG} Number of valid IP addresses fetched: {len(valid_ips)}")
                return valid_ips
            else:
                logger.error(f"{LOG_ERROR_TAG} Failed to fetch threat intelligence data from URL: {ti_url}, status code: {response.status_code}. Attempt {attempt + 1} of {REQUEST_RETRIES}.")
        except requests.RequestException as e:
            logger.error(f"{LOG_ERROR_TAG} Attempt {attempt + 1} failed with exception: {e}")
        
        if attempt < REQUEST_RETRIES - 1:
            logger.debug(f"{LOG_DEBUG_TAG} Retrying... (Attempt {attempt + 2}/{REQUEST_RETRIES})")
    logger.error(f"{LOG_ERROR_TAG} Failed to fetch threat intelligence data from URL: {ti_url} after {REQUEST_RETRIES} attempts.")
    return []


def get_csv_name_from_url(logger: logging.Logger, ti_url: str):
    parsed_path = urlparse(ti_url).path
    base_name = os.path.basename(parsed_path)
    name_without_ext = os.path.splitext(base_name)[0]
    logger.debug(f"{LOG_DEBUG_TAG} Extracted CSV name from URL: {name_without_ext}")
    csv_name = f"{name_without_ext}.csv"
    return csv_name

def get_csv_path(csv_name: str):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    lookups_dir = os.path.abspath(os.path.join(script_dir, "..", "lookups"))
    os.makedirs(lookups_dir, exist_ok=True)
    return os.path.join(lookups_dir, csv_name)

def compare_ip_lists(logger: logging.Logger, ti_data: list[str], csv_path: str):
    with open(csv_path, mode='r', newline='', encoding='utf-8') as csv_file:
        csv_lines = csv_file.readlines()

    old_list = set(line.strip() for line in csv_lines[1:] if line.strip())
    new_list = set(ip.strip() for ip in ti_data if ip.strip())
    added_ips = new_list - old_list
    removed_ips = old_list - new_list

    if added_ips:
        logger.debug(f"{LOG_DEBUG_TAG} New IP addresses added: {len(added_ips)}.")           

    if removed_ips:
        logger.debug(f"{LOG_DEBUG_TAG} IP addresses removed: {len(removed_ips)}.")
        
    if not added_ips and not removed_ips:
        logger.debug(f"{LOG_DEBUG_TAG} No changes in the threat intelligence data.")

    return added_ips, removed_ips

def _generate_logs(ti_data: list[str], ti_url: str, action: str):
    logs = [
        f'{datetime.now(timezone.utc).isoformat()} action="{action}", ip_address="{ip}", threat_list="{ti_url}"' 
        for ip in ti_data
    ]
    return logs

def validate_input(definition: smi.ValidationDefinition):
    return


def write_events(index: str, sourcetype: str, logs: list[str], input_name: str, event_writer: smi.EventWriter, logger: logging.Logger) -> None:
    for event in logs:
        try:
            event_writer.write_event(
                smi.Event(
                    data=event,
                    index=index,
                    sourcetype=sourcetype,
                )
            )
        except Exception as err:
            logger.error(f"{LOG_ERROR_TAG} Failed to write event for input: {input_name}, error: {err}")


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
                conf_name="moviri_ti_manager_addon_settings",
            )
            logger.setLevel(log_level)
            log.modular_input_start(logger, normalized_input_name)

            # Get input parameters
            index = input_item.get("index")
            sourcetype = input_item.get("sourcetype")
            ti_url = input_item.get("ti_url")

            logger.debug(
                f"{LOG_DEBUG_TAG} Input parameters: ti_url={ti_url}, index={index}, sourcetype={sourcetype}"
            )

            # Get data from the external threat list
            ti_data = get_threat_list(logger, ti_url)
            if ti_data:
                csv_name = get_csv_name_from_url(logger, ti_url)
                csv_path = get_csv_path(csv_name)
                if not os.path.exists(csv_path):
                    logger.debug(f"{LOG_DEBUG_TAG} CSV {csv_name} does not exist. Creating the file.")
                    with open(csv_path, mode='w', newline='', encoding='utf-8') as csv_file:
                        writer = csv.writer(csv_file)
                        writer.writerow(['ip_address'])
                        for ip in ti_data:
                            writer.writerow([ip])
                    logger.debug(f"{LOG_DEBUG_TAG} CSV {csv_name} file created. {len(ti_data)} IP addresses written to the file.")
                    logs = _generate_logs(ti_data, ti_url, "added")
                    write_events(index, sourcetype, logs, input_name, event_writer, logger)
                    log.events_ingested(logger, input_name, sourcetype, len(logs), index)
                    log.modular_input_end(logger, normalized_input_name)
                else:
                    logger.debug(f"{LOG_DEBUG_TAG} CSV {csv_name} already exists. Skipping file creation.")
                    added_ips, removed_ips = compare_ip_lists(logger, ti_data, csv_path)
                    if added_ips:
                        logs = _generate_logs(list(added_ips), ti_url, "added")
                        write_events(index, sourcetype, logs, input_name, event_writer, logger)
                        log.events_ingested(logger, input_name, sourcetype, len(logs), index)
                    if removed_ips:
                        logs = _generate_logs(list(removed_ips), ti_url, "removed")
                        write_events(index, sourcetype, logs, input_name, event_writer, logger)
                        log.events_ingested(logger, input_name, sourcetype, len(logs), index)
                    if added_ips or removed_ips:
                        with open(csv_path, mode='w', newline='', encoding='utf-8') as csv_file:
                            writer = csv.writer(csv_file)
                            writer.writerow(['ip_address'])
                            for ip in ti_data:
                                writer.writerow([ip])
                            logger.debug(f"{LOG_DEBUG_TAG} CSV {csv_name} file overwritten. {len(ti_data)} IP addresses written to the file.")
                    log.modular_input_end(logger, normalized_input_name)
            else:
                logger.warning(f"{LOG_WARNING_TAG} No data fetched from URL: {ti_url}. Skipping event writing.")
                log.modular_input_end(logger, normalized_input_name)
            
        except Exception as e:
            log.log_exception(
                logger,
                e,
                LOG_ERROR_TAG,
                msg_before=f"Exception raised while ingesting data for {normalized_input_name}: {e}",
            )