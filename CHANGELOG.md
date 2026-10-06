# Changelog

## 1.3.2
- Fixed: the old Ctrl+X kept opening the pill although Settings and config.json said Alt+X. Older versions
  had registered Ctrl+X with GNOME and, with auto-register off, nothing ever updated it. The widget now
  switches an existing registration to the configured key at start (a key you changed by hand in GNOME
  Settings is left alone; nothing new is registered while auto-register is off). Settings also tells you
  when GNOME has a different key than the one configured, and Apply fixes it.
- BACK button (settings and task pages): outlined pill with padding and margin; the hover highlight no longer
  clips its ends.

## 1.3.1
- The Add-a-task box is exactly as wide as the task list (and the highlighted new-task row); new setting
  `input_width` (50-100 %, default 100) makes it narrower, centred.

## 1.3.0
- Fixed: after visiting Settings and coming back, the clock and task list sat a few pixels to the right.
  Cause: the Settings page asked for 378 px but the notepad only has 368 px, so the frame silently grew.
  The page now needs far less width (long labels wrap or shorten) and a guard makes it impossible for any
  page to widen the notepad frame or stretch another page (at every notepad size, 0.7 to 1.2).
- New: click a task to open its complete text on its own page inside the pill (slide transition). The page
  shows state and time and has START / PAUSE, DONE / REOPEN, COPY and DELETE. BACK or Esc slides back.
  The pill does not auto-hide or fold away while you read a task (same as in Settings).
- New: Ctrl+S opens the settings page (press again to go back); works from the bare pill and from the
  notepad while the pill has keyboard focus. Ctrl+, still works too. It is not a global shortcut.
- New defaults: vault `~/Obsidian`, border colour #77767B, pill size 1.2, `auto_shortcut` off, game colours
  `pill`. Saved settings are never overwritten. With `auto_shortcut` off the widget does not register the
  open/close shortcut by itself: use Settings (Apply) or `nothing-tasks install-shortcut`.

## 1.2.3
- Fixed: after Win+D ("show desktop") or a minimise, the shortcut did nothing (or needed several presses). The
  toggle now looks at whether the pill is really on screen: the first press brings it back, the window is
  never re-mapped as "minimised", and a post-show check re-maps it if the window manager still hides it.
  Verified against real Mutter (`tests/test_wm_show_desktop.py`).
- Default shortcut is Alt+X again; a saved Ctrl+X (the 1.2.2 default) is switched once and re-registered.
- Fixed: the highlighted / hovered task row was lopsided on themes with classic scrollbars (an invisible
  scrollbar reserved 15 px on the right). The list has no reserved scrollbar width any more; the wheel scrolls.
- Resource use: no timers at all while the pill is hidden; one wake-up per second while it is shown; the
  idle game draws from cached art (6x cheaper), ticks at ~24 fps and pauses while the WM hides the pill;
  the glass background is cached while not animating; identical refreshes no longer rebuild the task rows;
  notes with thousands of tasks show the newest 200 (the note itself keeps everything).
- Fixed: changing the auto-hide time in Settings while the pill was open only took effect on the next show.
- UI: messages ("DELETED", "ADDED") no longer get cut off next to UNDO; settings labels wrap cleanly;
  no empty gap under the shortcut field.

## 1.2.2
- Ctrl+X is the default open/close shortcut again. A saved Alt+X (the 1.2.x default) is switched to the
  new default once and re-registered with GNOME automatically; a shortcut you pick afterwards is kept.
- Notepad: no dead space under the stopwatch, tighter spacing, four task rows visible at once at the
  default size, and a wider task list.
- About card redesigned: drawn icons (no font glyphs), aligned rows with Copy / Open actions.

## 1.2.1
- Tasks no longer get a visible `^t-xxxxxx` block id at the end of the line in Obsidian. Task identity is
  derived from the task text instead (duplicates are told apart by order). Old ids left in your note are
  removed once (a backup is kept) and a running timer follows its task. If you reword a task in Obsidian
  while it is being timed, the time is not saved and you get a message.
