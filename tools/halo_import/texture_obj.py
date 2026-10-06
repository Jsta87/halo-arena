#!/usr/bin/env python3
"""Attach Halo CE model base textures to an OBJ exported by halo_import.py.

This intentionally mirrors the layouts used by Halo CE Universal:
- soso base-map tag reference at 0xA4
- bitmap_group pixel-data tag_data at 0x30
- bitmap_group bitmaps tag_block at 0x60
- bitmap_data size 0x30
- DXT1/3/5 bitmap formats 14/15/16

For the first preview pass we export the top mip of DXT model base maps as
DDS and generate an MTL file that the existing OBJ already references by
material name.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

# Import the cache/tag parser next to this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import halo_import as hi

BITMAP_DATA_IN_RESOURCE_MAP_BIT = 1 << 8
BITMAP_FORMAT_DXT1 = 14
BITMAP_FORMAT_DXT3 = 15
BITMAP_FORMAT_DXT5 = 16


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "texture"


def dds_fourcc(fmt: int) -> bytes:
    if fmt == BITMAP_FORMAT_DXT1:
        return b"DXT1"
    if fmt == BITMAP_FORMAT_DXT3:
        return b"DXT3"
    if fmt == BITMAP_FORMAT_DXT5:
        return b"DXT5"
    raise hi.HaloMapError(f"unsupported preview bitmap format {fmt}; expected DXT1/3/5")


def dxt_top_size(width: int, height: int, fmt: int) -> int:
    block = 8 if fmt == BITMAP_FORMAT_DXT1 else 16
    return max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block


def write_dds(path: Path, width: int, height: int, fmt: int, payload: bytes) -> None:
    fourcc = dds_fourcc(fmt)
    linear_size = len(payload)

    # DDS_HEADER (124 bytes) + magic. We only export mip 0 for previewing.
    header = bytearray(124)
    struct.pack_into("<I", header, 0x00, 124)       # dwSize
    struct.pack_into("<I", header, 0x04, 0x00081007)  # CAPS|HEIGHT|WIDTH|PIXELFORMAT|LINEARSIZE
    struct.pack_into("<I", header, 0x08, height)
    struct.pack_into("<I", header, 0x0C, width)
    struct.pack_into("<I", header, 0x10, linear_size)
    struct.pack_into("<I", header, 0x18, 1)         # depth (ignored for 2D)

    # DDS_PIXELFORMAT at header offset 0x48.
    struct.pack_into("<I", header, 0x48, 32)
    struct.pack_into("<I", header, 0x4C, 0x00000004)  # DDPF_FOURCC
    header[0x50:0x54] = fourcc

    # DDSCAPS_TEXTURE
    struct.pack_into("<I", header, 0x68, 0x00001000)

    path.write_bytes(b"DDS " + header + payload)


def read_bitmap_preview(
    scenario_fp,
    cache: hi.CacheHeader,
    tags: list[hi.TagInstance],
    bitmap_tag: hi.TagInstance,
    bitmaps_map: Path,
) -> tuple[int, int, int, bytes]:
    # bitmap_group: pixel_data tag_data begins at 0x30; file_offset is +8.
    # bitmaps tag_block begins at 0x60.
    group = hi.read_at_pointer(scenario_fp, cache, bitmap_tag.base_address, 0x6C)
    pixel_data_file_offset = hi._i32(group, 0x38)
    bitmap_count, bitmap_ptr = hi.parse_tag_block(group, 0x60)

    if bitmap_count <= 0 or not bitmap_ptr:
        raise hi.HaloMapError(f"bitmap tag has no bitmap_data entries: {bitmap_tag.name}")

    # Model base maps use the first bitmap for this preview path.
    data = hi.read_at_pointer(scenario_fp, cache, bitmap_ptr, 0x30)
    width = struct.unpack_from("<h", data, 0x04)[0]
    height = struct.unpack_from("<h", data, 0x06)[0]
    fmt = struct.unpack_from("<h", data, 0x0C)[0]
    flags = struct.unpack_from("<H", data, 0x0E)[0]
    pixels_offset = hi._i32(data, 0x18)
    pixels_size = hi._i32(data, 0x1C)

    if width <= 0 or height <= 0:
        raise hi.HaloMapError(f"invalid bitmap dimensions {width}x{height}: {bitmap_tag.name}")

    top_size = dxt_top_size(width, height, fmt)
    final_offset = pixel_data_file_offset + pixels_offset

    if flags & BITMAP_DATA_IN_RESOURCE_MAP_BIT:
        if not bitmaps_map.exists():
            raise hi.HaloMapError(
                f"{bitmap_tag.name} is stored in bitmaps.map, but {bitmaps_map} does not exist"
            )
        with bitmaps_map.open("rb") as resource:
            resource.seek(final_offset)
            payload = resource.read(top_size)
        source = bitmaps_map.name
    else:
        scenario_fp.seek(final_offset)
        payload = scenario_fp.read(top_size)
        source = "scenario map"

    if len(payload) != top_size:
        raise hi.HaloMapError(
            f"short bitmap read for {bitmap_tag.name}: got {len(payload)}, expected {top_size} "
            f"at 0x{final_offset:X} from {source} (pixels_size={pixels_size})"
        )

    print(
        f"texture: {bitmap_tag.name}  {width}x{height} fmt={fmt} flags=0x{flags:04X} "
        f"source={source} offset=0x{final_offset:X} bytes={top_size}"
    )
    return width, height, fmt, payload


def model_shader_base_bitmap(
    fp,
    cache: hi.CacheHeader,
    tags: list[hi.TagInstance],
    shader_tag: hi.TagInstance,
) -> hi.TagInstance | None:
    if shader_tag.group_tag != "soso":
        return None

    # Halo CE Universal / custom_edition_bitmaps.c verifies that base_map.index
    # is at 0xB0, therefore the tag_reference itself begins at 0xA4.
    shader = hi.read_at_pointer(fp, cache, shader_tag.base_address, 0xB4)
    group, datum = hi.parse_tag_reference(shader, 0xA4)
    if datum == 0xFFFFFFFF:
        return None

    tag = hi.tag_by_datum(tags, datum)
    if not tag or tag.group_tag != "bitm":
        print(f"warning: {shader_tag.name} base map is {group} 0x{datum:08X}, not a bitm")
        return None
    return tag


def collect_model_shaders(fp, cache, tags, biped_name: str):
    biped = hi.find_tag(tags, biped_name, "bipd")
    obj = hi.read_at_pointer(fp, cache, biped.base_address, 0x48)
    _, model_datum = hi.parse_tag_reference(obj, 0x28)
    model_tag = hi.tag_by_datum(tags, model_datum)
    if not model_tag or model_tag.group_tag != "mode":
        raise hi.HaloMapError("could not resolve biped model")

    model = hi.read_at_pointer(fp, cache, model_tag.base_address, 0xE8)
    shader_count, shaders_ptr = hi.parse_tag_block(model, 0xDC)
    blob = hi.read_at_pointer(fp, cache, shaders_ptr, shader_count * 0x20)

    out = []
    for i in range(shader_count):
        row = blob[i * 0x20:(i + 1) * 0x20]
        _, datum = hi.parse_tag_reference(row, 0)
        tag = hi.tag_by_datum(tags, datum)
        if tag:
            out.append(tag)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Attach Halo CE base textures to an exported OBJ")
    parser.add_argument("map", type=Path, help="scenario .map used for the OBJ")
    parser.add_argument("obj", type=Path, help="OBJ produced by halo_import.py")
    parser.add_argument(
        "--biped",
        default=r"characters\cyborg_mp\cyborg_mp",
        help="biped tag path (default: multiplayer cyborg)",
    )
    parser.add_argument(
        "--bitmaps-map",
        type=Path,
        help="shared bitmaps.map; defaults to a bitmaps.map next to the scenario map",
    )
    args = parser.parse_args()

    if not args.obj.exists():
        print(f"texture_obj: OBJ does not exist: {args.obj}", file=sys.stderr)
        return 1

    bitmaps_map = args.bitmaps_map or args.map.with_name("bitmaps.map")
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
                            fp, cache, tags, bitmap, bitmaps_map
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
                mtl_lines.append("Kd 0.85 0.55 0.12")
                mtl_lines.append("Ks 0.8 0.8 0.8")
                mtl_lines.append("Ns 96")
            elif group == "schi":
                mtl_lines.append("Kd 0.15 0.55 1.0")
                mtl_lines.append("d 0.35")
            else:
                mtl_lines.append("Kd 1.0 1.0 1.0")
            if texture_file:
                mtl_lines.append(f"map_Kd {texture_file}")
            mtl_lines.append("")

        mtl_path.write_text("\n".join(mtl_lines) + "\n")

        obj_text = args.obj.read_text()
        mtllib_line = f"mtllib {mtl_path.name}"
        lines = obj_text.splitlines()
        lines = [line for line in lines if not line.startswith("mtllib ")]
        insert_at = 0
        while insert_at < len(lines) and lines[insert_at].startswith("#"):
            insert_at += 1
        lines.insert(insert_at, mtllib_line)
        args.obj.write_text("\n".join(lines) + "\n")

        print(f"wrote:   {mtl_path}")
        print(f"updated: {args.obj}")
        return 0

    except (OSError, hi.HaloMapError) as exc:
        print(f"texture_obj: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
