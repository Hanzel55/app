# main.py
import asyncio
import uvicorn
from app import start_grpc_server
from api import app as fastapi_app

async def main():
    # ---- Start gRPC server ----
    grpc_server = await start_grpc_server()

    # ---- Start FastAPI server ----
    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=8000)
    fastapi_server = uvicorn.Server(config)

    # Run both inside asyncio
    await asyncio.gather(
        fastapi_server.serve(),
        grpc_server.wait_for_termination(),
    )

if __name__ == "__main__":
    asyncio.run(main())
