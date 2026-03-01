"""Benchmark datasets for retrieval evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field

from graph_tool_call.core.tool import ToolParameter, ToolSchema


@dataclass
class QueryCase:
    """A single benchmark query with ground-truth relevant tools."""

    query: str
    relevant_tools: set[str]
    workflow: list[str] = field(default_factory=list)
    description: str = ""


def _tool(
    name: str,
    desc: str,
    params: list[tuple[str, str]] | None = None,
    tags: list[str] | None = None,
    domain: str | None = None,
) -> ToolSchema:
    parameters = [ToolParameter(name=n, type=t) for n, t in (params or [])]
    return ToolSchema(
        name=name, description=desc, parameters=parameters, tags=tags or [], domain=domain
    )


def petstore_dataset() -> tuple[list[ToolSchema], list[QueryCase]]:
    """Petstore-based benchmark dataset.

    Returns
    -------
    tuple[list[ToolSchema], list[QueryCase]]
        Tools and query cases with ground-truth.
    """
    tools = [
        _tool(
            "listPets",
            "List all pets",
            [("limit", "integer"), ("status", "string")],
            ["pet"],
            "pets",
        ),
        _tool(
            "createPet",
            "Create a new pet",
            [("name", "string"), ("status", "string")],
            ["pet"],
            "pets",
        ),
        _tool("getPetById", "Get a pet by ID", [("petId", "integer")], ["pet"], "pets"),
        _tool(
            "updatePet",
            "Update an existing pet",
            [("petId", "integer"), ("name", "string")],
            ["pet"],
            "pets",
        ),
        _tool("deletePet", "Delete a pet", [("petId", "integer")], ["pet"], "pets"),
        _tool("findPetsByStatus", "Find pets by status", [("status", "string")], ["pet"], "pets"),
        _tool("getInventory", "Returns pet inventories", [], ["store"], "store"),
        _tool(
            "placeOrder",
            "Place an order for a pet",
            [("petId", "integer"), ("quantity", "integer")],
            ["store"],
            "store",
        ),
        _tool(
            "getOrderById",
            "Find purchase order by ID",
            [("orderId", "integer")],
            ["store"],
            "store",
        ),
        _tool("deleteOrder", "Delete purchase order", [("orderId", "integer")], ["store"], "store"),
        _tool(
            "createUser",
            "Create user",
            [("username", "string"), ("email", "string")],
            ["user"],
            "user",
        ),
        _tool(
            "loginUser",
            "Log user into the system",
            [("username", "string"), ("password", "string")],
            ["user"],
            "user",
        ),
        _tool("logoutUser", "Log out current user", [], ["user"], "user"),
        _tool("getUserByName", "Get user by username", [("username", "string")], ["user"], "user"),
        _tool("updateUser", "Update user", [("username", "string")], ["user"], "user"),
        _tool("deleteUser", "Delete user", [("username", "string")], ["user"], "user"),
    ]

    queries = [
        QueryCase(
            query="find available pets",
            relevant_tools={"listPets", "findPetsByStatus"},
            description="Basic pet listing",
        ),
        QueryCase(
            query="add a new pet to the store",
            relevant_tools={"createPet"},
            description="Create operation",
        ),
        QueryCase(
            query="adopt a pet",
            relevant_tools={"getPetById", "updatePet", "placeOrder"},
            workflow=["findPetsByStatus", "getPetById", "placeOrder"],
            description="Multi-step workflow",
        ),
        QueryCase(
            query="manage user account",
            relevant_tools={"createUser", "getUserByName", "updateUser", "deleteUser"},
            description="CRUD user operations",
        ),
        QueryCase(
            query="check inventory and place order",
            relevant_tools={"getInventory", "placeOrder"},
            workflow=["getInventory", "placeOrder"],
            description="Store workflow",
        ),
        QueryCase(
            query="user login and profile",
            relevant_tools={"loginUser", "getUserByName"},
            workflow=["loginUser", "getUserByName"],
            description="Auth + profile flow",
        ),
        QueryCase(
            query="remove pet and cancel order",
            relevant_tools={"deletePet", "deleteOrder"},
            description="Multi-delete",
        ),
        QueryCase(
            query="update pet status",
            relevant_tools={"updatePet", "findPetsByStatus"},
            description="Update + search",
        ),
    ]

    return tools, queries


def synthetic_dataset(n: int = 500) -> tuple[list[ToolSchema], list[QueryCase]]:
    """Generate a synthetic dataset with n tools for stress testing.

    Parameters
    ----------
    n:
        Number of tools to generate.

    Returns
    -------
    tuple[list[ToolSchema], list[QueryCase]]
        Synthetic tools and query cases.
    """
    domains = ["user", "product", "order", "payment", "notification", "analytics", "auth", "file"]
    actions = ["get", "list", "create", "update", "delete", "search", "export", "import"]

    tools: list[ToolSchema] = []
    for i in range(n):
        domain = domains[i % len(domains)]
        action = actions[i % len(actions)]
        name = f"{action}_{domain}_{i}"
        desc = f"{action.capitalize()} {domain} resource #{i}"
        tools.append(
            _tool(
                name,
                desc,
                params=[(f"{domain}_id", "string"), ("limit", "integer")],
                tags=[domain, action],
                domain=domain,
            )
        )

    queries = [
        QueryCase(
            query=f"find {domain} items",
            relevant_tools={
                t.name
                for t in tools
                if domain in t.tags and ("search" in t.tags or "list" in t.tags)
            },
            description=f"Search {domain}",
        )
        for domain in domains[:4]
    ]

    return tools, queries
