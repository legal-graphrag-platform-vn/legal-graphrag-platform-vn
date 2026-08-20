import os
import asyncio
from neo4j import GraphDatabase

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "123456789")

driver = GraphDatabase.driver(
    os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
)

def get_doc():
    with driver.session() as session:
        result = session.run("MATCH (d:Document) WHERE d.id CONTAINS '13/1999/QH10' RETURN d.id, d.legal_status, d.effective_from, d.effective_to")
        for record in result:
            print(dict(record))

get_doc()
driver.close()
