import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SERVER_URL = "http://127.0.0.1:8000/mcp"


async def main():
    async with streamablehttp_client(SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Tools this server offers:", [t.name for t in tools.tools])

            result = await session.call_tool("list_files", {"directory": "."})
            print("\nResult of calling list_files:")
            print(result.content[0].text)


asyncio.run(main())
