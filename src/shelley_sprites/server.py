"""Shelley Sprites — Unified MCP server for sprite generation.

Entry point for the `shelley-sprites` CLI command.
Registers all tool modules into a single FastMCP instance.
"""

from mcp.server.fastmcp import FastMCP


def create_server() -> FastMCP:
    """Create and configure the Shelley Sprites MCP server."""
    mcp = FastMCP("shelley-sprites")

    from shelley_sprites import generate, palette, sheets

    generate.register(mcp)
    palette.register(mcp)
    sheets.register(mcp)

    return mcp


def main():
    """CLI entry point — starts the server over stdio."""
    from dotenv import load_dotenv

    load_dotenv()

    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
