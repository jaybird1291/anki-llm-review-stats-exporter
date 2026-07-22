from __future__ import annotations

"""
Export your Anki review history (revlog) as JSONL so you can analyze it with an LLM (ChatGPT, Claude, local models, etc.) **without** using any API.
- One JSON object per review (not per card)  
- Optional filters: time range, tags, minimum interval 
- Flexible schema: verbose or compact (short keys, smaller size)  
- Designed for decks you want to deeply analyze (e.g. language learning, kanji, med school, etc.)
"""

import json
import os
import time
import csv
from dataclasses import dataclass
from typing import Any, List, Optional
import re
import html

from aqt import mw
from aqt.qt import (
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
    QMessageBox,
    QPushButton,
    QDesktopServices,
    QUrl,
    QGuiApplication,
    Qt,
)
from aqt.utils import qconnect, tooltip
from aqt.operations import QueryOp
from anki.utils import ids2str
from anki.collection import Collection

# --------------------------------------------------------------------
# Data classes
# --------------------------------------------------------------------


@dataclass
class TimeRangeOption:
    """Predefined time range option for the export dialog."""

    label: str
    days: Optional[int]  # None == no time limit


@dataclass
class ExportResult:
    """Summary information returned by the export function."""

    count: int
    first_ts_ms: Optional[int]
    last_ts_ms: Optional[int]
    deck_label: str
    output_format_label: str
    output_path: str
    csv_pack_dir: Optional[str] = None
    csv_pack_files: Optional[List[str]] = None


@dataclass
class ReviewRecord:
    """One filtered review row with cleaned note fields."""

    ts_ms: int
    ts_iso: str
    review_date: str
    review_hour: int
    card_id: int
    note_id: int
    deck_id: int
    deck_name: str
    ease: int
    interval: int
    last_interval: int
    factor: int
    review_time_ms: int
    review_type: int
    fields: List[str]


@dataclass
class LoadedReviewData:
    """Filtered review data plus deck labels for summaries."""

    records: List[ReviewRecord]
    deck_label: str
    selected_deck_names: List[str]
    included_deck_names: List[str]


# --------------------------------------------------------------------
# Time range options
# --------------------------------------------------------------------


TIME_RANGE_OPTIONS: List[TimeRangeOption] = [
    TimeRangeOption("Last day (24h)", 1),
    TimeRangeOption("Last week (7 days)", 7),
    TimeRangeOption("Last month (30 days)", 30),
    TimeRangeOption("Last 3 months (90 days)", 90),
    TimeRangeOption("Last year (365 days)", 365),
    TimeRangeOption("All history", None),
]

OUTPUT_FORMAT_CSV = "csv"
OUTPUT_FORMAT_JSONL_VERBOSE = "jsonl_verbose"
OUTPUT_FORMAT_JSONL_COMPACT = "jsonl_compact"

OUTPUT_FORMAT_OPTIONS = [
    ("CSV (recommended for ChatGPT)", OUTPUT_FORMAT_CSV),
    ("JSONL verbose", OUTPUT_FORMAT_JSONL_VERBOSE),
    ("JSONL compact", OUTPUT_FORMAT_JSONL_COMPACT),
]

OUTPUT_FORMAT_LABELS = {
    value: label for label, value in OUTPUT_FORMAT_OPTIONS
}

LEECH_MIN_REVIEWS = 8
LEECH_MIN_AGAINS = 3
LEECH_MIN_AGAIN_RATE = 0.25
LEECH_MAX_LATEST_INTERVAL = 21
CSV_ENCODING = "utf-8-sig"


def _path_with_extension(path: str, extension: str) -> str:
    """Apply an expected extension when the path has no/known export extension."""
    if not path:
        return path

    root, ext = os.path.splitext(path)
    if ext.lower() == extension:
        return path
    if ext.lower() in ("", ".csv", ".jsonl"):
        return root + extension
    return path


def _extension_for_format(output_format: str) -> str:
    """Return the default file extension for an output format."""
    if output_format == OUTPUT_FORMAT_CSV:
        return ".csv"
    return ".jsonl"

# --------------------------------------------------------------------
# Main dialog
# --------------------------------------------------------------------


