import os
from dotenv import load_dotenv
import snowflake.connector

load_dotenv()



class SnowflakeService:

    def connect(self):

        conn = snowflake.connector.connect(

            user=os.getenv(
                "SNOWFLAKE_USER"
            ),

            password=os.getenv(
                "SNOWFLAKE_PASSWORD"
            ),

            account=os.getenv(
                "SNOWFLAKE_ACCOUNT"
            )

        )

        return conn



    def execute_query(
        self,
        query
    ):

        conn=self.connect()

        cursor=conn.cursor()

        try:

            cursor.execute(query)

            return cursor.fetchall()

        finally:

            cursor.close()
            conn.close()