# halo_import

Small Halo CE Xbox cache-file inspection/conversion tools for Halo Arena.

## First milestone

`halo_import.py` reads an Xbox Halo CE `.map` file and lists its tag table.

It intentionally operates only on locally supplied game data. Halo assets are
not committed to this repository.

### Usage

```bash
python3 tools/halo_import/halo_import.py /path/to/bloodgulch.map
```

Useful filters:

```bash
python3 tools/halo_import/halo_import.py bloodgulch.map --find cyborg
python3 tools/halo_import/halo_import.py bloodgulch.map --class mode
python3 tools/halo_import/halo_import.py bloodgulch.map --class bipd
```

The cache pointer conversion used by the inspector follows the Xbox layout in
Halo CE Universal: tag data is loaded at virtual address `0x803A6000`, so a
cached pointer maps back into the file relative to the map header's
`tag_data_offset`.

## Next

Once tag enumeration is verified against a real Xbox multiplayer map:

1. locate `characters\\cyborg_mp\\cyborg_mp`
2. follow its model reference
3. parse the `mode` tag
4. dump nodes / regions / permutations / geometries
5. decode geometry buffers
6. export a neutral mesh representation, then MD3
