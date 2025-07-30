from flask import Flask

from app import create_app, start_mqtt_thread

app = create_app()

if __name__ == '__main__':
    start_mqtt_thread()
    app.run(host='0.0.0.0', port=5001)