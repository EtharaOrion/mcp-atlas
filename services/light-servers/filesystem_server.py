import os
import base64
from pathlib import Path
from fastmcp import FastMCP

mcp = FastMCP("filesystem")
WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", "/workspace"))


@mcp.tool
async def list_directory(path: str = "") -> list:
    """List files and directories at the given path relative to workspace root."""
    target = (WORKSPACE_ROOT / path.lstrip("/")) if path else WORKSPACE_ROOT
    if not target.is_dir():
        return [f"Error: {path!r} is not a directory"]
    return sorted([
        str(p.relative_to(WORKSPACE_ROOT)) + ("/" if p.is_dir() else "")
        for p in target.iterdir()
    ])


@mcp.tool
async def read_text_file(path: str) -> str:
    """Read a text file at the given path relative to workspace root."""
    target = WORKSPACE_ROOT / path.lstrip("/")
    return target.read_text(errors="replace")


@mcp.tool
async def write_text_file(path: str, content: str) -> str:
    """Write text content to a file at the given path relative to workspace root."""
    target = WORKSPACE_ROOT / path.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"Wrote {len(content)} characters to {path}"


@mcp.tool
async def write_binary_file(path: str, content_base64: str) -> str:
    """Write base64-encoded binary content to a file at the given path relative to workspace root."""
    target = WORKSPACE_ROOT / path.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(content_base64)
    target.write_bytes(data)
    return f"Wrote {len(data)} bytes to {path}"


@mcp.tool
async def create_directory(path: str) -> str:
    """Create a directory (and parents) at the given path relative to workspace root."""
    target = WORKSPACE_ROOT / path.lstrip("/")
    target.mkdir(parents=True, exist_ok=True)
    return f"Created directory {path}"


@mcp.tool
async def file_exists(path: str) -> bool:
    """Check if a file or directory exists at the given path relative to workspace root."""
    return (WORKSPACE_ROOT / path.lstrip("/")).exists()


@mcp.tool
async def create_image(source_path: str, dest_path: str, width: int = 1200, height: int = 1200) -> str:
    """Convert and resize an image file. Both paths are relative to workspace root. Saves as PNG."""
    from PIL import Image
    src = WORKSPACE_ROOT / source_path.lstrip("/")
    dst = WORKSPACE_ROOT / dest_path.lstrip("/")
    dst.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(str(src)).convert("RGB")
    img = img.resize((width, height), Image.LANCZOS)
    img.save(str(dst), "PNG")
    return f"Created {width}x{height} PNG at {dest_path}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8002, host="0.0.0.0")
