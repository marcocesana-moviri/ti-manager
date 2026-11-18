from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Union

import requests
from solnlib import conf_manager, log
from splunklib import modularinput as smi

from configs import (
    ADDON_NAME,
    CONF_FILE_NAME,
    LOG_DEBUG_TAG,
    LOG_ERROR_TAG,
    LOG_INFO_TAG,
    LOG_WARNING_TAG,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF_SECONDS,
)

USER_AGENT = f"{ADDON_NAME}/1.0 (Splunk Modular Input)"
_INET_PTON = socket.inet_pton
_AF_INET = socket.AF_INET


@dataclass(frozen=True)
class FeedInputConfig:
    """Parametri risolti per una singola stanza di acquisizione feed TI."""
    raw_name: str
    normalized_name: str
    list_type: str
    ti_url: str
    ti_matching_regex: str

    @classmethod
    def from_stanza(cls, raw_name: str, stanza: Dict[str, Any]) -> FeedInputConfig:
        raw_type = str(stanza.get("list_type") or "blacklist").strip().lower()
        safe_type = "whitelists" if raw_type == "whitelist" else "blacklists"
        return cls(
            raw_name=raw_name,
            normalized_name=raw_name.split("/")[-1],
            list_type=safe_type,
            ti_url=(stanza.get("ti_url") or "").strip(),
            ti_matching_regex=(stanza.get("ti_matching_regex") or "").strip(),
        )


def logger_for_input(input_name: str) -> logging.Logger:
    return log.Logs().get_logger(f"{ADDON_NAME.lower()}_{input_name}")


def _get_target_paths(list_folder: str, input_name: str) -> tuple[str, str]:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_dir = os.path.abspath(os.path.join(script_dir, "..", "lookups", list_folder))
    os.makedirs(target_dir, exist_ok=True)
    csv_path = os.path.join(target_dir, f"{input_name}.csv")
    meta_path = os.path.join(target_dir, f".{input_name}.meta.json")
    return csv_path, meta_path


