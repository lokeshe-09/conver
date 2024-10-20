from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Dict
from pydantic import BaseModel
import json

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

class User(BaseModel):
    username: str
    age: int
    gender: str

class Message(BaseModel):
    sender: str
    receiver: str
    content: str

class Group(BaseModel):
    name: str
    members: List[str]

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.users: Dict[str, User] = {}
        self.messages: Dict[str, Dict[str, List[Message]]] = {}
        self.groups: Dict[str, Group] = {}

    async def connect(self, username: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[username] = websocket
        if username not in self.messages:
            self.messages[username] = {}

    def disconnect(self, username: str):
        del self.active_connections[username]

    async def send_personal_message(self, message: str, username: str):
        if username in self.active_connections:
            await self.active_connections[username].send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections.values():
            await connection.send_text(message)

    async def send_to_group(self, message: str, group_name: str):
        if group_name in self.groups:
            for member in self.groups[group_name].members:
                if member in self.active_connections:
                    await self.active_connections[member].send_text(message)

    def store_message(self, sender: str, receiver: str, content: str):
        message = Message(sender=sender, receiver=receiver, content=content)
        if receiver not in self.messages[sender]:
            self.messages[sender][receiver] = []
        self.messages[sender][receiver].append(message)
        if sender not in self.messages[receiver]:
            self.messages[receiver][sender] = []
        self.messages[receiver][sender].append(message)

manager = ConnectionManager()

@app.post("/register")
async def register(user: User):
    if user.username in manager.users:
        raise HTTPException(status_code=400, detail="Username already exists")
    manager.users[user.username] = user
    return {"message": "User registered successfully"}

@app.get("/")
async def get():
    return FileResponse("static/index.html")

@app.websocket("/ws/{username}")
async def websocket_endpoint(websocket: WebSocket, username: str):
    await manager.connect(username, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            if message["type"] == "chat":
                if message["receiver"] == "main":
                    await manager.broadcast(json.dumps({
                        "type": "chat",
                        "sender": username,
                        "content": message['content'],
                        "receiver": "main"
                    }))
                elif message["receiver"].startswith("group:"):
                    group_name = message["receiver"][6:]
                    await manager.send_to_group(json.dumps({
                        "type": "chat",
                        "sender": username,
                        "content": message['content'],
                        "receiver": message["receiver"]
                    }), group_name)
                else:
                    await manager.send_personal_message(json.dumps({
                        "type": "chat",
                        "sender": username,
                        "content": message['content'],
                        "receiver": message["receiver"]
                    }), message["receiver"])
                    manager.store_message(username, message["receiver"], message['content'])
            elif message["type"] == "create_group":
                manager.groups[message["group_name"]] = Group(name=message["group_name"], members=[username])
            elif message["type"] == "join_group":
                if message["group_name"] in manager.groups:
                    manager.groups[message["group_name"]].members.append(username)
    except WebSocketDisconnect:
        manager.disconnect(username)
        await manager.broadcast(json.dumps({
            "type": "system",
            "content": f"{username} left the chat"
        }))

@app.get("/online_users")
async def get_online_users():
    return {
        "online_users": [
            {"username": username, "gender": manager.users[username].gender}
            for username in manager.active_connections.keys()
        ]
    }

@app.get("/user_profile/{username}")
async def get_user_profile(username: str):
    if username in manager.users:
        return manager.users[username]
    raise HTTPException(status_code=404, detail="User not found")

@app.get("/inbox/{username}")
async def get_inbox(username: str):
    if username in manager.messages:
        return {"messages": manager.messages[username]}
    raise HTTPException(status_code=404, detail="User not found")

@app.get("/groups")
async def get_groups():
    return {"groups": list(manager.groups.keys())}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)