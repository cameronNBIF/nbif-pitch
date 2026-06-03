import logging
import azure.functions as func
from . import bp


@bp.route(route="pitch-intake", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.FUNCTION)
def pitch_intake(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP trigger for Pitch Intake Form submissions.
    Receives multipart/form-data from the Squarespace form,
    validates, stores, and creates Affinity records.
    """
    logging.info("Pitch Intake Form submission received.")

    # Placeholder response — full implementation in Step 7
    return func.HttpResponse(
        '{"status": "ok", "message": "Pitch intake endpoint is operational."}',
        status_code=200,
        mimetype="application/json"
    )