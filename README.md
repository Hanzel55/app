# Agent Connection Server

## Overview

This is a gRPC-based server application that manages bidirectional streaming connections from multiple agents and provides a unary RPC interface for clients (like Django applications) to send database queries to connected agents and receive results.

## Architecture

The application implements a **hub-and-spoke architecture** where:

- **Agents** connect via bidirectional streaming (`AgntService.Connect`) and maintain persistent connections
- **Clients** (Django, other services) use unary RPC (`ClientService.SendCommand`) to send commands and receive results synchronously
- The server tracks all agent connections, manages worker load balancing, and routes commands to the least-busy worker

## Key Components

### 1. **app.py** - Main Server Implementation

The core server that handles:
- Agent connection management via bidirectional streaming
- Command routing with load balancing
- Result tracking using asyncio Futures
- Worker load tracking

### 2. **app.proto** - Protocol Buffer Definitions

Defines the gRPC service contracts:
- `AgntService.Connect`: Bidirectional streaming for agent connections
- `ClientService.SendCommand`: Unary RPC for sending commands from clients
- Message types for communication between agents, server, and clients

## How It Works

### Agent Connection Flow

1. **Agent Connects**: An agent establishes a bidirectional streaming connection via `AgntService.Connect`
2. **Registration**: The agent sends its first message containing `agent_id` and `worker_id`
3. **Tracking**: The server stores:
   - Connection context in `connected_agents[agent_id][worker_id]`
   - Message queue in `agent_queues[agent_id][worker_id]`
   - Worker load in `worker_load[agent_id][worker_id]`
4. **Heartbeat**: Agents can send heartbeat messages to keep the connection alive
5. **Disconnection**: When an agent disconnects, all associated resources are cleaned up

### Command Execution Flow

1. **Client Sends Command**: A client calls `ClientService.SendCommand` with:
   - `agent_id`: Which agent group to target
   - `database`: Database type (e.g., "postgres", "mysql")
   - `query`: SQL query to execute
   - `tbl_name`: Table name (optional)

2. **Load Balancing**: The server selects the least-busy worker from the specified `agent_id`

3. **Request Routing**: 
   - A unique `request_id` is generated
   - An asyncio Future is created and stored in `pending_results`
   - The command is queued to the selected worker's queue
   - Worker load is incremented

4. **Agent Processing**: The agent receives the command via the streaming connection, executes the query, and sends back a `QueryResult` message

5. **Result Delivery**: 
   - The server receives the `QueryResult` with the matching `request_id`
   - The Future is resolved with the result data
   - Worker load is decremented
   - The result is returned to the client via the unary RPC response

### Data Structures

```python
# agent_id → { worker_id → grpc context }
connected_agents = {}

# agent_id → { worker_id → asyncio.Queue }
agent_queues = {}

# agent_id → { worker_id → active_task_count }
worker_load = {}

# (agent_id, request_id) → asyncio.Future
pending_results = {}
```

## Features

### 1. **Multi-Agent Support**
- Supports multiple agents with the same `agent_id` (multiple workers)
- Each worker is tracked independently

### 2. **Load Balancing**
- Automatically routes commands to the least-busy worker
- Tracks active task count per worker
- Ensures even distribution of workload

### 3. **Result Tracking**
- Uses asyncio Futures to track pending requests
- Unique request IDs prevent result mixing
- Automatic cleanup of completed requests

### 4. **Connection Management**
- Graceful handling of agent disconnections
- Automatic cleanup of resources when agents disconnect
- Heartbeat support for connection keep-alive

### 5. **Large Message Support**
- Configured to handle messages up to 2GB
- Suitable for large query results

## Usage

### Starting the Server

```bash
cd "app test"
python app.py
```

The server will start on port `50051` and listen for connections.

### Sending Commands from Client

See `client_example.py` for a complete example of how to connect as a client and send commands (only just fetching the data . inserting to postgres after fetching from agent is not implemented in client_example).

Basic usage:

