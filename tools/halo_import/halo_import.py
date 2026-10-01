#!/usr/bin/env python3
"""
Halo Arena - Halo CE Xbox cache (.map) inspector

Milestone 1:
  * Validate Halo CE Xbox cache header
  * Parse the cache tag header
  * Translate Xbox tag-cache virtual pointers
  * Enumerate tag class, datum index, name, and data address

The cache layout is based on structures in halo-ce-universal:
  source/cache/cache_files.c
  source/cache/physical_memory_map.c

No Halo game data is distributed by this tool.
"""

from __future__ import annotations

import argparse
import struct
import sys
import io
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional

CACHE_HEADER_SIZE = 0x800
TAG_CACHE_BASE = 0x803A6000
CACHE_VERSION_XBOX = 5

HEADER_SIG = b"daeh"
FOOTER_SIG = b"toof"
TAG_HEADER_SIG = b"sgat"

TAG_HEADER_SIZE = 0x24
TAG_INSTANCE_SIZE = 0x20


class HaloMapError(RuntimeError):
    pass


@dataclass
class CacheHeader:
    version: int
    file_length: int
    tag_data_offset: int
    tag_data_size: int
    name: str
    build: str
    scenario_type: int
    checksum: int


@dataclass
class TagHeader:
    tag_instances_ptr: int
    scenario_tag_index: int
    checksum: int
    tag_count: int
    vertex_buffer_count: int
    vertex_buffers_ptr: int
    index_buffer_count: int
    index_buffers_ptr: int


@dataclass
class TagInstance:
    absolute_index: int
    group_tag: str
    parent_group_1: str
    parent_group_2: str
    tag_index: int
    name_ptr: int
    base_address: int
    name: str

    @property
    def datum_index(self) -> int:
        return self.tag_index & 0xFFFF

    @property
    def salt(self) -> int:
        return (self.tag_index >> 16) & 0xFFFF


