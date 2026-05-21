## Xactly Confidential Author - Vikas R (X003286)

class CaseService:

    def __init__(self, sf_client):

        self.sf = sf_client

    def get_recent_cases(self):

        query = """
        SELECT
            Id,
            CaseNumber,
            Subject,
            Status,
            Owner.Name,
            Account.Name,
            Support_Level__c,
            Severity__c,
            Sevone__c,
            IsEscalated,
            (select CreatedBy.Name,
            CreatedDate,
            IsPublished from CaseComments where IsPublished=true order by CreatedDate Desc)
        FROM Case
        WHERE Status IN ('New', 'Open', 'Assigned') and  Owner.Name IN (
    'Abhishek Bose', 'Amit Bhojak', 'Amit Kumar', 'Amith Gujjar', 'Aniket Chinde', 
    'Anthony Pham', 'Aqsa Pandith', 'Becca Lozano', 'Chethan Kumar P.', 'Ganesh Babu', 
    'Gnanasiri Pechetti', 'Imari Killikelly', 'Infant Raj.', 'Ishaq Mathina', 'Joshua Halle', 
    'Kalyan Kumar', 'Karalie Murray', 'Karthik Dosapati', 'Kaushik Patowary', 'Mahesh P M', 
    'Merlyn Pushparaj', 'Mohamed Ramzin', 'Mohammad Raza', 'Mohammed Usman', 'Monika Sihag', 
    'Mugilan Gowthaman', 'Naveen Kumar Surisetti', 'Nilanjan Roy', 'Nupur Rao', 'Palak Kharche', 
    'Pallavi M R', 'Payal Gupta', 'Peter Kyller', 'Pooja Singh', 'Poonam Pandey', 
    'Prabu Rajendran', 'Prabu', 'Rohit Nargundkar', 'Sakthi Devi SK', 'Sanjay Kademani', 
    'Santosh Veduruvada', 'Santi Sahoo', 'Selvin Raja', 'Shahrukh Shahzad', 'Shakti Prasad Pati', 
    'Shreyas G Nambiar', 'Shivendra Yadav', 'Sindhu M Y', 'Sivagnana Bharathi Nagaraj', 'Sivaji Koya', 
    'Srinivas Aaguri', 'Sumit Paul', 'Sumit', 'Sushmitha Rayalkeri', 'Syeda Sajida', 
    'Tarun Buthala', 'Ullas Shenoy', 'Vikas R', 'Vilas Potadar', 'Vipul SG', 
    'Vishal Mavi', 'Yogesh R', 'Zareena Bano', 'Zareena'
)

        """

        result = self.sf.query_all(query)

        return result["records"]