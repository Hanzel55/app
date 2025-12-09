# app.py
import asyncio
import grpc
import json
import uuid

import app_pb2
import app_pb2_grpc


# --------------------------------------------------
# GLOBAL STATE
# --------------------------------------------------
connected_agents = {}          # agent_id → grpc context (stream)
agent_queues = {}              # agent_id → asyncio.Queue
pending_results = {}           # (agent_id, request_id) → asyncio.Future


# --------------------------------------------------
# GRPC SERVICE IMPLEMENTATION
# --------------------------------------------------
class AgntService(app_pb2_grpc.AgntServiceServicer):

    async def Connect(self, request_iterator, context):
        """
        Bidirectional stream called once per agent connection.
        """

        agent_id = None
        send_queue = asyncio.Queue()

        # Background task for sending messages
        outbound_task = asyncio.create_task(self._send_loop(send_queue, context))

        try:
            async for msg in request_iterator:

                # 1️⃣ First message must contain agent_id
                if agent_id is None:
                    if not msg.agent_id:
                        print("[SERVER] ERROR: Agent connected without agent_id")
                        break

                    agent_id = msg.agent_id
                    connected_agents[agent_id] = context
                    agent_queues[agent_id] = send_queue

                    print(f"[SERVER] Agent connected: {agent_id}")
                    continue

                # 2️⃣ Heartbeat
                if msg.heartbeat:
                    print(f"[SERVER] Heartbeat from {agent_id}: {msg.heartbeat}")
                    continue

                # 3️⃣ Table list response
                if msg.table_names.names:
                    print(f"[SERVER] Tables from {agent_id}: {msg.table_names.names}")
                    continue

                # 4️⃣ Query result
                if msg.query_result:
                    req_id = msg.query_result.request_id
                    result_data = json.loads(msg.query_result.json)
                    print(f"[SERVER] Query result from {agent_id}: {result_data}")

                    key = (agent_id, req_id)

                    # Fulfill the pending future
                    future = pending_results.pop(key, None)
                    if future:
                        future.set_result(result_data)

                    continue

        except Exception as e:
            print(f"[SERVER] Error with agent {agent_id}: {e}")

        finally:
            if agent_id:
                print(f"[SERVER] Agent disconnected: {agent_id}")
                connected_agents.pop(agent_id, None)
                agent_queues.pop(agent_id, None)

        outbound_task.cancel()
        await asyncio.sleep(0)

    # --------------------------------------------------
    async def _send_loop(self, queue, context):
        """Continuously send messages from queue to agent stream."""
        try:
            while True:
                msg = await queue.get()
                await context.write(msg)
        except Exception:
            pass


# --------------------------------------------------
# PUBLIC FUNCTION CALLED BY FASTAPI
# --------------------------------------------------
async def send_command(agent_id, database, query):
    """
    Sends a command to an agent and waits for its response.
    """

    if agent_id not in agent_queues:
        raise Exception(f"Agent {agent_id} not connected")

    # Create unique request_id for matching response
    request_id = str(uuid.uuid4())

    loop = asyncio.get_event_loop()
    future = loop.create_future()

    # Store the future
    pending_results[(agent_id, request_id)] = future

    # Prepare message
    msg = app_pb2.ServerMessage(
        database=database,
        query=query,
        request_id=request_id
    )

    print(f"[SERVER] Sending command to {agent_id}: {database} / {query} / req_id={request_id}")

    # Push to agent queue
    await agent_queues[agent_id].put(msg)

    # Wait for result from agent
    result = await future
    return result


# ------------------------------------------------------
# Start gRPC Server
# ------------------------------------------------------
async def start_grpc_server():
    server = grpc.aio.server()
    app_pb2_grpc.add_AgntServiceServicer_to_server(AgntService(), server)
    server.add_insecure_port("[::]:50051")
    await server.start()

    print("gRPC server started on port 50051")
    return server
