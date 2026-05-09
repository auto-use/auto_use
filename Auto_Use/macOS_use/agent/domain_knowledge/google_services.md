This is additional domain knowledge to work efficiently (use it wisely).
<additional_knowledge>
*Google services often expose fewer elements; if an element isn’t marked, use `shortcut_combo` first (use `canvas_input` only when needed).*
- In Google services, log `canvas_input` (what you typed/selected) in `memory` to avoid repeats.
1. Gmail.com
  - Single recipient:
    - After clicking Compose, fill **To -> Subject -> Body** (ideally in one step/sequence).
    - Format: `"action": [{"type": "input", "id": 104, "value": "<recipient_email>"},{"type": "input", "id": 105, "value": "<subject>"},{"type": "input", "id": 106, "value": "<body>"}]`
  - Multiple recipients:
    - Add all recipients in one go when possible: use `canvas_input` then confirm with `enter` to convert them into chips.
    - Format: `"action": [{"type": "click", "id": 104},{"type": "canvas_input", "value": "<r1>"},{"type": "shortcut_combo", "value": "enter"},{"type": "canvas_input", "value": "<r2>"},{"type": "shortcut_combo", "value": "enter"},{"type": "canvas_input", "value": "<r3>"}]`
  - Sending / attachments:
    - Sending or attaching files may require extra steps. Record progress clearly in `memory` (what is completed vs pending).
    - Email Image Handling: Never paste images directly into the body of an email. Always save the image as a local file first, then add it to the email strictly as an attachment.
    - Verify the email is sent by checking the UI (e.g., "Sent" label/folder visible in <os_vision>) before marking the ToDo as complete.
2. Calendar
  - You can open Google Calendar via:
    - direct link
    - Gmail right-side panel
    - Google Apps menu (beside the profile icon)
  - Calendar is often canvas-heavy, so rely on `shortcut_combo` frequently.
  - Once Calendar is open (any entry point):
    - Use `c` to start creating an event, then use `tab` to move through fields and `enter` to select/confirm.
- Format: `"action": [{"type": "shortcut_combo", "value": "c"},{"type": "shortcut_combo", "value": "tab"},{"type": "shortcut_combo", "value": "enter"}]`
  - This opens the event editor so you can set date/time, add guests, add a description, and then save.
3. Google Sheets Interaction
  - Core Mechanism: Sheets is canvas-heavy. Prioritize `shortcut_combo` and `canvas_input`.
    - Navigation (Critical):
      - ALWAYS access cells via `Name Box` + `Enter`.
      - Format: `[{"type": "input", "id": <name_box_id>, "value": "cell_ref"}, {"type": "shortcut_combo", "value": "enter"}]`
    - Data Entry (Row-by-Row):
      1. Reset: Start with `ctrl+home`. Verify `<t-name-box>` value is "A1".
      2. Input: Fill row using `tab` traversal.
      3. Format: `[{"type": "canvas_input", "value": "<col1>"}, {"type": "shortcut_combo", "value": "tab"}, {"type": "canvas_input", "value": "<col2>"}]`
    - Next Row: Jump to specific start cell of next row via `Name Box` + `Enter`.
    - State: Store web-collected data in `scratchpad` (do not re-search). Track entry row progress in `memory`.
  - Editing & Reading:
    - Assess: Use `<os_vision>` to identify layout.
    - Edit: Jump to cell -> `canvas_input` (auto-overwrites).
    - Read: Jump to cell -> Read from 'Formula Bar' or '<element_tree> valuePattern.value'.
  - Menus & Formatting:
    - Commands: Primary method is **Tool Finder** (`Alt + /`). Fallback to menu shortcuts (`Alt+f`, `Alt+e`).
      - Visibility: Ensure data fits.
        - Resize Workflow: Select col via Name Box (e.g., "A:A") -> `Enter` -> `Shift + Space` -> `Alt + /` -> Search "Resize column" -> "Fit to data".
</additional_knowledge>
