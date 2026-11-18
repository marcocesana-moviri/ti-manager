from __future__ import annotations

from splunklib import modularinput as smi

from ti_sync_core import (
    COLLECTION_ALLOWLIST,
    COLLECTION_MANUAL_ALLOWLIST,
    COLLECTION_MANUAL_DENYLIST,
    TargetProfile,
    execute_modular_input,
)

F5_TARGET_PROFILE = TargetProfile(
    target_name="f5",
    state_filename="state_f5.json",
    denylist_collection="denylist_f5",
    allowlist_collection=COLLECTION_ALLOWLIST,
    manual_collections_to_fetch=(
        COLLECTION_MANUAL_DENYLIST,
        COLLECTION_MANUAL_ALLOWLIST,
    ),
    blacklist_patterns=("*.csv",),
    whitelist_patterns=("*.csv",),
    sync_allowlist=True,
    export_csv_lookup=True,
)


def validate_input(definition: smi.ValidationDefinition) -> None:
    return


def stream_events(inputs: smi.InputDefinition, event_writer: smi.EventWriter) -> None:
    execute_modular_input(inputs, event_writer, F5_TARGET_PROFILE)