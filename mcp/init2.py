# mcp/init2.py
from mcp.registry2 import registry2
from mcp.tools2 import (
    get_task_graph,
    voice_cloning_synthesizer,
    query_stock_footage,
    face_swapper,
    identity_validator,
    lip_sync_aligner,
    commit_memory_p2,
    TOOL_SCHEMAS_2,
)


def register_tools_p2():
    """Registers all Phase 2 MCP tools at runtime."""
    registry2.register("get_task_graph",            get_task_graph,
                       schema=TOOL_SCHEMAS_2["get_task_graph"])
    registry2.register("voice_cloning_synthesizer", voice_cloning_synthesizer,
                       schema=TOOL_SCHEMAS_2["voice_cloning_synthesizer"])
    registry2.register("query_stock_footage",       query_stock_footage,
                       schema=TOOL_SCHEMAS_2["query_stock_footage"])
    registry2.register("face_swapper",              face_swapper,
                       schema=TOOL_SCHEMAS_2["face_swapper"])
    registry2.register("identity_validator",        identity_validator,
                       schema=TOOL_SCHEMAS_2["identity_validator"])
    registry2.register("lip_sync_aligner",          lip_sync_aligner,
                       schema=TOOL_SCHEMAS_2["lip_sync_aligner"])
    registry2.register("commit_memory",             commit_memory_p2,
                       schema=TOOL_SCHEMAS_2["commit_memory"])

    print(f"[MCP2] Registered tools: {registry2.list_tools()}")