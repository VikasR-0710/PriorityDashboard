import os
from dotenv import load_dotenv
import snowflake.connector
from config.delinea_loader import fetch_snowflake_credentials

load_dotenv()

class SnowflakeService:
    def connect(self, warehouse=None, database=None, schema=None):
        # 1. Try Delinea first
        creds = fetch_snowflake_credentials()
        
        if creds and creds.get("user") and creds.get("password"):
            user = creds["user"]
            password = creds["password"]
            account = creds["account"]
        else:
            # 2. Fallback to .env
            user = os.getenv("SNOWFLAKE_USER")
            password = os.getenv("SNOWFLAKE_PASSWORD")
            account = os.getenv("SNOWFLAKE_ACCOUNT")

        if not all([user, password, account]):
            raise ValueError("Snowflake credentials are missing. Check Delinea or .env file.")

        conn_kwargs = {"user": user, "password": password, "account": account}
        role = os.getenv("SNOWFLAKE_ROLE", "").strip()
        if role: conn_kwargs["role"] = role
        if warehouse: conn_kwargs["warehouse"] = warehouse
        if database: conn_kwargs["database"] = database
        if schema: conn_kwargs["schema"] = schema

        return snowflake.connector.connect(**conn_kwargs)

    def execute_query(self, query):
        conn = self.connect()
        cursor = conn.cursor()
        try:
            cursor.execute(query)
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()
