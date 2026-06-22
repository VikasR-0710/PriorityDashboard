
import os
import sys
import google.generativeai as genai

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import (
    GEMINI_API_KEY
)



class GeminiService:

    def __init__(self):

        genai.configure(
            api_key=GEMINI_API_KEY
        )

        self.model = genai.GenerativeModel(
            "models/gemini-2.5-flash"
        )



    def get_connection(self):

        return self.model