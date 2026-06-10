nbif-pitch-intake/
├── .funcignore
├── .gitignore
├── .venv/
├── function_app.py                          ← Entry point (imports blueprint)
├── host.json                                ← Function app configuration
├── local.settings.json                      ← Local app settings (not in Git)
├── requirements.txt                         ← Python dependencies
│
├── blueprint_pitch_intake/
│   ├── __init__.py                          ← Exports blueprint (bp)
│   ├── handler.py                           ← HTTP trigger — full pipeline orchestrator
│   ├── affinity_client.py                   ← Affinity API helpers (CRUD + file upload)
│   ├── storage_client.py                    ← Blob/Table/Queue helpers
│   ├── cloudflare_turnstile.py                         ← CAPTCHA verification
│   └── validators.py                        ← Input validation
│
└── tests/
    ├── __init__.py
    └── test_validators.py                   ← (placeholder for unit tests)