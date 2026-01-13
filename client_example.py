import asyncio
import grpc
import json
import psycopg2
import time

import app_pb2
import app_pb2_grpc


# ---------------- CONFIG ----------------
GRPC_SERVER = "127.0.0.1:50051"

BASE_QUERY = "SELECT * FROM dbo.[Employees]"

AGENT_ID = "agent-123"
DATABASE = "sqlserver"
TBL_NAME = "Employees"

PG_CONN_INFO = {
    "dbname": "mytestdb",
    "user": "postgres",
    "password": "Password@123",
    "host": "localhost",
    "port": 5432
}

TARGET_TABLE = 'GENERAL.Employees'


# ---------------- gRPC CALL ----------------
async def fetch_page_grpc(stub, offset, limit):
    paginated_query = f"""
        {BASE_QUERY}
        ORDER BY EmployeeID
        OFFSET {offset} ROWS
        FETCH NEXT {limit} ROWS ONLY
    """

    response = await stub.SendCommand(
        app_pb2.CommandRequest(
            agent_id=AGENT_ID,
            database=DATABASE,
            query=paginated_query,
            tbl_name=TBL_NAME
        )
    )

    # Convert JSON string → Python list
    try:
        return json.loads(response.json)
    except Exception:
        return []


# ---------------- MAIN LOGIC ----------------
async def main():
    overall_start = time.time()
    print(f"Process started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # PostgreSQL connection
    conn = psycopg2.connect(**PG_CONN_INFO)
    cur = conn.cursor()

    offset = 0
    limit = 110
    total = 0
    columns = None

    async with grpc.aio.insecure_channel(GRPC_SERVER,    options=[
        ("grpc.max_send_message_length", (2 * 1024 * 1024 * 1024) - 1),
        ("grpc.max_receive_message_length", (2 * 1024 * 1024 * 1024) - 1),
    ],) as channel:
        stub = app_pb2_grpc.ClientServiceStub(channel)

        while True:

            # -------- FETCH --------
            fetch_start = time.time()
            rows = await fetch_page_grpc(stub, offset, limit)
            fetch_time = time.time() - fetch_start

            print(f"[FETCH] Offset={offset}, Count={len(rows)}, Time={fetch_time:.3f}s")

            if not rows:
                print("No more rows. Finished.")
                break

            if columns is None:
                columns = list(rows[0].keys())
                print("Columns:", columns)

            # -------- INSERT (placeholder) --------
            insert_start = time.time()
            conn.commit()
            insert_time = time.time() - insert_start

            total += len(rows)

            print(f"[INSERT] Inserted={len(rows)}, Total={total}, Time={insert_time:.3f}s")
            print("-" * 60)

            if len(rows) < limit:
                break

            offset += limit

    cur.close()
    conn.close()

    overall_end = time.time()
    print(f"Process finished at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total Duration: {overall_end - overall_start:.3f} seconds")
    print("Done. Total inserted:", total)


# ---------------- ENTRY ----------------
if __name__ == "__main__":
    asyncio.run(main())
