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
    raw = path.read_bytes()
    if len(raw) < CACHE_HEADER_SIZE:
        raise HaloMapError("file is smaller than the 0x800-byte Halo cache header")
    expected_size = struct.unpack_from("<i", raw, 0x08)[0]
    if expected_size <= 0:
        raise HaloMapError(f"invalid cache size {expected_size}")
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
            f"decompressed map is too short: got {len(image):,} bytes, expected {expected_size:,}"
        )
    return io.BytesIO(image[:expected_size]), True


def read_cache_header(fp: BinaryIO) -> CacheHeader:
    fp.seek(0)
    data = fp.read(CACHE_HEADER_SIZE)
    if len(data) != CACHE_HEADER_SIZE:
        raise HaloMapError("file is smaller than the 0x800-byte Halo cache header")
    if data[0:4] != HEADER_SIG:
        raise HaloMapError(f"bad header signature {data[0:4]!r}; expected {HEADER_SIG!r}")
    version = _i32(data, 0x04)
    file_length = _i32(data, 0x08)
    tag_data_offset = _i32(data, 0x10)
    tag_data_size = _i32(data, 0x14)
    name = _cstring(data[0x20:0x40])
    build = _cstring(data[0x40:0x60])
    scenario_type = struct.unpack_from("<h", data, 0x60)[0]
    checksum = _u32(data, 0x64)
    if data[0x7FC:0x800] != FOOTER_SIG:
        raise HaloMapError(f"bad footer signature {data[0x7FC:0x800]!r}; expected {FOOTER_SIG!r}")
    if version != CACHE_VERSION_XBOX:
        raise HaloMapError(f"cache version {version}; expected Xbox Halo CE version {CACHE_VERSION_XBOX}")
    return CacheHeader(version, file_length, tag_data_offset, tag_data_size, name, build, scenario_type, checksum)


def read_tag_header(fp: BinaryIO, cache: CacheHeader) -> TagHeader:
    fp.seek(cache.tag_data_offset)
    data = fp.read(TAG_HEADER_SIZE)
    if len(data) != TAG_HEADER_SIZE:
        raise HaloMapError("could not read cache tag header")
    values = struct.unpack("<9I", data)
    tag_header = TagHeader(values[0], values[1], values[2], values[3], values[4], values[5], values[6], values[7])
    if data[0x20:0x24] != TAG_HEADER_SIG:
        raise HaloMapError(f"bad tag-header signature {data[0x20:0x24]!r}; expected {TAG_HEADER_SIG!r}")
    ptr_to_file_offset(tag_header.tag_instances_ptr, cache)
    return tag_header


def read_cstring_at_pointer(fp: BinaryIO, cache: CacheHeader, ptr: int, max_len: int = 4096) -> str:
    if ptr == 0:
        return ""
    fp.seek(ptr_to_file_offset(ptr, cache))
    raw = bytearray()
    while len(raw) < max_len:
        b = fp.read(1)
        if not b or b == b"\0":
            break
        raw += b
    return raw.decode("latin-1", errors="replace")


def read_tags(fp: BinaryIO, cache: CacheHeader, tags: TagHeader) -> list[TagInstance]:
    table_offset = ptr_to_file_offset(tags.tag_instances_ptr, cache)
    fp.seek(table_offset)
    table = fp.read(tags.tag_count * TAG_INSTANCE_SIZE)
    result = []
    for i in range(tags.tag_count):
        row = table[i * TAG_INSTANCE_SIZE:(i + 1) * TAG_INSTANCE_SIZE]
        group_tag = _fourcc(row[0:4])
        parent1 = _fourcc(row[4:8])
        parent2 = _fourcc(row[8:12])
        tag_index = _u32(row, 0x0C)
        name_ptr = _u32(row, 0x10)
        base_address = _u32(row, 0x14)
        try:
            name = read_cstring_at_pointer(fp, cache, name_ptr)
        except HaloMapError:
            name = f"<bad-name-ptr:0x{name_ptr:08X}>"
        result.append(TagInstance(i, group_tag, parent1, parent2, tag_index, name_ptr, base_address, name))
    return result


