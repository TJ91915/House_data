# Energy Dashboard

Streamlit dashboard for half-hourly Octopus consumption + cost, read live from Google Sheets.

## Run locally

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/streamlit run app.py
```

Auth: put `service-account-key.json` in the project root (gitignored), or create `.streamlit/secrets.toml` (see below). The app tries secrets first, then falls back to the key file.

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub (public is fine — secrets aren't committed).
2. On [share.streamlit.io](https://share.streamlit.io), "New app" → point at the repo, main branch, `app.py`.
3. In the app's **Settings → Secrets**, paste the contents of `.streamlit/secrets.toml.example`, filled in from your `service-account-key.json`.
4. Deploy. App sleeps after ~7 days idle; cold start is ~30s.

## Secrets format

`.streamlit/secrets.toml` (local) or Streamlit Cloud Secrets UI:

```toml
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "...@...iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
universe_domain = "googleapis.com"
```

The service account email needs read access to the spreadsheet.

## Data

Reads `Energy_1` (half-hourly kWh) and `Tariffs` (unit rates, standing charges) from sheet `1stKNr_MzA3fJL3kKSofMqxK4Nu66XbVtqsLzyosKqpQ`. Cost is recomputed in Python via `merge_asof` on the tariff valid-from dates — independent of any sheet formulas. Sheet reads are cached 1h; sidebar has a manual refresh button.
