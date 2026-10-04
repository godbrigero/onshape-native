"""Progressive native schema discovery with separate observation/replay evidence."""
import json
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parents[1] / "docs/evidence/workflow.json"
TYPES = Path(__file__).resolve().parents[1] / "data/native-commands.json"
READS = {
    "ui.GBTUiGetFeatureSettingsCall", "ui.GBTUiMeasureCall",
    "ui.sketch.GBTUiSketchGetConstraintGraphCall", "ui.sketch.GBTUiSketchGetProjectionCall",
    "ui.GBTUiMassPropCall", "ui.GBTUiGetQueryDataCall", "ui.document.GBTUiQueryInsertables",
    "ui.assembly.GBTUiAssemblyTreeItemDefinitionRequest",
}

VERIFIED = {"ui.assembly.GBTUiAssemblyInsertOccurrence", "ui.assembly.GBTUiAssemblyTreeItemDefinitionRequest", "ui.GBTUiBatchPartPropertyChange", "ui.GBTUiMassPropCall", "ui.assembly.GBTUiChangeOccurrenceFixedStatus",
            "ui.GBTUiUpdateEditRollbackState", "ui.GBTUiBeginEdit", "ui.GBTUiSpecifyFeature", "ui.GBTUiCommit",
            "ui.document.GBTUiEditElementGroups", "partstudiofolders.GBTUiCreateFolder",
            "partstudiofolders.GBTUiDeleteFolder", "ui.GBTUiRenameFeature", "ui.GBTUiReorderFeatures"}


def records():
    return json.loads(EVIDENCE.read_text())["records"]


def catalog(search=""):
    commands = {item["command"]: {"command": item["command"], "class_id": item["class_id"],
                                "read_only": item["command"] in READS, "evidence": "client-schema",
                                "replay_verified": item["command"] in VERIFIED, "defaults": item["defaults"]}
                for item in json.loads(TYPES.read_text())}
    for record in records():
        command = record["command"]
        name = command["$type"]
        item = commands.setdefault(name, {"command": name, "read_only": name in READS, "replay_verified": False})
        if "example" not in item:
            item.update({"evidence": "observed", "example": command, "sequence": record["sequence"]})
    return [value for key, value in commands.items() if search.lower() in key.lower()]


def is_allowed(name):
    return any(item["command"] == name for item in catalog())
