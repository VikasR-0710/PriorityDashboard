## Xactly Confidential Author - Vikas R (X003286)

from clients.salesforce_connector import SalesforceConnector



class CaseService:

    def __init__(self):

        connector = SalesforceConnector()

        self.sf = connector.connect()



    def get_connection(self):

        return self.sf