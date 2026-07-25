---
title: LangChain
description: Use graph-tool-call retrieval with LangChain tool adapters.
---

# LangChain

LangChain integrations should use graph-tool-call as a retrieval and filtering
layer before constructing the tool set sent to the model.

## Guidance

- retrieve a compact candidate set first
- preserve evidence for debugging
- keep execution credentials in the host application
- validate tool count and quality before widening the catalog

## Related Pages

- [Tool Graph Search](../search/tool-graph-search.mdx)
- [Public API](../reference/public-api.md)
