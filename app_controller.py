# app_controller.py
import asyncio
from app import send_command

async def trigger():
    # Example: ask agent to list tables
    # await send_command("agent-123", "postgres", "list_tables")

    # Example: run a real SQL query
    await send_command("agent-123", "postgres", "SELECT * FROM users")

if __name__ == "__main__":
    asyncio.run(trigger())



    

