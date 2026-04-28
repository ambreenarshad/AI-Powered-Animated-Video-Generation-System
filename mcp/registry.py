#mcp/registry.py
class MCPRegistry:
    """
    MCP-based tool registry.
    All tools must be discovered dynamically via this registry - no hardcoded APIs.
    Agents query this registry at runtime using structured schemas.
    """

    def __init__(self):
        self.tools = {}
        self.schemas = {}

    def register(self, name: str, func, schema: dict = None):
        """Register a tool with optional JSON schema for structured invocation."""
        self.tools[name] = func
        if schema:
            self.schemas[name] = schema

    def get_tool(self, name: str):
        if name not in self.tools:
            raise Exception(f"[MCP] Tool '{name}' not found in registry. Available: {list(self.tools.keys())}")
        return self.tools[name]

    def list_tools(self) -> list:
        """Allows agents to dynamically discover all registered tools."""
        return list(self.tools.keys())

    def get_schema(self, name: str) -> dict:
        return self.schemas.get(name, {})


registry = MCPRegistry()