def _cstring(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("latin-1", errors="replace")


def _fourcc(raw: bytes) -> str:
    # Halo tag classes are 32-bit multi-character constants. On the
    # little-endian Xbox cache they appear byte-reversed on disk:
    # 'mode' -> b'edom', 'bipd' -> b'dpib', etc.
    return raw[::-1].decode("latin-1", errors="replace")


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _i32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def ptr_to_file_offset(ptr: int, header: CacheHeader) -> int:
    if ptr == 0:
        return 0
    rel = ptr - TAG_CACHE_BASE
    if rel < 0 or rel >= header.tag_data_size:
        raise HaloMapError(
            f"pointer 0x{ptr:08X} is outside tag cache "
            f"0x{TAG_CACHE_BASE:08X}..0x{TAG_CACHE_BASE + header.tag_data_size:08X}"
        )
    return header.tag_data_offset + rel


def open_cache_image(path: Path) -> tuple[BinaryIO, bool]:
    """
    Return a seekable decompressed cache image.

    Xbox disc maps keep the 0x800-byte cache header uncompressed and store
    bytes after it as a zlib stream. The header offsets refer to the
    decompressed image, not the physical compressed file.
    """
    raw = path.read_bytes()
    if len(raw) < CACHE_HEADER_SIZE:
        raise HaloMapError("file is smaller than the 0x800-byte Halo cache header")

    # Read the expected decompressed size directly from the raw header.
    expected_size = struct.unpack_from("<i", raw, 0x08)[0]

    if expected_size <= 0:
        raise HaloMapError(f"invalid cache size {expected_size}")

    # A cached/decompressed map already has its declared size on disk.
    if len(raw) >= expected_size:
        return io.BytesIO(raw[:expected_size]), False

    try:
        payload = zlib.decompress(raw[CACHE_HEADER_SIZE:])
    except zlib.error as exc:
        raise HaloMapError(
            f"map appears compressed ({len(raw):,} bytes on disk, "
            f"{expected_size:,} bytes declared) but zlib decompression failed: {exc}"
        ) from exc

    image = raw[:CACHE_HEADER_SIZE] + payload
    if len(image) < expected_size:
        raise HaloMapError(
            f"decompressed map is too short: got {len(image):,} bytes, "
            f"expected {expected_size:,}"
        )

    return io.BytesIO(image[:expected_size]), True


def read_cache_header(fp: BinaryIO) -> CacheHeader:
    fp.seek(0)
    data = fp.read(CACHE_HEADER_SIZE)
    if len(data) != CACHE_HEADER_SIZE:
        raise HaloMapError("file is smaller than the 0x800-byte Halo cache header")

    if data[0:4] != HEADER_SIG:
        raise HaloMapError(
            f"bad header signature {data[0:4]!r}; expected {HEADER_SIG!r}"
        )

    # cache_files.c:
    # 0x00 signature
    # 0x04 version
    # 0x08 file length
    # 0x10 tag data offset
    # 0x14 tag data size
    # 0x20 name[0x20]
    # 0x40 build[0x20]
    # 0x60 scenario type (short)
    # 0x64 checksum
    # 0x7FC footer signature
    version = _i32(data, 0x04)
    file_length = _i32(data, 0x08)
    tag_data_offset = _i32(data, 0x10)
    tag_data_size = _i32(data, 0x14)
    name = _cstring(data[0x20:0x40])
    build = _cstring(data[0x40:0x60])
    scenario_type = struct.unpack_from("<h", data, 0x60)[0]
    checksum = _u32(data, 0x64)

    if data[0x7FC:0x800] != FOOTER_SIG:
        raise HaloMapError(
            f"bad footer signature {data[0x7FC:0x800]!r}; expected {FOOTER_SIG!r}"
        )
    if version != CACHE_VERSION_XBOX:
        raise HaloMapError(
            f"cache version {version}; expected Xbox Halo CE version {CACHE_VERSION_XBOX}"
        )
    if tag_data_offset < CACHE_HEADER_SIZE:
        raise HaloMapError(f"invalid tag data offset 0x{tag_data_offset:X}")
    if tag_data_size <= 0:
        raise HaloMapError(f"invalid tag data size 0x{tag_data_size:X}")

    return CacheHeader(
        version=version,
        file_length=file_length,
        tag_data_offset=tag_data_offset,
        tag_data_size=tag_data_size,
        name=name,
        build=build,
        scenario_type=scenario_type,
        checksum=checksum,
    )


def read_tag_header(fp: BinaryIO, cache: CacheHeader) -> TagHeader:
    fp.seek(cache.tag_data_offset)
    data = fp.read(TAG_HEADER_SIZE)
    if len(data) != TAG_HEADER_SIZE:
        raise HaloMapError("could not read cache tag header")

    # cache_file_tag_header is nine 32-bit values on Xbox.
    values = struct.unpack("<9I", data)

    tag_header = TagHeader(
        tag_instances_ptr=values[0],
        scenario_tag_index=values[1],
        checksum=values[2],
        tag_count=values[3],
        vertex_buffer_count=values[4],
        vertex_buffers_ptr=values[5],
        index_buffer_count=values[6],
        index_buffers_ptr=values[7],
    )

    signature = data[0x20:0x24]
    if signature != TAG_HEADER_SIG:
        raise HaloMapError(
            f"bad tag-header signature {signature!r}; expected {TAG_HEADER_SIG!r}"
        )

    if tag_header.tag_count <= 0 or tag_header.tag_count > 65535:
        raise HaloMapError(f"implausible tag count {tag_header.tag_count}")

    ptr_to_file_offset(tag_header.tag_instances_ptr, cache)
    return tag_header


def read_cstring_at_pointer(
    fp: BinaryIO, cache: CacheHeader, ptr: int, max_len: int = 4096
) -> str:
    if ptr == 0:
        return ""
    offset = ptr_to_file_offset(ptr, cache)
    fp.seek(offset)
    raw = bytearray()
    while len(raw) < max_len:
        b = fp.read(1)
        if not b:
            break
        if b == b"\0":
            break
        raw += b
    return raw.decode("latin-1", errors="replace")


def read_tags(
    fp: BinaryIO, cache: CacheHeader, tags: TagHeader
) -> list[TagInstance]:
    table_offset = ptr_to_file_offset(tags.tag_instances_ptr, cache)
    fp.seek(table_offset)
    table = fp.read(tags.tag_count * TAG_INSTANCE_SIZE)

    expected = tags.tag_count * TAG_INSTANCE_SIZE
    if len(table) != expected:
        raise HaloMapError(
            f"short tag table: got {len(table)} bytes, expected {expected}"
        )

    result: list[TagInstance] = []

    for i in range(tags.tag_count):
        off = i * TAG_INSTANCE_SIZE
        row = table[off : off + TAG_INSTANCE_SIZE]

        group_tag = _fourcc(row[0x00:0x04])
        parent1 = _fourcc(row[0x04:0x08])
        parent2 = _fourcc(row[0x08:0x0C])
        tag_index = _u32(row, 0x0C)
        name_ptr = _u32(row, 0x10)
        base_address = _u32(row, 0x14)

        try:
            name = read_cstring_at_pointer(fp, cache, name_ptr)
        except HaloMapError:
            name = f"<bad-name-ptr:0x{name_ptr:08X}>"

        result.append(
            TagInstance(
                absolute_index=i,
                group_tag=group_tag,
                parent_group_1=parent1,
                parent_group_2=parent2,
                tag_index=tag_index,
                name_ptr=name_ptr,
                base_address=base_address,
                name=name,
            )
        )

    return result



def find_tag(tags: list[TagInstance], name: str, tag_class: Optional[str] = None) -> TagInstance:
    wanted = name.lower().replace("/", "\\")
    for tag in tags:
        if tag.name.lower() == wanted and (tag_class is None or tag.group_tag.lower() == tag_class.lower()):
            return tag
    raise HaloMapError(
        f"tag not found: {name}" + (f" ({tag_class})" if tag_class else "")
    )


def read_at_pointer(fp: BinaryIO, cache: CacheHeader, ptr: int, size: int) -> bytes:
    off = ptr_to_file_offset(ptr, cache)
    fp.seek(off)
    data = fp.read(size)
    if len(data) != size:
        raise HaloMapError(
            f"short read at cache pointer 0x{ptr:08X}: got {len(data)}, expected {size}"
        )
    return data


def parse_tag_reference(data: bytes, offset: int = 0) -> tuple[str, int]:
    if offset < 0 or offset + 16 > len(data):
        raise HaloMapError("tag reference lies outside supplied data")
    group = _fourcc(data[offset : offset + 4])
    index = _u32(data, offset + 12)
    return group, index


def parse_tag_block(data: bytes, offset: int) -> tuple[int, int]:
    if offset < 0 or offset + 12 > len(data):
        raise HaloMapError("tag block lies outside supplied data")
    count = _i32(data, offset)
    address = _u32(data, offset + 4)
    return count, address


def tag_by_datum(tags: list[TagInstance], datum: int) -> Optional[TagInstance]:
    absolute = datum & 0xFFFF
    if 0 <= absolute < len(tags):
        candidate = tags[absolute]
        if candidate.tag_index == datum or (candidate.tag_index & 0xFFFF) == absolute:
            return candidate
    return None


def format_reference(tags: list[TagInstance], group: str, datum: int) -> str:
    if datum == 0xFFFFFFFF:
        return f"{group} NONE"
    tag = tag_by_datum(tags, datum)
    if tag:
        return f"{group} 0x{datum:08X}  {tag.name}"
    return f"{group} 0x{datum:08X}  <unresolved>"



def inspect_model_geometry(
    fp: BinaryIO,
    cache: CacheHeader,
    tags: list[TagInstance],
    model_tag: TagInstance,
) -> None:
    model = read_at_pointer(fp, cache, model_tag.base_address, 0xE8)
    geometry_count, geometries_ptr = parse_tag_block(model, 0xD0)
    shader_count, shaders_ptr = parse_tag_block(model, 0xDC)

    print()
    print("geometry detail:")
    print(f"  geometry blocks: {geometry_count}")
    print(f"  shader refs:     {shader_count}")

    # model_shader_reference is 0x20 bytes; tag_reference begins at +0.
    if shader_count > 0 and shaders_ptr:
        shader_blob = read_at_pointer(fp, cache, shaders_ptr, shader_count * 0x20)
        for si in range(shader_count):
            row = shader_blob[si * 0x20 : (si + 1) * 0x20]
            group, datum = parse_tag_reference(row, 0)
            perm = struct.unpack_from("<h", row, 0x10)[0]
            print(
                f"  shader[{si}]:      {format_reference(tags, group, datum)} "
                f"perm={perm}"
            )

    if geometry_count <= 0 or not geometries_ptr:
        return

    # struct model_geometry = reserved[0x24] + tag_block parts = 0x30.
    geometries = read_at_pointer(fp, cache, geometries_ptr, geometry_count * 0x30)

    for gi in range(geometry_count):
        grow = geometries[gi * 0x30 : (gi + 1) * 0x30]
        part_count, parts_ptr = parse_tag_block(grow, 0x24)
        print()
        print(f"  geometry[{gi}]: parts={part_count} addr=0x{parts_ptr:08X}")

        if part_count <= 0 or not parts_ptr:
            continue

        # models.c verifies sizeof(model_geometry_part) == 0x68.
        parts = read_at_pointer(fp, cache, parts_ptr, part_count * 0x68)

        for pi in range(part_count):
            prow = parts[pi * 0x68 : (pi + 1) * 0x68]

            flags = _u32(prow, 0x00)
            shader_index = struct.unpack_from("<h", prow, 0x04)[0]

            uv_count, uv_ptr = parse_tag_block(prow, 0x20)
            cv_count, cv_ptr = parse_tag_block(prow, 0x2C)
            tri_count, tri_ptr = parse_tag_block(prow, 0x38)

            # triangle_buffer @ 0x44, sizeof 0x10
            tb_type = struct.unpack_from("<h", prow, 0x44)[0]
            tb_count = _i32(prow, 0x48)
            tb_base = _u32(prow, 0x4C)
            tb_hw = _u32(prow, 0x50)

            # vertex_buffer @ 0x54, sizeof 0x14
            vb_type = struct.unpack_from("<h", prow, 0x54)[0]
            vb_count = _i32(prow, 0x58)
            vb_offset = _i32(prow, 0x5C)
            vb_base = _u32(prow, 0x60)
            vb_hw = _u32(prow, 0x64)

            print(
                f"    part[{pi}]: shader={shader_index} flags=0x{flags:08X} "
                f"uverts={uv_count} cverts={cv_count} tris={tri_count}"
            )
            print(
                f"             compressed=0x{cv_ptr:08X} "
                f"triangles=0x{tri_ptr:08X}"
            )
            print(
                f"             VB type={vb_type} count={vb_count} "
                f"offset={vb_offset} base=0x{vb_base:08X} hw=0x{vb_hw:08X}"
            )
            print(
                f"             IB type={tb_type} count={tb_count} "
                f"base=0x{tb_base:08X} hw=0x{tb_hw:08X}"
            )


def inspect_biped(
    fp: BinaryIO,
    cache: CacheHeader,
    tags: list[TagInstance],
    name: str,
) -> None:
    biped = find_tag(tags, name, "bipd")

    # _object_definition begins the biped definition.
    # model is at offset 0x28; animation_graph follows at 0x38.
    obj = read_at_pointer(fp, cache, biped.base_address, 0x48)
    model_group, model_index = parse_tag_reference(obj, 0x28)
    anim_group, anim_index = parse_tag_reference(obj, 0x38)

    print(f"biped:            0x{biped.tag_index:08X}  {biped.name}")
    print(f"model ref:        {format_reference(tags, model_group, model_index)}")
    print(f"animation ref:    {format_reference(tags, anim_group, anim_index)}")

    model_tag = tag_by_datum(tags, model_index)
    if not model_tag:
        raise HaloMapError(f"could not resolve model datum 0x{model_index:08X}")
    if model_tag.group_tag != "mode":
        raise HaloMapError(
            f"biped model points to {model_tag.group_tag}, expected mode"
        )

    # struct model is 0xE8 bytes. Its five trailing tag_block fields start:
    # markers 0xAC, nodes 0xB8, regions 0xC4, geometries 0xD0, shaders 0xDC.
    model = read_at_pointer(fp, cache, model_tag.base_address, 0xE8)

    blocks = [
        ("markers", 0xAC),
        ("nodes", 0xB8),
        ("regions", 0xC4),
        ("geometries", 0xD0),
        ("shaders", 0xDC),
    ]

    print(f"model tag:        0x{model_tag.tag_index:08X}  {model_tag.name}")
    print(f"model data:       0x{model_tag.base_address:08X}")

    for label, offset in blocks:
        count, address = parse_tag_block(model, offset)
        translated = "-"
        if count > 0 and address:
            try:
                translated = f"file+0x{ptr_to_file_offset(address, cache):08X}"
            except HaloMapError:
                translated = "<outside tag cache>"
        print(
            f"{label + ':':17s}{count:5d}  "
            f"addr=0x{address:08X}  {translated}"
        )

    inspect_model_geometry(fp, cache, tags, model_tag)


def print_header(path: Path, cache: CacheHeader, tags: TagHeader) -> None:
    print(f"file:             {path}")
    print(f"map name:         {cache.name}")
    print(f"build:            {cache.build}")
    print(f"cache version:    {cache.version}")
    print(f"scenario type:    {cache.scenario_type}")
    print(f"file length:      0x{cache.file_length:08X} ({cache.file_length:,})")
    print(f"tag data offset:  0x{cache.tag_data_offset:08X}")
    print(f"tag data size:    0x{cache.tag_data_size:08X}")
    print(f"tag cache base:   0x{TAG_CACHE_BASE:08X}")
    print(f"tag count:        {tags.tag_count}")
    print(f"scenario datum:   0x{tags.scenario_tag_index:08X}")
    print(f"vertex buffers:   {tags.vertex_buffer_count}")
    print(f"index buffers:    {tags.index_buffer_count}")
    print()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect Halo CE Xbox cache (.map) tag tables"
    )
    parser.add_argument("map", type=Path, help="Halo CE Xbox .map file")
    parser.add_argument(
        "--class",
        dest="tag_class",
        help="only show one tag class, e.g. mode, bipd, antr",
    )
    parser.add_argument(
        "--find",
        metavar="TEXT",
        help="case-insensitive substring filter on tag names",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="maximum number of matching tags to print (0 = all)",
    )
    parser.add_argument(
        "--inspect-biped",
        metavar="TAG_NAME",
        help="follow a biped's model/animation references and summarize its model blocks",
    )
    args = parser.parse_args(argv)

    try:
        fp, was_compressed = open_cache_image(args.map)
        with fp:
            cache = read_cache_header(fp)
            tags_header = read_tag_header(fp, cache)
            tags = read_tags(fp, cache, tags_header)
    except (OSError, HaloMapError) as exc:
        print(f"halo_import: {exc}", file=sys.stderr)
        return 1

    print_header(args.map, cache, tags_header)
    print(f"source format:     {'Xbox zlib-compressed' if was_compressed else 'uncompressed cache'}")
    print()

    if args.inspect_biped:
        try:
            fp, _ = open_cache_image(args.map)
            with fp:
                inspect_biped(fp, cache, tags, args.inspect_biped)
        except HaloMapError as exc:
            print(f"halo_import: {exc}", file=sys.stderr)
            return 1
        return 0

    needle = args.find.lower() if args.find else None
    wanted_class = args.tag_class.lower() if args.tag_class else None

    shown = 0
    for tag in tags:
        if wanted_class and tag.group_tag.lower() != wanted_class:
            continue
        if needle and needle not in tag.name.lower():
            continue

        print(
            f"{tag.absolute_index:5d}  "
            f"0x{tag.tag_index:08X}  "
            f"{tag.group_tag:4s}  "
            f"data=0x{tag.base_address:08X}  "
            f"{tag.name}"
        )
        shown += 1
        if args.limit and shown >= args.limit:
            break

    print(f"\n{shown} matching tag(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
