## Xactly Confidential Author - Vikas R (X003286)


from simple_salesforce import Salesforce

from case_analysis.config.settings import (
    SALESFORCE_USERNAME,
    SALESFORCE_COMBINED,
    SALESFORCE_DOMAIN
)



class SalesforceConnector:

    def __init__(self):
        self.sf = None

    def connect(self):

        combined = SALESFORCE_COMBINED

        password = combined[:-24]

        security_token = combined[-24:]

        self.sf = Salesforce(
            username=SALESFORCE_USERNAME,
            password=password,
            security_token=security_token,
            domain=SALESFORCE_DOMAIN
        )

        print("Connected to Salesforce")

        return self.sf



class CaseService:

    def __init__(self):

        connector = SalesforceConnector()

        self.sf = connector.connect()



    def get_connection(self):

        return self.sf