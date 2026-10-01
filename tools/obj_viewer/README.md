# Halo Arena OBJ Viewer

Tiny debugging viewer for OBJ files emitted by `tools/halo_import/halo_import.py`.

## Build

```bash
cmake -S tools/obj_viewer -B build/obj_viewer
cmake --build build/obj_viewer -j$(nproc)
```

Requires raylib development files to be installed.

## Run

```bash
./build/obj_viewer/halo_obj_viewer /tmp/cyborg.obj
```

Controls:

- Left mouse drag: orbit
- Mouse wheel: zoom
- Middle mouse drag: pan
- R or F: frame/reset model
- W: toggle wireframe
- Esc: quit
