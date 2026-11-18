from flask import Flask

from routes.api import api
from routes.web import web


def register_routes(app: Flask) -> None:
    app.register_blueprint(web)
    app.register_blueprint(api)
