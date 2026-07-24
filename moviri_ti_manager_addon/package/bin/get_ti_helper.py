import json
import logging
import ipaddress
import os

import requests
from solnlib import conf_manager, log
from splunklib import modularinput as smi
from urllib.parse import urlparse
from configs import (ADDON_NAME, LOG_DEBUG_TAG, LOG_INFO_TAG, LOG_ERROR_TAG, LOG_WARNING_TAG, LOG_CRITICAL_TAG, REQUEST_TIMEOUT, REQUEST_RETRIES)


def logger_for_input(input_name: str) -> logging.Logger:
    return log.Logs().get_logger(f"{ADDON_NAME.lower()}_{input_name}")


def get_threat_list(logger: logging.Logger, ti_url: str):
    logger.info(f"{LOG_DEBUG_TAG} Starting to fetch threat intelligence data from URL: {ti_url}")
    for attempt in range(REQUEST_RETRIES):
        try:
            response = requests.get(ti_url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                logger.info(f"{LOG_DEBUG_TAG} Successfully fetched threat intelligence data from URL: {ti_url}")
                lines = response.text.splitlines()
                valid_ips = [
                    line.strip()
                    for line in lines
                    if line.strip() and not line.strip().startswith('#')
                ]
                logger.info(f"{LOG_DEBUG_TAG} Number of valid IP addresses fetched: {len(valid_ips)}")
                return valid_ips
            else:
                logger.error(f"{LOG_ERROR_TAG} Failed to fetch threat intelligence data from URL: {ti_url}, status code: {response.status_code}. Attempt {attempt + 1} of {REQUEST_RETRIES}.")
        except requests.RequestException as e:
            logger.error(f"{LOG_ERROR_TAG} Attempt {attempt + 1} failed with exception: {e}")
        
        if attempt < REQUEST_RETRIES - 1:
            logger.info(f"{LOG_INFO_TAG} Retrying... (Attempt {attempt + 2}/{REQUEST_RETRIES})")
    logger.error(f"{LOG_ERROR_TAG} Failed to fetch threat intelligence data from URL: {ti_url} after {REQUEST_RETRIES} attempts.")
    return []


def get_csv_name_from_url(logger: logging.Logger, ti_url: str):
    parsed_path = urlparse(ti_url).path
    base_name = os.path.basename(parsed_path)
    name_without_ext = os.path.splitext(base_name)[0]
    logger.info(f"{LOG_DEBUG_TAG} Extracted CSV name from URL: {name_without_ext}")
    csv_name = f"{name_without_ext}.csv"
    return csv_name


def validate_input(definition: smi.ValidationDefinition):
    return


def write_events(
    index: str,
    sourcetype: str,
    events: list[dict],
    input_name: str,
    event_writer: smi.EventWriter,
    logger: logging.Logger,
) -> None:

    for event in events:
        try:
            event_writer.write_event(
                smi.Event(
                    data=json.dumps(event, ensure_ascii=False, default=str),
                    index=index,
                    sourcetype=sourcetype,
                )
            )
        except Exception as err:
            logger.error(f"{LOG_ERROR_TAG} Failed to write event for input: {input_name}, error: {err}")
    log.events_ingested(
        logger,
        input_name,
        sourcetype,
        len(events),
        index,
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
            csv_name = get_csv_name_from_url(logger, ti_url)
            

            write_events(index, sourcetype, data, input_name, event_writer, logger)
            
            log.events_ingested(
                logger,
                input_name,
                sourcetype,
                len(data),
                input_item.get("index"),
                account=input_item.get("account"),
            )
            log.modular_input_end(logger, normalized_input_name)
        except Exception as e:
            log.log_exception(
                logger,
                e,
                LOG_ERROR_TAG,
                msg_before=f"Exception raised while ingesting data for {normalized_input_name}: {e}",
            )