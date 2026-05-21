import google.generativeai as genai

from case_analysis.config.settings import (
    GEMINI_API_KEY
)

genai.configure(
    api_key=GEMINI_API_KEY
)



class GeminiService:

    def __init__(self):

        self.model = genai.GenerativeModel(
            "models/gemini-2.5-flash"
        )

    def analyze_case(self, case):

        prompt = f"""
        Analyze this Salesforce support case.

        Subject:
        {case['Subject']}

        Status:
        {case['Status']}
        """

        response = self.model.generate_content(
            prompt
        )

        return response.text