- The per-task button shows a pause icon (red) while that task is being timed; press it to pause, or press
  another task's play button to switch.
- The Add-a-task box border follows the pill border colour; new `input_scale` setting (default 0.85, a bit
  smaller than before).
- Redesigned About card in settings: app name with version badge, developer card with email (and Copy) and GitHub.
- The app name now lives in one constant (`APP_NAME`).

## 1.2.0
- Defaults updated to the author's config (border 1.0, input border 1, top margin 10, auto-hide 3 s,
  shortcut Alt+X, ...). The vault defaults to the author's folder when it exists, else ~/Obsidian.
  Existing config.json values are never overwritten. A changed shortcut is re-applied to GNOME.
- Glass effect (default on): translucent frosted pill with a soft sheen, denser while the notepad is open;
  strength setting; best-effort blur of what is behind (X11 only); light/dark theme that follows the system.
- Notepad is 10% smaller by default; `notepad_scale` setting (0.7-1.2).
- Idle game in the pill while the stopwatch is stopped (a pixel runner, Mario-style colours, original art):
  plays itself, click / Up / W to jump, coins, score and best score. Digits replace it while timing.
  Colours: mario or pill theme; can be switched off.
- Developer info in the settings page.

## 1.1.1
- New setting: border width of the task input (default 10 px, 0-12).
- Bigger settings (gear) and close icons in the notepad header.
- Settings page: no sliders or +/- spinners; sizes are typed numbers. The mouse wheel scrolls the
  page and can no longer change a value or a drop-down by accident.
- Showing the pill no longer takes keyboard focus by default (`focus_on_show` = false), which is the
  most likely reason the auto-hide dock popped up with it. Existing configs are migrated once.

## 1.1.0
- Ctrl+X is the default shortcut for opening AND closing the pill. The widget registers it with GNOME
  by itself on start (and repairs it if the path changes), so no terminal command is needed.
  The helper also starts the widget if it is not running.
- iPhone-style entrance: a small pill blooms in place at the top-middle with a spring, instead of
  sliding down; hiding shrinks it back.
- Bigger task controls (rows, buttons, text) and a wider notepad.
- Settings now open inside the pill (gear icon) instead of a separate window. Esc / BACK returns.
- Adding a task scrolls the list to it and flashes the new row; list position is kept on other refreshes.
- Task input is a wide red-bordered pill.

## 1.0.1
- First command now starts the widget in the background (it used to block the terminal) and always
  prints a readable error + log tail if start-up fails; new `debug` command.
- `install.sh` no longer needs pip; shortcut helper no longer depends on PATH.
- Refuses shortcuts that would hijack normal keys (e.g. plain Ctrl+X).

## 1.0.0
- Pill redesign: smaller dot-matrix stopwatch, red border (colour/width configurable).
- Entrance animation drops from the top edge of the screen with a springy, notification-style bounce.
- Auto-hide after N idle seconds (default 10); never while hovering or typing.
- Hide/show is now deterministic: no dependence on window focus, key-repeat guard, idempotent
  `hide`, watchdog. Shortcut uses a D-Bus fast path (`nothing-tasks-ctl`) instead of starting Python.
- Dock/top-bar: no taskbar entry, startup notification always completed, `focus_on_show` switch.
- Settings window (Ctrl+, / gear / `nothing-tasks settings`): every feature is configurable, live.
- Delete tasks with undo; toast messages for vault errors instead of crashes.
- Production hardening: validated config, atomic writes + fsync, file locking, rolling backups,
  CRLF preservation, task-text sanitising, vault-escape protection, rotating log, SIGTERM handling,
  multi-monitor placement, `doctor` and `status` commands.
- MCP server (`nothing-tasks-mcp`): list/add/complete/delete tasks, control the stopwatch.
- Packaging: `.deb`, pip (`pyproject.toml`), CI workflow, tests (core, MCP, headless UI smoke).
