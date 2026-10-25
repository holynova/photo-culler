"""Perceptual-hash duplicate / burst grouping."""
from __future__ import annotations

import imagehash
import numpy as np
from PIL import Image

HAMMING_THRESHOLD = 10  # phash-64 distance at which images are grouped

_POPCNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint16)


def phash_hex(img_rgb: np.ndarray) -> str | None:
    try:
        return str(imagehash.phash(Image.fromarray(img_rgb), hash_size=8))
    except Exception:
        return None


def _hamming_matrix(hashes: np.ndarray) -> np.ndarray:
    """Pairwise popcount of XOR for uint64 hashes, chunked to bound memory."""
    n = len(hashes)
    dist = np.zeros((n, n), dtype=np.uint8)
    chunk = 2048
    for i in range(0, n, chunk):
        block = hashes[i:i + chunk, None] ^ hashes[None, :]
        xor_bytes = block.view(np.uint8).reshape(block.shape[0], -1, 8)
        dist[i:i + chunk] = _POPCNT[xor_bytes].sum(axis=2).astype(np.uint8)
    return dist


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def build_groups(hash_hexes: list[str], threshold: int = HAMMING_THRESHOLD):
    """Group indices of near-identical / burst photos.

    Returns list of groups; each group is a list of (index, distance_to_representative).
    """
    hashes = np.array([int(h, 16) for h in hash_hexes], dtype=np.uint64)
    n = len(hashes)
    if n < 2:
        return []
    dist = _hamming_matrix(hashes)
    uf = UnionFind(n)
    iu, ju = np.triu_indices(n, k=1)
    close = dist[iu, ju] <= threshold
    for i, j in zip(iu[close], ju[close]):
        uf.union(int(i), int(j))

    components: dict[int, list[int]] = {}
    for idx in range(n):
        components.setdefault(uf.find(idx), []).append(idx)

    groups = []
    for members in components.values():
        if len(members) < 2:
            continue
        rep = min(members)  # stable representative = first index
        groups.append([(m, int(dist[rep, m])) for m in sorted(members)])
    return groups
