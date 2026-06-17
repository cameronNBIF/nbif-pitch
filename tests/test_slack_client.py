import os
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv()

# Initialize a Web API client
slack_token = os.environ["SLACK_BOT_USER_OAUTH_TOKEN"]
slack_intake_channel_id = os.environ["SLACK_INTAKE_CHANNEL_ID"]
client = WebClient(token=slack_token)

# Call the chat.postMessage method
try:
    response = client.chat_postMessage(
        channel=slack_intake_channel_id,
        text="Hello world",
    )
except SlackApiError as e:
    assert e.response["error"]
