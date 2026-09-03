# NBIF Pitch Intake Integration

This project is an Azure Function App that serves as the backend for the NBIF Pitch Intake form. It processes incoming pitch submissions, verifies CAPTCHA responses, archives the raw data, and automatically creates and populates corresponding records in Affinity CRM.

## Technologies Used

* **Language:** Python 3
* **Compute:** Azure Functions (v2 Programming Model)
* **Storage:** Azure Blob Storage (archiving), Azure Table Storage (deduplication), Azure Queue Storage (dead-lettering)
* **APIs & Services:** * Affinity API (for CRM data entry)
  * Cloudflare Turnstile (for CAPTCHA verification)
  * Microsoft Teams (Incoming Webhooks for notifications)
* **Authentication:** HTTP Basic Auth (Affinity API)
* **HTTP Client:** `requests` (with `urllib3` retry adapters)

## Workflow: How Data Travels

1. **Submission Arrival:** The HTML frontend form sends a POST request containing the form data and a Cloudflare Turnstile CAPTCHA token to the Azure Function's HTTP Trigger (`pitch-intake`).
2. **Verification & Validation:** The function verifies the CAPTCHA token against the Cloudflare API. It then validates the form payload (required fields, email regex, and exact dropdown option mapping).
3. **Deduplication Check:** The function generates a SHA-256 fingerprint using the submitter's email and company name. It queries Azure Table Storage to check for and reject duplicate submissions made within a 60-second window.
4. **Raw Archiving:** Before interacting with the CRM, the raw, validated submission is saved as a JSON file in Azure Blob Storage. This ensures no data is lost if downstream APIs fail.
5. **Affinity CRM Sync:**
   * **Person Resolution:** The function queries Affinity for an existing Person using the founder's email address. If no match is found, a new Person is created.
   * **Organization Resolution:** The function queries Affinity for an Organization using the company name. If no match is found, a new Organization is created.
   * **List Entry Creation:** The Organization is added to the specified Pitch Intake list.
   * **Field Population:** Global fields (e.g., Sector, Company Profile) are applied to the Organization entity, and list-specific fields (e.g., Investment Round Size, Potential Investment Amount) are applied directly to the list entry via `POST` requests.
6. **Post-Processing & Notifications:** The Azure Blob Storage archive is updated to include the newly generated Affinity IDs. Finally, an Adaptive Card summarizing the pitch is sent to a Microsoft Teams channel via a webhook.

## Reliability & Error Handling

To ensure data integrity, CRM operations are isolated from the initial data capture. If the Affinity API calls fail (e.g., due to an outage), the application catches the error and sends a payload containing the `submission_id`, error details, and the path to the Blob archive to an Azure Dead-Letter Queue (`pitchintakedeadletter`). This allows the team to manually review and re-process the submission later without asking the user to resubmit.

## External Dependencies (Manual Configuration)

Some configuration this project depends on lives **outside this repository** and outside of Azure App Settings — mainly in the Squarespace admin panel and third-party dashboards. None of it is version-controlled, so it's easy to lose track of. Any time one of these is added, changed, or added-to-a-new-page, **update this table**.

| What | Where it lives | Why it matters |
|---|---|---|
| Cloudflare Turnstile loader script (`api.js`) | Squarespace → **Website → Pages → *[specific page]* → Page Settings → Advanced → Page Header Code Injection**:<br>`<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>` | Required for the `.cf-turnstile` widget in `form/form.html` to render. **This is injected per-page, not site-wide** — if you add a new page or language variant of the form (e.g. a French version), you must add this script tag to that page's own Page Header Code Injection, or the CAPTCHA widget will silently fail to render. See the note at the top of `form/form.html`. Added 2026-07-06. |
| Turnstile site key | Embedded directly in `form/form.html` (`data-sitekey="..."`) | Public value, safe to keep in the HTML. Must match the key configured in the Cloudflare Turnstile dashboard. |
| Turnstile secret key | Cloudflare Turnstile dashboard (source of truth); stored in Azure App Settings as `CLOUDFLARE_TURNSTILE_SECRET_KEY` | Used server-side in `pitch_blueprint/cloudflare_turnstile.py` to verify submitted tokens. |
| Slack app OAuth token | Slack app configuration (source of truth); stored in Azure App Settings as `SLACK_BOT_USER_OAUTH_TOKEN` | Used by `pitch_blueprint/slack_client.py` to post intake notifications. |
| Slack intake channel ID | Slack workspace; stored in Azure App Settings as `SLACK_INTAKE_CHANNEL_ID` | Destination channel for notifications. |
| Microsoft Graph webhook subscription | Registered manually via `tools/register_subscription.py`; subscription ID stored in Azure Table Storage | Subscriptions expire after 3 days and must be renewed/re-registered, or inbox monitoring silently stops. Use `tools/clean_subscriptions.py` to clear stale subscriptions before re-registering. |
| Affinity field/list IDs (Sector, Venture Stage, etc.) | Affinity workspace; referenced via env vars (e.g. `AFFINITY_FIELD_ID_*`, `AFFINITY_LIST_ID`) in Azure App Settings | These are workspace-specific numeric IDs. If a field is renamed, deleted, or recreated in Affinity, its ID changes and the corresponding env var must be updated. Use `tools/get_affinity_list_fields.py` or `tools/print_fields.py` to look up current IDs. |

## Project Structure

* `function_app.py`: Entry point that registers the blueprint and Azure Function routes.
* `pitch_blueprint/handler.py`: Orchestrates the main data processing, validation, archiving, and syncing pipeline.
* `pitch_blueprint/affinity_client.py`: Modules for querying, creating, and updating Affinity CRM records, configured with connection pooling and exponential backoff.
* `pitch_blueprint/storage_client.py`: Modules for handling Blob archiving, Table deduplication logging, and Queue dead-lettering.
* `pitch_blueprint/validators.py`: Handles data validation, required field checks, and data type coercion.
* `pitch_blueprint/cloudflare_turnstile.py`: Handles server-side CAPTCHA token verification.
* `form/form.html`: The client-side HTML, CSS, and JavaScript implementation of the pitch intake form.
* `tools/`: A suite of standalone scripts used for environment configuration, including querying available Affinity lists, fields, and dropdown options.
