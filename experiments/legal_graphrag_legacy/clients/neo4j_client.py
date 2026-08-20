import warnings
import logging
from neo4j import GraphDatabase
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

# Tắt cảnh báo từ module warnings
warnings.filterwarnings("ignore")

# Tắt tận gốc log rác (ví dụ: Received notification from DBMS server) từ thư viện neo4j
logging.getLogger("neo4j").setLevel(logging.ERROR)

class Neo4jClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Neo4jClient, cls).__new__(cls)
            cls._instance.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        return cls._instance

    def execute_query(self, query, **parameters):
        with self.driver.session() as session:
            result = session.run(query, **parameters)
            return [record for record in result]
            
    def close(self):
        self.driver.close()
