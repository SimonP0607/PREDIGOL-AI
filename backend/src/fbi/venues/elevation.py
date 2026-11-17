"""Altitude of a point from the Copernicus DEM GLO-90 (AD-H04, IA-076): one read per 1-degree tile, never a web service.

WHICH MODEL, AND WHY. The Copernicus WorldDEM-90 (GLO-90, release 2021) covers the world at 3 arc-seconds (about 90 m) and is
licensed "on a free basis for the general public": reproduction, distribution, communication to the public, adaptation and
combination with other data, on condition of the notice below (licence of the Copernicus contributing missions, read on
16-nov-2026). It is published as Cloud-Optimised GeoTIFFs in the open bucket ``copernicus-dem-90m`` (AWS Registry of Open
Data), one file per 1x1 degree, no account. Ocean has no tile. It is a SURFACE model: stands and roofs are in it, so a
stadium's value is its altitude to within about +-30 m, which is what matters here (500 m and 2,850 m are different matches;
35 m and 60 m are not).

HOW IT IS READ. Only what is needed: the header of the file (its first 64 KB) and the byte range of the internal tile that holds
the point (a GLO-90 file is one 2048x2048 tile, about 1-4 MB compressed), each by an HTTP range request; the tile is
decompressed (DEFLATE), the floating-point predictor undone (TIFF predictor 3) and the pixel under the point read. A tile is
read once for all the stadiums in it; its sha256 goes into the evidence of each value.
"""

from __future__ import annotations

import hashlib
import math
import struct
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

DEM: Final = "copernicus_glo90"
DEM_RELEASE: Final = "COP-DEM GLO-90 2021_1 (AWS copernicus-dem-90m)"
BASE_URL: Final = "https://copernicus-dem-90m.s3.amazonaws.com/"
NOTICE: Final = ("produced using Copernicus WorldDEM-90 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 "
                 "provided under COPERNICUS by the European Union and ESA; all rights reserved")
"""The notice the licence asks for when values derived from the model are communicated to the public (Article 6(b))."""
LICENSE: Final = "Copernicus WorldDEM-90 licence (free for the general public, attribution required)"
HEADER_BYTES: Final = 65_536
PLAUSIBLE: Final = (-450.0, 5000.0)
"""Altitudes a football ground can have: the shore of the Dead Sea to the highest grounds of the Andes (about 4,400 m)."""
NODATA: Final = -32767.0

RangeReader = Callable[[str, int, int], bytes | None]
"""(url, first byte, last byte inclusive) -> the bytes, or None when the file does not exist (an ocean tile)."""


class DemError(Exception):
    """A file that is not the GeoTIFF this reader understands (compression, sample type, predictor)."""


def tile_name(lat: float, lon: float) -> str:
    """The GLO-90 file that holds the point: ``Copernicus_DSM_COG_30_N45_00_E006_00_DEM`` for (45.3, 6.7)."""
    la, lo = math.floor(lat), math.floor(lon)
    ns = f"{'N' if la >= 0 else 'S'}{abs(la):02d}"
    ew = f"{'E' if lo >= 0 else 'W'}{abs(lo):03d}"
    return f"Copernicus_DSM_COG_30_{ns}_00_{ew}_00_DEM"


def tile_url(name: str) -> str:
    return f"{BASE_URL}{name}/{name}.tif"


_TYPE_SIZE: Final = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8, 16: 8}
_TYPE_FMT: Final = {1: "B", 3: "H", 4: "I", 11: "f", 12: "d", 16: "Q"}


@dataclass(frozen=True, slots=True)
class Raster:
    """The full-resolution image of a GeoTIFF: size, internal tiling, where it is on the Earth."""

    width: int
    height: int
    tile_width: int
    tile_height: int
    offsets: tuple[int, ...]
    counts: tuple[int, ...]
    lon0: float
    lat0: float
    dx: float
    dy: float
    pixel_is_point: bool
    little_endian: bool
    nodata: float | None


