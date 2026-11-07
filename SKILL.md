---
name: document-expiry-watcher
description: Find documents on the NAS that carry renewal or expiry dates, such as warranties, insurance policies, permits, licences and contracts, and produce a dated report of what has expired or is expiring soon. Use when the user asks what is expiring, which documents need renewal, or to check expiry dates in a chosen folder. Read-only unless the user approves saving the report.
---

# Goal

Give the user a clear, source-linked report of which documents in a folder they choose have expired, expire within a chosen window, or have no readable date. The Skill only reads documents. It never moves, renames, tags, edits or deletes files. The report is shown in the conversation and is saved to the NAS only if the user approves. This is an on-demand check, not a scheduled alert.

# Required input

- One or more NAS folders to scan. If the user gives none, ask for one. Never default to the whole NAS.
- Look-ahead window for "expiring soon". Use 90 days unless the user states another.
- Optional: document kinds to focus on, for example insurance, warranty, permit, licence or contract.
- Today's date, taken from the conversation context. If it is not available, ask the user.

Do not ask the user for CLI parameters or internal IDs. The delegated experts own those.

# Generation-time capability evidence

- `ug-filesystem` → `file-agent`
- `ug-document` → `document-agent`
- `ug-knowledge` → `knowledge-agent`
- `ug-photo` → `photo-agent`

The photo-agent is used only for image-format documents that have no readable text.

# Orchestration

Run the steps in order. Pass only the real results of an upstream step to the downstream step. If an upstream result is missing, stop the steps that depend on it.

1. Delegate candidate discovery to the file expert, using the folder the user named:
   `delegate --target file-agent --instruction 'List the document files (PDF, DOCX, DOC, TXT and common image formats) in the folder the user named and its subfolders, up to a reasonable limit. Return for each file its full path, file name, size and last-modified time. Do not open, move, rename, tag or delete any file. If the folder does not exist or cannot be read, report a failure instead of guessing.'`
   If no files are returned, stop and report an empty result. Do not invent files.

2. Delegate date extraction to the document expert, using only the file list that file-agent returned:
   `delegate --target document-agent --instruction 'For each file in the file list returned by file-agent, read the real file content and extract the document kind, the issuer or counterparty if stated, and every date labelled as an expiry, renewal, valid-until, end or due date, copied exactly as written together with the label it appears under. Also extract the issue or start date if stated and mark it as an issue date, never as an expiry. If a file has no readable text or no such date, say so for that file. Do not infer a date that is not written in the document. Do not modify any file.'`

3. Only if document-agent reports image-format files with no readable text, delegate those files to the photo expert:
   `delegate --target photo-agent --instruction 'Read the text in the image files that document-agent reported as having no readable text. Return the recognised text for each file, or state that nothing was readable. Do not modify any file.'`
   Run the recognised text through the date rules of step 2. If this step fails or is unavailable, mark those files as unreadable and continue.

4. Build the report in the parent Skill from the real results only. Follow [the report format and date rules](references/report-format.md). Every row names its source file path. Compare each date with today's date to choose the group. Never invent or round a date.

5. Show the report and ask whether the user wants it saved. Only after the user agrees, delegate saving to the knowledge expert:
   `delegate --target knowledge-agent --instruction 'Save the report text shown to the user as a note named Document expiry report. Save it exactly as shown and do not change the content.'`
   Saving needs platform approval. Wait for it, and do not say the report is saved until the state is `completed`.

Supporting files: [usage guide](references/usage-guide.md), [test cases](references/test-cases.md), [disclosures](references/disclosure.md).

# Completion and failure

- `completed`: use the result and continue. Report a business result only after the expert returns `completed`.
- `failed`: report which step failed and why. Keep earlier real results, stop dependent steps, and do not guess dates to fill the gap.
- `cancelled`: report that the step was cancelled, stop dependent steps, keep earlier results, and say the report is partial.
- `waiting_user`: relay the expert's question to the user in plain words and wait for the answer.
- `waiting_approval`: tell the user which action needs approval, for example saving the report. Do not continue or claim the action happened until approval is given and the state is `completed`.

Empty and partial results:

- No documents found: say so, name the folder, and do not produce a report.
- Some documents unreadable or without a date: list them under "No readable date" and state how many files were checked in total.
- Never describe a partial scan as complete.
