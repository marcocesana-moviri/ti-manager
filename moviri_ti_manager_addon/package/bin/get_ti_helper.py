import json
import logging

import import_declare_test
from solnlib import conf_manager, log
from splunklib import modularinput as smi
from configs import ADDON_NAME, LOG_DEBUG_TAG, LOG_INFO_TAG, LOG_ERROR_TAG, LOG_WARNING_TAG, LOG_CRITICAL_TAG


def logger_for_input(input_name: str) -> logging.Logger:
    return log.Logs().get_logger(f"{ADDON_NAME.lower()}_{input_name}")


def get_data_from_api(logger: logging.Logger, api_key: str):
    logger.info("Getting data from an external API")
    dummy_data = [
        {
            "line1": "hello",
        },
        {
            "line2": "world",
        },
    ]
    return dummy_data


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
            data = get_threat_list(logger, ti_url)

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