import csv
import glob
import ipaddress
import logging
import os
import tempfile
import json
import urllib.parse
import requests
from datetime import datetime, timezone
from typing import Optional

from solnlib import conf_manager, credentials, log
from splunklib import modularinput as smi

from configs import (
    ADDON_NAME,
    CONF_FILE_NAME,
    LOG_INFO_TAG,
    LOG_DEBUG_TAG,
    LOG_ERROR_TAG,
    LOG_WARNING_TAG,
    ACCOUNT_CONF_FILE_NAME
)

MERGED_CSV_FILENAME = "merged_threat_list.csv"


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


def get_account_settings(
    session_key: str, account_name: str, logger: logging.Logger
) -> tuple[Optional[str], Optional[str]]:

    splunk_username = None
    splunk_password = None

    try:
        cfm = _get_conf_manager(session_key, ACCOUNT_CONF_FILE_NAME)
        account_conf_file = cfm.get_conf(ACCOUNT_CONF_FILE_NAME)
        account_data = account_conf_file.get(account_name)
        splunk_username = account_data.get("splunk_username") if account_data else None
        logger.debug(
            f"{LOG_DEBUG_TAG} Retrieved account settings for account: {account_name}, splunk_username: {splunk_username}"
        )

        cm = _get_credential_manager(session_key, ACCOUNT_CONF_FILE_NAME)
        credential_data = cm.get_password(account_name)
        splunk_password = json.loads(credential_data).get("splunk_password") if credential_data else None
        logger.debug(f"{LOG_DEBUG_TAG} Retrieved secret key for account: {account_name}")
    except Exception as err:
        splunk_username = splunk_username or None
        splunk_password = splunk_password or None
        logger.error(f"{LOG_ERROR_TAG} Failed to retrieve account settings for {account_name}, error: {err}")

    return splunk_username, splunk_password

def get_manual_blacklist(
    logger: logging.Logger, 
    lookups_dir: str, 
    splunk_username: str, 
    splunk_password: str,
    splunk_host: str = "192.168.15.49",
    splunk_port: int = 8089
) -> None:
    """
    Scarica la manual blacklist dal KV Store di Splunk e la salva come CSV.
    """
    # Parametri dell'endpoint
    app_name = "search"
    collection_name = "manual_blacklist"
    
    url = f"https://{splunk_host}:{splunk_port}/servicesNS/nobody/{app_name}/storage/collections/data/{collection_name}"
    
    # Equivalente al parametro -d 'limit=50000' in GET
    params = {
        "limit": 50000
    }

    logger.debug(f"{LOG_DEBUG_TAG} Richiesta della manual blacklist dal KV Store: {url}")

    try:
        # Esecuzione della richiesta GET (verify=False simula il flag -k di curl)
        response = requests.get(
            url,
            auth=(splunk_username, splunk_password),
            params=params,
            verify=False,
            timeout=30
        )
        
        # Lancia un'eccezione se il server restituisce un codice di errore HTTP (es. 401, 404, 500)
        response.raise_for_status()
        
        # Parsing del JSON restituito
        data = response.json()
        
        # Percorso in cui salvare il file scaricato
        csv_path = os.path.join(lookups_dir, "manual_blacklist.csv")
        
        # Salvataggio dei dati su file CSV
        with open(csv_path, mode="w", newline="", encoding="utf-8") as csv_file:
            # Scegli le colonne che il tuo extract_networks_from_csvs si aspetta di trovare
            writer = csv.writer(csv_file)
            writer.writerow(["ip_address"])
            
            for item in data:
                ip = item.get("ip_address")
                if ip:  # Salviamo solo se il campo ip è presente
                    writer.writerow([ip])
                    
        logger.info(f"{LOG_INFO_TAG} Scaricati {len(data)} record dal KV Store e salvati in {csv_path}")

    except requests.exceptions.RequestException as e:
        logger.error(f"{LOG_INFO_TAG} Errore durante il recupero della manual blacklist dal KV Store: {e}")


