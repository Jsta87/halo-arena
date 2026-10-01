# Halo Arena

Experimental deathmatch game that combines Halo CE-style gameplay and locally imported Halo CE assets with ioquake3 as the engine chassis.

## Current milestone

**Milestone 1: rechargeable Halo-style shields**

Development is happening on `milestone-1-shields`.

## Repository model

Halo Arena does **not** store or redistribute Halo CE game data. The eventual importer will consume data extracted locally from a user's own Halo CE Xbox disc/ISO.

ioq3 is treated as the upstream engine. Halo-specific changes are kept isolated where practical.

## Local bootstrap

Clone this repository, then import ioquake3 into your working tree:

```bash
git clone git@github.com:Jsta87/halo-arena.git
cd halo-arena
git checkout milestone-1-shields

./tools/bootstrap_ioq3.sh
```

Then apply the Halo shield overlay:

```bash
python3 tools/apply_halo_shield.py .
```

Inspect before committing locally:

```bash
git diff
```

## Immediate roadmap

1. Halo-style shield/health loop
2. Minimal shield HUD
3. Halo CE asset importer
4. Multiplayer Spartan model in a Quake III map
5. Halo pistol / assault rifle / grenades / melee
6. Expand toward a full Halo Arena deathmatch ruleset
