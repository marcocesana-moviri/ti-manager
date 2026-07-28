import csv
import ipaddress
import logging
import os
import tempfile
import time
import re
from urllib.parse import urlparse
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
    """Scarica il feed da `ti_url` con retry e backoff.

    Estrae l'IP ed il CIDR (se presente) usando `ip_regex`.
    Ogni riga viene validata come IP/CIDR tramite la libreria ipaddress:
    le righe non valide o che non matchano la regex vengono scartate
    e contate. Il risultato è de-duplicato e ordinato.
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
                # Applica la regex passata come parametro
                match = ip_regex.search(candidate)
                if not match:
                    invalid_count += 1
                    continue
                groups = match.groups()   
                if len(groups) >= 1:
                    ip = match.group(1)
                    cidr = match.group(2) if len(groups) >= 2 and match.group(2) else "32"
                else:
                    # Fallback: la regex ha fatto match ma non ha capturing group.
                    # Prendiamo l'intero match (group 0) e cerchiamo di separare IP e CIDR a mano.
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


def get_csv_name_from_url(logger: logging.Logger, ti_url: str) -> str:
    parsed_path = urlparse(ti_url).path
    base_name = os.path.basename(parsed_path)
    name_without_ext = os.path.splitext(base_name)[0] or "threat_list"
    csv_name = f"{name_without_ext}.csv"
    logger.debug(f"{LOG_DEBUG_TAG} CSV file name derived from URL: {csv_name}")
    return csv_name


def get_csv_path(csv_name: str) -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    lookups_dir = os.path.abspath(os.path.join(script_dir, "..", "lookups"))
    os.makedirs(lookups_dir, exist_ok=True)
    return os.path.join(lookups_dir, csv_name)


def write_ip_csv(csv_path: str, ip_list: list[str], ti_description: str) -> None:
    """Scrive la lookup CSV in modo atomico (file temporaneo + rename)."""
    directory = os.path.dirname(csv_path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["ip_address", "ti_description"])           
            for ip in sorted(ip_list):
                writer.writerow([ip, ti_description])        
        os.replace(tmp_path, csv_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def validate_input(definition: smi.ValidationDefinition):
    return


def _process_ti_updates(
    logger: logging.Logger,
    ti_description: str,
    ti_url: str,
    ti_matching_regex: str,
) -> None:
    """Scarica il feed e aggiorna eventi/CSV."""
    ti_data = get_threat_list(logger, ti_url, ti_matching_regex)
    if not ti_data:
        logger.warning(f"{LOG_WARNING_TAG} No data fetched from URL: {ti_url}. Skipping.")
        return

    csv_name = get_csv_name_from_url(logger, ti_url)
    csv_path = get_csv_path(csv_name)
    file_exists = os.path.exists(csv_path)

    if not file_exists:
        logger.debug(f"{LOG_DEBUG_TAG} CSV {csv_name} does not exist. Creating it with {len(ti_data)} IP(s).")
        write_ip_csv(csv_path, ti_data, ti_description)
        return

    write_ip_csv(csv_path, ti_data, ti_description)
    logger.debug(f"{LOG_DEBUG_TAG} CSV {csv_name} refreshed with {len(ti_data)} IP(s).")


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

            ti_description = input_item.get("description")
            ti_url = input_item.get("ti_url")
            ti_matching_regex = input_item.get("ti_matching_regex")

            logger.debug(
                f"{LOG_DEBUG_TAG} Input parameters: description={ti_description}, ti_url={ti_url}, ti_matching_regex={ti_matching_regex}"
            )

            _process_ti_updates(logger, ti_description, ti_url, ti_matching_regex)

        except Exception as e:
            log.log_exception(
                logger,
                e,
                LOG_ERROR_TAG,
                msg_before=f"Exception raised while ingesting data for {normalized_input_name}: {e}",
            )
        finally:
            log.modular_input_end(logger, normalized_input_name)