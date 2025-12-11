# api.py
from fastapi import FastAPI
from pydantic import BaseModel
from app import send_command

app = FastAPI()

class CommandRequest(BaseModel):
    agentid: str
    database: str
    query: str
    tbl_name: str

@app.get("/")
def root():
    return {"message": "FastAPI is running along with gRPC"}

@app.post("/send-command")
async def send_command_api(request: CommandRequest):
    result = await send_command(request.agentid, request.database, request.query, request.tbl_name)

    return {"status": "success", "message": result}

