# Shelley Sprites

MCP server for generating consistent pixel art sprite animations for Shelley Guitars game characters.

## Tools

- **register_character** — Register a character with reference sprite and extract palette
- **generate_sprite_frame** — Generate a single animation frame via FLUX Kontext
- **generate_animation** — Generate a complete animation sequence (multiple frames)
- **list_character_animations** — List all generated animations for a character
- **extract_sprite_palette** — Analyze colors in a sprite image
- **apply_palette_to_sprite** — Enforce a character's palette on a sprite
- **compare_palettes** — Compare color palettes between two sprites
- **assemble_sprite_sheet** — Pack frames into a sprite sheet PNG
- **split_sprite_sheet** — Split a sheet into individual frames
- **export_to_godot** — Copy sprites into a Godot project directory

## Setup

```bash
pip install -e ".[all]"
shelley-sprites  # starts MCP server on stdio
```