class LLMStatsDialog(QDialog):
    """Configuration dialog for the LLM stats export."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export LLM Stats (revlog)")
        self.resize(560, 520)

        # Deck selection
        self.deck_list = QListWidget(self)
        self.deck_list.setMinimumHeight(150)
        self.deck_list.setToolTip(
            "Choose one or more decks. Subdecks are included automatically."
        )
        self._populate_decks()
        self.select_all_decks_button = QPushButton("Select all", self)
        self.clear_decks_button = QPushButton("Clear", self)
        self.select_all_decks_button.clicked.connect(
            lambda _checked=False: self._set_all_deck_checks(Qt.CheckState.Checked)
        )
        self.clear_decks_button.clicked.connect(
            lambda _checked=False: self._set_all_deck_checks(Qt.CheckState.Unchecked)
        )

        # Output format selection
        self.output_format_combo = QComboBox(self)
        for label, value in OUTPUT_FORMAT_OPTIONS:
            self.output_format_combo.addItem(label, value)

        # Predefined time range selection
        self.range_combo = QComboBox(self)
        for opt in TIME_RANGE_OPTIONS:
            self.range_combo.addItem(opt.label, opt.days)

        # Custom number of days (optional)
        self.custom_days_spin = QSpinBox(self)
        # 0 = disabled → use the predefined time range instead
        self.custom_days_spin.setRange(0, 3650)
        self.custom_days_spin.setValue(0)
        self.custom_days_spin.setToolTip(
            "Advanced: custom number of days. "
            "Leave 0 to use the selected predefined range above."
        )
        custom_lbl = QLabel("Custom days (optional)")

        # Output path
        self.path_edit = QLineEdit(self)
        self.path_edit.setPlaceholderText("Output file path (.csv or .jsonl)")
        self.browse_button = QLabel('<a href="#">Browse...</a>', self)
        self.browse_button.setOpenExternalLinks(False)
        self.browse_button.linkActivated.connect(self._browse)
        self.output_format_combo.currentIndexChanged.connect(
            self._on_output_format_changed
        )

        # Field indices to export (optional)
        self.field_indexes_edit = QLineEdit(self)
        self.field_indexes_edit.setPlaceholderText("e.g. 0,1,2 (leave empty = all)")
        self.field_indexes_edit.setToolTip(
            "Indexes of note fields to export (0 = first field). "
            "Leave empty to export all fields."
        )

        # Filters: tags
        self.tags_edit = QLineEdit(self)
        self.tags_edit.setPlaceholderText("e.g. tag1,tag2 (leave empty = no filter)")
        self.tags_edit.setToolTip(
            "Comma-separated tag names. "
            "Only reviews whose note has at least one of these tags will be exported."
        )

        # Filters: minimum interval (days)
        self.min_interval_spin = QSpinBox(self)
        self.min_interval_spin.setRange(0, 365000)
        self.min_interval_spin.setValue(0)
        self.min_interval_spin.setToolTip(
            "Minimum interval (in days) for the review's new interval (r.ivl). "
            "Leave 0 to disable this filter."
        )

        # Export schema options
        self.include_ids_checkbox = QCheckBox("Include card/note/deck IDs")
        self.include_ids_checkbox.setChecked(False)
        self.include_ids_checkbox.setToolTip(
            "If checked, include card_id, note_id and deck_id in the output."
        )

        self.include_deck_name_checkbox = QCheckBox("Include deck name in JSONL")
        self.include_deck_name_checkbox.setChecked(False)
        self.include_deck_name_checkbox.setToolTip(
            "If checked, include deck_name for each JSONL verbose review. "
            "CSV exports always include deck_name."
        )

        self.include_ts_ms_checkbox = QCheckBox("Include raw timestamp (ts_ms)")
        self.include_ts_ms_checkbox.setChecked(False)
        self.include_ts_ms_checkbox.setToolTip(
            "If checked, include the raw millisecond timestamp (ts_ms) in addition to ts_iso."
        )

        self.csv_pack_checkbox = QCheckBox(
            "Create CSV pack with summaries + schema.md"
        )
        self.csv_pack_checkbox.setChecked(False)
        self.csv_pack_checkbox.setToolTip(
            "If checked in CSV mode, create a folder with reviews.csv, "
            "summary CSV files, and a schema.md guide."
        )

        # Form layout
        form = QFormLayout()
        deck_layout = QVBoxLayout()
        deck_layout.addWidget(self.deck_list)

        deck_buttons_layout = QHBoxLayout()
        deck_buttons_layout.addWidget(self.select_all_decks_button)
        deck_buttons_layout.addWidget(self.clear_decks_button)
        deck_buttons_layout.addStretch()
        deck_layout.addLayout(deck_buttons_layout)

        form.addRow("Decks:", deck_layout)
        form.addRow("Output format:", self.output_format_combo)
        form.addRow("Time range:", self.range_combo)

        custom_layout = QHBoxLayout()
        custom_layout.addWidget(custom_lbl)
        custom_layout.addWidget(self.custom_days_spin)
        form.addRow(custom_layout)

        form.addRow("Fields to export:", self.field_indexes_edit)
        form.addRow("Filter by tags:", self.tags_edit)
        form.addRow("Minimum interval (days):", self.min_interval_spin)

        # Export schema options row
        schema_layout = QVBoxLayout()
        schema_layout.addWidget(self.include_ids_checkbox)
        schema_layout.addWidget(self.include_deck_name_checkbox)
        schema_layout.addWidget(self.include_ts_ms_checkbox)
        form.addRow("Export schema:", schema_layout)
        form.addRow("CSV pack:", self.csv_pack_checkbox)

        path_layout = QHBoxLayout()
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.browse_button)
        form.addRow("File:", path_layout)

        # OK / Cancel buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

        # Default output path in the user's profile folder
        default_path = os.path.join(
            mw.pm.profileFolder(),
            "llm_review_stats.csv",
        )
        self.path_edit.setText(default_path)
        self._update_format_dependent_controls()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _populate_decks(self) -> None:
        """Populate the deck list using mw.col.decks.all_names_and_ids()."""
        self.deck_list.clear()
        current_deck_id = self._current_deck_id()
        decks = list(
            mw.col.decks.all_names_and_ids()
        )  # returns (name, id) on recent Anki versions
        decks.sort(key=lambda d: d.name.lower())
        for d in decks:
            item = QListWidgetItem(d.name)
            item.setData(Qt.ItemDataRole.UserRole, int(d.id))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if current_deck_id is not None and int(d.id) == current_deck_id
                else Qt.CheckState.Unchecked
            )
            self.deck_list.addItem(item)

        if self.deck_list.count() and not self.selected_deck_ids():
            self.deck_list.item(0).setCheckState(Qt.CheckState.Checked)

    def _current_deck_id(self) -> Optional[int]:
        """Return Anki's current deck id when available."""
        try:
            deck = mw.col.decks.current()
            if isinstance(deck, dict):
                deck_id = deck.get("id")
            else:
                deck_id = getattr(deck, "id", None)
            return int(deck_id) if deck_id is not None else None
        except Exception:
            return None

    def _set_all_deck_checks(self, state) -> None:
        """Set every deck checkbox to the given state."""
        for row in range(self.deck_list.count()):
            self.deck_list.item(row).setCheckState(state)

    def _on_output_format_changed(self, *_args) -> None:
        """Update file extension and CSV-only controls when format changes."""
        extension = _extension_for_format(self.output_format())
        self.path_edit.setText(_path_with_extension(self.path_edit.text(), extension))
        self._update_format_dependent_controls()

    def _update_format_dependent_controls(self) -> None:
        """Enable controls only when they apply to the selected format."""
        output_format = self.output_format()
        is_csv = output_format == OUTPUT_FORMAT_CSV
        is_jsonl_verbose = output_format == OUTPUT_FORMAT_JSONL_VERBOSE

        self.csv_pack_checkbox.setEnabled(is_csv)
        if not is_csv:
            self.csv_pack_checkbox.setChecked(False)

        self.include_deck_name_checkbox.setEnabled(is_jsonl_verbose)

    def _browse(self) -> None:
        """Open a file dialog to choose the export path."""
        output_format = self.output_format()
        if output_format == OUTPUT_FORMAT_CSV:
            filters = "CSV (*.csv);;All files (*.*)"
        else:
            filters = "JSON Lines (*.jsonl);;All files (*.*)"

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Choose output file",
            self.path_edit.text(),
            filters,
        )
        if path:
            extension = _extension_for_format(output_format)
            self.path_edit.setText(_path_with_extension(path, extension))

    # ------------------------------------------------------------------
    # Public helpers to read dialog state
    # ------------------------------------------------------------------

    def selected_deck_ids(self) -> list[int]:
        """Return the checked deck ids."""
        deck_ids: list[int] = []
        for row in range(self.deck_list.count()):
            item = self.deck_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                deck_ids.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return deck_ids

    def selected_days(self) -> Optional[int]:
        """
        Return the number of days to export.

        If a custom number of days is specified (> 0), it takes precedence.
        Otherwise, the value from the predefined range is used (may be None).
        """
        custom_days = self.custom_days_spin.value()
        if custom_days and custom_days > 0:
            return custom_days
        return self.range_combo.currentData()

    def selected_field_indexes(self) -> Optional[list[int]]:
        """
        Return a list of 0-based field indices to export, or None if the user
        left the field empty (meaning: export all fields).
        """
        text = self.field_indexes_edit.text().strip()
        if not text:
            return None

        idxs: list[int] = []
        seen: set[int] = set()
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                i = int(part)
                if i >= 0 and i not in seen:
                    idxs.append(i)
                    seen.add(i)
            except ValueError:
                # Silently ignore invalid values
                continue

        return idxs or None

    def selected_tags(self) -> Optional[list[str]]:
        """
        Return a list of tag names for filtering, or None if no tags were given.

        Only reviews whose note has at least one of these tags will be exported.
        """
        text = self.tags_edit.text().strip()
        if not text:
            return None

        # Accept "tag1,tag2" or "tag1, tag2"
        tags: list[str] = []
        for part in text.replace(",", " ").split():
            t = part.strip().lower()
            if t:
                tags.append(t)

        return tags or None

    def min_interval(self) -> Optional[int]:
        """
        Return the minimum interval (in days) for the review's new interval (r.ivl),
        or None if no minimum is set.
        """
        value = self.min_interval_spin.value()
        if value > 0:
            return value
        return None

    def include_ids(self) -> bool:
        """Whether to include card/note/deck IDs in the export."""
        return self.include_ids_checkbox.isChecked()

    def include_deck_name(self) -> bool:
        """Whether to include deck_name in the export."""
        return self.include_deck_name_checkbox.isChecked()

    def include_ts_ms(self) -> bool:
        """Whether to include the raw timestamp (ts_ms) in the export."""
        return self.include_ts_ms_checkbox.isChecked()

    def output_format(self) -> str:
        """Return the selected output format."""
        return str(self.output_format_combo.currentData())

    def create_csv_pack(self) -> bool:
        """Whether to create the optional CSV pack."""
        return self.csv_pack_checkbox.isChecked()

    def output_path(self) -> str:
        """Return the output file path."""
        return self.path_edit.text().strip()


