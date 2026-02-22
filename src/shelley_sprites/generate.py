"""Sprite generation tools — create animation frames from reference sprites.

Two generation modes:
  1. ASSISTED (default, no token needed) — prepares prompts and reference paths,
     you call FLUX Kontext via the HuggingFace MCP tools, then feed the result
     back through ingest_generated_frame for post-processing.
  2. DIRECT (requires HF_TOKEN) — calls FLUX Kontext via gradio_client automatically.

Post-processes all frames for palette consistency and proper sizing.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

from shelley_sprites.palette import enforce_palette, extract_palette

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATA_DIR = Path(os.environ.get("SHELLEY_SPRITES_DATA", "~/.shelley-sprites")).expanduser()
CHARACTERS_DIR = DATA_DIR / "characters"

# HF Space for image editing
KONTEXT_SPACE = "black-forest-labs/FLUX.1-Kontext-Dev"

# Optional: set HF_TOKEN for direct generation (no assisted mode needed)
HF_TOKEN = os.environ.get("HF_TOKEN", "")


def _ensure_dirs():
    """Create data directories if they don't exist."""
    CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)


def _get_character_dir(character: str) -> Path:
    """Get or create directory for a character's data."""
    d = CHARACTERS_DIR / character.lower().replace(" ", "_")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_character_config(character: str) -> dict:
    """Load character config (palette, size, references)."""
    config_path = _get_character_dir(character) / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


def _save_character_config(character: str, config: dict):
    """Save character config."""
    config_path = _get_character_dir(character) / "config.json"
    config_path.write_text(json.dumps(config, indent=2))


