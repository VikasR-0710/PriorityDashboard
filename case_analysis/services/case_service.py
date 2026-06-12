import os
from simple_salesforce import Salesforce
from case_analysis.config.settings import SALESFORCE_USERNAME, SALESFORCE_COMBINED, SALESFORCE_DOMAIN
from case_analysis.config.delinea_loader import fetch_salesforce_credentials

class SalesforceConnector:
    def __init__(self):
        self.sf = None

    def connect(self):
        # 1. Try Delinea first
        creds = fetch_salesforce_credentials()
        
        if creds and creds.get("username") and creds.get("password"):
            username = creds["username"]
            password = creds["password"]
            security_token = creds.get("security_token") or os.getenv("SALESFORCE_SECURITY_TOKEN", "")
            domain = os.getenv("SALESFORCE_DOMAIN", "login")
        else:
            # 2. Fallback to .env (preserving your original combined logic)
            username = SALESFORCE_USERNAME
            combined = SALESFORCE_COMBINED or ""
            
            if len(combined) >= 24:
                password = combined[:-24]
                security_token = combined[-24:]
            else:
                password = combined
                security_token = ""
            domain = SALESFORCE_DOMAIN or "login"

        if not all([username, password, domain]):
            raise ValueError("Salesforce credentials are missing. Check Delinea or .env file.")

        self.sf = Salesforce(
            username=username,
            password=password,
            security_token=security_token,
            domain=domain
        )
        print("✅ Connected to Salesforce")
        return self.sf


class CaseService:
    def __init__(self):
        connector = SalesforceConnector()
        self.sf = connector.connect()

    def get_connection(self):
        return self.sf