#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
overlay = root / "overlay" / "code" / "game"

required = [
    root / "code/game/bg_public.h",
    root / "code/game/g_local.h",
    root / "code/game/g_combat.c",
    root / "code/game/g_client.c",
    root / "code/game/g_active.c",
    root / "cmake/basegame.cmake",
]

missing = [str(p) for p in required if not p.exists()]
if missing:
    raise SystemExit("Missing ioquake3 files:\n  " + "\n  ".join(missing))

for name in ("g_halo_shield.c", "g_halo_shield.h"):
    src = overlay / name
    dst = root / "code/game" / name
    shutil.copyfile(src, dst)
    print(f"[ok] copied {dst.relative_to(root)}")

def replace_once(path, old, new, label):
    data = path.read_text()
    if new in data:
        print(f"[skip] {label}")
        return
    if old not in data:
        raise SystemExit(f"[fail] {label}: anchor not found in {path}")
    path.write_text(data.replace(old, new, 1))
    print(f"[ok] {label}")

def ensure_include(path, include_line):
    data = path.read_text()
    if include_line in data:
        print(f"[skip] include {include_line} in {path.name}")
        return
    anchor = '#include "g_local.h"\n'
    if anchor not in data:
        raise SystemExit(f"[fail] include anchor not found in {path}")
    path.write_text(data.replace(anchor, anchor + include_line + "\n", 1))
    print(f"[ok] add {include_line} to {path.name}")

# Shared stat
p = root / "code/game/bg_public.h"
data = p.read_text()
if "STAT_SHIELD" not in data:
    old = "\tSTAT_MAX_HEALTH\t\t\t\t\t// health / armor limit, changeable by handicap\n} statIndex_t;"
    new = "\tSTAT_MAX_HEALTH,\t\t\t\t// health / armor limit, changeable by handicap\n\tSTAT_SHIELD\t\t\t\t\t// Halo Arena rechargeable energy shield\n} statIndex_t;"
    if old not in data:
        raise SystemExit("[fail] add STAT_SHIELD: anchor not found")
    p.write_text(data.replace(old, new, 1))
    print("[ok] add STAT_SHIELD")
else:
    print("[skip] STAT_SHIELD already present")

# Private server-side state
replace_once(
    root / "code/game/g_local.h",
    "\tint\t\t\ttimeResidual;\n",
    "\tint\t\t\ttimeResidual;\n\n"
    "\t// Halo Arena prototype shield state\n"
    "\tfloat\t\thaloShield;\n"
    "\tint\t\t\thaloShieldLastDamageTime;\n",
    "add gclient shield fields"
)

for name in ("g_active.c", "g_client.c", "g_combat.c"):
    ensure_include(root / "code/game" / name, '#include "g_halo_shield.h"')

# Spawn reset
p = root / "code/game/g_client.c"
data = p.read_text()
if "Halo_ShieldReset( ent );" not in data:
    anchor = "\tclient->ps.stats[STAT_MAX_HEALTH] = client->pers.maxHealth;\n"
    if anchor not in data:
        raise SystemExit("[fail] ClientSpawn anchor not found")
    p.write_text(data.replace(anchor, anchor + "\n\tHalo_ShieldReset( ent );\n", 1))
    print("[ok] reset shield in ClientSpawn")
else:
    print("[skip] ClientSpawn shield reset already present")

# Damage hook
p = root / "code/game/g_combat.c"
data = p.read_text()
if "Halo_ShieldAbsorbDamage( targ, take, dflags )" not in data:
    anchor = "\ttake = damage;\n\n\t// save some from armor\n"
    repl = (
        "\ttake = damage;\n\n"
        "\t// Halo Arena: energy shield absorbs damage first.\n"
        "\tif ( client ) {\n"
        "\t\ttake = Halo_ShieldAbsorbDamage( targ, take, dflags );\n"
        "\t}\n\n"
        "\t// save some from armor\n"
    )
    if anchor not in data:
        raise SystemExit("[fail] G_Damage anchor not found")
    p.write_text(data.replace(anchor, repl, 1))
    print("[ok] hook shield into G_Damage")
else:
    print("[skip] G_Damage shield hook already present")

# Recharge hook
p = root / "code/game/g_active.c"
data = p.read_text()
if "Halo_ShieldThink( ent );" not in data:
    anchor = "void ClientEndFrame( gentity_t *ent ) {\n"
    if anchor not in data:
        raise SystemExit("[fail] ClientEndFrame anchor not found")
    p.write_text(data.replace(anchor, anchor + "\tHalo_ShieldThink( ent );\n\n", 1))
    print("[ok] hook shield recharge into ClientEndFrame")
else:
    print("[skip] ClientEndFrame shield hook already present")

# CMake source registration
p = root / "cmake/basegame.cmake"
data = p.read_text()
entry = "    ${SOURCE_DIR}/game/g_halo_shield.c\n"
if "g_halo_shield.c" not in data:
    anchor = "    ${SOURCE_DIR}/game/g_combat.c\n"
    if anchor not in data:
        raise SystemExit("[fail] CMake game source anchor not found")
    p.write_text(data.replace(anchor, anchor + entry, 1))
    print("[ok] add g_halo_shield.c to GAME_SOURCES")
else:
    print("[skip] g_halo_shield.c already in GAME_SOURCES")

print("\nHalo shield prototype applied.")
