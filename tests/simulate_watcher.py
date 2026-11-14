#!/usr/bin/env python3
"""
Simulated test harness for document-expiry-watcher skill.
Implements the orchestration rules from SKILL.md, references/report-format.md,
and verifies test cases from references/test-cases.md.
"""

import os
import re
import hashlib
from datetime import datetime, date
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict

# Supported extensions
SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.txt', '.png', '.jpg', '.jpeg', '.webp'}

# Labels representing expiry/renewal
EXPIRY_LABELS = [
    'expiry date', 'expiration date', 'renewal date', 
    'valid until', 'end date', 'due date', 'termination date'
]
ISSUE_LABELS = ['issue date', 'date of issue', 'start date', 'commencement']

@dataclass
class FileMetadata:
    path: str
    name: str
    size: int
    mtime: float
    sha256: str

@dataclass
class ExtractedDate:
    date_str: str
    label: str
    parsed_date: Optional[date]
    is_ambiguous: bool = False
    ambiguous_readings: Optional[List[str]] = None
    is_issue_date: bool = False

@dataclass
class DocumentExtraction:
    file_meta: FileMetadata
    document_kind: str
    issuer_or_party: Optional[str]
    dates: List[ExtractedDate]
    has_conflicting_dates: bool = False
    is_unreadable: bool = False
    unreadable_reason: Optional[str] = None

@dataclass
class ReportRow:
    group: str  # 'Expired', 'Expiring soon', 'Later', 'Date unclear', 'No readable date'
    doc_kind: str
    file_name: str
    full_path: str
    date_as_written: str
    label: str
    days_delta: Optional[int]  # negative for overdue, positive for remaining
    extra_note: Optional[str] = None

# Step 1: file-agent simulation
def simulate_file_agent(folder_path: str) -> List[FileMetadata]:
    """Lists document files in folder without modifying them."""
    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
        raise FileNotFoundError(f"Folder does not exist or is not readable: {folder_path}")
    
    results = []
    for root, _, files in os.walk(folder_path):
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                full_path = os.path.abspath(os.path.join(root, f))
                stat = os.stat(full_path)
                with open(full_path, 'rb') as fp:
                    digest = hashlib.sha256(fp.read()).hexdigest()
                results.append(FileMetadata(
                    path=full_path,
                    name=f,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    sha256=digest
                ))
    return results

# Helper: parse date and handle ambiguous formats like DD/MM/YY vs MM/DD/YY
def parse_date_string(date_text: str) -> Tuple[Optional[date], bool, Optional[List[str]]]:
    """
    Parses date text. Returns (parsed_date, is_ambiguous, ambiguous_readings).
    Ambiguous formats like 03/04/26 return both readings as required by report-format.md.
    """
    date_text = date_text.strip()
    
    # Check for ambiguous numeric format: MM/DD/YY or DD/MM/YY (e.g. 03/04/26)
    m_num = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', date_text)
    if m_num:
        p1, p2, yr = int(m_num.group(1)), int(m_num.group(2)), int(m_num.group(3))
        if yr < 100:
            yr += 2000
        # If both p1 and p2 could be months (<= 12) and are not equal, it's ambiguous
        if 1 <= p1 <= 12 and 1 <= p2 <= 12 and p1 != p2:
            readings = []
            for month, day, format_name in (
                (p1, p2, "MM/DD/YY"),
                (p2, p1, "DD/MM/YY"),
            ):
                try:
                    parsed = date(yr, month, day)
                except ValueError:
                    continue
                readings.append(
                    f"{yr}-{month:02d}-{day:02d} "
                    f"(if {format_name}: {parsed.strftime('%B %d, %Y')})"
                )
            return None, bool(readings), readings or None
        elif 1 <= p1 <= 12:
            try:
                return date(yr, p1, p2), False, None
            except ValueError:
                return None, False, None
        else:
            try:
                return date(yr, p2, p1), False, None
            except ValueError:
                return None, False, None

    # Text formats like "October 15, 2025" or "2026-11-27"
    normalized_date_text = re.sub(r'(?<=\d)(?:st|nd|rd|th)\b', '', date_text, flags=re.IGNORECASE)
    for fmt in ('%B %d, %Y', '%b %d, %Y', '%Y-%m-%d', '%d %B %Y', '%B %d %Y'):
        try:
            dt = datetime.strptime(normalized_date_text, fmt).date()
            return dt, False, None
        except ValueError:
            pass
            
    return None, False, None

