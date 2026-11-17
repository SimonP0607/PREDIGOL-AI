"""IA-076 (AD-H04): the GLO-90 reader - tile names, the GeoTIFF header, predictor 3, the pixel under a point, plausibility."""

from __future__ import annotations

import struct
import zlib

import pytest

from fbi.venues.elevation import (
    DemError,
    DemReader,
    by_tile,
    decode_row,
    parse_header,
    pixel_of,
    tile_name,
    tile_url,
)


def _predictor3(rows: list[list[float]], width: int) -> bytes:
    out = bytearray()
    for row in rows:
        be = struct.pack(f">{width}f", *(row + [0.0] * (width - len(row))))
        planes = bytearray(be[j * 4 + k] for k in range(4) for j in range(width))
        diff = bytearray(planes)
        for i in range(len(diff) - 1, 0, -1):
            diff[i] = (planes[i] - planes[i - 1]) & 0xFF
        out += diff
    return bytes(out)


def make_tiff(values: list[list[float]], *, lon0: float, lat0: float, step: float, predictor: int = 3) -> bytes:
    h, w = len(values), len(values[0])
    tw = th = 16
    data = zlib.compress(_predictor3(values + [[0.0] * w] * (th - h), tw))
    entries: list[tuple[int, int, int, bytes]] = []
    extra = bytearray()
    base = 8

    def add(tag: int, typ: int, vals: tuple[float, ...]) -> None:
        fmt = {3: "H", 4: "I", 12: "d"}[typ]
        raw = struct.pack(f"<{len(vals)}{fmt}", *vals)
        entries.append((tag, typ, len(vals), raw))

    for tag, typ, vals in ((256, 3, (w,)), (257, 3, (h,)), (258, 3, (32,)), (259, 3, (8,)), (262, 3, (1,)),
                           (277, 3, (1,)), (317, 3, (predictor,)), (322, 3, (tw,)), (323, 3, (th,)), (324, 4, (0,)),
                           (325, 4, (len(data),)), (339, 3, (3,)), (33550, 12, (step, step, 0.0)),
                           (33922, 12, (0.0, 0.0, 0.0, lon0, lat0, 0.0))):
        add(tag, typ, vals)
    n = len(entries)
    ifd_size = 2 + 12 * n + 4
    extra_at = base + ifd_size
    body = bytearray()
    for tag, typ, cnt, raw in entries:
        if len(raw) <= 4:
            body += struct.pack("<HHI", tag, typ, cnt) + raw.ljust(4, b"\0")
        else:
            body += struct.pack("<HHII", tag, typ, cnt, extra_at + len(extra))
            extra += raw
    data_at = extra_at + len(extra)
    head = bytearray(b"II" + struct.pack("<HI", 42, base) + struct.pack("<H", n) + body + struct.pack("<I", 0) + extra)
    # patch the tile offset (tag 324) to where the data lands
    i = head.find(struct.pack("<HHI", 324, 4, 1))
    head[i + 8:i + 12] = struct.pack("<I", data_at)
    return bytes(head) + data


def reader_of(files: dict[str, bytes]) -> DemReader:
    def read(url: str, first: int, last: int) -> bytes | None:
        blob = files.get(url)
        return None if blob is None else blob[first:last + 1]
    return DemReader(read)


def test_tile_names_follow_the_bucket() -> None:
    assert tile_name(45.3, 6.7) == "Copernicus_DSM_COG_30_N45_00_E006_00_DEM"
    assert tile_name(-16.5, -68.12) == "Copernicus_DSM_COG_30_S17_00_W069_00_DEM"
    assert tile_name(0.5, -0.5) == "Copernicus_DSM_COG_30_N00_00_W001_00_DEM"
    assert tile_url("X").endswith("/X/X.tif")


def test_the_pixel_under_a_point_is_read_through_predictor_3() -> None:
    grid = [[float(100 * r + c) for c in range(10)] for r in range(10)]
    grid[3][4] = 3637.25
    blob = make_tiff(grid, lon0=-69.0, lat0=-16.0, step=0.1)
    raster = parse_header(blob)
    assert (raster.width, raster.height, raster.tile_width) == (10, 10, 16)
    assert pixel_of(raster, -16.35, -68.55) == (4, 3)
    assert pixel_of(raster, -10.0, -68.55) is None
    r = reader_of({tile_url(tile_name(-16.35, -68.55)): blob})
    alt = r.altitude(-16.35, -68.55)
    assert alt.status == "ok" and alt.meters in (3637.2, 3637.3)
    assert alt.tile_sha256 and alt.pixel == (4, 3)
    assert r.altitude(-16.05, -68.95).meters == 0.0
    assert r.tiles_read == 1  # the second point is in the tile already read


def test_sea_nodata_and_implausible_values_give_no_altitude() -> None:
    grid = [[-32767.0, 9000.0], [12.0, 12.0]]
    blob = make_tiff(grid, lon0=10.0, lat0=46.0, step=0.5)
    r = reader_of({tile_url(tile_name(45.9, 10.1)): blob})
    assert r.altitude(45.9, 10.1).status == "nodata"
    assert r.altitude(45.9, 10.6).status == "implausible"
    assert r.altitude(40.0, -30.0).status == "no_tile"


def test_a_file_this_reader_does_not_understand_is_refused() -> None:
    with pytest.raises(DemError):
        parse_header(make_tiff([[1.0]], lon0=0, lat0=1, step=1, predictor=2))
    with pytest.raises(DemError):
        parse_header(b"GIF89a" + b"\0" * 10)


def test_decode_row_and_order_by_tile() -> None:
    raw = _predictor3([[1.5, -2.0, 3.25]], 4)
    assert decode_row(raw, 4, 0)[:3] == [1.5, -2.0, 3.25]
    pts = by_tile([(1, 40.4, -3.7), (2, 51.5, -0.1), (3, 40.6, -3.2)])
    assert [p[0] for p in pts][0:2] in ([1, 3], [2, 1]) and {p[0] for p in pts} == {1, 2, 3}
