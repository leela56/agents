from google_auth_oauthlib.flow import Flow

client_config = {
    "web": {
        "client_id": "client_id_val",
        "client_secret": "client_secret_val",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost:8000/auth/callback"],
    }
}
flow = Flow.from_client_config(client_config, scopes=[])
print(flow.client_config)