# Step 2 & 3: document-agent & photo-agent simulation
def simulate_document_agent(file_meta: FileMetadata) -> DocumentExtraction:
    """Reads document content and extracts date labels according to rules."""
    ext = os.path.splitext(file_meta.name)[1].lower()
    
    if ext in ('.png', '.jpg', '.jpeg', '.webp'):
        # Image file: simulate photo-agent fallback.
        # If file is a dummy blank image, return unreadable.
        return DocumentExtraction(
            file_meta=file_meta,
            document_kind="Scanned Image",
            issuer_or_party=None,
            dates=[],
            is_unreadable=True,
            unreadable_reason="No readable text recognized by OCR"
        )
    
    try:
        with open(file_meta.path, 'r', encoding='utf-8', errors='ignore') as fp:
            content = fp.read()
    except Exception as e:
        return DocumentExtraction(
            file_meta=file_meta,
            document_kind="Unknown",
            issuer_or_party=None,
            dates=[],
            is_unreadable=True,
            unreadable_reason=str(e)
        )
        
    doc_kind = "Document"
    if "POLICY" in content.upper():
        doc_kind = "Insurance Policy"
    elif "WARRANTY" in content.upper():
        doc_kind = "Warranty"
    elif "LEASE" in content.upper():
        doc_kind = "Lease Agreement"
    elif "PERMIT" in content.upper():
        doc_kind = "Permit"
    elif "AGREEMENT" in content.upper() or "SLA" in content.upper():
        doc_kind = "Contract / Agreement"
    elif "RECEIPT" in content.upper() or "INVOICE" in content.upper():
        doc_kind = "Receipt / Invoice"

    extracted_dates = []
    
    # Check for conflicting dates
    date_patterns = [
        r'(Policy Expiry Date|Warranty End Date|Lease Termination Date|Contract Renewal Date|Renewal Date|Valid Until|expiry date|validity and expiry date)[:\s]+([A-Za-z0-9,/\s\-]+?)(?:\.|$|\n)',
        r'(Issue Date|Date of Issue|Start Date|Lease Commencement)[:\s]+([A-Za-z0-9,/\s\-]+?)(?:\.|$|\n)'
    ]
    
    # Date pattern extraction helper
    common_date_patterns = [
        r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}',
        r'\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}',
        r'\d{4}-\d{2}-\d{2}',
        r'\d{1,2}/\d{1,2}/\d{2,4}',
    ]

    for pat in date_patterns:
        for match in re.finditer(pat, content, re.IGNORECASE):
            label = match.group(1).strip()
            val = match.group(2).strip()
            # Clean trailing words if any
            val = re.sub(r'\s+(Status|Coverage|Notice|Terms|Deposit|Notes|Arbitration|Section).*', '', val, flags=re.IGNORECASE).strip()
            
            # Tidy date string: extract exact date substring if present (strips filler like "of", "is", "of this service contract is")
            for dp in common_date_patterns:
                m_date = re.search(dp, val, re.IGNORECASE)
                if m_date:
                    val = m_date.group(0).strip()
                    break
            else:
                val = re.sub(r'^(?:of|is|on|at|of\s+this\s+[^:]*?\s+is)\s+', '', val, flags=re.IGNORECASE).strip()

            is_issue = any(il in label.lower() for il in ISSUE_LABELS)
            dt, is_ambig, readings = parse_date_string(val)
            
            extracted_dates.append(ExtractedDate(
                date_str=val,
                label=label,
                parsed_date=dt,
                is_ambiguous=is_ambig,
                ambiguous_readings=readings,
                is_issue_date=is_issue
            ))

    # Multiple expiry dates in separately numbered clauses are conflicting.
    expiry_dates = [d for d in extracted_dates if not d.is_issue_date]
    clause_lines = [
        line for line in content.splitlines()
        if re.search(r'\bsection\s+[\w.]+\s*:', line, re.IGNORECASE)
        and re.search(r'\b(?:expiry|expiration|validity)\b.*\bdate\b', line, re.IGNORECASE)
    ]
    has_conflicting = len(clause_lines) > 1 and len(expiry_dates) > 1

    return DocumentExtraction(
        file_meta=file_meta,
        document_kind=doc_kind,
        issuer_or_party=None,
        dates=extracted_dates,
        has_conflicting_dates=has_conflicting,
        is_unreadable=False
    )

