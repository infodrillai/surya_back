"""
CLS Surya ERP - Batch Process Entry Naming Utility

Handles automatic naming for PU Batches and Belt Batches with separate sequential
counters per batch type, stage, and calendar year (2 digits: YY).

Formats:
  PU Batches:
    Stage 1: S1-PU-INSERTING-YY-00001
    Stage 2: S2-PU-CASTING-YY-00001
    Stage 3: S3-PU-CNC-YY-00001

  Belt Batches:
    Stage 1: S1-BELT-ROLLING-YY-00001
    Stage 2: S2-BELT-SIZING-YY-00001
    Stage 3: S3-BELT-FINISHED-YY-00001
    Stage 4: S4-BELT-CNC-YY-00001

All series use Frappe's database-level row locking via `tabSeries` (FOR UPDATE),
ensuring transaction safety and preventing duplicate numbering during concurrent saves.
"""
import frappe
from frappe.model.naming import make_autoname
from frappe.utils import cint

PU_BATCH_SERIES = {
    1: "S1-PU-INSERTING-.YY.-.#####",
    2: "S2-PU-CASTING-.YY.-.#####",
    3: "S3-PU-CNC-.YY.-.#####",
}

BELT_BATCH_SERIES = {
    1: "S1-BELT-ROLLING-.YY.-.#####",
    2: "S2-BELT-SIZING-.YY.-.#####",
    3: "S3-BELT-FINISHED-.YY.-.#####",
    4: "S4-BELT-CNC-.YY.-.#####",
}


def get_pu_batch_series(stage):
    """Return naming series pattern for a given PU stage (1, 2, 3)."""
    return PU_BATCH_SERIES.get(cint(stage), "S1-PU-INSERTING-.YY.-.#####")


def get_belt_batch_series(stage):
    """Return naming series pattern for a given Belt stage (1, 2, 3, 4)."""
    return BELT_BATCH_SERIES.get(cint(stage), "S1-BELT-ROLLING-.YY.-.#####")


def get_process_entry_id(batch_type, stage):
    """
    Generate next process entry ID using Frappe's database-locked transaction-safe
    make_autoname mechanism on tabSeries.
    """
    batch_type_str = (batch_type or "").upper()
    if "BELT" in batch_type_str:
        series = get_belt_batch_series(stage)
    else:
        series = get_pu_batch_series(stage)
    return make_autoname(series)


def pu_batch_autoname(doc, method=None):
    """
    Autoname hook for Stage 1 Batch, Stage 2 Batch, Stage 3 Batch.
    Does not overwrite existing document IDs.
    """
    if doc.name:
        return

    stage = cint(getattr(doc, "STAGE", None) or doc.get("stage"))
    if not stage:
        doctype = doc.doctype or ""
        if "1" in doctype:
            stage = 1
        elif "2" in doctype:
            stage = 2
        elif "3" in doctype:
            stage = 3
        else:
            stage = 1

    pattern = get_pu_batch_series(stage)
    doc.name = make_autoname(pattern, doc=doc)


def belt_batch_autoname(doc, method=None):
    """
    Autoname hook for Belt Batch.
    Does not overwrite existing document IDs.
    """
    if doc.name:
        return

    stage = cint(doc.get("process_step") or doc.get("stage") or 1)
    pattern = get_belt_batch_series(stage)
    doc.name = make_autoname(pattern, doc=doc)
