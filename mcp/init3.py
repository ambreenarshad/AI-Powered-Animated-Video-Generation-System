# mcp/init3.py
from mcp.registry3 import registry3
from mcp.tools3 import (
    image_generator,
    scene_animator,
    av_compositor,
    commit_memory_p3,
    TOOL_SCHEMAS_3,
)


def register_tools_p3():
    """Registers all Phase 3 MCP tools at runtime."""
    registry3.register("image_generator",
                       image_generator,
                       schema=TOOL_SCHEMAS_3["image_generator"])
    registry3.register("scene_animator",
                       scene_animator,
                       schema=TOOL_SCHEMAS_3["scene_animator"])
    registry3.register("av_compositor",
                       av_compositor,
                       schema=TOOL_SCHEMAS_3["av_compositor"])
    registry3.register("commit_memory",
                       commit_memory_p3,
                       schema=TOOL_SCHEMAS_3["commit_memory"])

    print(f"[MCP3] Registered tools: {registry3.list_tools()}")