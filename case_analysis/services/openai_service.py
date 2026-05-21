from openai import OpenAI
import os



class OpenAIService:

    def __init__(self):

        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY")
        )

    def analyze_case(self, case_data):

        prompt = f"""
        Analyze this Salesforce support case.

        Case Number:
        {case_data.get("CaseNumber")}

        Subject:
        {case_data.get("Subject")}

        Status:
        {case_data.get("Status")}

        Customer:
        {case_data.get("Account", {}).get("Name", "")}

        Escalated:
        {case_data.get("IsEscalated")}

        Return ONLY one word:

        Positive
        Neutral
        Negative
        Critical
        """

        response = self.client.chat.completions.create(

            model="gpt-4o-mini",

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            temperature=0
        )

        return response.choices[0].message.content.strip()