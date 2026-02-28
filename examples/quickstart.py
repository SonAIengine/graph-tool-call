"""graph-tool-call quickstart example."""

from graph_tool_call import ToolGraph

# 1. Create a ToolGraph
tg = ToolGraph()

# 2. Register tools (OpenAI function-calling format)
openai_tools = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file from disk",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                    "encoding": {"type": "string", "description": "File encoding"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write contents to a file on disk",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file from the filesystem",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to delete"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List all files and directories in a given path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": "Execute a SQL query on the database",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL query string"},
                },
                "required": ["sql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_record",
            "description": "Insert a new record into a database table",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "Table name"},
                    "data": {"type": "object", "description": "Record data"},
                },
                "required": ["table", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email to a recipient",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
]

tg.add_tools(openai_tools)
print(f"Registered: {tg}")

# 3. Organize tools with categories and relations
tg.add_domain("io", description="Input/Output operations")
tg.add_domain("data", description="Data management")

tg.add_category("file_operations", domain="io", description="File system operations")
tg.add_category("database", domain="data", description="Database operations")
tg.add_category("communication", description="External communication tools")
tg.add_category("search", description="Information retrieval")

tg.assign_category("read_file", "file_operations")
tg.assign_category("write_file", "file_operations")
tg.assign_category("delete_file", "file_operations")
tg.assign_category("list_directory", "file_operations")
tg.assign_category("query_database", "database")
tg.assign_category("insert_record", "database")
tg.assign_category("send_email", "communication")
tg.assign_category("search_web", "search")

# 4. Define explicit relations
tg.add_relation("read_file", "write_file", "complementary")
tg.add_relation("write_file", "delete_file", "similar_to")
tg.add_relation("query_database", "insert_record", "complementary")
tg.add_relation("list_directory", "read_file", "requires")

print(f"After organizing: {tg}")

# 5. Query-based retrieval
queries = [
    "I want to read a file and save changes",
    "query the database and insert new data",
    "send an email with search results",
    "list and delete files",
]

for query in queries:
    results = tg.retrieve(query, top_k=3)
    tool_names = [t.name for t in results]
    print(f"\nQuery: '{query}'")
    print(f"  Retrieved: {tool_names}")

# 6. Save and load
tg.save("/tmp/tool_graph.json")
loaded = ToolGraph.load("/tmp/tool_graph.json")
print(f"\nLoaded from disk: {loaded}")
