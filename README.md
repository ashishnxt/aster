# Nothing Tasks

A Dynamic-Island style pill for Ubuntu 22.04 (GNOME): a dot-matrix stopwatch at the top-centre of
your screen with a red outline. Press **Space** and it morphs into a task notepad whose tasks live
in an **Obsidian** note. An optional **MCP server** lets AI assistants manage the same tasks.

## Install
**.deb (recommended)**

    sudo apt install ./nothing-tasks_1.0.0_all.deb
    nothing-tasks settings                  # opens the pill with the settings page: pick your Obsidian vault
    nothing-tasks doctor                    # checks everything

**From source (no pip needed)**

    sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0     # usually already there
    python3 run.py toggle            # try it without installing anything
    ./install.sh                     # optional: commands in ~/.local/bin + autostart
    ./uninstall.sh                   # to remove

The first command starts the widget in the background and returns; later commands reach it instantly.
Something not working? `nothing-tasks doctor` (or `python3 run.py doctor`), then `nothing-tasks debug`.
MCP needs `pip install mcp` (or `sudo apt install python3-pip` first).

## Use
| Where | Key | Action |
|---|---|---|
| anywhere | **Ctrl+X** (default) | open / close the pill |
| pill | click | open the notepad (default: the pill has no keyboard focus) |
| pill | `Space` / `Enter` / `Esc` | notepad / start-pause / hide - only with *Keyboard focus on show* ON |
| notepad | type + `Enter` | add task (written to Obsidian immediately) |
| notepad | `Esc` / click away | fold back into the pill |
| notepad | `Ctrl+,` or ⚙ | settings page inside the pill (`Esc` / BACK returns) |

Rows: `○ ●` done · `▶` time this task (elapsed time is written back as `⏱ 00:42:10`) · `×` delete (with UNDO).
Edits made in Obsidian appear live. The pill hides itself after 10 idle seconds (never while your mouse is
over it or you are typing).

## The shortcut
The widget registers **Ctrl+X** with GNOME itself (open if hidden, close if visible) and repairs it when needed;
change it any time in the settings page. Heads-up: a global Ctrl+X means **Cut stops working in other apps**.
`<Super>t` or `<Ctrl><Alt>n` avoid that. If the widget is not running, the shortcut starts it.

## Commands
`nothing-tasks [toggle|show|hide|expand|collapse|focus|settings|start|quit|status|doctor|install-shortcut|remove-shortcut|autostart on|off]`
Shortcuts use `nothing-tasks-ctl`, a tiny script that talks to the running widget over D-Bus in ~10 ms.

## Settings (all live, saved to `~/.config/nothing-tasks/config.json`)
Vault folder · note name · accent colour · **border colour/width** · pill size · distance from top ·
seconds strip · monitor (pointer/primary) · animations on/off + speed · **auto-hide seconds** ·
auto-hide while timer runs · fold when clicking away · **focus_on_show** · start at login ·
keyboard shortcut · log level · reset to defaults.

## MCP server (Claude and other assistants)
    pip install mcp
    claude mcp add nothing-tasks -- nothing-tasks-mcp
Tools: `list_tasks add_task complete_task delete_task start_timer pause_timer reset_timer timer_status`.
The widget and the server share file locks and the timer state, so they can run at the same time.

## Robustness
Atomic fsync'd writes · file locking · rolling backups (`~/.local/state/nothing-tasks/backups`, last 10) ·
CRLF preserved · config validated and clamped (a corrupt file is kept as `.corrupt`) · vault errors show as
a message in the notepad instead of crashing · task text sanitised · note path cannot leave the vault ·
rotating log `~/.local/state/nothing-tasks/app.log` · clean exit on SIGTERM · timer survives reboots.

## Troubleshooting
* **Dock / top bar pops up when the pill shows** - by default the pill no longer takes keyboard focus when it
  appears (some auto-hide docks react when focus moves). Click the pill to open the notepad. Turn
  *Keyboard focus on show* ON in Settings if you prefer Space/Enter/Esc to work on the bare pill.
* **Pill is not exactly at the top edge** - on Wayland it runs through XWayland to position itself
  (`NT_NATIVE_WAYLAND=1` disables that). GNOME may keep windows below the top bar; adjust *Distance from top edge*.
* Nothing happens: `nothing-tasks quit`, then `nothing-tasks debug` shows errors live; `doctor` prints the recent log
  (`~/.local/state/nothing-tasks/app.log` and `startup.log`).

## Development
    pip install pytest ruff mcp && xvfb-run -a pytest      # core, MCP and headless UI smoke tests
    bash packaging/build_deb.sh                            # dist/*.deb
Python 3.10+ (target: Ubuntu 22.04). The test suite was run on Python 3.12 in a virtual display.
