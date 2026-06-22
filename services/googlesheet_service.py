

import gspread
from google.oauth2.service_account import Credentials



class GoogleSheetService:

    def __init__(self):

        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]

        credentials = Credentials.from_service_account_file(
            "config/credentials.json",
            scopes=scope
        )

        self.client = gspread.authorize(
            credentials
        )



    def get_connection(self):

        return self.client