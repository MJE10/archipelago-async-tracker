import asyncio
import websockets
import sys
import json

# --- CONFIGURATION ---
LISTEN_HOST = "localhost"
LISTEN_PORT = 8765
# TARGET_URL = "wss://archipelago.gg:59247"  # Change this to your destination URL
TARGET_URL = "ws://localhost:55555"  # Change this to your destination URL
# ---------------------

async def forward(source, destination, direction_label):
    """Handles forwarding messages from source to destination."""
    try:
        async for message in source:
            # Print the content of the message
            content = json.loads(message)
            for cmd in content:
                print(f"[{direction_label}]: {json.dumps(cmd)[:1000]}")

            # if json.loads(message)[0]["cmd"] != "Bounce":
            
            # Forward the message to the other side
            await destination.send(message)
    except websockets.exceptions.ConnectionClosed:
        pass

async def proxy_handler(client_ws):
    """Manages the lifecycle of a single proxied connection."""
    print(f"New connection received. Connecting to {TARGET_URL}...")
    
    try:
        # Connect to the remote target URL
        async with websockets.connect(TARGET_URL) as target_ws:
            print("Connected to target. Start forwarding...")

            # Create two concurrent tasks: 
            # 1. Client to Target
            # 2. Target to Client
            client_to_target = asyncio.create_task(
                forward(client_ws, target_ws, "CLIENT -> TARGET")
            )
            target_to_client = asyncio.create_task(
                forward(target_ws, client_ws, "TARGET -> CLIENT")
            )

            # Wait for either task to finish (meaning one side closed the connection)
            done, pending = await asyncio.wait(
                [client_to_target, target_to_client],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Clean up pending tasks
            for task in pending:
                task.cancel()
            
            print("Connection closed by one of the parties.")

    except Exception as e:
        print(f"Error during proxying: {e}")
    finally:
        await client_ws.close()
        print("Proxy session ended.")

async def main():
    print(f"Starting WebSocket proxy on ws://{LISTEN_HOST}:{LISTEN_PORT}")
    print(f"Forwarding to {TARGET_URL}")
    
    async with websockets.serve(proxy_handler, LISTEN_HOST, LISTEN_PORT):
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProxy server stopped.")
        sys.exit(0)