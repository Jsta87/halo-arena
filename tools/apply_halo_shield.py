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

replace_once(
    root / "code/game/bg_public.h",
    "STAT_MAX_HEALTH\t\t\t\t// health / armor limit, changable by handicap\n} statIndex_t;",
    "STAT_MAX_HEALTH,\t\t\t\t// health / armor limit, changable by handicap\n\tSTAT_SHIELD\t\t\t\t\t// Halo Arena rechargeable energy shield\n} statIndex_t;",
    "add STAT_SHIELD"
)

replace_once(
    root / "code/game/g_local.h",
    "\tint\t\t\ttimeResidual;\n",
    "\tint\t\t\ttimeResidual;\n\n"
    "\t// Halo Arena prototype shield state\n"
    "\tfloat\t\thaloShield;\n"
    "\tint\t\t\thaloShieldLastDamageTime;\n",
    "add gclient shield fields"
)

p = root / "code/game/g_client.c"
data = p.read_text()
if "Halo_ShieldReset( ent );" not in data:
    anchor = "\tclient->ps.stats[STAT_MAX_HEALTH] = client->pers.maxHealth;\n"
    if anchor not in data:
        raise SystemExit("[fail] ClientSpawn anchor not found")
    p.write_text(data.replace(anchor, anchor + "\n\tHalo_ShieldReset( ent );\n", 1))
    print("[ok] reset shield in ClientSpawn")

p = root / "code/game/g_combat.c"
data = p.read_text()
if "Halo_ShieldAbsorbDamage( targ, take, dflags )" not in data:
    anchor = "\ttake = damage;\n\tsave = 0;\n"
    repl = (
        "\ttake = damage;\n"
        "\tsave = 0;\n\n"
        "\t// Halo Arena: energy shield absorbs damage before health.\n"
        "\tif ( client ) {\n"
        "\t\ttake = Halo_ShieldAbsorbDamage( targ, take, dflags );\n"
        "\t}\n"
    )
    if anchor not in data:
        raise SystemExit("[fail] G_Damage anchor not found")
    p.write_text(data.replace(anchor, repl, 1))
    print("[ok] hook shield into G_Damage")

p = root / "code/game/g_active.c"
data = p.read_text()
if "Halo_ShieldThink( ent );" not in data:
    anchor = "void ClientEndFrame( gentity_t *ent ) {\n"
    if anchor not in data:
        raise SystemExit("[fail] ClientEndFrame anchor not found")
    p.write_text(data.replace(anchor, anchor + "\tHalo_ShieldThink( ent );\n\n", 1))
    print("[ok] hook shield recharge into ClientEndFrame")

print("\nShield prototype applied. Add code/game/g_halo_shield.c to the game source list if needed.")
