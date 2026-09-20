import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("file-tools")


@mcp.tool()
def list_files(directory: str = ".") -> str:
    """List the files in a directory on this computer."""
    return "\n".join(os.listdir(directory))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
