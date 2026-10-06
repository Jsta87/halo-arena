#!/usr/bin/env python3
"""Attach Halo CE model base textures to an OBJ exported by halo_import.py.

Texture extraction mirrors Halo CE Universal's cache/resource-map layouts.
For bitmap_data with the in-resource-map flag, bitmaps.map is resolved by
its own resource index using the '<tag>__pixels' entry, rather than treating
scenario-relative offsets as raw offsets into bitmaps.map.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import halo_import as hi

BITMAP_DATA_IN_RESOURCE_MAP_BIT = 1 << 8
BITMAP_FORMAT_DXT1 = 14
BITMAP_FORMAT_DXT3 = 15
BITMAP_FORMAT_DXT5 = 16


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "texture"


def dds_fourcc(fmt: int) -> bytes:
    return {BITMAP_FORMAT_DXT1: b"DXT1", BITMAP_FORMAT_DXT3: b"DXT3", BITMAP_FORMAT_DXT5: b"DXT5"}[fmt]


def dxt_top_size(width: int, height: int, fmt: int) -> int:
    block = 8 if fmt == BITMAP_FORMAT_DXT1 else 16
    return max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block


def write_dds(path: Path, width: int, height: int, fmt: int, payload: bytes) -> None:
    header = bytearray(124)
    struct.pack_into("<I", header, 0x00, 124)
    struct.pack_into("<I", header, 0x04, 0x00081007)
    struct.pack_into("<I", header, 0x08, height)
    struct.pack_into("<I", header, 0x0C, width)
    struct.pack_into("<I", header, 0x10, len(payload))
    struct.pack_into("<I", header, 0x18, 1)
    struct.pack_into("<I", header, 0x48, 32)
    struct.pack_into("<I", header, 0x4C, 0x00000004)
    header[0x50:0x54] = dds_fourcc(fmt)
    struct.pack_into("<I", header, 0x68, 0x00001000)
    path.write_bytes(b"DDS " + header + payload)


def read_cstring_at(fp, offset: int, limit: int = 1024) -> str:
    fp.seek(offset)
    raw = bytearray()
    while len(raw) < limit:
        b = fp.read(1)
        if not b or b == b"\0":
            break
        raw += b
    return raw.decode("latin-1", errors="replace")


def resource_map_items(path: Path) -> dict[str, tuple[int, int]]:
    """Return resource-map item name -> (data_offset, size)."""
    with path.open("rb") as fp:
        header = fp.read(16)
        if len(header) != 16:
            raise hi.HaloMapError(f"invalid resource map header: {path}")
        _map_type, names_offset, index_offset, count = struct.unpack("<iiii", header)
        if count < 0 or count > 100000:
            raise hi.HaloMapError(f"implausible resource-map item count {count}")
        fp.seek(index_offset)
        index = fp.read(count * 12)
        if len(index) != count * 12:
            raise hi.HaloMapError(f"short resource-map index: {path}")
        result = {}
        for i in range(count):
            name_rel, size, data_offset = struct.unpack_from("<iii", index, i * 12)
            name = read_cstring_at(fp, names_offset + name_rel)
            result[name.lower()] = (data_offset, size)
        return result


def read_bitmap_preview(scenario_fp, cache, bitmap_tag, bitmaps_map: Path, resource_items):
    group = hi.read_at_pointer(scenario_fp, cache, bitmap_tag.base_address, 0x6C)
    pixel_data_file_offset = hi._i32(group, 0x38)
    bitmap_count, bitmap_ptr = hi.parse_tag_block(group, 0x60)
    if bitmap_count <= 0 or not bitmap_ptr:
        raise hi.HaloMapError(f"bitmap tag has no bitmap_data entries: {bitmap_tag.name}")

    data = hi.read_at_pointer(scenario_fp, cache, bitmap_ptr, 0x30)
    width = struct.unpack_from("<h", data, 0x04)[0]
    height = struct.unpack_from("<h", data, 0x06)[0]
    fmt = struct.unpack_from("<h", data, 0x0C)[0]
    flags = struct.unpack_from("<H", data, 0x0E)[0]
    pixels_offset = hi._i32(data, 0x18)
    pixels_size = hi._i32(data, 0x1C)

    if fmt not in (BITMAP_FORMAT_DXT1, BITMAP_FORMAT_DXT3, BITMAP_FORMAT_DXT5):
        raise hi.HaloMapError(f"unsupported preview bitmap format {fmt}: {bitmap_tag.name}")
    if width <= 0 or height <= 0:
        raise hi.HaloMapError(f"invalid bitmap dimensions {width}x{height}: {bitmap_tag.name}")

    top_size = dxt_top_size(width, height, fmt)

    if flags & BITMAP_DATA_IN_RESOURCE_MAP_BIT:
        if not bitmaps_map.exists():
            raise hi.HaloMapError(f"{bitmap_tag.name} needs {bitmaps_map}")

        pixel_item_name = (bitmap_tag.name + "__pixels").lower()
        item = resource_items.get(pixel_item_name)
        if item:
            data_offset, item_size = item
            final_offset = data_offset
            source_note = f"resource item {bitmap_tag.name}__pixels"
        else:
            # Stock Xbox maps commonly store pixels_offset as an absolute
            # offset into bitmaps.map. Do not add the scenario tag_data
            # pixel_data.file_offset here; that was the old bug.
            final_offset = pixels_offset
            item_size = pixels_size
            source_note = "bitmap_data pixels_offset"

        with bitmaps_map.open("rb") as fp:
            fp.seek(final_offset)
            payload = fp.read(top_size)
        source = bitmaps_map.name
    else:
        final_offset = pixel_data_file_offset + pixels_offset
        scenario_fp.seek(final_offset)
        payload = scenario_fp.read(top_size)
        source = "scenario map"
        source_note = "group pixel_data + bitmap pixels_offset"

    if len(payload) != top_size:
        raise hi.HaloMapError(
            f"short bitmap read for {bitmap_tag.name}: got {len(payload)}, expected {top_size}"
        )

    print(
        f"texture: {bitmap_tag.name} {width}x{height} fmt={fmt} flags=0x{flags:04X} "
        f"source={source} offset=0x{final_offset:X} ({source_note}) bytes={top_size}"
    )
    return width, height, fmt, payload


def model_shader_base_bitmap(fp, cache, tags, shader_tag):
    if shader_tag.group_tag != "soso":
        return None
    shader = hi.read_at_pointer(fp, cache, shader_tag.base_address, 0xB4)
    _group, datum = hi.parse_tag_reference(shader, 0xA4)
    if datum == 0xFFFFFFFF:
        return None
    tag = hi.tag_by_datum(tags, datum)
    return tag if tag and tag.group_tag == "bitm" else None


def collect_model_shaders(fp, cache, tags, biped_name: str):
    biped = hi.find_tag(tags, biped_name, "bipd")
    obj = hi.read_at_pointer(fp, cache, biped.base_address, 0x48)
    _, model_datum = hi.parse_tag_reference(obj, 0x28)
    model_tag = hi.tag_by_datum(tags, model_datum)
    model = hi.read_at_pointer(fp, cache, model_tag.base_address, 0xE8)
    shader_count, shaders_ptr = hi.parse_tag_block(model, 0xDC)
    blob = hi.read_at_pointer(fp, cache, shaders_ptr, shader_count * 0x20)
    out = []
    for i in range(shader_count):
        _, datum = hi.parse_tag_reference(blob[i * 0x20:(i + 1) * 0x20], 0)
        tag = hi.tag_by_datum(tags, datum)
        if tag:
            out.append(tag)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Attach Halo CE base textures to an exported OBJ")
    parser.add_argument("map", type=Path)
    parser.add_argument("obj", type=Path)
    parser.add_argument("--biped", default=r"characters\cyborg_mp\cyborg_mp")
    parser.add_argument("--bitmaps-map", type=Path)
    args = parser.parse_args()

    bitmaps_map = args.bitmaps_map or args.map.with_name("bitmaps.map")
    resource_items = resource_map_items(bitmaps_map) if bitmaps_map.exists() else {}
    out_dir = args.obj.parent
    mtl_path = args.obj.with_suffix(".mtl")

    try:
        fp, _ = hi.open_cache_image(args.map)
        with fp:
            cache = hi.read_cache_header(fp)
            tags_header = hi.read_tag_header(fp, cache)
            tags = hi.read_tags(fp, cache, tags_header)
            shaders = collect_model_shaders(fp, cache, tags, args.biped)
            materials = []

            for shader in shaders:
                material_name = shader.name.replace("\\", "_")
                texture_file = None
                bitmap = model_shader_base_bitmap(fp, cache, tags, shader)
                if bitmap:
                    try:
                        width, height, fmt, payload = read_bitmap_preview(
                            fp, cache, bitmap, bitmaps_map, resource_items
                        )
                        texture_file = safe_name(material_name) + ".dds"
                        write_dds(out_dir / texture_file, width, height, fmt, payload)
                        print(f"wrote:   {out_dir / texture_file}")
                    except hi.HaloMapError as exc:
                        print(f"warning: could not export {shader.name}: {exc}")
                materials.append((material_name, shader.group_tag, texture_file))

        mtl_lines = ["# Halo Arena preview materials", ""]
        for name, group, texture_file in materials:
            mtl_lines.append(f"newmtl {name}")
            if "visor" in name.lower():
                mtl_lines += ["Kd 0.85 0.55 0.12", "Ks 0.8 0.8 0.8", "Ns 96"]
            elif group == "schi":
                mtl_lines += ["Kd 0.15 0.55 1.0", "d 0.35"]
            else:
                mtl_lines.append("Kd 1.0 1.0 1.0")
            if texture_file:
                mtl_lines.append(f"map_Kd {texture_file}")
            mtl_lines.append("")

        mtl_path.write_text("\n".join(mtl_lines) + "\n")
        lines = [line for line in args.obj.read_text().splitlines() if not line.startswith("mtllib ")]
        insert_at = 0
        while insert_at < len(lines) and lines[insert_at].startswith("#"):
            insert_at += 1
        lines.insert(insert_at, f"mtllib {mtl_path.name}")
        args.obj.write_text("\n".join(lines) + "\n")
        print(f"wrote:   {mtl_path}")
        print(f"updated: {args.obj}")
        return 0
    except (OSError, hi.HaloMapError, KeyError) as exc:
        print(f"texture_obj: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