async def _generate_via_gradio(
    reference_path: str,
    prompt: str,
    seed: int = -1,
    steps: int = 24,
    guidance: float = 2.5,
) -> str:
    """Call FLUX Kontext via gradio_client and return output image path."""
    from gradio_client import Client, handle_file

    client = Client(KONTEXT_SPACE, token=HF_TOKEN or None)

    result = client.predict(
        input_image=handle_file(reference_path),
        prompt=prompt,
        seed=seed if seed >= 0 else 0,
        randomize_seed=seed < 0,
        guidance_scale=guidance,
        steps=steps,
        api_name="/infer",
    )

    # Result is (image_dict, seed_used) — image_dict has 'path' key
    if isinstance(result, (list, tuple)):
        img_data = result[0]
        if isinstance(img_data, dict):
            return img_data.get("path", img_data.get("url", ""))
        return str(img_data)
    if isinstance(result, dict):
        return result.get("path", result.get("url", ""))
    return str(result)


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP):
    """Register sprite generation tools."""

    @mcp.tool()
    async def register_character(
        character: str,
        reference_image: str,
        sprite_width: int = 64,
        sprite_height: int = 64,
    ) -> str:
        """Register a character with a reference sprite image.

        Extracts the color palette and stores it for consistent generation.
        Call this once per character before generating frames.

        Args:
            character: Character name (e.g., "po")
            reference_image: Path to a reference sprite PNG
            sprite_width: Target sprite width in pixels
            sprite_height: Target sprite height in pixels
        """
        _ensure_dirs()
        ref_path = Path(reference_image).expanduser()
        if not ref_path.exists():
            return f"Error: reference image not found: {reference_image}"

        # Extract palette from reference
        colors = extract_palette(str(ref_path), max_colors=16)

        # Copy reference to character dir
        char_dir = _get_character_dir(character)
        import shutil

        dest = char_dir / f"reference_{ref_path.name}"
        shutil.copy2(ref_path, dest)

        config = _get_character_config(character)
        config.update(
            {
                "name": character,
                "sprite_width": sprite_width,
                "sprite_height": sprite_height,
                "palette": colors,
                "references": config.get("references", []) + [str(dest)],
            }
        )
        _save_character_config(character, config)

        return (
            f"Registered '{character}' with {len(colors)} palette colors.\n"
            f"Sprite size: {sprite_width}x{sprite_height}\n"
            f"Reference saved: {dest}\n"
            f"Palette: {colors}"
        )

    @mcp.tool()
    async def prepare_sprite_prompt(
        character: str,
        animation: str,
        frame_description: str,
    ) -> str:
        """Prepare a FLUX Kontext prompt and reference image path for sprite generation.

        ASSISTED MODE — no HF token needed.
        Returns the prompt and reference image path. The caller then:
          1. Calls FLUX Kontext (via HF dynamic_space tool) with the returned prompt + image
          2. Feeds the output image URL/path back via ingest_generated_frame

        Args:
            character: Character name (must be registered first)
            animation: Animation name (e.g., "run", "idle", "slide")
            frame_description: Describe the pose for this frame.
                E.g., "running pose, left foot forward, arms pumping, frame 2 of 6"
        """
        config = _get_character_config(character)
        if not config:
            return f"Error: character '{character}' not registered. Call register_character first."

        ref = config.get("references", [None])[0]
        if not ref or not Path(ref).exists():
            return f"Error: no valid reference image for '{character}'."

        prompt = (
            f"Transform this pixel art character sprite into: {frame_description}. "
            f"Maintain the exact same pixel art style, character design, colors, "
            f"and proportions. Keep the transparent background. "
            f"This is a frame for a '{animation}' animation in a 2D side-scrolling game."
        )

        return (
            f"READY FOR GENERATION\n"
            f"====================\n"
            f"Character: {character}\n"
            f"Animation: {animation}\n"
            f"Reference image: {ref}\n"
            f"Sprite size: {config.get('sprite_width', 64)}x{config.get('sprite_height', 64)}\n"
            f"\n"
            f"FLUX Kontext prompt:\n{prompt}\n"
            f"\n"
            f"NEXT STEP: Call FLUX Kontext with:\n"
            f'  space_name: "mcp-tools/FLUX.1-Kontext-Dev"\n'
            f'  input_image: "{ref}"\n'
            f'  prompt: "{prompt}"\n'
            f"\n"
            f"Then call ingest_generated_frame with the output image URL/path."
        )

    @mcp.tool()
    async def ingest_generated_frame(
        character: str,
        animation: str,
        image_path: str,
        enforce_character_palette: bool = True,
    ) -> str:
        """Ingest and post-process a generated sprite frame.

        ASSISTED MODE step 2 — after FLUX Kontext generates an image,
        feed it here for resizing, palette enforcement, and storage.

        Also works for importing any external sprite image into the system.

        Args:
            character: Character name (must be registered)
            animation: Animation name (e.g., "run", "idle")
            image_path: Path or URL to the generated image
            enforce_character_palette: If True, snap colors to character palette.
        """
        _ensure_dirs()
        config = _get_character_config(character)
        if not config:
            return f"Error: character '{character}' not registered."

        from PIL import Image

        p = Path(image_path).expanduser()

        # If it's a URL, download it first
        if image_path.startswith(("http://", "https://")):
            async with httpx.AsyncClient() as client:
                resp = await client.get(image_path)
                resp.raise_for_status()
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                tmp.write(resp.content)
                tmp.close()
                p = Path(tmp.name)

        if not p.exists():
            return f"Error: image not found: {image_path}"

        img = Image.open(p).convert("RGBA")

        # Resize to target sprite size using nearest-neighbor (preserves pixels)
        w = config.get("sprite_width", 64)
        h = config.get("sprite_height", 64)
        if img.size != (w, h):
            img = img.resize((w, h), Image.NEAREST)

        # Enforce palette
        if enforce_character_palette and config.get("palette"):
            img = enforce_palette(img, config["palette"])

        # Save to character animation dir
        char_dir = _get_character_dir(character)
        anim_dir = char_dir / "animations" / animation
        anim_dir.mkdir(parents=True, exist_ok=True)

        existing = sorted(anim_dir.glob("frame_*.png"))
        next_num = len(existing)
        out_file = anim_dir / f"frame_{next_num:02d}.png"
        img.save(out_file, "PNG")

        return (
            f"Ingested frame: {out_file}\n"
            f"Animation: {animation}, Frame: {next_num}\n"
            f"Size: {w}x{h}\n"
            f"Palette enforced: {enforce_character_palette}"
        )

    @mcp.tool()
    async def generate_sprite_frame(
        character: str,
        animation: str,
        frame_description: str,
        reference_image: str = "",
        seed: int = -1,
        enforce_character_palette: bool = True,
    ) -> str:
        """Generate a single sprite frame (DIRECT MODE — requires HF_TOKEN).

        If HF_TOKEN is not set, returns an error directing you to use
        prepare_sprite_prompt + ingest_generated_frame instead.

        Args:
            character: Character name (must be registered first)
            animation: Animation name (e.g., "run", "idle", "slide")
            frame_description: Describe the pose for this frame.
            reference_image: Optional specific reference image path.
            seed: Random seed for reproducibility. -1 for random.
            enforce_character_palette: If True, snap output colors to character palette.
        """
        if not HF_TOKEN:
            return (
                "No HF_TOKEN set — use ASSISTED mode instead:\n"
                "  1. Call prepare_sprite_prompt to get the prompt + reference\n"
                "  2. Call FLUX Kontext via the HuggingFace MCP dynamic_space tool\n"
                "  3. Call ingest_generated_frame with the result\n"
                "\n"
                "Or set HF_TOKEN env var for direct generation."
            )

        _ensure_dirs()
        config = _get_character_config(character)
        if not config and not reference_image:
            return (
                f"Error: character '{character}' not registered and no reference_image provided. "
                f"Call register_character first."
            )

        ref = reference_image
        if not ref and config.get("references"):
            ref = config["references"][0]
        if not ref or not Path(ref).exists():
            return f"Error: no valid reference image. Got: {ref}"

        prompt = (
            f"Transform this pixel art character sprite into: {frame_description}. "
            f"Maintain the exact same pixel art style, character design, colors, "
            f"and proportions. Keep the transparent background. "
            f"This is a frame for a '{animation}' animation in a 2D side-scrolling game."
        )

        try:
            output_path = await _generate_via_gradio(
                reference_path=ref,
                prompt=prompt,
                seed=seed,
            )
        except Exception as e:
            return f"Error calling FLUX Kontext: {e}"

        # Post-process via ingest
        return await ingest_generated_frame(
            character=character,
            animation=animation,
            image_path=output_path,
            enforce_character_palette=enforce_character_palette,
        )

    @mcp.tool()
    async def plan_animation(
        character: str,
        animation: str,
        frame_count: int = 6,
        animation_description: str = "",
    ) -> str:
        """Plan an animation sequence — returns per-frame prompts for generation.

        Works in both modes:
        - ASSISTED: Returns all prompts so you can call FLUX Kontext for each,
          then ingest_generated_frame for each result.
        - DIRECT (with HF_TOKEN): Use generate_animation instead.

        Has built-in frame descriptions for common animations:
        idle, run, slide, stumble, jump, double_jump.

        Args:
            character: Character name (must be registered)
            animation: Animation name (e.g., "run", "idle", "slide", "stumble")
            frame_count: Number of frames to generate (default 6)
            animation_description: Optional override. If empty, uses built-in descriptions.
        """
        config = _get_character_config(character)
        if not config:
            return f"Error: character '{character}' not registered. Call register_character first."

        # Built-in animation descriptions
        ANIM_FRAMES = {
            "idle": [
                "standing still, neutral pose, slight breathing motion",
                "standing still, chest slightly expanded, breathing in",
                "standing still, neutral pose, breathing out",
                "standing still, slight head bob, relaxed",
            ],
            "run": [
                "running, right foot forward, left arm forward, body leaning",
                "running, right foot pushing off ground, both arms mid-swing",
                "running, airborne between steps, both feet off ground",
                "running, left foot forward, right arm forward, body leaning",
                "running, left foot pushing off ground, both arms mid-swing",
                "running, airborne between steps, transitioning back to first pose",
            ],
            "slide": [
                "sliding on ground, body low, legs extended forward, arms back",
                "sliding on ground, body very low, maximum extension",
                "sliding, starting to rise, legs still forward",
                "transitioning from slide back to running stance",
            ],
            "stumble": [
                "tripping forward, arms flailing, surprise expression",
                "falling forward, hands reaching to catch self",
                "on hands and knees, dazed expression",
                "pushing up from ground, recovering",
                "standing back up, shaking off, slightly dazed",
            ],
            "jump": [
                "crouching, preparing to jump, knees bent",
                "launching upward, legs extending, arms rising",
                "ascending, body stretched upward, arms up",
                "peak of jump, fully extended, slight pause feel",
                "descending, body starting to curl",
                "landing, knees bending to absorb impact",
            ],
            "double_jump": [
                "at peak of first jump, curling for second jump",
                "launching upward again, burst of energy",
                "ascending higher, body stretched",
                "second peak, fully extended",
                "descending from double jump",
                "landing with more impact, deeper knee bend",
            ],
        }

        if animation_description:
            descriptions = [
                f"{animation_description} — frame {i + 1} of {frame_count}"
                for i in range(frame_count)
            ]
        elif animation in ANIM_FRAMES:
            base = ANIM_FRAMES[animation]
            descriptions = [base[i % len(base)] for i in range(frame_count)]
        else:
            descriptions = [
                f"{animation} animation — frame {i + 1} of {frame_count}, "
                f"smooth transition from previous pose"
                for i in range(frame_count)
            ]

        ref = config.get("references", [None])[0]
        w = config.get("sprite_width", 64)
        h = config.get("sprite_height", 64)

        lines = [
            f"ANIMATION PLAN: {character}/{animation}",
            f"{'=' * 40}",
            f"Reference: {ref}",
            f"Sprite size: {w}x{h}",
            f"Frames: {frame_count}",
            f"",
        ]

        for i, desc in enumerate(descriptions):
            prompt = (
                f"Transform this pixel art character sprite into: {desc}. "
                f"Maintain the exact same pixel art style, character design, colors, "
                f"and proportions. Keep the transparent background. "
                f"This is a frame for a '{animation}' animation in a 2D side-scrolling game."
            )
            lines.append(f"FRAME {i}:")
            lines.append(f"  Description: {desc}")
            lines.append(f"  Prompt: {prompt}")
            lines.append("")

        lines.append(f"WORKFLOW:")
        lines.append(f"  For each frame, call FLUX Kontext with the prompt + reference image,")
        lines.append(f"  then call ingest_generated_frame('{character}', '{animation}', <output_url>)")

        return "\n".join(lines)

    @mcp.tool()
    async def generate_animation(
        character: str,
        animation: str,
        frame_count: int = 6,
        animation_description: str = "",
        seed: int = -1,
    ) -> str:
        """Generate a complete animation sequence (DIRECT MODE — requires HF_TOKEN).

        If HF_TOKEN is not set, returns an error directing you to use
        plan_animation + manual FLUX calls + ingest_generated_frame instead.

        Args:
            character: Character name (must be registered)
            animation: Animation name (e.g., "run", "idle", "slide", "stumble")
            frame_count: Number of frames to generate (default 6)
            animation_description: Optional override for the animation description.
            seed: Base seed. Each frame uses seed+frame_num for slight variation.
        """
        if not HF_TOKEN:
            return (
                "No HF_TOKEN set — use ASSISTED mode instead:\n"
                "  1. Call plan_animation to get per-frame prompts\n"
                "  2. Call FLUX Kontext for each frame via HF dynamic_space tool\n"
                "  3. Call ingest_generated_frame for each output\n"
                "\n"
                "Or set HF_TOKEN env var for direct generation."
            )

        config = _get_character_config(character)
        if not config:
            return f"Error: character '{character}' not registered. Call register_character first."

        # Use plan_animation to get descriptions, then generate each
        plan = await plan_animation(character, animation, frame_count, animation_description)

        results = []
        # Extract descriptions from the built-in ANIM_FRAMES via the same logic
        ANIM_FRAMES = {
            "idle": ["standing still, neutral pose, slight breathing motion", "standing still, chest slightly expanded, breathing in", "standing still, neutral pose, breathing out", "standing still, slight head bob, relaxed"],
            "run": ["running, right foot forward, left arm forward, body leaning", "running, right foot pushing off ground, both arms mid-swing", "running, airborne between steps, both feet off ground", "running, left foot forward, right arm forward, body leaning", "running, left foot pushing off ground, both arms mid-swing", "running, airborne between steps, transitioning back to first pose"],
            "slide": ["sliding on ground, body low, legs extended forward, arms back", "sliding on ground, body very low, maximum extension", "sliding, starting to rise, legs still forward", "transitioning from slide back to running stance"],
            "stumble": ["tripping forward, arms flailing, surprise expression", "falling forward, hands reaching to catch self", "on hands and knees, dazed expression", "pushing up from ground, recovering", "standing back up, shaking off, slightly dazed"],
            "jump": ["crouching, preparing to jump, knees bent", "launching upward, legs extending, arms rising", "ascending, body stretched upward, arms up", "peak of jump, fully extended, slight pause feel", "descending, body starting to curl", "landing, knees bending to absorb impact"],
            "double_jump": ["at peak of first jump, curling for second jump", "launching upward again, burst of energy", "ascending higher, body stretched", "second peak, fully extended", "descending from double jump", "landing with more impact, deeper knee bend"],
        }

        if animation_description:
            descriptions = [f"{animation_description} — frame {i + 1} of {frame_count}" for i in range(frame_count)]
        elif animation in ANIM_FRAMES:
            base = ANIM_FRAMES[animation]
            descriptions = [base[i % len(base)] for i in range(frame_count)]
        else:
            descriptions = [f"{animation} animation — frame {i + 1} of {frame_count}" for i in range(frame_count)]

        for i, desc in enumerate(descriptions):
            frame_seed = seed + i if seed >= 0 else -1
            result = await generate_sprite_frame(
                character=character,
                animation=animation,
                frame_description=desc,
                seed=frame_seed,
                enforce_character_palette=True,
            )
            results.append(f"Frame {i}: {result}")

        char_dir = _get_character_dir(character)
        anim_dir = char_dir / "animations" / animation

        return (
            f"Generated {frame_count} frames for '{character}/{animation}':\n"
            + "\n---\n".join(results)
            + f"\n\nAll frames saved to: {anim_dir}"
        )

    @mcp.tool()
    async def list_character_animations(character: str) -> str:
        """List all generated animations and frames for a character.

        Args:
            character: Character name
        """
        char_dir = _get_character_dir(character)
        anim_dir = char_dir / "animations"

        if not anim_dir.exists():
            return f"No animations found for '{character}'."

        lines = [f"Animations for '{character}':"]
        for anim in sorted(anim_dir.iterdir()):
            if anim.is_dir():
                frames = sorted(anim.glob("frame_*.png"))
                lines.append(f"  {anim.name}: {len(frames)} frames")
                for f in frames:
                    lines.append(f"    - {f.name}")

        config = _get_character_config(character)
        if config.get("palette"):
            lines.append(f"\nPalette: {len(config['palette'])} colors")
        if config.get("sprite_width"):
            lines.append(f"Sprite size: {config['sprite_width']}x{config['sprite_height']}")

        return "\n".join(lines)