# --------------------------------------------------------------------
# Deck utilities
# --------------------------------------------------------------------


def _deck_and_child_ids(col: Collection, deck_id: int) -> List[int]:
    """
    Return the deck id and all child deck ids, in a way that works across
    multiple Anki versions.
    """
    decks: List[int] = [deck_id]

    # Newer Anki: DeckManager.deck_and_child_ids()
    try:
        manager = col.decks
        if hasattr(manager, "deck_and_child_ids"):
            return list(manager.deck_and_child_ids(deck_id))
    except Exception:
        # Fallback to older behavior below
        pass

    # Fallback: recursively descend via decks.children()
    def collect(did: int, acc: List[int]) -> None:
        for name, child_id in col.decks.children(did):
            acc.append(child_id)
            collect(child_id, acc)

    collect(deck_id, decks)
    return decks


def _deck_and_child_ids_for_roots(
    col: Collection, deck_ids: List[int]
) -> List[int]:
    """Return the de-duplicated union of each deck id and its child deck ids."""
    dids: List[int] = []
    seen: set[int] = set()

    for deck_id in deck_ids:
        for did in _deck_and_child_ids(col, deck_id):
            did = int(did)
            if did in seen:
                continue
            seen.add(did)
            dids.append(did)

    return dids


# --------------------------------------------------------------------
# Field cleaning utilities
# --------------------------------------------------------------------

_SOUND_RE = re.compile(r"\[sound:[^\]]+\]", re.IGNORECASE)
_IMG_TAG_RE = re.compile(r"<img[^>]*>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_field_value(text: str) -> str:
    """
    Clean an Anki field value:

    - remove [sound:xxx.mp3] references
    - remove <img ...> tags
    - unescape HTML entities (&nbsp; → space, etc.)
    - remove remaining HTML tags
    - normalize whitespace
    """
    if not text:
        return ""

    # Remove [sound:...]
    text = _SOUND_RE.sub("", text)

    # Remove <img ...>
    text = _IMG_TAG_RE.sub("", text)

    # Unescape HTML entities (&nbsp; → space, etc.)
    text = html.unescape(text)

    # Remove remaining HTML tags (<b>, <span>, etc.)
    text = _HTML_TAG_RE.sub("", text)

    # Collapse whitespace
    text = _WS_RE.sub(" ", text).strip()

    return text


# --------------------------------------------------------------------
# Export logic (revlog to CSV/JSONL)
# --------------------------------------------------------------------


def _export_llm_stats_jsonl_legacy(
    col: Collection,
    deck_ids: List[int],
    days: Optional[int],
    out_path: str,
    field_indexes: Optional[list[int]] = None,
    tags_filter: Optional[list[str]] = None,
    min_interval: Optional[int] = None,
    include_ids: bool = False,
    include_deck_name: bool = False,
    include_ts_ms: bool = False,
    compact_schema: bool = False,
) -> ExportResult:
    """
    Heavy function executed in a background thread via QueryOp.

    Returns an ExportResult with summary information.
    """
    if not deck_ids:
        raise ValueError("Select at least one deck.")

    dids = _deck_and_child_ids_for_roots(col, deck_ids)
    dids_str = ids2str(dids)

    where_clauses = [f"c.did IN {dids_str}"]
    params: list = []

    # Time filter on revlog.id (timestamp in ms since epoch)
    if days is not None:
        now_sec = time.time()
        cutoff_ms = int((now_sec - days * 86400) * 1000)
        where_clauses.append("r.id >= ?")
        params.append(cutoff_ms)

    # Tag filter (note tags)
    # Anki stores tags in n.tags as " tag1 tag2 ", all lowercased.
    if tags_filter:
        tag_clauses: list[str] = []
        for tag in tags_filter:
            tag_clauses.append("n.tags LIKE ?")
            params.append(f"% {tag} %")
        if tag_clauses:
            where_clauses.append("(" + " OR ".join(tag_clauses) + ")")

    # Minimum interval filter (on the new interval r.ivl)
    if min_interval is not None:
        where_clauses.append("r.ivl >= ?")
        params.append(min_interval)

    where_sql = " AND ".join(where_clauses)

    # Join revlog + cards + notes to get deck and fields in one query,
    # which minimizes Python/SQLite round-trips (important for large revlogs).
    # n.flds is a string with fields separated by \x1f.
    sql = f"""
SELECT
    r.id,           -- timestamp (ms)
    r.cid,          -- card id
    c.nid,          -- note id
    c.did,          -- deck id
    r.ease,         -- chosen button (1-4)
    r.ivl,          -- new interval (days)
    r.lastIvl,      -- previous interval (days)
    r.factor,       -- ease factor
    r.time,         -- response time (ms)
    r.type,         -- review type (0=learn,1=review,2=relearn,3=filtered)
    n.flds,         -- concatenated note fields
    n.tags          -- note tags (for info, even if we don't export them yet)
FROM revlog r
JOIN cards c ON c.id = r.cid
JOIN notes n ON n.id = c.nid
WHERE {where_sql}
ORDER BY r.id
"""

    # Preload deck names to avoid lookups in the main loop
    deck_names = {d.id: d.name for d in col.decks.all_names_and_ids()}
    selected_deck_names = [deck_names.get(deck_id, "<unknown>") for deck_id in deck_ids]
    if len(selected_deck_names) == 1:
        deck_label = selected_deck_names[0]
    elif len(selected_deck_names) <= 3:
        deck_label = ", ".join(selected_deck_names)
    else:
        deck_label = f"{len(selected_deck_names)} selected decks"

    # Stream writing to JSONL file (one review per line)
    folder = os.path.dirname(out_path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    count = 0
    first_ts_ms: Optional[int] = None
    last_ts_ms: Optional[int] = None

    with open(out_path, "w", encoding="utf-8") as fh:
        for row in col.db.execute(sql, *params):
            (
                ts_ms,
                cid,
                nid,
                did,
                ease,
                ivl,
                last_ivl,
                factor,
                review_time_ms,
                rev_type,
                flds,
                _note_tags,  # currently unused, but fetched for completeness
            ) = row

            # Track actual date range covered (based on exported reviews)
            if first_ts_ms is None:
                first_ts_ms = ts_ms
            last_ts_ms = ts_ms

            raw_fields = flds.split("\x1f") if flds else []

            # Select which fields to export (by index)
            if field_indexes is not None:
                selected: list[str] = []
                for idx in field_indexes:
                    if 0 <= idx < len(raw_fields):
                        selected.append(clean_field_value(raw_fields[idx]))
                fields = selected
            else:
                # All fields, cleaned
                fields = [clean_field_value(v) for v in raw_fields]

            # Build JSON object (two modes: full vs compact)
            ts_iso = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_ms / 1000.0)
            )

            if compact_schema:
                # Compact schema: short keys, no IDs/deck_name/ts_ms
                # You should explain this schema in your LLM prompt.
                obj: dict = {
                    "t": ts_iso,          # timestamp ISO
                    "rt": rev_type,       # review type (0,1,2,3)
                    "e": ease,            # ease (1–4)
                    "i": ivl,             # new interval (days)
                    "li": last_ivl,       # previous interval (days)
                    "f": factor,          # ease factor
                    "ms": review_time_ms, # answer time in ms
                    "flds": fields,       # list of cleaned fields
                }
            else:
                # Verbose schema (original)
                obj: dict = {
                    "ts_iso": ts_iso,
                    "ease": ease,
                    "interval": ivl,
                    "last_interval": last_ivl,
                    "factor": factor,
                    "review_time_ms": review_time_ms,
                    "review_type": rev_type,
                    "fields": fields,
                }

                # Optional schema elements
                if include_ts_ms:
                    obj["ts_ms"] = ts_ms

                if include_ids:
                    obj["card_id"] = cid
                    obj["note_id"] = nid
                    obj["deck_id"] = did

                if include_deck_name:
                    obj["deck_name"] = deck_names.get(did, "<unknown>")

            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
            count += 1

    return ExportResult(
        count=count,
        first_ts_ms=first_ts_ms,
        last_ts_ms=last_ts_ms,
        deck_label=deck_label,
        output_format_label="JSONL compact" if compact_schema else "JSONL verbose",
        output_path=out_path,
    )


