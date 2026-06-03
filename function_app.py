import azure.functions as func
import datetime
import json
import logging

from pitch_blueprint import bp

app = func.FunctionApp()
app.register_functions(bp)