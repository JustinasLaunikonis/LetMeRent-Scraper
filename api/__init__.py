from flask import Flask

from api.logging_utils import configure_logging
from api.routes import api


def create_app():
    configure_logging()

    app = Flask(__name__)
    app.register_blueprint(api)
    return app