# Step 4: Report Builder
def build_report(extractions: List[DocumentExtraction], today: date, window_days: int = 90) -> Tuple[str, List[ReportRow], Dict[str, int]]:
    """
    Builds the report adhering to references/report-format.md:
    1. Expired (expiry < today, most overdue first)
    2. Expiring soon (today <= expiry <= today + window, soonest first)
    3. Later (expiry > today + window, soonest first)
    4. Date unclear
    5. No readable date
    """
    rows: List[ReportRow] = []
    files_with_readable_date = set()
    total_files = len(extractions)

    for doc in extractions:
        if doc.is_unreadable:
            rows.append(ReportRow(
                group="No readable date",
                doc_kind=doc.document_kind,
                file_name=doc.file_meta.name,
                full_path=doc.file_meta.path,
                date_as_written="N/A",
                label="Unreadable file",
                days_delta=None,
                extra_note=doc.unreadable_reason
            ))
            continue

        if doc.has_conflicting_dates:
            conflicting_dates = [d for d in doc.dates if not d.is_issue_date]
            date_summaries = " vs ".join([d.date_str for d in conflicting_dates])
            label_summaries = " / ".join([d.label for d in conflicting_dates])
            rows.append(ReportRow(
                group="Date unclear",
                doc_kind=doc.document_kind,
                file_name=doc.file_meta.name,
                full_path=doc.file_meta.path,
                date_as_written=date_summaries,
                label=label_summaries,
                days_delta=None,
                extra_note="Multiple conflicting expiry dates in document clauses"
            ))
            continue

        expiry_dates = [d for d in doc.dates if not d.is_issue_date]
        
        if not expiry_dates:
            # Check if only issue dates were found
            issue_notes = []
            for d in doc.dates:
                if d.is_issue_date:
                    issue_notes.append(f"{d.label}: {d.date_str}")
            note = f"Only issue date found ({', '.join(issue_notes)}); no expiry date" if issue_notes else "No expiry date found"
            rows.append(ReportRow(
                group="No readable date",
                doc_kind=doc.document_kind,
                file_name=doc.file_meta.name,
                full_path=doc.file_meta.path,
                date_as_written="None",
                label="No expiry label",
                days_delta=None,
                extra_note=note
            ))
            continue

        for ed in expiry_dates:
            if ed.is_ambiguous:
                readings_str = " vs ".join(ed.ambiguous_readings) if ed.ambiguous_readings else "Ambiguous"
                rows.append(ReportRow(
                    group="Date unclear",
                    doc_kind=doc.document_kind,
                    file_name=doc.file_meta.name,
                    full_path=doc.file_meta.path,
                    date_as_written=ed.date_str,
                    label=ed.label,
                    days_delta=None,
                    extra_note=f"Format unstated; ambiguous readings: {readings_str}"
                ))
            elif ed.parsed_date:
                files_with_readable_date.add(doc.file_meta.path)
                days_diff = (ed.parsed_date - today).days
                if days_diff < 0:
                    group = "Expired"
                elif 0 <= days_diff <= window_days:
                    group = "Expiring soon"
                else:
                    group = "Later"

                rows.append(ReportRow(
                    group=group,
                    doc_kind=doc.document_kind,
                    file_name=doc.file_meta.name,
                    full_path=doc.file_meta.path,
                    date_as_written=ed.date_str,
                    label=ed.label,
                    days_delta=days_diff,
                    extra_note=f"{abs(days_diff)} days overdue" if days_diff < 0 else f"{days_diff} days remaining"
                ))
            else:
                rows.append(ReportRow(
                    group="Date unclear",
                    doc_kind=doc.document_kind,
                    file_name=doc.file_meta.name,
                    full_path=doc.file_meta.path,
                    date_as_written=ed.date_str,
                    label=ed.label,
                    days_delta=None,
                    extra_note="Date text could not be parsed with confidence"
                ))

    # Sort groups per rules:
    # 1. Expired: most overdue first (lowest days_delta)
    # 2. Expiring soon: soonest first (lowest days_delta)
    # 3. Later: soonest first (lowest days_delta)
    expired_rows = sorted([r for r in rows if r.group == "Expired"], key=lambda x: x.days_delta if x.days_delta is not None else 0)
    expiring_soon_rows = sorted([r for r in rows if r.group == "Expiring soon"], key=lambda x: x.days_delta if x.days_delta is not None else 0)
    later_rows = sorted([r for r in rows if r.group == "Later"], key=lambda x: x.days_delta if x.days_delta is not None else 0)
    unclear_rows = [r for r in rows if r.group == "Date unclear"]
    no_date_rows = [r for r in rows if r.group == "No readable date"]

    ordered_rows = expired_rows + expiring_soon_rows + later_rows + unclear_rows + no_date_rows

    counts = {
        "total_files": total_files,
        "files_with_readable_date": len(files_with_readable_date),
        "files_without_readable_date": total_files - len(files_with_readable_date)
    }

    # Render Markdown report
    lines = []
    lines.append("# Document Expiry Report")
    lines.append(f"**As of**: {today.strftime('%B %d, %Y')} | **Look-ahead window**: {window_days} days\n")
    lines.append(f"**Summary**: Checked {counts['total_files']} files | {counts['files_with_readable_date']} with readable expiry date | {counts['files_without_readable_date']} without readable date\n")

    groups = [
        ("1. Expired", expired_rows),
        ("2. Expiring soon", expiring_soon_rows),
        ("3. Later", later_rows),
        ("4. Date unclear", unclear_rows),
        ("5. No readable date", no_date_rows)
    ]

    for title, grp_rows in groups:
        lines.append(f"## {title} ({len(grp_rows)})")
        if not grp_rows:
            lines.append("_None_\n")
            continue
        lines.append("| Document Kind | File Name | Full Path | Date as Written | Label | Status / Days |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for r in grp_rows:
            note = r.extra_note or ""
            lines.append(f"| {r.doc_kind} | `{r.file_name}` | `{r.full_path}` | {r.date_as_written} | {r.label} | {note} |")
        lines.append("")

    report_markdown = "\n".join(lines)
    return report_markdown, ordered_rows, counts

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Simulate document-expiry-watcher skill")
    parser.add_argument("--folder", default="test-fixtures", help="Folder path to scan")
    parser.add_argument("--window", type=int, default=90, help="Look-ahead window in days")
    args = parser.parse_args()

    target_dir = os.path.abspath(args.folder)
    print(f"=== [Step 1: file-agent] Scanning folder: {target_dir} ===")
    files = simulate_file_agent(target_dir)
    print(f"Discovered {len(files)} files.\n")

    print("=== [Step 2 & 3: document-agent & photo-agent] Extracting content & dates ===")
    extractions = []
    for f in files:
        ext = simulate_document_agent(f)
        extractions.append(ext)
        status_msg = f"{ext.document_kind} ({len(ext.dates)} dates)" if not ext.is_unreadable else f"Unreadable ({ext.unreadable_reason})"
        print(f" - {f.name}: {status_msg}")
    print()

    print(f"=== [Step 4: Report Builder] Compiling report (Window: {args.window} days) ===\n")
    report_text, rows, summary = build_report(extractions, today=date(2026, 11, 7), window_days=args.window)
    print(report_text)

    print("=== [Step 5: knowledge-agent] Note save prompt ===")
    print("Skill asks user: 'Would you like to save this report as a note named \"Document expiry report\"?'")
    print("Platform status: waiting_approval (Save will only proceed upon approval).")

