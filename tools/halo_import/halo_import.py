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
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional

CACHE_HEADER_SIZE = 0x800
TAG_CACHE_BASE = 0x803A6000
CACHE_VERSION_XBOX = 5

HEADER_SIG = b"head"
FOOTER_SIG = b"foot"
TAG_HEADER_SIG = b"tags"

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
    # Halo tag classes are stored as four bytes that read naturally in-file
    # on the little-endian Xbox cache.
    return raw.decode("latin-1", errors="replace")


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
    args = parser.parse_args(argv)

    try:
        with args.map.open("rb") as fp:
            cache = read_cache_header(fp)
            tags_header = read_tag_header(fp, cache)
            tags = read_tags(fp, cache, tags_header)
    except (OSError, HaloMapError) as exc:
        print(f"halo_import: {exc}", file=sys.stderr)
        return 1

    print_header(args.map, cache, tags_header)

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
