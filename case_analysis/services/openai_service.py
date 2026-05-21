## Xactly Confidential Author - Vikas R (X003286)

import os
from openai import OpenAI



class OpenAIService:

    def __init__(self):

        self.client = OpenAI(
            api_key=os.getenv(
                "OPENAI_API_KEY"
            )
        )



    def get_connection(self):

        return self.client