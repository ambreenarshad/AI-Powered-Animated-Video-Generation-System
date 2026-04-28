#mcp/init.py
from mcp.registry import registry
from mcp.tools import (
    generate_script_segment,
    commit_memory,
    generate_image,
    TOOL_SCHEMAS
)

def register_tools():
    """
    Registers all MCP tools dynamically at runtime.
    Per spec: all tools are discovered via registry - no hardcoded APIs in agents.
    """
    registry.register("generate_script_segment", generate_script_segment,
                      schema=TOOL_SCHEMAS["generate_script_segment"])

    registry.register("commit_memory", commit_memory,
                      schema=TOOL_SCHEMAS["commit_memory"])

    registry.register("generate_image", generate_image,
                      schema=TOOL_SCHEMAS["generate_image"])

    print(f"[MCP] Registered tools: {registry.list_tools()}")