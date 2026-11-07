# Report format and date rules

## Groups (in this order)

1. **Expired**: expiry date is before today. Most overdue first.
2. **Expiring soon**: expiry date falls from today up to the end of the look-ahead window. Soonest first.
3. **Later**: expiry date is after the window. Soonest first.
4. **Date unclear**: a date was found but cannot be read with confidence, or several conflicting expiry dates were found. Show what the document says.
5. **No readable date**: no expiry or renewal date found, or the file could not be read.

## Row contents

Document kind, file name, full path, the date exactly as written, the label it appeared under, and days remaining or days overdue.

## Date rules

- Use only dates labelled as expiry, renewal, valid until, end or due. An issue or start date is never an expiry date.
- Ambiguous numeric dates such as 03/04/26 go to "Date unclear" showing both readings, unless the document states its date format.
- If a document has several expiry dates (for example one per cover item), list each one on its own row.
- Show a summary line first: files checked, files with a readable date, files without one.
- Do not change, move, rename or tag any file. Suggestions about what to renew are wording only.
