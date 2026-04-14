from google_auth_oauthlib.flow import Flow

client_config = {
    "web": {
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost:8000/auth/callback"],
    }
}
flow = Flow.from_client_config(
    client_config,
    scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    redirect_uri="http://localhost:8000/auth/callback",
)

try:
    flow.fetch_token(code="dummy_code_that_should_trigger_a_400_from_google")
except Exception as e:
    import traceback
    traceback.print_exc()
