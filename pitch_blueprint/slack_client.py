import logging

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


def send_slack_notification(token: str, channel_id: str, form_data: dict) -> None:
    """
    Send a notification to the #intake Slack channel.
    Non-critical — failures are logged but don't affect the submission.
    """

    business_name = form_data.get("business_name", "Unknown")
    first_name = form_data.get("first_name", "")
    last_name = form_data.get("last_name", "")

    text = (
        f"📩 *New Pitch Submission: {business_name}*\n"
        f"*Contact:* {first_name} {last_name}\n"
        f"*Email:* {form_data.get('email', 'N/A')}\n"
        f"*Phone:* {form_data.get('phone', 'N/A')}\n"
        f"*Sector:* {form_data.get('sector', 'N/A')}\n"
        f"*Venture Stage:* {form_data.get('venture_stage', 'N/A')}\n"
        f"*Company Profile:* {form_data.get('company_profile', 'N/A')}\n"
        f"*Discovery:* {form_data.get('discovery', 'N/A')}"
    )

    try:
        client = WebClient(token=token)
        client.chat_postMessage(channel=channel_id, text=text)
        logger.info(f"Slack notification sent for: {business_name}")
    except SlackApiError as e:
        logger.error(
            f"Slack notification failed: {e.response['error']}. Non-critical — continuing."
        )
    except Exception as e:
        logger.error(f"Slack notification failed: {e}. Non-critical — continuing.")