def push_merged_blacklist(
    logger: logging.Logger,
    splunk_username: str,
    splunk_password: str,
    added_ips: set,
    removed_ips: set,
    splunk_host: str = "192.168.15.49",
    splunk_port: int = 8089
) -> None:
    """
    Sincronizza le modifiche della blacklist con il KV Store remoto 'merged_blacklist'.
    """
    app_name = "search"
    collection_name = "merged_blacklist"
    base_url = f"https://{splunk_host}:{splunk_port}/servicesNS/nobody/{app_name}/storage/collections/data/{collection_name}"
    
    auth_tuple = (splunk_username, splunk_password)
    
    # 1. Gestione delle RIMOZIONI (DELETE)
    if removed_ips:
        logger.debug(f"{LOG_DEBUG_TAG} Rimozione di {len(removed_ips)} IP dal KV Store {collection_name}")
        for ip in removed_ips:
            # Sostituisce la '/' della subnet con '%2F' per non rompere il path dell'URL REST
            safe_key = urllib.parse.quote(ip, safe="")
            delete_url = f"{base_url}/{safe_key}"
            
            try:
                response = requests.delete(
                    delete_url,
                    auth=auth_tuple,
                    verify=False,
                    timeout=10
                )
                # Ignoriamo errore 404: se l'IP non c'è già, l'obiettivo è comunque raggiunto
                if response.status_code not in (200, 404):
                    response.raise_for_status()
            except requests.exceptions.RequestException as e:
                logger.error(f"{LOG_ERROR_TAG} Errore durante l'eliminazione dell'IP {ip} dal KV Store: {e}")

    # 2. Gestione delle AGGIUNTE (POST via batch_save)
    if added_ips:
        logger.debug(f"{LOG_DEBUG_TAG} Aggiunta di {len(added_ips)} IP al KV Store {collection_name}")
        batch_url = f"{base_url}/batch_save"
        headers = {"Content-Type": "application/json"}
        
        # Creazione della lista di dizionari per il payload JSON
        # Assumo che added_ips sia un iterabile di stringhe (es. ["1.1.1.1/32", ...])
        # Aggiungo _user???????????
        payload = [{"_key": ip, "ip_address": ip} for ip in added_ips]
        
        # Splunk ha un limite sulle dimensioni delle richieste batch (di default spesso 1000 o 10MB)
        # Dividiamo in chunk di 1000 elementi per sicurezza
        chunk_size = 1000
        for i in range(0, len(payload), chunk_size):
            chunk = payload[i:i + chunk_size]
            try:
                response = requests.post(
                    batch_url,
                    auth=auth_tuple,
                    headers=headers,
                    json=chunk,
                    verify=False,
                    timeout=30
                )
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                logger.error(f"{LOG_ERROR_TAG} Errore durante il push batch ({len(chunk)} elementi) al KV Store: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"{LOG_ERROR_TAG} Dettaglio risposta Splunk: {e.response.text}")


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
    splunk_username: str,
    splunk_password: str,
    event_writer: smi.EventWriter,
) -> None:
    
    lookups_dir = get_lookups_dir()
    merged_path = os.path.join(lookups_dir, MERGED_CSV_FILENAME)

    # 0. Recupera dal kvstore di uno dei search head la manual blacklist
    get_manual_blacklist(logger, lookups_dir, splunk_username, splunk_password)

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
        logger.debug(f"{LOG_DEBUG_TAG} Pushing updated merged CSV to remote KV Store")
        push_merged_blacklist(
            logger,
            splunk_username,
            splunk_password,
            added_ips,
            removed_ips
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

            index = input_item.get("index", "default")
            sourcetype = input_item.get("sourcetype", "threat_intel")
            account_name = input_item.get("account")

            splunk_username, splunk_password = get_account_settings(session_key, account_name, logger)

            logger.debug(
                f"{LOG_DEBUG_TAG} Starting local lookup merge process: index={index}, sourcetype={sourcetype}"
            )

            _process_local_lookups(logger, input_name, index, sourcetype, splunk_username, splunk_password, event_writer)

        except Exception as e:
            log.log_exception(
                logger,
                e,
                LOG_ERROR_TAG,
                msg_before=f"Exception raised while executing modular input {normalized_input_name}: {e}",
            )
        finally:
            log.modular_input_end(logger, normalized_input_name)