```python
import asyncio
import grpc
import app_pb2
import app_pb2_grpc

async def send_query():
    async with grpc.aio.insecure_channel('localhost:50051') as channel:
        stub = app_pb2_grpc.ClientServiceStub(channel)
        
        request = app_pb2.CommandRequest(
            agent_id="agent-123",
            database="postgres",
            query="SELECT * FROM users LIMIT 10",
            tbl_name="users"
        )
        
        response = await stub.SendCommand(request)
        print(f"Result: {response.json}")
        print(f"Message: {response.message}")
        print(f"Meta Data: {response.meta_data}")

asyncio.run(send_query())
```

### Using the Internal send_command Function

If you're running code within the same process as the server:

```python
from app import send_command

async def example():
    result = await send_command(
        agent_id="agent-123",
        database="postgres",
        query="SELECT * FROM users",
        tbl_name="users"
    )
    
    print(f"Result: {result['result']}")
    print(f"Message: {result['message']}")
    print(f"Meta Data: {result['meta_data']}")
```

## Protocol Buffer Messages

### AgentMessage (Agent → Server)
- `agent_id`: Agent identifier (sent once on connection)
- `worker_id`: Worker identifier (sent once on connection)
- `heartbeat`: Keep-alive message
- `query_result`: Query execution result
- `message`: Optional message or error description

### ServerMessage (Server → Agent)
- `database`: Database type
- `query`: SQL query to execute
- `request_id`: Unique request identifier
- `tbl_name`: Table name

### CommandRequest (Client → Server)
- `agent_id`: Target agent group
- `database`: Database type
- `query`: SQL query
- `tbl_name`: Table name

### CommandResponse (Server → Client)
- `json`: Query result as JSON string
- `message`: Status or error message
- `meta_data`: Table metadata as JSON string

## Error Handling

- **Agent Not Connected**: Raises exception if `agent_id` has no connected workers
- **No Available Worker**: Raises exception if all workers are disconnected
- **Connection Errors**: Handled gracefully with cleanup
- **Result Timeout**: Futures can be cancelled if needed (not currently implemented with timeout)

## Requirements

See `requirements.txt` for all dependencies. Key packages:
- `grpcio` and `grpcio-tools`: gRPC framework
- `asyncio`: Async/await support (built-in)

## Development

### Regenerating Protocol Buffers

If you modify `app.proto`, regenerate the Python files:

```bash
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. app.proto
```

### Testing

1. Start the server: `python app.py`
2. Connect an agent (implement agent client)
3. Run client example: `python client_example.py`

## Architecture Diagram

```
┌─────────────┐
│   Client    │ (Django, etc.)
│  (Unary)    │
└──────┬──────┘
       │ SendCommand RPC
       ▼
┌─────────────────────────────────┐
│      gRPC Server (app.py)       │
│  ┌───────────────────────────┐  │
│  │  ClientService            │  │
│  │  (Unary RPC Handler)      │  │
│  └───────────┬───────────────┘  │
│              │                   │
│  ┌───────────▼───────────────┐  │
│  │  send_command()           │  │
│  │  - Load Balancing         │  │
│  │  - Future Management      │  │
│  └───────────┬───────────────┘  │
│              │                   │
│  ┌───────────▼───────────────┐  │
│  │  AgntService              │  │
│  │  (Streaming Handler)      │  │
│  └───────────┬───────────────┘  │
└──────────────┼──────────────────┘
               │
       ┌───────┴───────┐
       │               │
       ▼               ▼
┌──────────┐    ┌──────────┐
│ Agent 1  │    │ Agent 2  │
│ Worker 1 │    │ Worker 1 │
│          │    │          │
│ Worker 2 │    │ Worker 2 │
└──────────┘    └──────────┘
```

## Notes

- The server uses asyncio for concurrent handling of multiple agents
- Each agent connection runs in its own coroutine
- Worker load is tracked per agent group
- Results are matched using `(agent_id, request_id)` tuples
- The server supports large messages (up to 2GB) for handling large query results



## for testing
- first run python app.py to start grpc server
- after executing app.py , run client_example.py in another terminal