def parse_header(head: bytes, read_more: Callable[[int, int], bytes] | None = None) -> Raster:
    """The first image (full resolution) of a tiled, DEFLATE-compressed, float32 GeoTIFF with predictor 3. ``read_more`` fetches
    a range of the file when a tag's values lie beyond ``head``."""
    if head[:2] not in (b"II", b"MM"):
        raise DemError("not a TIFF file")
    e = "<" if head[:2] == b"II" else ">"
    if struct.unpack(e + "H", head[2:4])[0] != 42:
        raise DemError("BigTIFF or not a TIFF file")
    ifd = struct.unpack(e + "I", head[4:8])[0]

    def data_at(offset: int, size: int) -> bytes:
        if offset + size <= len(head):
            return head[offset:offset + size]
        if read_more is None:
            raise DemError("a tag lies beyond the header read")
        return read_more(offset, offset + size - 1)

    (n,) = struct.unpack(e + "H", data_at(ifd, 2))
    tags: dict[int, tuple[int, int, bytes]] = {}
    entries = data_at(ifd + 2, 12 * n)
    for i in range(n):
        tag, typ, cnt, raw = struct.unpack(e + "HHI4s", entries[12 * i:12 * i + 12])
        size = _TYPE_SIZE.get(typ, 1) * cnt
        payload = raw[:size] if size <= 4 else data_at(struct.unpack(e + "I", raw)[0], size)
        tags[tag] = (typ, cnt, payload)

    def values(tag: int) -> tuple[float, ...]:
        if tag not in tags:
            raise DemError(f"tag {tag} missing")
        typ, cnt, payload = tags[tag]
        if typ not in _TYPE_FMT:
            raise DemError(f"tag {tag} has type {typ}")
        return struct.unpack(e + f"{cnt}{_TYPE_FMT[typ]}", payload)

    def one(tag: int, default: int | None = None) -> int:
        if tag not in tags and default is not None:
            return default
        return int(values(tag)[0])

    if one(259) not in (8, 32946):
        raise DemError("compression is not DEFLATE")
    if one(258) != 32 or one(339, 1) != 3:
        raise DemError("samples are not float32")
    if one(317, 1) != 3:
        raise DemError("predictor is not the floating-point one")
    if one(277, 1) != 1 or 322 not in tags:
        raise DemError("not a single-band tiled image")
    scale = values(33550)
    tie = values(33922)
    pixel_is_point = False
    if 34735 in tags:
        keys = values(34735)
        for k in range(4, len(keys) - 3, 4):
            if int(keys[k]) == 1025 and int(keys[k + 1]) == 0:
                pixel_is_point = int(keys[k + 3]) == 2
    nodata: float | None = None
    if 42113 in tags:
        try:
            nodata = float(tags[42113][2].rstrip(b"\x00").decode())
        except ValueError:
            nodata = None
    return Raster(width=one(256), height=one(257), tile_width=one(322), tile_height=one(323),
                  offsets=tuple(int(v) for v in values(324)), counts=tuple(int(v) for v in values(325)),
                  lon0=float(tie[3]) - float(tie[0]) * float(scale[0]), lat0=float(tie[4]) + float(tie[1]) * float(scale[1]),
                  dx=float(scale[0]), dy=float(scale[1]), pixel_is_point=pixel_is_point, little_endian=e == "<",
                  nodata=nodata)


def pixel_of(r: Raster, lat: float, lon: float) -> tuple[int, int] | None:
    """(column, row) of the pixel under the point, or None when the point is outside the image."""
    fx, fy = (lon - r.lon0) / r.dx, (r.lat0 - lat) / r.dy
    x, y = (round(fx), round(fy)) if r.pixel_is_point else (math.floor(fx), math.floor(fy))
    if 0 <= x < r.width and 0 <= y < r.height:
        return x, y
    return None


def decode_row(tile: bytes, tile_width: int, row: int) -> list[float]:
    """One row of a decompressed tile with TIFF predictor 3: the row's bytes are differenced and stored as byte planes, most
    significant first; undo both and read big-endian float32 samples."""
    n = tile_width * 4
    raw = tile[row * n:(row + 1) * n]
    if len(raw) != n:
        raise DemError("tile shorter than its declared size")
    acc = bytearray(raw)
    for i in range(1, n):
        acc[i] = (acc[i] + acc[i - 1]) & 0xFF
    w = tile_width
    joined = bytes(acc[k * w + j] for j in range(w) for k in range(4))
    return list(struct.unpack(f">{w}f", joined))


