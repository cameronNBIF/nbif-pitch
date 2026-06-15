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
3. **Deduplication Check:** The function generates a SHA-256 fingerprint using the submitter's email and business name. It queries Azure Table Storage to check for and reject duplicate submissions made within a 60-second window.
4. **Raw Archiving:** Before interacting with the CRM, the raw, validated submission is saved as a JSON file in Azure Blob Storage. This ensures no data is lost if downstream APIs fail.
5. **Affinity CRM Sync:**
   * **Person Resolution:** The function queries Affinity for an existing Person using the founder's email address. If no match is found, a new Person is created.
   * **Organization Resolution:** The function queries Affinity for an Organization using the business name. If no match is found, a new Organization is created.
   * **List Entry Creation:** The Organization is added to the specified Pitch Intake list.
   * **Field Population:** Global fields (e.g., Sector, Company Profile) are applied to the Organization entity, and list-specific fields (e.g., Investment Round Size, Potential Investment Amount) are applied directly to the list entry via `POST` requests.
6. **Post-Processing & Notifications:** The Azure Blob Storage archive is updated to include the newly generated Affinity IDs. Finally, an Adaptive Card summarizing the pitch is sent to a Microsoft Teams channel via a webhook.

## Reliability & Error Handling

To ensure data integrity, CRM operations are isolated from the initial data capture. If the Affinity API calls fail (e.g., due to an outage), the application catches the error and sends a payload containing the `submission_id`, error details, and the path to the Blob archive to an Azure Dead-Letter Queue (`pitchintakedeadletter`). This allows the team to manually review and re-process the submission later without asking the user to resubmit.

## Project Structure

* `function_app.py`: Entry point that registers the blueprint and Azure Function routes.
* `pitch_blueprint/handler.py`: Orchestrates the main data processing, validation, archiving, and syncing pipeline.
* `pitch_blueprint/affinity_client.py`: Modules for querying, creating, and updating Affinity CRM records, configured with connection pooling and exponential backoff.
* `pitch_blueprint/storage_client.py`: Modules for handling Blob archiving, Table deduplication logging, and Queue dead-lettering.
* `pitch_blueprint/validators.py`: Handles data validation, required field checks, and data type coercion.
* `pitch_blueprint/cloudflare_turnstile.py`: Handles server-side CAPTCHA token verification.
* `form/form.html`: The client-side HTML, CSS, and JavaScript implementation of the pitch intake form.
* `tools/`: A suite of standalone scripts used for environment configuration, including querying available Affinity lists, fields, and dropdown options.