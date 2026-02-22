"""Sprite sheet assembly tools — combine frames into sheets for Godot import.

Takes individual animation frames and packs them into horizontal/grid
sprite sheets that Godot's SpriteFrames or AnimatedSprite2D can consume.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP):
    """Register sprite sheet tools."""

    @mcp.tool()
    async def assemble_sprite_sheet(
        character: str,
        animation: str,
        columns: int = 0,
        padding: int = 0,
        output_path: str = "",
    ) -> str:
        """Assemble individual frames into a sprite sheet PNG.

        Reads all frame_*.png files from a character's animation directory
        and packs them into a single horizontal or grid sprite sheet.

        Args:
            character: Character name
            animation: Animation name (e.g., "run", "idle")
            columns: Frames per row. 0 = single horizontal row (all in one line).
            padding: Pixels between frames (default 0, no padding).
            output_path: Where to save the sheet. If empty, saves next to the frames.
        """
        from PIL import Image

        import shelley_sprites.generate as gen

        char_dir = gen._get_character_dir(character)
        anim_dir = char_dir / "animations" / animation

        if not anim_dir.exists():
            return f"Error: no animation '{animation}' found for '{character}'."

        frames = sorted(anim_dir.glob("frame_*.png"))
        if not frames:
            return f"Error: no frames found in {anim_dir}"

        # Load all frames
        images = [Image.open(f).convert("RGBA") for f in frames]
        w, h = images[0].size

        # Calculate grid
        n = len(images)
        cols = columns if columns > 0 else n
        rows = (n + cols - 1) // cols

        sheet_w = cols * w + (cols - 1) * padding
        sheet_h = rows * h + (rows - 1) * padding

        sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))

        for i, img in enumerate(images):
            col = i % cols
            row = i // cols
            x = col * (w + padding)
            y = row * (h + padding)
            sheet.paste(img, (x, y))

        # Save
        if output_path:
            out = Path(output_path).expanduser()
        else:
            out = anim_dir / f"{animation}_sheet.png"

        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out, "PNG")

        return (
            f"Sprite sheet assembled: {out}\n"
            f"Frames: {n} ({cols}x{rows} grid)\n"
            f"Frame size: {w}x{h}\n"
            f"Sheet size: {sheet_w}x{sheet_h}\n"
            f"Padding: {padding}px"
        )

    @mcp.tool()
    async def split_sprite_sheet(
        sheet_path: str,
        frame_width: int,
        frame_height: int,
        character: str = "",
        animation: str = "",
        output_dir: str = "",
    ) -> str:
        """Split a sprite sheet into individual frame PNGs.

        Useful for importing existing sprite sheets and breaking them into
        individual frames for editing or re-assembly.

        Args:
            sheet_path: Path to the sprite sheet PNG
            frame_width: Width of each frame in pixels
            frame_height: Height of each frame in pixels
            character: If set, saves frames into the character's animation dir.
            animation: Animation name (required if character is set).
            output_dir: Where to save frames. Used if character is not set.
        """
        from PIL import Image

        import shelley_sprites.generate as gen

        p = Path(sheet_path).expanduser()
        if not p.exists():
            return f"Error: file not found: {sheet_path}"

        sheet = Image.open(p).convert("RGBA")
        sw, sh = sheet.size

        cols = sw // frame_width
        rows = sh // frame_height

        if cols == 0 or rows == 0:
            return (
                f"Error: sheet {sw}x{sh} is smaller than frame size "
                f"{frame_width}x{frame_height}"
            )

        # Determine output directory
        if character and animation:
            out_dir = gen._get_character_dir(character) / "animations" / animation
        elif output_dir:
            out_dir = Path(output_dir).expanduser()
        else:
            out_dir = p.parent / p.stem

        out_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        for row in range(rows):
            for col in range(cols):
                x = col * frame_width
                y = row * frame_height
                frame = sheet.crop((x, y, x + frame_width, y + frame_height))

                # Skip fully transparent frames
                if frame.getextrema()[3][1] == 0:
                    continue

                out_file = out_dir / f"frame_{count:02d}.png"
                frame.save(out_file, "PNG")
                count += 1

        return (
            f"Split {p.name} into {count} frames.\n"
            f"Grid: {cols}x{rows}, Frame size: {frame_width}x{frame_height}\n"
            f"Saved to: {out_dir}"
        )

    @mcp.tool()
    async def export_to_godot(
        character: str,
        animation: str,
        godot_project_path: str,
        sprite_dir: str = "sprites",
    ) -> str:
        """Export an animation's frames and sheet to a Godot project directory.

        Copies individual frames and the sprite sheet into the Godot project's
        sprite directory, ready for import.

        Args:
            character: Character name
            animation: Animation name
            godot_project_path: Path to the Godot project root (where project.godot lives)
            sprite_dir: Subdirectory within the Godot project for sprites (default "sprites")
        """
        import shutil

        import shelley_sprites.generate as gen

        char_dir = gen._get_character_dir(character)
        anim_dir = char_dir / "animations" / animation

        if not anim_dir.exists():
            return f"Error: no animation '{animation}' found for '{character}'."

        godot_root = Path(godot_project_path).expanduser()
        if not (godot_root / "project.godot").exists():
            return f"Error: no project.godot found at {godot_root}"

        dest = godot_root / sprite_dir / character.lower() / animation
        dest.mkdir(parents=True, exist_ok=True)

        copied = 0
        for f in sorted(anim_dir.glob("*.png")):
            shutil.copy2(f, dest / f.name)
            copied += 1

        return (
            f"Exported {copied} files to: {dest}\n"
            f"Godot project: {godot_root}\n"
            f"Ready for import in Godot's FileSystem dock."
        )