def _load_http_cache_meta(meta_path: str, csv_path: str) -> Dict[str, str]:
    """Carica ETag e Last-Modified solo se il CSV locale esiste ancora su disco."""
    if not os.path.exists(csv_path) or not os.path.exists(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _atomic_write_text(target_path: str, content: str) -> None:
    target_dir = os.path.dirname(target_path)
    prefix = f".{os.path.basename(target_path)}_"
    fd, tmp_path = tempfile.mkstemp(dir=target_dir, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, mode="w", newline="", encoding="utf-8") as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _save_http_cache_meta(meta_path: str, response: requests.Response) -> None:
    etag = response.headers.get("ETag")
    last_modified = response.headers.get("Last-Modified")
    if not etag and not last_modified:
        if os.path.exists(meta_path):
            try:
                os.remove(meta_path)
            except OSError:
                pass
        return

    meta_payload = json.dumps(
        {"etag": etag or "", "last_modified": last_modified or ""},
        indent=2,
        sort_keys=True,
    ) + "\n"
    _atomic_write_text(meta_path, meta_payload)


def _normalize_ip_or_cidr(raw_value: str) -> Optional[str]:
    """
    Normalizza un IP o CIDR in formato canonico (/32 per IPv4 singoli, /128 per IPv6 singoli).
    Usa socket.inet_pton come fast-path per singoli IPv4.
    """
    if "/" not in raw_value and ":" not in raw_value:
        try:
            _INET_PTON(_AF_INET, raw_value)
            return f"{raw_value}/32"
        except OSError:
            pass

    try:
        return str(ipaddress.ip_network(raw_value, strict=False))
    except ValueError:
        return None


def _extract_candidate_from_match(match: re.Match[str]) -> str:
    groups = match.groups()
    if len(groups) >= 1:
        ip = match.group(1) or ""
        cidr = match.group(2) if len(groups) >= 2 else None
        return f"{ip}/{cidr}" if cidr else ip
    return match.group(0)


def _download_and_parse_feed(
    logger: logging.Logger,
    ti_url: str,
    ip_regex: Union[str, re.Pattern[str]],
    cache_meta: Dict[str, str],
) -> tuple[str, Optional[List[str]], Optional[requests.Response]]:
    """
    Scarica e analizza il feed TI in streaming con supporto a HTTP 304 Not Modified.
    Restituisce (status, sorted_ips, response) dove status è:
    - "not_modified": il feed remoto non è cambiato (HTTP 304)
    - "updated": download completato con successo (sorted_ips può essere vuoto se il feed è vuoto)
    - "failed": errore HTTP/rete dopo tutti i tentativi
    """
    compiled_regex = re.compile(ip_regex) if isinstance(ip_regex, str) else ip_regex

    headers: Dict[str, str] = {"User-Agent": USER_AGENT}
    if cache_meta.get("etag"):
        headers["If-None-Match"] = cache_meta["etag"]
    if cache_meta.get("last_modified"):
        headers["If-Modified-Since"] = cache_meta["last_modified"]

    logger.info(f"{LOG_INFO_TAG} [FEED] Starting fetch url={ti_url}")
    start_time = time.perf_counter()

    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            with requests.get(
                ti_url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                stream=True,
            ) as response:
                if response.status_code == 304:
                    elapsed = time.perf_counter() - start_time
                    logger.info(
                        f"{LOG_INFO_TAG} [FEED] Remote feed unchanged (HTTP 304) "
                        f"url={ti_url} elapsed={elapsed:.2f}s"
                    )
                    return "not_modified", None, response

                response.raise_for_status()

                valid_ips: Set[str] = set()
                total_lines = 0
                regex_fails = 0
                invalid_ips = 0

                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue

                    line = (
                        raw_line.decode("utf-8", errors="ignore")
                        if isinstance(raw_line, bytes)
                        else raw_line
                    )
                    candidate = line.strip()
                    if not candidate or candidate.startswith("#"):
                        continue

                    total_lines += 1
                    match = compiled_regex.search(candidate)
                    if not match:
                        regex_fails += 1
                        continue

                    extracted = _extract_candidate_from_match(match).strip()
                    normalized = _normalize_ip_or_cidr(extracted)
                    if normalized is not None:
                        valid_ips.add(normalized)
                    else:
                        invalid_ips += 1

                elapsed = time.perf_counter() - start_time
                logger.info(
                    f"{LOG_INFO_TAG} [FEED] Parsed feed url={ti_url} attempt={attempt} "
                    f"unique_ips={len(valid_ips)} total_lines={total_lines} "
                    f"regex_fails={regex_fails} invalid_ips={invalid_ips} elapsed={elapsed:.2f}s"
                )
                return "updated", sorted(valid_ips), response

        except requests.RequestException as exc:
            if attempt < REQUEST_RETRIES:
                delay = RETRY_BACKOFF_SECONDS * attempt
                logger.warning(
                    f"{LOG_WARNING_TAG} [FEED] Retryable download error url={ti_url} "
                    f"attempt={attempt}/{REQUEST_RETRIES} backoff={delay}s error={exc!r}"
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"{LOG_ERROR_TAG} [FEED] Download failed permanently url={ti_url} "
                    f"attempts={REQUEST_RETRIES} error={exc!r}"
                )

    return "failed", None, None


def _process_ti_feed(logger: logging.Logger, config: FeedInputConfig) -> None:
    csv_path, meta_path = _get_target_paths(config.list_type, config.normalized_name)
    cache_meta = _load_http_cache_meta(meta_path, csv_path)

    status, ip_list, response = _download_and_parse_feed(
        logger=logger,
        ti_url=config.ti_url,
        ip_regex=config.ti_matching_regex,
        cache_meta=cache_meta,
    )

    if status in ("failed", "not_modified") or ip_list is None:
        return

    new_content = "ip\n" + ("\n".join(ip_list) + "\n" if ip_list else "")

    # Evita di alterare il timestamp (mtime) del CSV se i record estratti sono identici
    content_changed = True
    if os.path.exists(csv_path):
        try:
            with open(csv_path, "r", encoding="utf-8") as existing_file:
                if existing_file.read() == new_content:
                    content_changed = False
        except OSError:
            pass

    if content_changed:
        _atomic_write_text(csv_path, new_content)
        logger.info(
            f"{LOG_INFO_TAG} [FILE] Updated local lookup file={csv_path} records={len(ip_list)}"
        )
    else:
        logger.info(
            f"{LOG_INFO_TAG} [FILE] Extracted records identical to local CSV; preserving mtime "
            f"file={csv_path} records={len(ip_list)}"
        )

    if response is not None:
        _save_http_cache_meta(meta_path, response)


def validate_input(definition: smi.ValidationDefinition) -> None:
    return


def stream_events(inputs: smi.InputDefinition, event_writer: smi.EventWriter) -> None:
    session_key = inputs.metadata["session_key"]

    for raw_input_name, stanza in inputs.inputs.items():
        config = FeedInputConfig.from_stanza(raw_input_name, stanza)
        logger = logger_for_input(config.normalized_name)

        try:
            log_level = conf_manager.get_log_level(
                logger=logger,
                session_key=session_key,
                app_name=ADDON_NAME,
                conf_name=CONF_FILE_NAME,
            )
            logger.setLevel(log_level)
            log.modular_input_start(logger, config.normalized_name)

            if not config.ti_url or not config.ti_matching_regex:
                logger.error(
                    f"{LOG_ERROR_TAG} [CONFIG] Missing required parameters input={config.normalized_name} "
                    f"ti_url={config.ti_url!r} has_regex={bool(config.ti_matching_regex)}"
                )
                continue

            _process_ti_feed(logger, config)

        except re.error as regex_err:
            logger.error(
                f"{LOG_ERROR_TAG} [CONFIG] Invalid regex pattern input={config.normalized_name} "
                f"regex={config.ti_matching_regex!r} error={regex_err!r}"
            )
        except Exception as exc:
            log.log_exception(
                logger,
                exc,
                LOG_ERROR_TAG,
                msg_before=f"[FEED] Unhandled exception in input={config.normalized_name}: {exc}",
            )
        finally:
            log.modular_input_end(logger, config.normalized_name)