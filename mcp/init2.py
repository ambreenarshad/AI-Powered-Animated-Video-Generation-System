# mcp/init2.py
from mcp.registry2 import registry2
from mcp.tools2 import (
    get_task_graph,
    voice_cloning_synthesizer,
    commit_memory_p2,
    TOOL_SCHEMAS_2,
)


def register_tools_p2():
    """Registers all Phase 2 MCP tools at runtime."""
    registry2.register("get_task_graph",
                       get_task_graph,
                       schema=TOOL_SCHEMAS_2["get_task_graph"])
    registry2.register("voice_cloning_synthesizer",
                       voice_cloning_synthesizer,
                       schema=TOOL_SCHEMAS_2["voice_cloning_synthesizer"])
    registry2.register("commit_memory",
                       commit_memory_p2,
                       schema=TOOL_SCHEMAS_2["commit_memory"])

    print(f"[MCP2] Registered tools: {registry2.list_tools()}")