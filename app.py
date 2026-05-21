import os
from api import create_app


app = create_app()


if __name__ == "__main__":
    app.run(host=os.getenv("FLASK_HOST", "0.0.0.0"), port=int(os.getenv("FLASK_PORT", "5000")))
