"""Agent Builder — use Claude Agent SDK to build sites like Lovable/Bolt.

Instead of a single API call, runs a full Claude Code-like agent that:
1. Creates project structure (React + Tailwind + Vite OR simple HTML)
2. Writes all files
3. Runs npm run build (if React)
4. We deploy the output to Cloudflare Pages

This is the "Lovable from Telegram" experience.
"""

import logging
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


async def build_site_with_agent(
    description: str,
    slug: str,
    mode: str = "simple",  # "simple" (HTML only) or "react" (full React app)
) -> dict:
    """Build a site using Claude Agent SDK.

    Args:
        description: What to build (from user's Telegram message)
        slug: URL slug for the site
        mode: "simple" for single HTML, "react" for full React+Vite app

    Returns:
        {"success": True, "output_dir": "/path/to/build", "files": [...]}
        or {"success": False, "error": "..."}
    """
    try:
        from claude_agent_sdk import query
    except ImportError:
        logger.warning("claude-agent-sdk not installed, falling back to API call")
        return {"success": False, "error": "Agent SDK not installed"}

    # Create temp directory for the project
    work_dir = Path(tempfile.mkdtemp(prefix=f"wai-site-{slug}-"))

    try:
        if mode == "simple":
            prompt = _simple_site_prompt(description)
            allowed_tools = ["Write", "Read"]
        else:
            prompt = _react_site_prompt(description)
            allowed_tools = ["Write", "Edit", "Read", "Bash"]

        # Run the agent
        files_created = []
        result_text = ""

        async for message in query(
            prompt=prompt,
            options={
                "cwd": str(work_dir),
                "allowedTools": allowed_tools,
                "permissionMode": "bypassPermissions",
                "allowDangerouslySkipPermissions": True,
                "maxTurns": 15,
                "model": "claude-haiku-4-5",  # Fast + cheap for site generation
            },
        ):
            if hasattr(message, "result"):
                result_text = message.result
            # Track file creation via system messages
            if hasattr(message, "type") and message.type == "system":
                logger.debug(f"Agent: {message}")

        # Check what was created
        for f in work_dir.rglob("*"):
            if f.is_file():
                files_created.append(str(f.relative_to(work_dir)))

        # For React mode, check for dist/ directory
        output_dir = work_dir
        if mode == "react":
            dist_dir = work_dir / "dist"
            if dist_dir.exists():
                output_dir = dist_dir

        logger.info(f"Agent built site: {len(files_created)} files in {work_dir}")

        return {
            "success": True,
            "output_dir": str(output_dir),
            "work_dir": str(work_dir),
            "files": files_created,
            "result": result_text,
        }

    except Exception as e:
        logger.error(f"Agent builder failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def cleanup_build(work_dir: str) -> None:
    """Clean up temporary build directory."""
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        pass


def _simple_site_prompt(description: str) -> str:
    """Prompt for single-file HTML site."""
    return f"""Create a beautiful, modern, professional single-page website.

Description: {description}

Requirements:
- Write a single index.html file with embedded CSS and JavaScript
- Modern, clean, responsive design (mobile-first)
- Beautiful typography, generous spacing, professional color scheme
- Smooth animations and hover effects
- Use emoji for icons (no external dependencies)
- Include a footer: "Made with Wai ✨"
- Do NOT use any external CDN, fonts, or frameworks
- The file must be self-contained and look stunning

Write the file to index.html in the current directory."""


def _react_site_prompt(description: str) -> str:
    """Prompt for full React + Vite + Tailwind site."""
    return f"""Create a beautiful React + Tailwind CSS website using Vite.

Description: {description}

Steps:
1. Run: npm create vite@latest . -- --template react-ts
2. Run: npm install
3. Install Tailwind: npm install -D tailwindcss @tailwindcss/vite
4. Configure Tailwind in vite.config.ts
5. Create beautiful components with Tailwind classes
6. Include professional animations, responsive design
7. Add footer: "Made with Wai ✨"
8. Run: npm run build

The dist/ directory will be deployed automatically."""
