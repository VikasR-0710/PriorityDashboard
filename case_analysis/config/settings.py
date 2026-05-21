import os
from dotenv import load_dotenv

load_dotenv()



SALESFORCE_USERNAME = os.getenv(
    "SALESFORCE_USERNAME"
)

SALESFORCE_COMBINED = os.getenv(
    "SALESFORCE_COMBINED"
)

SALESFORCE_DOMAIN = os.getenv(
    "SALESFORCE_DOMAIN"
)



OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY"
)

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY"
)



APTEDGE_API_KEY = os.getenv(
    "APTEDGE_API_KEY"
)

APTEDGE_BASE_URL = os.getenv(
    "APTEDGE_BASE_URL"
)

APTEDGE_MODEL = os.getenv(
    "APTEDGE_MODEL"
)