def find_tag(tags: list[TagInstance], name: str, tag_class: Optional[str] = None) -> TagInstance:
    wanted = name.lower().replace("/", "\\")
    for tag in tags:
        if tag.name.lower() == wanted and (tag_class is None or tag.group_tag.lower() == tag_class.lower()):
            return tag
    raise HaloMapError(f"tag not found: {name}" + (f" ({tag_class})" if tag_class else ""))


def read_at_pointer(fp: BinaryIO, cache: CacheHeader, ptr: int, size: int) -> bytes:
    fp.seek(ptr_to_file_offset(ptr, cache))
    data = fp.read(size)
    if len(data) != size:
        raise HaloMapError(f"short read at cache pointer 0x{ptr:08X}: got {len(data)}, expected {size}")
    return data


def parse_tag_reference(data: bytes, offset: int = 0) -> tuple[str, int]:
    return _fourcc(data[offset:offset + 4]), _u32(data, offset + 12)


def parse_tag_block(data: bytes, offset: int) -> tuple[int, int]:
    return _i32(data, offset), _u32(data, offset + 4)


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
    return f"{group} 0x{datum:08X}  {tag.name if tag else '<unresolved>'}"


def _sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def unpack_halo_vector(packed: int) -> tuple[float, float, float]:
    xi = _sign_extend(packed & 0x7FF, 11)
    yj = _sign_extend((packed >> 11) & 0x7FF, 11)
    zk = _sign_extend((packed >> 22) & 0x3FF, 10)
    return (xi * 2.0 + 1.0) / 2047.0, (yj * 2.0 + 1.0) / 2047.0, (zk * 2.0 + 1.0) / 1023.0


def unpack_halo_texcoord(value: int) -> float:
    signed = value if value < 0x8000 else value - 0x10000
    return (signed * 2.0 + 1.0) / 65535.0


def read_d3d_resource(fp: BinaryIO, cache: CacheHeader, ptr: int) -> tuple[int, int, int]:
    return struct.unpack("<III", read_at_pointer(fp, cache, ptr, 12))


def vertex_resource_data_to_file_offset(data: int, cache: CacheHeader) -> int:
    return ptr_to_file_offset(data | 0x80000000, cache)


def index_resource_data_to_file_offset(data: int, cache: CacheHeader) -> int:
    return ptr_to_file_offset(data, cache)


def read_model_vertex(fp: BinaryIO, offset: int) -> dict:
    fp.seek(offset)
    raw = fp.read(0x20)
    x, y, z = struct.unpack_from("<3f", raw, 0x00)
    tu, tv = struct.unpack_from("<HH", raw, 0x18)
    return {
        "position": (x, y, z),
        "normal": unpack_halo_vector(_u32(raw, 0x0C)),
        "texcoord": (unpack_halo_texcoord(tu), unpack_halo_texcoord(tv)),
    }


def strip_to_triangles(indices: list[int], vertex_count: int) -> tuple[list[tuple[int, int, int]], int, int]:
    faces = []
    restart_count = 0
    out_of_range = 0
    strip = []

    def flush_strip() -> None:
        nonlocal out_of_range
        for i in range(len(strip) - 2):
            a, b, c = strip[i], strip[i + 1], strip[i + 2]
            if i & 1:
                a, b = b, a
            if a == b or b == c or a == c:
                continue
            if a >= vertex_count or b >= vertex_count or c >= vertex_count:
                out_of_range += 1
                continue
            faces.append((a, b, c))

    for index in indices:
        if index == 0xFFFF:
            restart_count += 1
            flush_strip()
            strip = []
        else:
            strip.append(index)
    flush_strip()
    return faces, restart_count, out_of_range


