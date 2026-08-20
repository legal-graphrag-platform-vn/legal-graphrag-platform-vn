from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://graph-connection.lamdx4.duckdns.org:7687", auth=("neo4j", "123456789"))
with driver.session() as session:
    result = session.run("""
        MATCH (d:Document)
        WHERE toLower(d.title) CONTAINS "luật doanh nghiệp"
          AND toString(d.issued_date) CONTAINS "2020"
        RETURN properties(d) as props
    """)
    for r in result:
        print("===")
        for k, v in r['props'].items():
            print(f"{k}: {v}")
driver.close()