@dataclass(frozen=True, slots=True)
class Altitude:
    meters: float | None
    """Rounded to 0.1 m; None when there is no tile (sea), no data or an implausible value."""
    tile: str
    tile_sha256: str | None
    pixel: tuple[int, int] | None
    status: str
    """``ok``, ``no_tile``, ``outside``, ``nodata`` or ``implausible``."""


class DemReader:
    """Reads altitudes through ``fetch`` (a range reader), caching each tile it decoded: group the points by tile
    (``tile_name``) to read each file once."""

    def __init__(self, fetch: RangeReader, *, keep: int = 4) -> None:
        self._fetch = fetch
        self._keep = keep
        self._cache: dict[str, tuple[Raster, bytes, str] | None] = {}
        self.tiles_read = 0
        self.bytes_read = 0

    def _tile(self, name: str, lat: float, lon: float) -> tuple[Raster, bytes, str] | None:
        if name in self._cache:
            return self._cache[name]
        url = tile_url(name)
        head = self._fetch(url, 0, HEADER_BYTES - 1)
        if head is None:
            self._remember(name, None)
            return None
        self.bytes_read += len(head)

        def more(a: int, b: int) -> bytes:
            got = self._fetch(url, a, b)
            if got is None:
                raise DemError("the file vanished while reading it")
            self.bytes_read += len(got)
            return got

        raster = parse_header(head, more)
        # A GLO-90 file is one internal tile and is kept; a file of several keeps nothing and is read again per point.
        px = pixel_of(raster, lat, lon)
        index = 0 if px is None else (px[1] // raster.tile_height) * math.ceil(raster.width / raster.tile_width) + (
            px[0] // raster.tile_width)
        start, count = raster.offsets[index], raster.counts[index]
        compressed = more(start, start + count - 1)
        self.tiles_read += 1
        entry = (raster, zlib.decompress(compressed), hashlib.sha256(compressed).hexdigest())
        if len(raster.offsets) == 1:
            self._remember(name, entry)
        return entry

    def _remember(self, name: str, entry: tuple[Raster, bytes, str] | None) -> None:
        if len(self._cache) >= self._keep:
            self._cache.pop(next(iter(self._cache)))
        self._cache[name] = entry

    def altitude(self, lat: float, lon: float) -> Altitude:
        name = tile_name(lat, lon)
        entry = self._tile(name, lat, lon)
        if entry is None:
            return Altitude(None, name, None, None, "no_tile")
        raster, tile, digest = entry
        px = pixel_of(raster, lat, lon)
        if px is None:
            return Altitude(None, name, digest, None, "outside")
        x, y = px
        value = decode_row(tile, raster.tile_width, y % raster.tile_height)[x % raster.tile_width]
        if math.isnan(value) or value <= NODATA + 1 or (raster.nodata is not None and value == raster.nodata):
            return Altitude(None, name, digest, px, "nodata")
        if not PLAUSIBLE[0] <= value <= PLAUSIBLE[1]:
            return Altitude(None, name, digest, px, "implausible")
        return Altitude(round(value, 1), name, digest, px, "ok")


def by_tile(points: Iterable[tuple[int, float, float]]) -> list[tuple[int, float, float]]:
    """The points (id, lat, lon) ordered by their tile, so a reader with a small cache reads each tile once."""
    return sorted(points, key=lambda p: (tile_name(p[1], p[2]), p[0]))


def http_range_reader(*, timeout: float = 120.0, user_agent: str = "predigol-venues/1") -> RangeReader:
    """A range reader over HTTPS (httpx): 404 or 403 (the bucket answers 403 for a key that does not exist) is None."""
    import httpx

    client = httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": user_agent})

    def read(url: str, first: int, last: int) -> bytes | None:
        response = client.get(url, headers={"Range": f"bytes={first}-{last}"})
        if response.status_code in (403, 404):
            return None
        response.raise_for_status()
        return response.content

    return read