def export_model_obj(fp: BinaryIO, cache: CacheHeader, tags: list[TagInstance], biped_name: str, output: Path, geometry_index: int = 0) -> None:
    biped = find_tag(tags, biped_name, "bipd")
    objdef = read_at_pointer(fp, cache, biped.base_address, 0x48)
    _, model_index = parse_tag_reference(objdef, 0x28)
    model_tag = tag_by_datum(tags, model_index)
    model = read_at_pointer(fp, cache, model_tag.base_address, 0xE8)
    geometry_count, geometries_ptr = parse_tag_block(model, 0xD0)
    shader_count, shaders_ptr = parse_tag_block(model, 0xDC)

    shader_names = []
    shader_blob = read_at_pointer(fp, cache, shaders_ptr, shader_count * 0x20)
    for si in range(shader_count):
        _, datum = parse_tag_reference(shader_blob[si * 0x20:(si + 1) * 0x20], 0)
        shader_tag = tag_by_datum(tags, datum)
        shader_names.append(shader_tag.name.replace("\\", "_") if shader_tag else f"shader_{si}")

    geometries = read_at_pointer(fp, cache, geometries_ptr, geometry_count * 0x30)
    grow = geometries[geometry_index * 0x30:(geometry_index + 1) * 0x30]
    part_count, parts_ptr = parse_tag_block(grow, 0x24)
    parts = read_at_pointer(fp, cache, parts_ptr, part_count * 0x68)

    lines = ["# Halo Arena intermediate OBJ", f"# source biped: {biped.name}", f"# source model: {model_tag.name}", f"# geometry LOD block: {geometry_index}", ""]
    vertex_base = 1
    total_vertices = total_faces = 0

    for pi in range(part_count):
        prow = parts[pi * 0x68:(pi + 1) * 0x68]
        shader_index = struct.unpack_from("<h", prow, 0x04)[0]
        triangle_count = _i32(prow, 0x48)
        index_resource_ptr = _u32(prow, 0x50)
        vertex_count = _i32(prow, 0x58)
        vertex_offset = _i32(prow, 0x5C)
        vertex_resource_ptr = _u32(prow, 0x64)

        _, vb_data, _ = read_d3d_resource(fp, cache, vertex_resource_ptr)
        _, ib_data, _ = read_d3d_resource(fp, cache, index_resource_ptr)
        voff = vertex_resource_data_to_file_offset(vb_data, cache) + vertex_offset
        ioff = index_resource_data_to_file_offset(ib_data, cache)

        vertices = [read_model_vertex(fp, voff + vi * 0x20) for vi in range(vertex_count)]
        fp.seek(ioff)
        raw_indices = fp.read((triangle_count + 2) * 2)
        indices = list(struct.unpack("<" + "H" * (triangle_count + 2), raw_indices))
        faces, restart_count, out_of_range = strip_to_triangles(indices, vertex_count)

        print(f"export part[{pi}]: verts={vertex_count} strip_tris={triangle_count} indices={len(indices)} restarts={restart_count} out_of_range_windows={out_of_range} faces={len(faces)}")

        shader_name = shader_names[shader_index] if 0 <= shader_index < len(shader_names) else f"shader_{shader_index}"
        lines += [f"o geometry_{geometry_index}_part_{pi}", f"g {shader_name}", f"usemtl {shader_name}"]

        for v in vertices:
            x, y, z = v["position"]
            lines.append(f"v {x:.9g} {y:.9g} {z:.9g}")
        for v in vertices:
            u, vv = v["texcoord"]
            lines.append(f"vt {u:.9g} {1.0 - vv:.9g}")
        for v in vertices:
            nx, ny, nz = v["normal"]
            lines.append(f"vn {nx:.9g} {ny:.9g} {nz:.9g}")
        for a, b, c in faces:
            aa, bb, cc = vertex_base + a, vertex_base + b, vertex_base + c
            # Xbox/Halo strip winding is opposite OBJ/OpenGL's outward-facing winding.
            lines.append(f"f {aa}/{aa}/{aa} {cc}/{cc}/{cc} {bb}/{bb}/{bb}")

        vertex_base += vertex_count
        total_vertices += vertex_count
        total_faces += len(faces)
        lines.append("")

    output.write_text("\n".join(lines) + "\n")
    print(f"\nOBJ written:       {output}\ngeometry:          {geometry_index}\nparts:             {part_count}\nvertices:          {total_vertices}\nfaces:             {total_faces}")


