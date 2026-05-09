This is additional domain knowledge to work efficiently (use it wisely).
<additional_knowledge>
*Microsoft services often expose fewer elements; be ready to use `shortcut_combo` and `canvas_input`.*

1. Excel Online:
   - If you use `web` to collect data, store the final numbers/answers in `scratchpad` (so you don't re-search).
   - Sheets is mostly canvas-heavy, so use `shortcut_combo` and `canvas_input` often.
   - Table entry (row-by-row, horizontal):
     - Fill each row in one go (cell1 -> tab -> cell2 -> tab ...), then move to the next row.
     - First, confirm the active cell. If it is not A1, jump to A1:
       - "action": [{"type": "shortcut_combo", "value": "ctrl+home"}]
     - You can confirm the current cell via the Name Box element (e.g., `name="name-box"` with `valuePattern.value="A1"`).
     - To enter a row:
      - Click the Name Box (name-box), type the target start cell (e.g., "A1", "A2"), then "shortcut_combo": "enter" then use `canvas_input` with `tab` to fill across the row.
      - Example Format: `"action": [{"type": "input", "id": <name_box_id>, "text": "A1"},{"type": "shortcut_combo", "value": "enter"},{"type": "canvas_input", "text": "<col1>"},{"type": "shortcut_combo", "value": "tab"},{"type": "canvas_input", "text": "<col2>"},{"type": "shortcut_combo", "value": "tab"}]`
     - Repeat for each row with `name box` not with `enter` to move to next row. Track progress in `memory` (e.g., "Completed rows: header + A2–A5").
   - Editing / reading values:
     - First, use <os_vision> to understand the table layout and which cell needs change.
     - Jump to the exact cell via the Name box, then overwrite using `canvas_input`. Cell edit overwrites by itself.
     - To read a cell precisely: jump to the cell and read the value from the Formula Bar / <element_tree> valuePattern.value.
   - Use Excel's search:
     - Searching for actions like "Download a copy" can open menus that download .xlsx.
     - Alternatively use File -> Export for PDF/CSV options.
   - Shortcuts: `ctrl+home` (go to A1), `ctrl+end` (go to last cell), `ctrl+s` (save), `ctrl+z` (undo).

2. Word Online:
   - Document editing is mostly canvas-heavy, use `canvas_input` for typing content.
   - Use `shortcut_combo` for formatting: `ctrl+b` (bold), `ctrl+i` (italic), `ctrl+u` (underline).
   - Navigation: `ctrl+home` (start of doc), `ctrl+end` (end of doc), `ctrl+f` (find).
   - Saving: Documents auto-save, but use `ctrl+s` to force save or File -> Save As for different formats.
   - To download: File -> Save As -> Download a Copy (or Export to PDF).

3. Outlook (outlook.live.com / outlook.office.com):
   - Single recipient:
     - After clicking New mail/Compose, fill **To -> Subject -> Body** (ideally in one step/sequence).
     - Format: `"action": [{"type": "input", "id": <to_element>, "text": "<email>"},{"type": "input", "id": <subject_element>, "text": "<subject>"},{"type": "click", "id": <body_element>},{"type": "canvas_input", "text": "<body_text>"}]`
   - Multiple recipients:
     - Add recipients one by one using `canvas_input` + `enter` to convert them into chips.
   - Attachments:
     - Click Attach button, navigate file picker, select file.
     - Record progress clearly in `memory` (what is completed vs pending).
   - Sending:
     - Verify email is ready (recipients, subject, body filled).
     - Click Send button or use `ctrl+enter` shortcut.
   - Calendar (Outlook Calendar):
     - Create event via New event button or `ctrl+shift+e`.
     - Fill in: Title, Date/Time, Location, Attendees.
     - Use `tab` to navigate between fields.

4. General Microsoft shortcuts and fallbacks:
   - Use `shortcut_combo` for common actions when elements aren't exposed.
   - Use `canvas_input` when the editor/grid is focused but not addressable via numbered elements.
   - Common shortcuts: `ctrl+s` (save), `ctrl+z` (undo), `ctrl+y` (redo), `ctrl+p` (print), `ctrl+f` (find).
</additional_knowledge>
