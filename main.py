from gevent import monkey

monkey.patch_all()  # needs this as early as possible to avoid erratic behaviour


from constants import ACCESS_LEVELS, LOG_FILE
import logging
import os.path
import sys

from flask import Flask
from flask import request
from flask import _request_ctx_stack
from flask_sqlalchemy import SQLAlchemy
from flask_session import Session

# from flask import session

from importlib import import_module
from logging.handlers import RotatingFileHandler
from pathlib import Path

from werkzeug.exceptions import NotFound
from werkzeug.exceptions import HTTPException
from werkzeug.exceptions import Unauthorized
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from authenticate import Auth
from models import loadSession, User
from authflask import AuthFlask
from tzlogging import TZLogger


class FlaskPortal:
    def __find_app_modules(self):
        modules = [
            os.path.dirname(x).replace("/", ".")
            for x in Path("apps").glob("*/*/__init__.py")
        ]
        modules = list(
            filter(lambda x: x.find("..") < 0, modules)
        )  # remove hidden apps

        self.app.logger.info("modules:" + str(modules))
        # dynamically import each module discovered
        for mod in modules:
            import_module(mod)

        # converting the modules list to dictionary using the access level type as the key.
        modules_dict = {}
        for actype in ACCESS_LEVELS:
            modules_dict[actype] = [
                x for x in modules if x.find("apps.{}.".format(actype)) >= 0
            ]
            modules_dict[actype].sort()

        endpoint_app_dict = {}
        all_apps_endpoints = []
        bad_endpoints = ["static", ".js", ".css", "<path:"]
        for actype in modules_dict:
            for app_name in modules_dict[actype]:
                # find AuthFlask app object in the imported modules, as it can be of any name.
                afapps = [
                    (key, getattr(sys.modules[app_name], key))
                    for key in sys.modules[app_name].__dict__.keys()
                    if type(getattr(sys.modules[app_name], key)) == AuthFlask
                ]
                if len(afapps) == 0:
                    self.app.logger.warning(
                        "Found no AuthFlask app. Not loaded: {}".format(app_name)
                    )
                    continue
                elif len(afapps) > 1:
                    self.app.logger.warning(
                        "Multiple AuthFlask apps were detected. Only one is loaded: {}".format(
                            app_name
                        )
                    )
                else:
                    self.app.logger.info(
                        "Info: Found an AuthFlask app:{}.{}".format(
                            app_name, afapps[0][0]
                        )
                    )
                app_obj = afapps[0][1]
                endpoint = "/" + app_name.replace(".", "/")
                endpoint_app_dict[endpoint] = app_obj

                ## collect all "good" endpoints to display on the dashboard
                #                all_apps_endpoints.append((endpoint, app_obj.permission, app_name)) #root endpoint will be added by the code below anyway
                subendpoints = list(
                    set(["%s" % rule for rule in app_obj.url_map.iter_rules()])
                )  # remove duplicates
                filtered_subendpoints = []
                for rule in subendpoints:  # remove bad endpoints
                    count = 0
                    for pattern in bad_endpoints:
                        if rule.find(pattern) >= 0:
                            break
                        else:
                            count += 1
                    if count == len(bad_endpoints):
                        filtered_subendpoints.append(rule)
                subendpoints = filtered_subendpoints
                self.app.logger.info(subendpoints)
                for ep in subendpoints:
                    all_apps_endpoints.append(
                        (endpoint + ep, app_obj.permission, app_name + ep)
                    )
        return endpoint_app_dict, all_apps_endpoints

    def __init__(self):

        self.app = Flask(__name__, static_url_path="/static", static_folder="./static")

        # add a logging handler to the app
        self.app.logger = TZLogger(__name__, LOG_FILE).getLogger()

        # collect all legit apps under "apps" directory and create a dictionary having the endpoint (eg. /devel/xxx) as the key.
        self.endpoint_app_dict, self.all_apps_endpoints = self.__find_app_modules()

        self.app.logger.info("endpoints: " + str(self.endpoint_app_dict))
        self.app.wsgi_app = DispatcherMiddleware(
            self.app.wsgi_app, self.endpoint_app_dict
        )
        self.auth = Auth(self.app)

        self.app.config[
            "SQLALCHEMY_DATABASE_URI"
        ] = "mysql+pymysql://{}:{}@{}/{}".format(
            Auth.MYSQL_USERNAME, Auth.MYSQL_PASSWORD, Auth.MYSQL_IP, Auth.MYSQL_DB
        )
        self.app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

        self.db = SQLAlchemy(self.app)
        self.db.init_app(self.app)

        self.app.config.from_object(__name__)
        self.app.secret_key = Auth.SECRET_KEY
        self.app.debug = True
        # SESSION_TYPE='filesystem'
        # SESSION_PERMANENT=False
        # Session(self.app) #supports for Server-side Session. Optional

        self.dbsession = loadSession(self.app.config["SQLALCHEMY_DATABASE_URI"])


flask_portal = FlaskPortal()
main_app = flask_portal.app


from routes import *
from errors import *


# @main_app.shell_context_processor
# def make_shell_context():
#     """
#     Run `FASK_APP=app.py; flask shell` for an interpreter with local structures.
#     """
#     return {'db': main_app.db, 'User': models.User}
