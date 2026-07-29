import csv
import glob
import ipaddress
import logging
import os
import tempfile
from datetime import datetime, timezone

from solnlib import conf_manager, log
from splunklib import modularinput as smi

from configs import (
    ADDON_NAME,
    CONF_FILE_NAME,
    LOG_DEBUG_TAG,
    LOG_ERROR_TAG,
    LOG_WARNING_TAG,
)

MERGED_CSV_FILENAME = "merged_threat_list.csv"


def logger_for_input(input_name: str) -> logging.Logger:
    return log.Logs().get_logger(f"{ADDON_NAME.lower()}_{input_name}")


def get_lookups_dir() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    lookups_dir = os.path.abspath(os.path.join(script_dir, "..", "lookups"))
    os.makedirs(lookups_dir, exist_ok=True)
    return lookups_dir


def extract_networks_from_csvs(logger: logging.Logger, lookups_dir: str) -> tuple[list, list]:
    """
    Legge tutti i CSV in ../lookups (escluso il file mergiato).
    Tenta di fare il parsing della prima colonna come rete IPv4 o IPv6.
    """
    ipv4_nets = []
    ipv6_nets = []
    
    csv_pattern = os.path.join(lookups_dir, "*.csv")
    csv_files = glob.glob(csv_pattern)
    
    for filepath in csv_files:
        filename = os.path.basename(filepath)
        if filename == MERGED_CSV_FILENAME:
            continue  # Salta il file generato da noi
            
        logger.debug(f"{LOG_DEBUG_TAG} Reading source CSV: {filename}")
        try:
            with open(filepath, mode="r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if not row:
                        continue
                    
                    candidate = row[0].strip()
                    # Salta eventuali header o righe vuote
                    if not candidate or candidate.lower() in ("ip", "ip_address", "cidr"):
                        continue
                        
                    try:
                        # strict=False permette di convertire host bit settati nella subnet base corretta
                        net = ipaddress.ip_network(candidate, strict=False)
                        if net.version == 4:
                            ipv4_nets.append(net)
                        else:
                            ipv6_nets.append(net)
                    except ValueError:
                        # Non è un IP/CIDR valido, probabilmente è la descrizione o un errore nel file
                        pass
        except Exception as e:
            logger.warning(f"{LOG_WARNING_TAG} Error reading {filename}: {e}")
            
    return ipv4_nets, ipv6_nets


def optimize_ips(logger: logging.Logger, ipv4_nets: list, ipv6_nets: list) -> set[str]:
    """
    Usa collapse_addresses per eliminare IP/subnet duplicate o sovrapposte.
    Ritorna un set di stringhe ottimizzate.
    """
    logger.debug(f"{LOG_DEBUG_TAG} Collapsing {len(ipv4_nets)} IPv4 and {len(ipv6_nets)} IPv6 raw entries...")
    
    collapsed_v4 = list(ipaddress.collapse_addresses(ipv4_nets))
    collapsed_v6 = list(ipaddress.collapse_addresses(ipv6_nets))
    
    optimized_set = {str(net) for net in (collapsed_v4 + collapsed_v6)}
    logger.debug(f"{LOG_DEBUG_TAG} Collapsed to {len(optimized_set)} unique optimized subnets/IPs.")
    
    return set(optimized_set)


def read_existing_merged(merged_path: str) -> set[str]:
    """Legge il file generato all'esecuzione precedente per poter calcolare il diff."""
    if not os.path.exists(merged_path):
        return set()

    existing = set()
    with open(merged_path, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0].strip() and row[0].strip() != "ip_address":
                existing.add(row[0].strip())
    return existing


def write_merged_csv(merged_path: str, ip_set: set[str]) -> None:
    """Scrive la nuova lookup mergiata in modo atomico."""
    directory = os.path.dirname(merged_path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["ip_address"])
            for ip in sorted(ip_set):
                writer.writerow([ip])
        os.replace(tmp_path, merged_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def diff_ip_lists(logger: logging.Logger, new_ips: set[str], existing_ips: set[str]) -> tuple[set[str], set[str]]:
    added_ips = new_ips - existing_ips
    removed_ips = existing_ips - new_ips

    if added_ips:
        logger.debug(f"{LOG_DEBUG_TAG} {len(added_ips)} new IP(s)/Subnet(s) to add.")
    if removed_ips:
        logger.debug(f"{LOG_DEBUG_TAG} {len(removed_ips)} IP(s)/Subnet(s) to remove.")
    if not added_ips and not removed_ips:
        logger.debug(f"{LOG_DEBUG_TAG} No differences found since the last run.")

    return added_ips, removed_ips


def _generate_logs(ip_iterable: set[str], action: str) -> list[str]:
    timestamp = datetime.now(timezone.utc).isoformat()
    return [
        f'{timestamp} action="{action}", ip_address="{ip}", source="local_merge"'
        for ip in ip_iterable
    ]


def write_events(
    index: str,
    sourcetype: str,
    logs: list[str],
    input_name: str,
    event_writer: smi.EventWriter,
    logger: logging.Logger,
) -> None:
    for event_data in logs:
        try:
            event = smi.Event(
                data=event_data,
                index=index,
                sourcetype=sourcetype,
            )
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
    event_writer: smi.EventWriter,
) -> None:
    
    lookups_dir = get_lookups_dir()
    merged_path = os.path.join(lookups_dir, MERGED_CSV_FILENAME)

    # 1. Parsing di tutti i CSV (escluso quello mergiato)
    ipv4_nets, ipv6_nets = extract_networks_from_csvs(logger, lookups_dir)
    
    # 2. Ottimizzazione, dedup e merge delle subnet
    new_merged_ips = optimize_ips(logger, ipv4_nets, ipv6_nets)
    
    # 3. Lettura dello stato precedente
    existing_ips = read_existing_merged(merged_path)

    # 4. Calcolo del diff
    added_ips, removed_ips = diff_ip_lists(logger, new_merged_ips, existing_ips)

    # 5. Generazione ed invio eventi a Splunk per le modifiche
    if added_ips:
        logs_added = _generate_logs(added_ips, "added")
        write_events(index, sourcetype, logs_added, input_name, event_writer, logger)
        log.events_ingested(logger, input_name, sourcetype, len(logs_added), index)

    if removed_ips:
        logs_removed = _generate_logs(removed_ips, "removed")
        write_events(index, sourcetype, logs_removed, input_name, event_writer, logger)
        log.events_ingested(logger, input_name, sourcetype, len(logs_removed), index)

    # 6. Aggiornamento del file di stato locale (se necessario)
    if added_ips or removed_ips or not os.path.exists(merged_path):
        logger.debug(f"{LOG_DEBUG_TAG} Writing updated merged CSV to {merged_path}")
        write_merged_csv(merged_path, new_merged_ips)


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

            index = input_item.get("index", "default")
            sourcetype = input_item.get("sourcetype", "threat_intel")

            logger.debug(
                f"{LOG_DEBUG_TAG} Starting local lookup merge process: index={index}, sourcetype={sourcetype}"
            )

            _process_local_lookups(logger, input_name, index, sourcetype, event_writer)

        except Exception as e:
            log.log_exception(
                logger,
                e,
                LOG_ERROR_TAG,
                msg_before=f"Exception raised while executing modular input {normalized_input_name}: {e}",
            )
        finally:
            log.modular_input_end(logger, normalized_input_name)