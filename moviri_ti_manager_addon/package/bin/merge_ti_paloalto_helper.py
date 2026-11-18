from __future__ import annotations

from splunklib import modularinput as smi

from ti_sync_core import (
    COLLECTION_MANUAL_ALLOWLIST,
    COLLECTION_MANUAL_DENYLIST,
    TargetProfile,
    execute_modular_input,
)

PALOALTO_TARGET_PROFILE = TargetProfile(
    target_name="paloalto",
    state_filename="state_paloalto.json",
    denylist_collection="denylist_paloalto",
    manual_collections_to_fetch=(
        COLLECTION_MANUAL_DENYLIST,
        COLLECTION_MANUAL_ALLOWLIST,
        "es_automatic_detection",
    ),
    blacklist_patterns=(
        "manual_denylist_f5_paloalto.csv",
        "es_automatic_detection.csv",
    ),
    whitelist_patterns=("*.csv",),
    sync_allowlist=False,
    export_csv_lookup=False,
)


def validate_input(definition: smi.ValidationDefinition) -> None:
    return


def stream_events(inputs: smi.InputDefinition, event_writer: smi.EventWriter) -> None:
    execute_modular_input(inputs, event_writer, PALOALTO_TARGET_PROFILE)