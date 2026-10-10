#!/usr/bin/env python3
from pathlib import Path

p = Path("tools/linux_build.py")
s = p.read_text(encoding="utf-8")

# Native Raspberry Pi OS armhf keeps the game's required 32-bit pointer ABI.
for old in (
    '    "--target=i686-linux-gnu",\n',
    '    "-m32",\n',
    '    "-malign-double",\n',
    '    "-freg-struct-return",\n',
):
    if old not in s:
        raise SystemExit(f"expected Linux ABI flag not found: {old!r}")
    s = s.replace(old, "")

old = 'return "-march=x86-64" if getattr(sln, "port_portable", False) else "-march=native"'
if old not in s:
    raise SystemExit("march_flag implementation changed upstream")
s = s.replace(old, 'return "-mcpu=cortex-a53"')

old = '["--target=i686-linux-gnu", "-m32", "-no-pie", "-g", *sysroot_ldflags,'
count = s.count(old)
if count != 2:
    raise SystemExit(f"expected two i686 linker flag sites, found {count}")
s = s.replace(old, '["-no-pie", "-g", *sysroot_ldflags,')

# VideoCore uses the renderer's existing GLES path.
needle = '    "-DHALO_LINUX_PLATFORM_LAYER",\n'
if needle not in s:
    raise SystemExit("platform define list changed upstream")
s = s.replace(needle, needle + '    "-DHALO_GLES=1",\n', 1)

# Game/XDK-facing units need the renderer selection too.
needle = '    "-fms-extensions",\n'
if needle not in s:
    raise SystemExit("ABI flag list changed upstream")
s = s.replace(needle, needle + '    "-DHALO_GLES=1",\n', 1)

p.write_text(s, encoding="utf-8")
