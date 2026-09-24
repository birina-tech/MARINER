
import asyncio
from fastapi import FastAPI, WebSocket
from typing import List

### initialize the web server
app = FastAPI()
active_connections: List[WebSocket] = []

### define the background loop (replaces PyQt5 QTimer)
async def simulation_loop():
    while True:
        ### calculate the new positions and rules for all active ships here
        

        ### Need to add script here


        ### package the current coordinates into a simple dictionary
        payload = {"ship_1": {"x": 100, "y": 200, "heading": 45}}
        
        ### broadcast that telemetry to any connected web browsers
        for connection in active_connections:
            await connection.send_json(payload)
            
        ### pause the loop for 50ms before the next tick
        await asyncio.sleep(0.05)

### use lifespan events to start the simulation loop when the server boots up
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(simulation_loop())

### open a websocket endpoint for the frontend to connect to
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except:
        active_connections.remove(websocket)
