import os
from waitress import serve
from bring_loader.app import create_app

app = create_app()

if __name__ == "__main__":
    serve(app, host=os.environ.get("APP_BIND", "127.0.0.1"), port=int(os.environ.get("APP_PORT", "8723")))
