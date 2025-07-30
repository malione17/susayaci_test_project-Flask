import os
from flask import Flask
from flask_sock import Sock
from .routes import register_routes
from .websocket_handler import register_websocket
from .db import init_db


sock = Sock()
clients = []

def create_app():
    app = Flask(__name__)

    init_db()
    register_routes(app)
    sock.init_app(app)
    register_websocket(sock)



    return app

def start_mqtt_thread():
    from threading import Thread
    from .mqtt_handler import start_mqtt
    t = Thread(target=start_mqtt, daemon=True)
    t.start()