def _deck_label(deck_names: List[str]) -> str:
    """Return a compact label for the selected decks."""
    if len(deck_names) == 1:
        return deck_names[0]
    if len(deck_names) <= 3:
        return ", ".join(deck_names)
    return f"{len(deck_names)} selected decks"


def _local_date(ts_ms: int) -> str:
    """Return the local calendar date for a revlog timestamp."""
    return time.strftime("%Y-%m-%d", time.localtime(ts_ms / 1000.0))


def _load_review_data(
    col: Collection,
    deck_ids: List[int],
    days: Optional[int],
    field_indexes: Optional[list[int]] = None,
    tags_filter: Optional[list[str]] = None,
    min_interval: Optional[int] = None,
) -> LoadedReviewData:
    """Load filtered review rows once so all exporters share the same data."""
    if not deck_ids:
        raise ValueError("Select at least one deck.")

    dids = _deck_and_child_ids_for_roots(col, deck_ids)
    dids_str = ids2str(dids)

    where_clauses = [f"c.did IN {dids_str}"]
    params: list[Any] = []

    if days is not None:
        now_sec = time.time()
        cutoff_ms = int((now_sec - days * 86400) * 1000)
        where_clauses.append("r.id >= ?")
        params.append(cutoff_ms)

    if tags_filter:
        tag_clauses: list[str] = []
        for tag in tags_filter:
            tag_clauses.append("n.tags LIKE ?")
            params.append(f"% {tag} %")
        if tag_clauses:
            where_clauses.append("(" + " OR ".join(tag_clauses) + ")")

    if min_interval is not None:
        where_clauses.append("r.ivl >= ?")
        params.append(min_interval)

    where_sql = " AND ".join(where_clauses)
    sql = f"""
SELECT
    r.id,
    r.cid,
    c.nid,
    c.did,
    r.ease,
    r.ivl,
    r.lastIvl,
    r.factor,
    r.time,
    r.type,
    n.flds,
    n.tags
FROM revlog r
JOIN cards c ON c.id = r.cid
JOIN notes n ON n.id = c.nid
WHERE {where_sql}
ORDER BY r.id
"""

    deck_names = {int(d.id): d.name for d in col.decks.all_names_and_ids()}
    selected_deck_names = [
        deck_names.get(int(deck_id), "<unknown>") for deck_id in deck_ids
    ]
    included_deck_names = [deck_names.get(int(did), "<unknown>") for did in dids]

    records: List[ReviewRecord] = []
    for row in col.db.execute(sql, *params):
        (
            ts_ms,
            cid,
            nid,
            did,
            ease,
            ivl,
            last_ivl,
            factor,
            review_time_ms,
            rev_type,
            flds,
            _note_tags,
        ) = row

        raw_fields = flds.split("\x1f") if flds else []
        clean_fields = [clean_field_value(v) for v in raw_fields]
        local_time = time.localtime(ts_ms / 1000.0)

        records.append(
            ReviewRecord(
                ts_ms=ts_ms,
                ts_iso=time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_ms / 1000.0)
                ),
                review_date=time.strftime("%Y-%m-%d", local_time),
                review_hour=int(local_time.tm_hour),
                card_id=cid,
                note_id=nid,
                deck_id=did,
                deck_name=deck_names.get(int(did), "<unknown>"),
                ease=ease,
                interval=ivl,
                last_interval=last_ivl,
                factor=factor,
                review_time_ms=review_time_ms,
                review_type=rev_type,
                fields=clean_fields,
            )
        )

    return LoadedReviewData(
        records=records,
        deck_label=_deck_label(selected_deck_names),
        selected_deck_names=selected_deck_names,
        included_deck_names=included_deck_names,
    )


