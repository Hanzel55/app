# app.py
import asyncio
import grpc
import uuid

import app_pb2
import app_pb2_grpc


# --------------------------------------------------
# GLOBAL STATE
# --------------------------------------------------

# agent_id → { worker_id → grpc context }
connected_agents = {}

# agent_id → { worker_id → asyncio.Queue }
agent_queues = {}

# agent_id → { worker_id → active_task_count }
worker_load = {}

# (agent_id, request_id) → asyncio.Future
pending_results = {}



# HELPER: Pick least-busy worker
def pick_least_busy_worker(agent_id):
    workers = worker_load.get(agent_id, {})
    if not workers:
        return None
    return min(workers, key=lambda w: workers[w])


# GRPC SERVICE IMPLEMENTATION
class AgntService(app_pb2_grpc.AgntServiceServicer):

    async def Connect(self, request_iterator, context):
        agent_id = None
        worker_id = None
        send_queue = asyncio.Queue()

        outbound_task = asyncio.create_task(
            self._send_loop(send_queue, context)
        )

        try:
            while True:
                try:
                    msg = await request_iterator.__anext__()

                except StopAsyncIteration:
                    # ✅ Agent really disconnected
                    break

                except asyncio.CancelledError:
                    # ✅ Client cancelled SendCommand → IGNORE
                    continue

                except Exception as e:
                    print(f"[SERVER] Error {agent_id}/{worker_id}: {e}")
                    continue

                # ---------------- NORMAL MESSAGE HANDLING ----------------

                if agent_id is None:
                    if not msg.agent_id or not msg.worker_id:
                        print("[SERVER] ERROR: Missing agent_id or worker_id")
                        break

                    agent_id = msg.agent_id
                    worker_id = msg.worker_id

                    connected_agents.setdefault(agent_id, {})
                    agent_queues.setdefault(agent_id, {})
                    worker_load.setdefault(agent_id, {})

                    connected_agents[agent_id][worker_id] = context
                    agent_queues[agent_id][worker_id] = send_queue
                    worker_load[agent_id][worker_id] = 0

                    print(f"[SERVER] Connected: {agent_id} / {worker_id}")
                    continue

                if msg.heartbeat:
                    continue

                if msg.query_result:
                    req_id = msg.query_result.request_id
                    key = (agent_id, req_id)

                    future = pending_results.pop(key, None)
                    if future:
                        if not future.done():
                            future.set_result({
                                "result": msg.query_result.json,
                                "message": msg.message,
                                "meta_data": msg.query_result.tbl_meta_data,
                            })
                        else:
                            pass

                    worker_load[agent_id][worker_id] = max(
                        0, worker_load[agent_id][worker_id] - 1
                    )   

        finally:
            # ✅ Cleanup ONLY once, ONLY on real disconnect
            print(f"[SERVER] Disconnected: {agent_id}/{worker_id}")

            if agent_id and worker_id:
                connected_agents.get(agent_id, {}).pop(worker_id, None)
                agent_queues.get(agent_id, {}).pop(worker_id, None)
                worker_load.get(agent_id, {}).pop(worker_id, None)

                if not agent_queues.get(agent_id):
                    connected_agents.pop(agent_id, None)
                    agent_queues.pop(agent_id, None)
                    worker_load.pop(agent_id, None)

            outbound_task.cancel()
            await asyncio.sleep(0)


    # --------------------------------------------------
    async def _send_loop(self, queue, context):
        """
        Single writer per stream (gRPC requirement)
        """
        try:
            while True: 
                msg = await queue.get()
                await context.write(msg)
        except Exception:
            pass

    # ---------- DJANGO RPC ----------
    async def SendCommand(self, request, context):
        """
        Called by Django to this code via gRPC
        """
        result = await send_command(
            request.agent_id,
            request.database,
            request.query,
            request.tbl_name,
            request.db_config
        )

        return app_pb2.CommandResponse(
            json=result["result"],
            message=result["message"],
            meta_data=result["meta_data"],
        )


# PUBLIC FUNCTION 
async def send_command(agent_id, database, query, tbl_name, db_config):
    """
    Sends DB query to the least-busy worker and waits for result. (send to agent)
    """

    if agent_id not in agent_queues or not agent_queues[agent_id]:
        raise Exception(f"Agent {agent_id} not connected")

    worker_id = pick_least_busy_worker(agent_id)
    if not worker_id:
        raise Exception("No available worker")

    request_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    future = loop.create_future()

    pending_results[(agent_id, request_id)] = future

    msg = app_pb2.ServerMessage(
        database=database,
        query=query,
        request_id=request_id,
        tbl_name=tbl_name,
        db_config=db_config
    )

    # 🔼 Increment worker load BEFORE sending
    worker_load[agent_id][worker_id] += 1

    print(
        f"[SERVER] Sending → {agent_id}/{worker_id} "
        f"(load={worker_load[agent_id][worker_id]}) "
        f"req_id={request_id}"
    )

    await agent_queues[agent_id][worker_id].put(msg)
    import time
    start_time = time.perf_counter()
    res = await future
    end_time = time.perf_counter()
    print(f"Time taken: {end_time - start_time} seconds")
    return res


# --------------------------------------------------
# START gRPC SERVER
# --------------------------------------------------
async def start_grpc_server():


    server = grpc.aio.server(options=[
        ('grpc.max_send_message_length', (2 * 1024 * 1024 * 1024) - 1),
        ('grpc.max_receive_message_length', (2 * 1024 * 1024 * 1024) - 1)
    ])

    servicer = AgntService()

    app_pb2_grpc.add_AgntServiceServicer_to_server(servicer, server)
    app_pb2_grpc.add_ClientServiceServicer_to_server(servicer, server)

    with open("TLS/server.key", "rb") as f:
        private_key = f.read()

    with open("TLS/server.pem", "rb") as f:
        certificate = f.read()

    server_credentials = grpc.ssl_server_credentials(
        [(private_key, certificate)]
    )
    
    server.add_secure_port("[::]:50051", server_credentials)
    await server.start()

    print(" gRPC server running on :50051")
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(start_grpc_server())