import sys
from neo4j import GraphDatabase

uri = sys.argv[1]
try:
    driver = GraphDatabase.driver(uri, auth=("neo4j", "123456789"))
    driver.verify_connectivity()
    print(f"Success with {uri}!")
    driver.close()
except Exception as e:
    print(f"Failed {uri}: {e}")
