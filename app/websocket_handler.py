import json
clients = []

def register_websocket(sock):
    @sock.route('/ws')
    def ws_handler(ws):
        clients.append(ws)
        while True:
            msg = ws.receive()
            if msg is None:
                clients.remove(ws)
                break

def notify_clients(data):
    print("Websocket calisiyor")
    for ws in clients[:]:
        try:
            ws.send(json.dumps(data))
        except:
            clients.remove(ws)
