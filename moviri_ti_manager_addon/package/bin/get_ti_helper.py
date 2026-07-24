import csv
import ipaddress
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

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


def is_valid_ip(value: str) -> bool:
    """True se `value` è un indirizzo IPv4/IPv6 o una rete CIDR sintatticamente valida."""
    try:
        ipaddress.ip_network(value, strict=False)
        return True
    except ValueError:
        return False


def get_threat_list(logger: logging.Logger, ti_url: str) -> list[str]:
    """Scarica il feed da `ti_url` con retry e backoff.

    Ogni riga viene validata come IP/CIDR: le righe non valide vengono scartate
    e contate, non propagate silenziosamente nella lookup. Il risultato è
    de-duplicato e ordinato per rendere i diff deterministici.
    """
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
                if is_valid_ip(candidate):
                    valid_ips.append(candidate)
                else:
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


def read_existing_ips(csv_path: str) -> set[str]:
    """Legge la colonna ip_address dalla lookup esistente (set vuoto se il file non esiste)."""
    if not os.path.exists(csv_path):
        return set()

    with open(csv_path, mode="r", newline="", encoding="utf-8") as csv_file:
        rows = list(csv.reader(csv_file))

    if not rows:
        return set()

    # La prima riga è l'header, viene saltata.
    return {row[0].strip() for row in rows[1:] if row and row[0].strip()}


def write_ip_csv(csv_path: str, ip_list: list[str]) -> None:
    """Scrive la lookup CSV in modo atomico (file temporaneo + rename)."""
    directory = os.path.dirname(csv_path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["ip_address"])
            for ip in sorted(ip_list):
                writer.writerow([ip])
        os.replace(tmp_path, csv_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def diff_ip_lists(
    logger: logging.Logger, new_ips: list[str], existing_ips: set[str]
) -> tuple[set[str], set[str]]:
    """Confronta il nuovo elenco di IP con quello già presente nella lookup."""
    new_set = set(new_ips)
    added_ips = new_set - existing_ips
    removed_ips = existing_ips - new_set

    if added_ips:
        logger.debug(f"{LOG_DEBUG_TAG} New IP address(es) added: {len(added_ips)}.")
    if removed_ips:
        logger.debug(f"{LOG_DEBUG_TAG} IP address(es) removed: {len(removed_ips)}.")
    if not added_ips and not removed_ips:
        logger.debug(f"{LOG_DEBUG_TAG} No changes in the threat intelligence data.")

    return added_ips, removed_ips


def _generate_logs(ip_list: list[str], ti_url: str, action: str) -> list[str]:
    timestamp = datetime.now(timezone.utc).isoformat()
    return [
        f'{timestamp} action="{action}", ip_address="{ip}", threat_list="{ti_url}"'
        for ip in ip_list
    ]


def validate_input(definition: smi.ValidationDefinition):
    return


def write_events(
    index: str,
    sourcetype: str,
    logs: list[str],
    input_name: str,
    event_writer: smi.EventWriter,
    logger: logging.Logger,
) -> None:
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
            logger.error(f"{LOG_ERROR_TAG} Failed to write event for input '{input_name}': {err}")


def _process_ti_updates(
    logger: logging.Logger,
    input_name: str,
    index: str,
    sourcetype: str,
    ti_url: str,
    event_writer: smi.EventWriter,
) -> None:
    """Scarica il feed, calcola il diff rispetto alla lookup e aggiorna eventi/CSV."""
    ti_data = get_threat_list(logger, ti_url)
    if not ti_data:
        logger.warning(f"{LOG_WARNING_TAG} No data fetched from URL: {ti_url}. Skipping event writing.")
        return

    csv_name = get_csv_name_from_url(logger, ti_url)
    csv_path = get_csv_path(csv_name)
    file_exists = os.path.exists(csv_path)

    if not file_exists:
        logger.debug(f"{LOG_DEBUG_TAG} CSV {csv_name} does not exist. Creating it with {len(ti_data)} IP(s).")
        write_ip_csv(csv_path, ti_data)
        logs = _generate_logs(ti_data, ti_url, "added")
        write_events(index, sourcetype, logs, input_name, event_writer, logger)
        log.events_ingested(logger, input_name, sourcetype, len(logs), index)
        return

    existing_ips = read_existing_ips(csv_path)
    added_ips, removed_ips = diff_ip_lists(logger, ti_data, existing_ips)

    if added_ips:
        logs = _generate_logs(sorted(added_ips), ti_url, "added")
        write_events(index, sourcetype, logs, input_name, event_writer, logger)
        log.events_ingested(logger, input_name, sourcetype, len(logs), index)

    if removed_ips:
        logs = _generate_logs(sorted(removed_ips), ti_url, "removed")
        write_events(index, sourcetype, logs, input_name, event_writer, logger)
        log.events_ingested(logger, input_name, sourcetype, len(logs), index)

    if added_ips or removed_ips:
        write_ip_csv(csv_path, ti_data)
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

            index = input_item.get("index")
            sourcetype = input_item.get("sourcetype")
            ti_url = input_item.get("ti_url")

            logger.debug(
                f"{LOG_DEBUG_TAG} Input parameters: ti_url={ti_url}, index={index}, sourcetype={sourcetype}"
            )

            _process_ti_updates(logger, input_name, index, sourcetype, ti_url, event_writer)

        except Exception as e:
            log.log_exception(
                logger,
                e,
                LOG_ERROR_TAG,
                msg_before=f"Exception raised while ingesting data for {normalized_input_name}: {e}",
            )
        finally:
            log.modular_input_end(logger, normalized_input_name)