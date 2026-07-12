# Infra — Legal GraphRAG

Docker Compose setup cho Neo4j 5.26.28 Community — graph database + vector index của hệ thống Legal GraphRAG.

---

## Cấu trúc

```
infra/
├── docker-compose.yml              # Neo4j service definition
├── docker-compose.m3.yml           # Dedicated disposable Milestone A runtime
├── .env.example                    # Template env vars
├── Makefile                        # Shortcut commands
└── neo4j/
    └── init/
        └── 01_schema_init.cypher   # Uniqueness constraints + indexes + vector index
```

---

## Lần đầu setup

```bash
# 1. Copy env và điền password
cp .env.example .env
# Sửa NEO4J_PASSWORD trong .env

# 2. Khởi động Neo4j (tự chờ đến khi healthy)
make up

# 3. Khởi tạo schema (idempotent, có thể chạy lại)
make init-schema

# 4. Verify
make verify-schema
```

Sau bước 4, kết quả mong đợi:
- `9` uniqueness constraints cho `Document`, `Issuer`, `Chapter`, `Article`, `Clause`, `Point`, `LegalConcept`, `LegalSubject`, `LegalAction`
- `10+` indexes (lookup + temporal + fulltext + vector)
- `2` vector indexes (`article_embedding`, `clause_embedding` — 1024 dims, cosine)

---

## Các lệnh thường dùng

| Lệnh | Tác dụng |
|---|---|
| `make up` | Start Neo4j, đợi healthy |
| `make down` | Stop Neo4j |
| `make logs` | Xem logs real-time |
| `make status` | Kiểm tra container health |
| `make init-schema` | Apply schema (idempotent, safe to rerun) |
| `make verify-schema` | In ra list constraints + indexes |
| `make shell-neo4j` | Mở cypher-shell interactive |
| `make clean` | Xóa toàn bộ data volumes (⚠️ không phục hồi được) |

## Disposable M3 runtime

Milestone A không dùng development database ở port `7687`. Runtime riêng có
container `graphrag-neo4j-m3`, named volume `graphrag-neo4j-m3-data`, Browser
port `7475`, và Bolt port `7688`.

```bash
make m3-up
make m3-init-schema
make m3-verify-schema
make m3-status
make m3-snapshot OUTPUT=empty.json
make m3-write
make m3-snapshot OUTPUT=write_1.json
make m3-embed
make m3-vector-smoke
make m3-graph-quality
make m3-integration
```

Reset là destructive nhưng chỉ áp dụng cho named volume M3. Cả hai opt-in là bắt buộc:

```bash
RUN_M3_DESTRUCTIVE=1 CONFIRM_M3_RESET=YES make m3-reset
```

Integration tests cũng fail-closed và chỉ nhận disposable URI:

```bash
cd ..
RUN_NEO4J_INTEGRATION=1 \
NEO4J_URI=bolt://localhost:7688 \
uv run pytest tests/integration -q -m integration
```

Không dùng `RUN_NEO4J_INTEGRATION` để cấp quyền reset và không dùng
`RUN_M3_DESTRUCTIVE` để bỏ qua integration guard.

---

## Truy cập

| Interface | URL | Dùng để |
|---|---|---|
| Neo4j Browser | http://localhost:7474 | Viết Cypher, xem graph visual |
| Bolt (driver) | bolt://localhost:7687 | Python/pipeline kết nối |
| M3 Neo4j Browser | http://localhost:7475 | Disposable Milestone A only |
| M3 Bolt | bolt://localhost:7688 | Guarded M3 write/test/snapshot |

Credentials: `neo4j` / giá trị `NEO4J_PASSWORD` trong `.env`

---

## Schema overview

Toàn bộ spec hiện hành tại [`plans/legal_ontology.md`](../plans/legal_ontology.md). [`plans/archive/02_ontology_specification_superseded.md`](../plans/archive/02_ontology_specification_superseded.md) chỉ là tài liệu lịch sử.

### Node types
```
:Document
:Issuer
:Chapter
:Article    (embedding 1024d)
:Clause     (embedding 1024d — unit retrieval chính)
:Point
:LegalConcept
:LegalSubject
:LegalAction
```

### Relation types
```
ISSUED_BY, CONTAINS, AMENDS, REPEALS, REPLACES, GUIDES,
REFERS_TO, DEFINES, REGULATES, REQUIRES, HAS_CONDITION, HAS_EXCEPTION
```

Legacy aliases như `AMENDED_BY`, `REPEALED_BY`, `REPLACED_BY`, `IMPLEMENTED_BY`, `REFERENCES` không phải behavior hiện hành.

### Quick verify query (chạy trong Neo4j Browser)
```cypher
// Xem toàn bộ schema
:schema

// Xem vector indexes
SHOW VECTOR INDEXES;

// Test vector index hoạt động
CALL db.index.vector.queryNodes('clause_embedding', 5, $embedding)
YIELD node, score RETURN node.id, score;
```

---

## Notes

- **APOC**: Tự download khi Neo4j khởi động lần đầu (cần internet). Dùng cho `apoc.path.expand` trong retrieval query.
- **Data persistence**: Dùng bind mounts tại `infra/data/neo4j/`. Data không mất khi `make down`, chỉ mất khi `make clean`.
- **`IF NOT EXISTS`**: Script `01_schema_init.cypher` idempotent — chạy nhiều lần không bị lỗi.
- **Community Edition boundary**: `01_schema_init.cypher` chỉ bootstrap uniqueness constraints và indexes. Mọi mandatory property checks phải chạy ở application layer trước `MERGE`.
- **Enterprise note**: Database-level existence/type constraints chỉ là hướng mở rộng tương lai nếu chuyển sang Enterprise Edition.
