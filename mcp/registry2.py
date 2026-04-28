# mcp/registry2.py
"""
Phase 2 MCP Registry — separate instance from Phase 1 to avoid tool collisions.
"""


class MCPRegistry2:
    def __init__(self):
        self.tools   = {}
        self.schemas = {}

    def register(self, name: str, func, schema: dict = None):
        self.tools[name]  = func
        if schema:
            self.schemas[name] = schema

    def get_tool(self, name: str):
        if name not in self.tools:
            raise Exception(
                f"[MCP2] Tool '{name}' not registered. "
                f"Available: {list(self.tools.keys())}"
            )
        return self.tools[name]

    def list_tools(self) -> list:
        return list(self.tools.keys())

    def get_schema(self, name: str) -> dict:
        return self.schemas.get(name, {})


registry2 = MCPRegistry2()