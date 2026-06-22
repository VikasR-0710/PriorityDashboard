import os
from openai import OpenAI
from config.delinea_loader import fetch_openai_credentials

class OpenAIService:
    def __init__(self):
        # 1. Try Delinea first
        creds = fetch_openai_credentials()
        
        if creds and creds.get("api_key"):
            api_key = creds["api_key"]
        else:
            # 2. Fallback to .env
            api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError("OpenAI API Key is missing. Check Delinea or .env file.")

        self.client = OpenAI(api_key=api_key)

    def get_connection(self):
        return self.client