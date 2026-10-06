#!/usr/bin/env bash
# Builds dist/nothing-tasks_<version>_all.deb   (run from the project root)
set -euo pipefail
cd "$(dirname "$0")/.."
VER=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' nothing_tasks/__init__.py)
PKG=nothing-tasks; ROOT=$(mktemp -d); trap 'rm -rf "$ROOT"' EXIT
LIB="$ROOT/usr/lib/python3/dist-packages/nothing_tasks"

install -d "$LIB" "$ROOT/usr/bin" "$ROOT/usr/share/applications" "$ROOT/etc/xdg/autostart" \
           "$ROOT/usr/share/doc/$PKG" "$ROOT/DEBIAN"
install -m 644 nothing_tasks/*.py "$LIB/"
for entry in "nothing-tasks:nothing_tasks.cli" "nothing-tasks-mcp:nothing_tasks.mcp_server"; do
  name=${entry%%:*}; mod=${entry##*:}
  printf '#!/usr/bin/python3\nimport sys\nfrom %s import main\nsys.exit(main())\n' "$mod" > "$ROOT/usr/bin/$name"
  chmod 755 "$ROOT/usr/bin/$name"
done
install -m 755 bin/nothing-tasks-ctl "$ROOT/usr/bin/nothing-tasks-ctl"
install -m 644 packaging/nothing-tasks.desktop "$ROOT/usr/share/applications/"
install -m 644 packaging/nothing-tasks-autostart.desktop "$ROOT/etc/xdg/autostart/nothing-tasks.desktop"
install -m 644 README.md CHANGELOG.md LICENSE "$ROOT/usr/share/doc/$PKG/"

cat > "$ROOT/DEBIAN/control" << CTRL
Package: $PKG
Version: $VER
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, libglib2.0-bin
Suggests: python3-pip
Maintainer: Ashish <ashishaxm11@gmail.com>
Description: Dynamic-Island style stopwatch pill with Obsidian task notepad
 A dot-matrix stopwatch pill at the top of the screen that morphs into a task
 notepad. Tasks sync to an Obsidian note; an optional MCP server
 (pip install mcp) lets AI assistants manage them too.
CTRL
printf '#!/bin/sh\nset -e\npython3 -m compileall -q /usr/lib/python3/dist-packages/nothing_tasks >/dev/null 2>&1 || true\necho "Nothing Tasks installed. Run: nothing-tasks install-shortcut   (binds Super+T)"\n' > "$ROOT/DEBIAN/postinst"
printf '#!/bin/sh\nset -e\nrm -rf /usr/lib/python3/dist-packages/nothing_tasks/__pycache__\n' > "$ROOT/DEBIAN/prerm"
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm"

mkdir -p dist
dpkg-deb --build --root-owner-group "$ROOT" "dist/${PKG}_${VER}_all.deb" >/dev/null
echo "built dist/${PKG}_${VER}_all.deb"
