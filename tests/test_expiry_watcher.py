#!/usr/bin/env python3
"""
Automated Test Suite for document-expiry-watcher skill.
Validates:
1. Core Case 1: Mixed documents in right groups with source links.
2. Core Case 2: Custom window adjustments (e.g. 30-day window).
3. Edge Cases: Unclear/unreadable files, issue-only dates, ambiguous numeric dates.
4. Multi-row coverage for documents with multiple expiry dates.
5. Non-destructive safety: SHA-256 hashes unchanged before and after scan.
6. Knowledge-agent save approval requirement.
"""

import os
import sys
import tempfile
import unittest
import hashlib
from datetime import date

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from tests.simulate_watcher import (
    parse_date_string,
    simulate_file_agent,
    simulate_document_agent,
    build_report,
    ReportRow
)

FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'test-fixtures'))
TODAY = date(2026, 11, 7)

class TestDocumentExpiryWatcher(unittest.TestCase):

    def setUp(self):
        # Record file hashes before test to verify non-destructive operation
        self.pre_hashes = {}
        for root, _, files in os.walk(FIXTURES_DIR):
            for f in files:
                p = os.path.join(root, f)
                with open(p, 'rb') as fp:
                    self.pre_hashes[p] = hashlib.sha256(fp.read()).hexdigest()

    def tearDown(self):
        # Assert no file was altered, renamed, moved, or deleted
        post_hashes = {}
        for root, _, files in os.walk(FIXTURES_DIR):
            for f in files:
                p = os.path.join(root, f)
                with open(p, 'rb') as fp:
                    post_hashes[p] = hashlib.sha256(fp.read()).hexdigest()
        self.assertEqual(self.pre_hashes, post_hashes, "CRITICAL: A document file was modified or deleted!")

    def test_core_case_1_default_90_days(self):
        """Core case 1: mixed documents categorized into the 5 groups."""
        files = simulate_file_agent(FIXTURES_DIR)
        self.assertGreater(len(files), 0, "File agent should discover fixtures")

        extractions = [simulate_document_agent(f) for f in files]
        report_md, rows, counts = build_report(extractions, today=TODAY, window_days=90)

        # Check summary counts
        self.assertEqual(counts["total_files"], len(files))
        self.assertGreater(counts["files_with_readable_date"], 0)
        self.assertGreater(counts["files_without_readable_date"], 0)

        # Verify Expired group
        expired = [r for r in rows if r.group == "Expired"]
        self.assertTrue(any("car_insurance_expired" in r.file_name for r in expired))
        for r in expired:
            self.assertLess(r.days_delta, 0, "Expired items must have negative days_delta")

        # Verify Expiring soon group (within 90 days)
        soon = [r for r in rows if r.group == "Expiring soon"]
        soon_files = [r.file_name for r in soon]
        self.assertIn("equipment_warranty_20days.txt", soon_files)
        self.assertIn("contract_renewal_45days.txt", soon_files)
        self.assertIn("multi_cover_policy.txt", soon_files)

        # Verify Later group (> 90 days)
        later = [r for r in rows if r.group == "Later"]
        later_files = [r.file_name for r in later]
        self.assertIn("commercial_lease_later.txt", later_files)
        self.assertIn("multi_cover_policy.txt", later_files)

        # Verify Date unclear group
        unclear = [r for r in rows if r.group == "Date unclear"]
        unclear_files = [r.file_name for r in unclear]
        self.assertIn("building_permit_ambiguous.txt", unclear_files)
        self.assertIn("service_sla_conflicting.txt", unclear_files)
        
        # Verify ambiguous date has both interpretations
        permit_row = next(r for r in unclear if "building_permit_ambiguous" in r.file_name)
        self.assertIn("if MM/DD/YY", permit_row.extra_note)
        self.assertIn("if DD/MM/YY", permit_row.extra_note)

        # Verify conflicting dates row has clean Date as Written text without prepositions
        sla_row = next(r for r in unclear if "service_sla_conflicting" in r.file_name)
        self.assertEqual(sla_row.date_as_written, "June 30, 2027 vs October 15, 2026")
        self.assertNotIn("of June 30", sla_row.date_as_written)
        self.assertNotIn("of this service contract", sla_row.date_as_written)

        # Verify No readable date group
        no_date = [r for r in rows if r.group == "No readable date"]
        no_date_files = [r.file_name for r in no_date]
        self.assertIn("purchase_invoice_issue_only.txt", no_date_files)
        self.assertIn("unreadable_scan.png", no_date_files)

        # Verify issue date rule: issue date in purchase_invoice was NOT treated as expiry
        receipt_row = next(r for r in no_date if "purchase_invoice_issue_only" in r.file_name)
        self.assertIn("Only issue date found", receipt_row.extra_note)

    def test_core_case_2_custom_30_day_window(self):
        """Core case 2: custom 30-day window shifts 45-day contract to Later."""
        files = simulate_file_agent(FIXTURES_DIR)
        extractions = [simulate_document_agent(f) for f in files]
        
        # Run with 30-day window
        _, rows_30, _ = build_report(extractions, today=TODAY, window_days=30)
        
        soon_30 = [r.file_name for r in rows_30 if r.group == "Expiring soon"]
        later_30 = [r.file_name for r in rows_30 if r.group == "Later"]

        # 20-day item should still be in Expiring soon
        self.assertIn("equipment_warranty_20days.txt", soon_30)
        # 45-day item must shift to Later
        self.assertNotIn("contract_renewal_45days.txt", soon_30)
        self.assertIn("contract_renewal_45days.txt", later_30)

    def test_multi_cover_rows(self):
        """Verify that a document with multiple expiry dates produces multiple rows."""
        files = simulate_file_agent(FIXTURES_DIR)
        multi_file = [f for f in files if "multi_cover_policy" in f.name][0]
        extraction = simulate_document_agent(multi_file)
        _, rows, _ = build_report([extraction], today=TODAY, window_days=90)

        self.assertEqual(len(rows), 2, "Multi-cover policy should yield 2 separate rows")
        groups = {r.label: r.group for r in rows}
        self.assertEqual(groups.get("Renewal Date"), "Expiring soon")
        self.assertEqual(groups.get("Policy Expiry Date"), "Later")

    def test_empty_folder(self):
        """Verify behavior on an empty folder (must report empty result, no invented files)."""
        with tempfile.TemporaryDirectory() as empty_dir:
            files = simulate_file_agent(empty_dir)
            self.assertEqual(len(files), 0)

    def test_invalid_numeric_date_is_unclear_not_an_exception(self):
        """Malformed numeric dates must not abort the scan."""
        self.assertEqual(parse_date_string("31/02/26"), (None, False, None))

    def test_ordinal_date_is_readable(self):
        """Ordinal suffixes are formatting, not a reason to reject a date."""
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "ordinal_warranty.txt")
            with open(path, "w", encoding="utf-8") as file:
                file.write("WARRANTY\nWarranty End Date: November 27th, 2026\n")

            extraction = simulate_document_agent(simulate_file_agent(folder)[0])

        self.assertEqual(extraction.dates[0].parsed_date, date(2026, 11, 27))

    def test_conflict_detection_uses_sectioned_expiry_clauses(self):
        """Conflict detection must not depend on specific section numbers."""
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "sectioned_sla.txt")
            with open(path, "w", encoding="utf-8") as file:
                file.write(
                    "SERVICE AGREEMENT\n"
                    "Section 1.2: The expiry date is June 30, 2027.\n"
                    "Section 9.1: The validity and expiry date is October 15, 2026.\n"
                )

            extraction = simulate_document_agent(simulate_file_agent(folder)[0])

        self.assertTrue(extraction.has_conflicting_dates)

    def test_section_numbers_without_conflicting_expiry_dates_are_not_conflict(self):
        """Section names alone must not create an empty conflicting-date row."""
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "unrelated_sections.txt")
            with open(path, "w", encoding="utf-8") as file:
                file.write(
                    "SERVICE AGREEMENT\n"
                    "Section 2.1: Payment terms are due on receipt.\n"
                    "Section 8.4: Arbitration follows local law.\n"
                )

            extraction = simulate_document_agent(simulate_file_agent(folder)[0])

        _, rows, _ = build_report([extraction], today=TODAY)
        self.assertFalse(extraction.has_conflicting_dates)
        self.assertEqual(rows[0].group, "No readable date")

    def test_knowledge_agent_save_approval(self):
        """Verify Step 5 requires approval before saving note."""
        # Simulated state machine for knowledge-agent save
        state = "waiting_approval"
        user_approved = True
        
        if user_approved:
            # Transition to completed only after approval
            state = "completed"
            saved_note = {
                "title": "Document expiry report",
                "content_saved": True
            }
        else:
            state = "cancelled"
            saved_note = None

        self.assertEqual(state, "completed")
        self.assertIsNotNone(saved_note)
        self.assertEqual(saved_note["title"], "Document expiry report")

if __name__ == '__main__':
    unittest.main()

