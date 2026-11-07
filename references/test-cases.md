# Test cases for a NAS run

## Core case 1: folder with mixed documents
A folder holds an insurance policy PDF, a warranty PDF and a permit DOCX with different expiry dates. Expected: one report with each document in the right group, every row linked to its path, no file changed.

## Core case 2: custom window
The user asks what expires in the next 30 days for a folder of licences. Expected: only documents inside 30 days appear under "Expiring soon", and the report states the 30-day window.

## Edge case: unclear and unreadable files
The folder contains a scanned image with no text, a PDF with the date 03/04/26 and no stated format, and a file with only an issue date. Expected: all three appear under "Date unclear" or "No readable date", none gets an invented expiry date, and the summary line shows the counts.

## Automated local test harness
The test cases above are implemented in `tests/test_expiry_watcher.py` against the files in `test-fixtures/`:
- **Run test suite**: `python3 -m unittest discover -s tests -v`
- **Run CLI simulation**: `python3 tests/simulate_watcher.py --folder test-fixtures --window 90`
All tests verify non-destructive operation by validating SHA-256 file hashes before and after execution.