def _ensure_parent_folder(path: str) -> None:
    """Create a file's parent folder if one was specified."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)


def _json_fields(record: ReviewRecord, field_indexes: Optional[list[int]]) -> List[str]:
    """Return fields in the existing JSONL list shape."""
    if field_indexes is None:
        return list(record.fields)
    return [record.fields[idx] for idx in field_indexes if idx < len(record.fields)]


def _csv_field_indexes(
    records: List[ReviewRecord], field_indexes: Optional[list[int]]
) -> List[int]:
    """Return the stable field indexes that should become CSV columns."""
    if field_indexes is not None:
        return list(field_indexes)
    max_fields = max((len(record.fields) for record in records), default=0)
    return list(range(max_fields))


def _review_csv_headers(
    field_columns: List[int], include_ids: bool, include_ts_ms: bool
) -> List[str]:
    """Return stable headers for review-level CSV output."""
    headers = ["ts_iso"]
    if include_ts_ms:
        headers.append("ts_ms")
    headers.extend(["review_date", "review_hour", "deck_name"])
    if include_ids:
        headers.extend(["card_id", "note_id", "deck_id"])
    headers.extend(
        [
            "ease",
            "interval",
            "last_interval",
            "factor",
            "review_time_ms",
            "review_type",
        ]
    )
    headers.extend([f"field_{idx}" for idx in field_columns])
    return headers


def _review_csv_row(
    record: ReviewRecord,
    field_columns: List[int],
    include_ids: bool,
    include_ts_ms: bool,
) -> dict:
    """Convert one review record into a CSV row dict."""
    row: dict = {
        "ts_iso": record.ts_iso,
        "review_date": record.review_date,
        "review_hour": record.review_hour,
        "deck_name": record.deck_name,
        "ease": record.ease,
        "interval": record.interval,
        "last_interval": record.last_interval,
        "factor": record.factor,
        "review_time_ms": record.review_time_ms,
        "review_type": record.review_type,
    }
    if include_ts_ms:
        row["ts_ms"] = record.ts_ms
    if include_ids:
        row["card_id"] = record.card_id
        row["note_id"] = record.note_id
        row["deck_id"] = record.deck_id
    for idx in field_columns:
        row[f"field_{idx}"] = record.fields[idx] if idx < len(record.fields) else ""
    return row


def _write_reviews_csv(
    path: str,
    records: List[ReviewRecord],
    field_indexes: Optional[list[int]],
    include_ids: bool,
    include_ts_ms: bool,
) -> List[str]:
    """Write review-level CSV and return its headers."""
    _ensure_parent_folder(path)
    field_columns = _csv_field_indexes(records, field_indexes)
    headers = _review_csv_headers(field_columns, include_ids, include_ts_ms)

    with open(path, "w", encoding=CSV_ENCODING, newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for record in records:
            writer.writerow(
                _review_csv_row(record, field_columns, include_ids, include_ts_ms)
            )
    return headers


def _write_jsonl(
    path: str,
    records: List[ReviewRecord],
    field_indexes: Optional[list[int]],
    include_ids: bool,
    include_deck_name: bool,
    include_ts_ms: bool,
    compact_schema: bool,
) -> None:
    """Write verbose or compact JSONL while preserving the existing schema."""
    _ensure_parent_folder(path)

    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fields = _json_fields(record, field_indexes)

            if compact_schema:
                obj: dict = {
                    "t": record.ts_iso,
                    "rt": record.review_type,
                    "e": record.ease,
                    "i": record.interval,
                    "li": record.last_interval,
                    "f": record.factor,
                    "ms": record.review_time_ms,
                    "flds": fields,
                }
            else:
                obj = {
                    "ts_iso": record.ts_iso,
                    "ease": record.ease,
                    "interval": record.interval,
                    "last_interval": record.last_interval,
                    "factor": record.factor,
                    "review_time_ms": record.review_time_ms,
                    "review_type": record.review_type,
                    "fields": fields,
                }
                if include_ts_ms:
                    obj["ts_ms"] = record.ts_ms
                if include_ids:
                    obj["card_id"] = record.card_id
                    obj["note_id"] = record.note_id
                    obj["deck_id"] = record.deck_id
                if include_deck_name:
                    obj["deck_name"] = record.deck_name

            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _avg(values: List[float]) -> str:
    """Return a compact average string, or empty for no data."""
    if not values:
        return ""
    return f"{sum(values) / len(values):.2f}"


def _median(values: List[float]) -> str:
    """Return a compact median string, or empty for no data."""
    if not values:
        return ""
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return f"{values[mid]:.2f}"
    return f"{(values[mid - 1] + values[mid]) / 2:.2f}"


def _rate(part: int, total: int) -> str:
    """Return a four-decimal rate string."""
    if total <= 0:
        return "0.0000"
    return f"{part / total:.4f}"


def _write_dict_csv(path: str, headers: List[str], rows: List[dict]) -> None:
    """Write a CSV file from dictionaries."""
    _ensure_parent_folder(path)
    with open(path, "w", encoding=CSV_ENCODING, newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_daily_summary_csv(path: str, records: List[ReviewRecord]) -> List[str]:
    """Write one row per local review date."""
    headers = [
        "review_date",
        "review_count",
        "again_count",
        "again_rate",
        "average_review_time_ms",
        "average_interval",
        "median_interval",
    ]
    by_date: dict[str, dict] = {}
    for record in records:
        stats = by_date.setdefault(
            record.review_date,
            {"count": 0, "again": 0, "times": [], "intervals": []},
        )
        stats["count"] += 1
        stats["again"] += 1 if record.ease == 1 else 0
        stats["times"].append(float(record.review_time_ms))
        stats["intervals"].append(float(record.interval))

    rows: List[dict] = []
    for review_date in sorted(by_date):
        stats = by_date[review_date]
        rows.append(
            {
                "review_date": review_date,
                "review_count": stats["count"],
                "again_count": stats["again"],
                "again_rate": _rate(stats["again"], stats["count"]),
                "average_review_time_ms": _avg(stats["times"]),
                "average_interval": _avg(stats["intervals"]),
                "median_interval": _median(stats["intervals"]),
            }
        )

    _write_dict_csv(path, headers, rows)
    return headers


def _write_deck_summary_csv(path: str, records: List[ReviewRecord]) -> List[str]:
    """Write one row per deck found in the exported reviews."""
    headers = [
        "deck_name",
        "review_count",
        "again_count",
        "again_rate",
        "average_review_time_ms",
        "first_review_date",
        "last_review_date",
    ]
    by_deck: dict[str, dict] = {}
    for record in records:
        stats = by_deck.setdefault(
            record.deck_name,
            {"count": 0, "again": 0, "times": [], "first": None, "last": None},
        )
        stats["count"] += 1
        stats["again"] += 1 if record.ease == 1 else 0
        stats["times"].append(float(record.review_time_ms))
        stats["first"] = (
            record.ts_ms
            if stats["first"] is None
            else min(stats["first"], record.ts_ms)
        )
        stats["last"] = (
            record.ts_ms if stats["last"] is None else max(stats["last"], record.ts_ms)
        )

    rows: List[dict] = []
    for deck_name in sorted(by_deck):
        stats = by_deck[deck_name]
        rows.append(
            {
                "deck_name": deck_name,
                "review_count": stats["count"],
                "again_count": stats["again"],
                "again_rate": _rate(stats["again"], stats["count"]),
                "average_review_time_ms": _avg(stats["times"]),
                "first_review_date": _local_date(stats["first"])
                if stats["first"] is not None
                else "",
                "last_review_date": _local_date(stats["last"])
                if stats["last"] is not None
                else "",
            }
        )

    _write_dict_csv(path, headers, rows)
    return headers


def _card_summary_entries(records: List[ReviewRecord]) -> List[dict]:
    """Aggregate review rows at card level."""
    by_card: dict[int, dict] = {}
    for record in records:
        stats = by_card.setdefault(
            record.card_id,
            {
                "card_id": record.card_id,
                "note_id": record.note_id,
                "deck_id": record.deck_id,
                "deck_name": record.deck_name,
                "count": 0,
                "again": 0,
                "times": [],
                "first": record.ts_ms,
                "last": record.ts_ms,
                "latest_interval": record.interval,
                "fields": record.fields,
            },
        )
        stats["count"] += 1
        stats["again"] += 1 if record.ease == 1 else 0
        stats["times"].append(float(record.review_time_ms))
        stats["first"] = min(stats["first"], record.ts_ms)
        if record.ts_ms >= stats["last"]:
            stats["last"] = record.ts_ms
            stats["latest_interval"] = record.interval
            stats["deck_id"] = record.deck_id
            stats["deck_name"] = record.deck_name
            stats["fields"] = record.fields

    return sorted(
        by_card.values(),
        key=lambda stats: (-stats["count"], -stats["again"], stats["deck_name"]),
    )


def _summary_field_values(entry: dict, field_columns: List[int]) -> dict:
    """Return field_N values for a card-level summary entry."""
    fields = entry["fields"]
    return {
        f"field_{idx}": fields[idx] if idx < len(fields) else ""
        for idx in field_columns
    }


def _write_card_summary_csv(
    path: str,
    records: List[ReviewRecord],
    field_indexes: Optional[list[int]],
    include_ids: bool,
) -> List[str]:
    """Write one row per card."""
    field_columns = _csv_field_indexes(records, field_indexes)
    headers: List[str] = []
    if include_ids:
        headers.extend(["card_id", "note_id", "deck_id"])
    headers.extend(
        [
            "deck_name",
            "total_reviews",
            "again_count",
            "again_rate",
            "first_review_date",
            "last_review_date",
            "latest_interval",
            "average_review_time_ms",
        ]
    )
    headers.extend([f"field_{idx}" for idx in field_columns])

    rows: List[dict] = []
    for entry in _card_summary_entries(records):
        row: dict = {
            "deck_name": entry["deck_name"],
            "total_reviews": entry["count"],
            "again_count": entry["again"],
            "again_rate": _rate(entry["again"], entry["count"]),
            "first_review_date": _local_date(entry["first"]),
            "last_review_date": _local_date(entry["last"]),
            "latest_interval": entry["latest_interval"],
            "average_review_time_ms": _avg(entry["times"]),
        }
        if include_ids:
            row["card_id"] = entry["card_id"]
            row["note_id"] = entry["note_id"]
            row["deck_id"] = entry["deck_id"]
        row.update(_summary_field_values(entry, field_columns))
        rows.append(row)

    _write_dict_csv(path, headers, rows)
    return headers


def _leech_score(entry: dict) -> float:
    """Score difficult cards for leech candidate sorting."""
    again_rate = entry["again"] / entry["count"] if entry["count"] else 0
    short_interval_pressure = max(0, LEECH_MAX_LATEST_INTERVAL - entry["latest_interval"])
    return round(
        entry["again"] * 10
        + entry["count"]
        + again_rate * 100
        + short_interval_pressure,
        2,
    )


def _is_leech_candidate(entry: dict) -> bool:
    """Return True if a card meets the documented conservative thresholds."""
    if entry["count"] < LEECH_MIN_REVIEWS:
        return False
    if entry["again"] < LEECH_MIN_AGAINS:
        return False
    if entry["count"] and entry["again"] / entry["count"] < LEECH_MIN_AGAIN_RATE:
        return False
    return entry["latest_interval"] <= LEECH_MAX_LATEST_INTERVAL


def _write_leech_candidates_csv(
    path: str,
    records: List[ReviewRecord],
    field_indexes: Optional[list[int]],
    include_ids: bool,
) -> List[str]:
    """Write likely leech candidates sorted by difficulty."""
    field_columns = _csv_field_indexes(records, field_indexes)
    headers: List[str] = []
    if include_ids:
        headers.extend(["card_id", "note_id", "deck_id"])
    headers.extend(
        [
            "deck_name",
            "total_reviews",
            "again_count",
            "again_rate",
            "latest_interval",
            "first_review_date",
            "last_review_date",
            "average_review_time_ms",
            "difficulty_score",
            "leech_rule",
        ]
    )
    headers.extend([f"field_{idx}" for idx in field_columns])

    entries = [
        entry for entry in _card_summary_entries(records) if _is_leech_candidate(entry)
    ]
    entries.sort(
        key=lambda entry: (
            -_leech_score(entry),
            -entry["again"],
            -entry["count"],
            entry["latest_interval"],
        )
    )

    rule = (
        f"reviews>={LEECH_MIN_REVIEWS}, again_count>={LEECH_MIN_AGAINS}, "
        f"again_rate>={LEECH_MIN_AGAIN_RATE:.2f}, "
        f"latest_interval<={LEECH_MAX_LATEST_INTERVAL}"
    )
    rows: List[dict] = []
    for entry in entries:
        row: dict = {
            "deck_name": entry["deck_name"],
            "total_reviews": entry["count"],
            "again_count": entry["again"],
            "again_rate": _rate(entry["again"], entry["count"]),
            "latest_interval": entry["latest_interval"],
            "first_review_date": _local_date(entry["first"]),
            "last_review_date": _local_date(entry["last"]),
            "average_review_time_ms": _avg(entry["times"]),
            "difficulty_score": _leech_score(entry),
            "leech_rule": rule,
        }
        if include_ids:
            row["card_id"] = entry["card_id"]
            row["note_id"] = entry["note_id"]
            row["deck_id"] = entry["deck_id"]
        row.update(_summary_field_values(entry, field_columns))
        rows.append(row)

    _write_dict_csv(path, headers, rows)
    return headers


def _column_description(column: str) -> str:
    """Return a schema description for a CSV column."""
    descriptions = {
        "ts_iso": "UTC review timestamp in ISO 8601 format.",
        "ts_ms": "Raw review timestamp in milliseconds since Unix epoch.",
        "review_date": "Local calendar date used for daily grouping.",
        "review_hour": "Local hour of day, 0-23.",
        "deck_name": "Anki deck name for the reviewed card.",
        "card_id": "Anki card ID.",
        "note_id": "Anki note ID.",
        "deck_id": "Anki deck ID.",
        "ease": "Answer button: 1=Again, 2=Hard, 3=Good, 4=Easy.",
        "interval": "New interval after the review, in Anki's revlog units/days.",
        "last_interval": "Previous interval before the review.",
        "factor": "Ease factor stored by Anki, e.g. 2500 means 2.5x.",
        "review_time_ms": "Answer time in milliseconds.",
        "review_type": "Review type: 0=learn, 1=review, 2=relearn, 3=filtered.",
        "review_count": "Number of review rows in the group.",
        "total_reviews": "Number of reviews for this card.",
        "again_count": "Number of reviews answered with Again (ease=1).",
        "again_rate": "again_count divided by review_count or total_reviews.",
        "average_review_time_ms": "Mean answer time in milliseconds.",
        "average_interval": "Mean new interval for the group.",
        "median_interval": "Median new interval for the group.",
        "first_review_date": "Local date of the first exported review in the group.",
        "last_review_date": "Local date of the last exported review in the group.",
        "latest_interval": "New interval from the latest exported review for the card.",
        "difficulty_score": "Internal sorting score for leech_candidates.csv.",
        "leech_rule": "Threshold rule used to include the row as a candidate.",
    }
    if column.startswith("field_"):
        return "Cleaned exported note field value."
    return descriptions.get(column, "Generated export column.")


def _format_filter_summary(
    days: Optional[int],
    tags_filter: Optional[list[str]],
    min_interval: Optional[int],
    field_indexes: Optional[list[int]],
) -> List[str]:
    """Describe filters for schema.md."""
    time_range = "All history" if days is None else f"Last {days} days"
    tags = ", ".join(tags_filter) if tags_filter else "None"
    min_ivl = str(min_interval) if min_interval is not None else "None"
    fields = (
        "All note fields"
        if field_indexes is None
        else ", ".join(f"field_{idx}" for idx in field_indexes)
    )
    return [
        f"- Time range: {time_range}",
        f"- Tag filter: {tags}",
        f"- Minimum interval: {min_ivl}",
        f"- Exported fields: {fields}",
    ]


def _append_column_docs(lines: List[str], filename: str, headers: List[str]) -> None:
    """Append file and column documentation to schema.md lines."""
    lines.append(f"## {filename}")
    lines.append("")
    lines.append(f"Columns: {', '.join(headers) if headers else '(none)'}")
    lines.append("")
    for header in headers:
        lines.append(f"- `{header}`: {_column_description(header)}")
    lines.append("")


def _write_schema_md(
    path: str,
    data: LoadedReviewData,
    days: Optional[int],
    tags_filter: Optional[list[str]],
    min_interval: Optional[int],
    field_indexes: Optional[list[int]],
    include_ids: bool,
    include_ts_ms: bool,
    file_headers: dict[str, List[str]],
) -> None:
    """Write the CSV pack guide and ready-to-use ChatGPT prompt."""
    selected_decks = ", ".join(data.selected_deck_names) or "(none)"
    included_decks = ", ".join(sorted(set(data.included_deck_names))) or "(none)"
    found_decks = ", ".join(sorted({r.deck_name for r in data.records})) or "(none)"

    lines: List[str] = [
        "# LLM Review Stats CSV Pack Schema",
        "",
        "This pack was generated from Anki revlog review history.",
        "",
        "## Export Context",
        "",
        f"- Selected decks: {selected_decks}",
        f"- Included decks after subdeck expansion: {included_decks}",
        f"- Decks found in exported rows: {found_decks}",
        "- Subdeck behavior: each checked deck includes all of its subdecks. "
        "Overlapping deck selections are de-duplicated.",
        "- Timestamps: `ts_iso` is UTC. `review_date` and `review_hour` are local "
        "time and are used for date/hour summaries.",
        f"- card/note/deck IDs included: {'yes' if include_ids else 'no'}",
        f"- raw `ts_ms` included: {'yes' if include_ts_ms else 'no'}",
        "",
        "## Filters Used",
        "",
    ]
    lines.extend(_format_filter_summary(days, tags_filter, min_interval, field_indexes))
    lines.extend(
        [
            "",
            "## Files",
            "",
            "- `reviews.csv`: one row per exported review.",
            "- `daily_summary.csv`: one row per local review date.",
            "- `deck_summary.csv`: one row per deck found in the exported rows.",
            "- `card_summary.csv`: one row per Anki card, sorted by review count.",
            "- `leech_candidates.csv`: difficult cards matching conservative thresholds.",
            "- `schema.md`: this guide.",
            "",
            "## Numeric Code Mappings",
            "",
            "- `ease`: 1=Again, 2=Hard, 3=Good, 4=Easy.",
            "- `review_type`: 0=learn, 1=review, 2=relearn, 3=filtered.",
            "",
            "## Leech Candidate Thresholds",
            "",
            f"A card appears in `leech_candidates.csv` only when all are true: "
            f"`total_reviews >= {LEECH_MIN_REVIEWS}`, "
            f"`again_count >= {LEECH_MIN_AGAINS}`, "
            f"`again_rate >= {LEECH_MIN_AGAIN_RATE:.2f}`, and "
            f"`latest_interval <= {LEECH_MAX_LATEST_INTERVAL}`.",
            "",
            "The `difficulty_score` is only for sorting candidates, not an Anki score.",
            "",
        ]
    )

    for filename in [
        "reviews.csv",
        "daily_summary.csv",
        "deck_summary.csv",
        "card_summary.csv",
        "leech_candidates.csv",
    ]:
        _append_column_docs(lines, filename, file_headers.get(filename, []))

    lines.extend(
        [
            "## Ready-To-Use ChatGPT Prompt",
            "",
            "Use Data Analysis / Python. Load the attached CSV files with pandas. "
            "Do not infer statistics from the preview only. First report row counts, "
            "column names, date range, and decks found. Then analyze lapses, leeches, "
            "review load, time-of-day patterns, deck-level patterns, and actionable "
            "study recommendations. Show the code or calculations used for important claims.",
            "",
        ]
    )

    _ensure_parent_folder(path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _csv_pack_dir(out_path: str) -> str:
    """Return the CSV pack folder path next to the selected output path."""
    root, _ext = os.path.splitext(out_path)
    return f"{root}_csv_pack"


def _write_csv_pack(
    out_path: str,
    data: LoadedReviewData,
    field_indexes: Optional[list[int]],
    include_ids: bool,
    include_ts_ms: bool,
    days: Optional[int],
    tags_filter: Optional[list[str]],
    min_interval: Optional[int],
) -> tuple[str, List[str]]:
    """Write reviews.csv, summaries, and schema.md into the pack folder."""
    pack_dir = _csv_pack_dir(out_path)
    os.makedirs(pack_dir, exist_ok=True)

    file_headers: dict[str, List[str]] = {}
    file_headers["reviews.csv"] = _write_reviews_csv(
        os.path.join(pack_dir, "reviews.csv"),
        data.records,
        field_indexes,
        include_ids,
        include_ts_ms,
    )
    file_headers["daily_summary.csv"] = _write_daily_summary_csv(
        os.path.join(pack_dir, "daily_summary.csv"), data.records
    )
    file_headers["deck_summary.csv"] = _write_deck_summary_csv(
        os.path.join(pack_dir, "deck_summary.csv"), data.records
    )
    file_headers["card_summary.csv"] = _write_card_summary_csv(
        os.path.join(pack_dir, "card_summary.csv"),
        data.records,
        field_indexes,
        include_ids,
    )
    file_headers["leech_candidates.csv"] = _write_leech_candidates_csv(
        os.path.join(pack_dir, "leech_candidates.csv"),
        data.records,
        field_indexes,
        include_ids,
    )
    _write_schema_md(
        os.path.join(pack_dir, "schema.md"),
        data,
        days,
        tags_filter,
        min_interval,
        field_indexes,
        include_ids,
        include_ts_ms,
        file_headers,
    )

    return pack_dir, list(file_headers.keys()) + ["schema.md"]


def export_llm_stats(
    col: Collection,
    deck_ids: List[int],
    days: Optional[int],
    out_path: str,
    field_indexes: Optional[list[int]] = None,
    tags_filter: Optional[list[str]] = None,
    min_interval: Optional[int] = None,
    include_ids: bool = False,
    include_deck_name: bool = False,
    include_ts_ms: bool = False,
    output_format: str = OUTPUT_FORMAT_CSV,
    create_csv_pack: bool = False,
) -> ExportResult:
    """
    Heavy function executed in a background thread via QueryOp.

    Returns an ExportResult with summary information.
    """
    if output_format not in OUTPUT_FORMAT_LABELS:
        raise ValueError(f"Unknown output format: {output_format}")

    out_path = _path_with_extension(out_path, _extension_for_format(output_format))
    data = _load_review_data(
        col=col,
        deck_ids=deck_ids,
        days=days,
        field_indexes=field_indexes,
        tags_filter=tags_filter,
        min_interval=min_interval,
    )

    csv_pack_dir: Optional[str] = None
    csv_pack_files: Optional[List[str]] = None
    if output_format == OUTPUT_FORMAT_CSV:
        _write_reviews_csv(
            path=out_path,
            records=data.records,
            field_indexes=field_indexes,
            include_ids=include_ids,
            include_ts_ms=include_ts_ms,
        )
        if create_csv_pack:
            csv_pack_dir, csv_pack_files = _write_csv_pack(
                out_path=out_path,
                data=data,
                field_indexes=field_indexes,
                include_ids=include_ids,
                include_ts_ms=include_ts_ms,
                days=days,
                tags_filter=tags_filter,
                min_interval=min_interval,
            )
    else:
        _write_jsonl(
            path=out_path,
            records=data.records,
            field_indexes=field_indexes,
            include_ids=include_ids,
            include_deck_name=include_deck_name,
            include_ts_ms=include_ts_ms,
            compact_schema=output_format == OUTPUT_FORMAT_JSONL_COMPACT,
        )

    first_ts_ms = data.records[0].ts_ms if data.records else None
    last_ts_ms = data.records[-1].ts_ms if data.records else None

    return ExportResult(
        count=len(data.records),
        first_ts_ms=first_ts_ms,
        last_ts_ms=last_ts_ms,
        deck_label=data.deck_label,
        output_format_label=OUTPUT_FORMAT_LABELS[output_format],
        output_path=out_path,
        csv_pack_dir=csv_pack_dir,
        csv_pack_files=csv_pack_files,
    )

# --------------------------------------------------------------------
# UI glue + background operation
# --------------------------------------------------------------------


def _format_date_range(first_ts_ms: Optional[int], last_ts_ms: Optional[int]) -> str:
    """Format the date range for display in the summary."""
    if first_ts_ms is None or last_ts_ms is None:
        return "N/A"

    # Use local time for display
    start_str = time.strftime(
        "%Y-%m-%d", time.localtime(first_ts_ms / 1000.0)
    )
    end_str = time.strftime(
        "%Y-%m-%d", time.localtime(last_ts_ms / 1000.0)
    )
    if start_str == end_str:
        return start_str
    return f"{start_str} – {end_str}"


def on_export_llm_stats() -> None:
    """Show the configuration dialog and run the export in the background."""
    if mw.col is None:
        return

    dlg = LLMStatsDialog(mw)
    if not dlg.exec():
        return

    deck_ids = dlg.selected_deck_ids()
    days = dlg.selected_days()
    out_path = dlg.output_path()
    field_indexes = dlg.selected_field_indexes()
    tags_filter = dlg.selected_tags()
    min_interval = dlg.min_interval()
    include_ids = dlg.include_ids()
    include_deck_name = dlg.include_deck_name()
    include_ts_ms = dlg.include_ts_ms()
    output_format = dlg.output_format()
    create_csv_pack = dlg.create_csv_pack()
    out_path = _path_with_extension(out_path, _extension_for_format(output_format))

    if not out_path:
        tooltip("Invalid file path.")
        return
    if not deck_ids:
        tooltip("Select at least one deck.")
        return

    def _on_success(result: ExportResult) -> None:
        # Always show a summary dialog, even if 0 reviews were exported.
        date_range = _format_date_range(result.first_ts_ms, result.last_ts_ms)

        extra_info = ""
        if result.count == 0:
            extra_info = (
                "\n\nNo reviews matched the selected filters.\n"
                "Try:\n"
                "- Time range: All history\n"
                "- Clear tag filter\n"
                "- Minimum interval: 0\n"
                "\nFiles were still created with headers"
                " (and schema.md for CSV packs).\n"
            )

        text_lines = [
            "Export complete.",
            "",
            f"Format: {result.output_format_label}",
            f"Decks: {result.deck_label}",
            f"Reviews exported: {result.count}",
            f"Date range: {date_range}",
            "",
        ]
        if result.csv_pack_dir:
            text_lines.extend(
                [
                    f"File: {result.output_path}",
                    f"CSV pack folder: {result.csv_pack_dir}",
                    "CSV pack files: "
                    + ", ".join(result.csv_pack_files or []),
                ]
            )
        else:
            text_lines.append(f"File: {result.output_path}")

        if extra_info:
            text_lines.append(extra_info)

        summary = "\n".join(text_lines)

        box = QMessageBox(mw)
        box.setWindowTitle("LLM Stats Export")
        box.setText(summary)

        # Buttons: Open folder, Copy path, OK
        open_btn = QPushButton("Open folder")
        copy_btn = QPushButton("Copy path")
        ok_btn = QPushButton("OK")

        # PyQt6 style roles
        box.addButton(open_btn, QMessageBox.ButtonRole.ActionRole)
        box.addButton(copy_btn, QMessageBox.ButtonRole.ActionRole)
        box.addButton(ok_btn, QMessageBox.ButtonRole.AcceptRole)

        box.exec()

        clicked = box.clickedButton()
        if clicked is open_btn:
            folder = result.csv_pack_dir or os.path.dirname(result.output_path)
            if folder:
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        elif clicked is copy_btn:
            QGuiApplication.clipboard().setText(
                result.csv_pack_dir or result.output_path
            )

    def _on_failure(exc: Exception) -> None:
        box = QMessageBox(mw)
        box.setWindowTitle("LLM Stats Export - Error")
        box.setText(f"Error during export:\n{exc}")
        box.setIcon(QMessageBox.Critical)
        box.exec()

    op = QueryOp(
        parent=mw,
        op=lambda col: export_llm_stats(
            col=col,
            deck_ids=deck_ids,
            days=days,
            out_path=out_path,
            field_indexes=field_indexes,
            tags_filter=tags_filter,
            min_interval=min_interval,
            include_ids=include_ids,
            include_deck_name=include_deck_name,
            include_ts_ms=include_ts_ms,
            output_format=output_format,
            create_csv_pack=create_csv_pack,
        ),
        success=_on_success,
    )
    op.failure(_on_failure)
    op.with_progress(label="Exporting review stats…").run_in_background()


# --------------------------------------------------------------------
# Add menu entry under Tools
# --------------------------------------------------------------------

action = QAction("Export LLM Stats…", mw)
qconnect(action.triggered, on_export_llm_stats)
mw.form.menuTools.addAction(action)