def inspect_model_geometry(fp: BinaryIO, cache: CacheHeader, tags: list[TagInstance], model_tag: TagInstance) -> None:
    model = read_at_pointer(fp, cache, model_tag.base_address, 0xE8)
    geometry_count, geometries_ptr = parse_tag_block(model, 0xD0)
    shader_count, shaders_ptr = parse_tag_block(model, 0xDC)
    print("\ngeometry detail:")
    print(f"  geometry blocks: {geometry_count}\n  shader refs:     {shader_count}")
    shader_blob = read_at_pointer(fp, cache, shaders_ptr, shader_count * 0x20)
    for si in range(shader_count):
        group, datum = parse_tag_reference(shader_blob[si * 0x20:(si + 1) * 0x20], 0)
        print(f"  shader[{si}]:      {format_reference(tags, group, datum)}")
    geometries = read_at_pointer(fp, cache, geometries_ptr, geometry_count * 0x30)
    for gi in range(geometry_count):
        part_count, parts_ptr = parse_tag_block(geometries[gi * 0x30:(gi + 1) * 0x30], 0x24)
        print(f"\n  geometry[{gi}]: parts={part_count} addr=0x{parts_ptr:08X}")


def inspect_biped(fp: BinaryIO, cache: CacheHeader, tags: list[TagInstance], name: str) -> None:
    biped = find_tag(tags, name, "bipd")
    obj = read_at_pointer(fp, cache, biped.base_address, 0x48)
    model_group, model_index = parse_tag_reference(obj, 0x28)
    anim_group, anim_index = parse_tag_reference(obj, 0x38)
    print(f"biped:            0x{biped.tag_index:08X}  {biped.name}")
    print(f"model ref:        {format_reference(tags, model_group, model_index)}")
    print(f"animation ref:    {format_reference(tags, anim_group, anim_index)}")
    model_tag = tag_by_datum(tags, model_index)
    model = read_at_pointer(fp, cache, model_tag.base_address, 0xE8)
    print(f"model tag:        0x{model_tag.tag_index:08X}  {model_tag.name}")
    print(f"model data:       0x{model_tag.base_address:08X}")
    for label, offset in [("markers", 0xAC), ("nodes", 0xB8), ("regions", 0xC4), ("geometries", 0xD0), ("shaders", 0xDC)]:
        count, address = parse_tag_block(model, offset)
        print(f"{label + ':':17s}{count:5d}  addr=0x{address:08X}")
    inspect_model_geometry(fp, cache, tags, model_tag)


def print_header(path: Path, cache: CacheHeader, tags: TagHeader) -> None:
    print(f"file:             {path}\nmap name:         {cache.name}\nbuild:            {cache.build}\ncache version:    {cache.version}\nscenario type:    {cache.scenario_type}\nfile length:      0x{cache.file_length:08X} ({cache.file_length:,})\ntag data offset:  0x{cache.tag_data_offset:08X}\ntag data size:    0x{cache.tag_data_size:08X}\ntag cache base:   0x{TAG_CACHE_BASE:08X}\ntag count:        {tags.tag_count}\nscenario datum:   0x{tags.scenario_tag_index:08X}\nvertex buffers:   {tags.vertex_buffer_count}\nindex buffers:    {tags.index_buffer_count}\n")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Halo CE Xbox cache (.map) tag tables")
    parser.add_argument("map", type=Path)
    parser.add_argument("--class", dest="tag_class")
    parser.add_argument("--find")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--inspect-biped")
    parser.add_argument("--export-obj", type=Path)
    parser.add_argument("--geometry", type=int, default=0)
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
    print(f"source format:     {'Xbox zlib-compressed' if was_compressed else 'uncompressed cache'}\n")

    if args.inspect_biped:
        fp, _ = open_cache_image(args.map)
        with fp:
            inspect_biped(fp, cache, tags, args.inspect_biped)
        if args.export_obj:
            fp, _ = open_cache_image(args.map)
            with fp:
                export_model_obj(fp, cache, tags, args.inspect_biped, args.export_obj, args.geometry)
        return 0

    needle = args.find.lower() if args.find else None
    wanted_class = args.tag_class.lower() if args.tag_class else None
    shown = 0
    for tag in tags:
        if wanted_class and tag.group_tag.lower() != wanted_class:
            continue
        if needle and needle not in tag.name.lower():
            continue
        print(f"{tag.absolute_index:5d}  0x{tag.tag_index:08X}  {tag.group_tag:4s}  data=0x{tag.base_address:08X}  {tag.name}")
        shown += 1
        if args.limit and shown >= args.limit:
            break
    print(f"\n{shown} matching tag(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
