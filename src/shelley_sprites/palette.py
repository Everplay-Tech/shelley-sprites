"""Palette extraction and enforcement for pixel art sprite consistency.

Ensures all generated sprites use the same color palette as reference sprites.
Uses nearest-neighbor color matching to snap generated pixels to the canonical palette.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from mcp.server.fastmcp import FastMCP


def extract_palette(image_path: str, max_colors: int = 16) -> list[list[int]]:
    """Extract the color palette from a sprite image.

    Returns a list of [R, G, B, A] colors sorted by frequency (most common first).
    Ignores fully transparent pixels.
    """
    from PIL import Image

    img = Image.open(image_path).convert("RGBA")
    pixels = list(img.getdata())

    # Count colors, skip fully transparent
    counts: dict[tuple[int, ...], int] = {}
    for px in pixels:
        if px[3] < 10:  # skip near-transparent
            continue
        counts[px] = counts.get(px, 0) + 1

    # Sort by frequency
    sorted_colors = sorted(counts.items(), key=lambda x: -x[1])

    # Take top N
    palette = [list(c) for c, _ in sorted_colors[:max_colors]]
    return palette


def _color_distance(c1: list[int], c2: list[int]) -> float:
    """Weighted Euclidean distance in RGBA space.

    Weights R/G/B more heavily than alpha for perceptual matching.
    """
    dr = (c1[0] - c2[0]) * 0.30
    dg = (c1[1] - c2[1]) * 0.59
    db = (c1[2] - c2[2]) * 0.11
    da = (c1[3] - c2[3]) * 0.10 if len(c1) > 3 and len(c2) > 3 else 0
    return math.sqrt(dr * dr + dg * dg + db * db + da * da)


def _nearest_palette_color(pixel: tuple, palette: list[list[int]]) -> tuple:
    """Find the nearest palette color to a given pixel."""
    px = list(pixel)
    best = palette[0]
    best_dist = _color_distance(px, best)

    for color in palette[1:]:
        d = _color_distance(px, color)
        if d < best_dist:
            best = color
            best_dist = d

    return tuple(best)


def remove_background(img, bg_threshold: int = 240):
    """Remove white/near-white background from a generated sprite.

    FLUX Kontext outputs white backgrounds instead of transparency.
    This converts near-white pixels to fully transparent.
    """
    from PIL import Image

    img = img.convert("RGBA")
    pixels = list(img.getdata())
    new_pixels = []

    for px in pixels:
        r, g, b, a = px
        # If pixel is near-white and opaque, make it transparent
        if r >= bg_threshold and g >= bg_threshold and b >= bg_threshold and a > 200:
            new_pixels.append((0, 0, 0, 0))
        else:
            new_pixels.append(px)

    result = Image.new("RGBA", img.size)
    result.putdata(new_pixels)
    return result


def enforce_palette(img, palette: list[list[int]], alpha_threshold: int = 10, strip_bg: bool = True):
    """Snap all pixels in an image to the nearest palette color.

    Fully transparent pixels stay transparent. Semi-transparent pixels
    get snapped to the nearest opaque palette color but keep their alpha.
    If strip_bg is True, removes white backgrounds before processing.
    """
    from PIL import Image

    if strip_bg:
        img = remove_background(img)

    img = img.convert("RGBA")
    pixels = list(img.getdata())
    new_pixels = []

    for px in pixels:
        if px[3] < alpha_threshold:
            # Keep transparent pixels transparent
            new_pixels.append((0, 0, 0, 0))
        else:
            nearest = _nearest_palette_color(px, palette)
            # Keep original alpha but use palette RGB
            if len(nearest) >= 4:
                new_pixels.append((nearest[0], nearest[1], nearest[2], px[3]))
            else:
                new_pixels.append((nearest[0], nearest[1], nearest[2], px[3]))

    result = Image.new("RGBA", img.size)
    result.putdata(new_pixels)
    return result


def palette_to_hex(palette: list[list[int]]) -> list[str]:
    """Convert RGBA palette to hex strings for display."""
    hexes = []
    for c in palette:
        if len(c) >= 3:
            hexes.append(f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}")
    return hexes


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP):
    """Register palette tools."""

    @mcp.tool()
    async def extract_sprite_palette(
        image_path: str,
        max_colors: int = 16,
    ) -> str:
        """Extract the color palette from a sprite image.

        Useful for analyzing existing sprites before generation.
        Returns colors sorted by frequency.

        Args:
            image_path: Path to a PNG sprite file
            max_colors: Maximum number of palette colors to extract
        """
        p = Path(image_path).expanduser()
        if not p.exists():
            return f"Error: file not found: {image_path}"

        colors = extract_palette(str(p), max_colors)
        hexes = palette_to_hex(colors)

        lines = [f"Palette from {p.name} ({len(colors)} colors):"]
        for i, (rgba, h) in enumerate(zip(colors, hexes)):
            lines.append(f"  {i + 1}. {h} — RGBA({rgba[0]}, {rgba[1]}, {rgba[2]}, {rgba[3]})")

        return "\n".join(lines)

    @mcp.tool()
    async def apply_palette_to_sprite(
        image_path: str,
        character: str,
        output_path: str = "",
    ) -> str:
        """Apply a character's registered palette to a sprite image.

        Snaps all pixel colors to the nearest color in the character's palette.
        Useful for cleaning up generated sprites that are slightly off-palette.

        Args:
            image_path: Path to the sprite to fix
            character: Character whose palette to use
            output_path: Where to save. If empty, overwrites the input.
        """
        from PIL import Image

        import shelley_sprites.generate as gen

        p = Path(image_path).expanduser()
        if not p.exists():
            return f"Error: file not found: {image_path}"

        config = gen._get_character_config(character)
        if not config.get("palette"):
            return f"Error: no palette registered for '{character}'. Call register_character first."

        img = Image.open(p)
        result = enforce_palette(img, config["palette"])

        out = Path(output_path).expanduser() if output_path else p
        result.save(out, "PNG")

        return f"Palette enforced on {p.name} using {character}'s {len(config['palette'])}-color palette.\nSaved to: {out}"

    @mcp.tool()
    async def compare_palettes(
        image_a: str,
        image_b: str,
    ) -> str:
        """Compare the color palettes of two sprite images.

        Shows which colors match, which are unique to each, and the overall
        similarity score. Useful for checking if a generated sprite matches
        the reference style.

        Args:
            image_a: Path to first sprite
            image_b: Path to second sprite
        """
        pa = Path(image_a).expanduser()
        pb = Path(image_b).expanduser()
        if not pa.exists():
            return f"Error: file not found: {image_a}"
        if not pb.exists():
            return f"Error: file not found: {image_b}"

        colors_a = extract_palette(str(pa), max_colors=16)
        colors_b = extract_palette(str(pb), max_colors=16)

        hex_a = set(palette_to_hex(colors_a))
        hex_b = set(palette_to_hex(colors_b))

        shared = hex_a & hex_b
        only_a = hex_a - hex_b
        only_b = hex_b - hex_a

        similarity = len(shared) / max(len(hex_a | hex_b), 1) * 100

        lines = [
            f"Palette Comparison:",
            f"  {pa.name}: {len(hex_a)} colors",
            f"  {pb.name}: {len(hex_b)} colors",
            f"  Shared: {len(shared)} colors ({similarity:.0f}% overlap)",
            f"",
            f"Shared colors: {', '.join(sorted(shared)) or 'none'}",
            f"Only in {pa.name}: {', '.join(sorted(only_a)) or 'none'}",
            f"Only in {pb.name}: {', '.join(sorted(only_b)) or 'none'}",
        ]

        return "\n".join(lines)
