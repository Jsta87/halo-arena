# Halo CE asset importer plan

Halo Arena will not commit Halo CE game assets.

## Initial input

During development, the importer should first consume the extracted Halo CE Xbox map directory produced from the user's own disc/ISO:

```text
maps/
  bitmaps.map
  sounds.map
  ui.map
  bloodgulch.map
  ...
```

This avoids coupling the first converter directly to XISO parsing.

## First target

The first asset milestone is the multiplayer Spartan:

1. locate the relevant biped/model tags
2. decode geometry
3. decode material and bitmap references
4. decode animation references
5. dump a neutral intermediate representation
6. convert verified data into Quake-friendly runtime assets

## Intermediate representation

Prefer a neutral debug-friendly format before MD3:

```text
halo_import_out/
  manifest.json
  meshes/
    spartan.mesh.json
  textures/
  animations/
```

This lets us validate vertices, indices, UVs, materials, nodes, and animation transforms independently before committing to an MD3 exporter.

## Repository rule

No extracted Halo CE assets, map data, textures, sounds, or models should be committed to Git.
