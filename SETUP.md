# Shelley Sprites — Setup Guide

## For Rizky (or anyone on the team)

### 1. Clone / Copy the server

```bash
# If you have access to Magus's machine, it's at:
# /Users/magus/shelley-sprites/

# Otherwise, copy the whole shelley-sprites/ folder to your machine
```

### 2. Create virtual environment and install

```bash
cd shelley-sprites
python3 -m venv .venv
.venv/bin/pip install -e ".[all]"
```

### 3. Get a HuggingFace token

1. Go to https://huggingface.co/settings/tokens
2. Create a token with these permissions:
   - `Read access to contents of all repos under your personal namespace`
   - `Make calls to Inference Providers`
3. HF Pro ($9/mo) recommended for unlimited sprite generation

### 4. Register in Claude Code

Add to your `~/.mcp.json`:

```json
{
  "mcpServers": {
    "shelley-sprites": {
      "command": "/path/to/shelley-sprites/.venv/bin/shelley-sprites",
      "args": [],
      "env": {
        "HF_TOKEN": "hf_your_token_here"
      }
    }
  }
}
```

### 5. Restart Claude Code

The `shelley-sprites` tools will appear in your tool list.

---

## Quick Start — Generating Sprites

### Step 1: Register a character

```
register_character("po", "/path/to/reference_sprite.png", sprite_width=64, sprite_height=64)
```

This extracts Po's 16-color palette and stores the reference for all future generations.

### Step 2: Generate a single frame

```
generate_sprite_frame("po", "run", "running, right foot forward, arms pumping")
```

FLUX Kontext edits the reference sprite into the described pose, then:
- Resizes to 64x64 (nearest-neighbor, preserves pixel art)
- Strips white background to transparent
- Snaps all colors to Po's registered palette

### Step 3: Generate a full animation

```
generate_animation("po", "run", frame_count=6)
```

Uses built-in frame descriptions for: idle, run, slide, stumble, jump, double_jump.
Or provide your own: `generate_animation("po", "dance", animation_description="doing a breakdance")`

### Step 4: Assemble sprite sheet

```
assemble_sprite_sheet("po", "run")
```

Packs all frames into a horizontal PNG strip for Godot.

### Step 5: Export to Godot

```
export_to_godot("po", "run", "/path/to/godot/project")
```

Copies frames + sheet into `sprites/po/run/` inside the Godot project.

---

## All Tools

| Tool | What it does |
|------|-------------|
| `register_character` | Register character with reference sprite + palette extraction |
| `generate_sprite_frame` | Generate one frame (direct mode, needs HF_TOKEN) |
| `generate_animation` | Generate full animation sequence (direct mode) |
| `plan_animation` | Get per-frame prompts without generating (for manual control) |
| `prepare_sprite_prompt` | Get prompt + reference for one frame (assisted mode) |
| `ingest_generated_frame` | Import + post-process an externally generated image |
| `list_character_animations` | Show all animations and frames for a character |
| `extract_sprite_palette` | Analyze colors in any sprite image |
| `apply_palette_to_sprite` | Force a character's palette onto any sprite |
| `compare_palettes` | Compare colors between two sprites |
| `assemble_sprite_sheet` | Pack frames into a sprite sheet PNG |
| `split_sprite_sheet` | Break a sheet into individual frames |
| `export_to_godot` | Copy animation assets into a Godot project |

## Data Location

All character data lives in `~/.shelley-sprites/characters/{name}/`:
```
~/.shelley-sprites/characters/po/
  config.json          — palette, sprite size, reference paths
  reference_*.png      — stored reference sprites
  animations/
    run/
      frame_00.png ... frame_05.png
      run_sheet.png
    idle/
      frame_00.png ... frame_03.png
      idle_sheet.png
```
