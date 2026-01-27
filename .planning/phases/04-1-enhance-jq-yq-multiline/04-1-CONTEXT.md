# Phase 4.1: Enhance jq/yq for Complex Multiline Queries - Context

**Gathered:** 2026-01-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Enhance existing query_json and query_yaml tools to handle complex multiline jq/yq expressions with comments, nested functions, and special characters. Does NOT add new query capabilities or file format support—focuses solely on eliminating escaping/parsing issues that break complex expressions.

**Concrete Problem:**
Agents send complex queries (like the dbt lineage traversal example with recursive functions and comments) that break when passed as command-line arguments to jq/yq binaries.

</domain>

<decisions>
## Implementation Decisions

### Input Method (Query Execution)
- Use **temp file approach**: Write query string to temporary file, pass file path to jq/yq binary
- For jq: Use `jq -f /tmp/query.jq data.json`
- For yq: Use `yq -f /tmp/query.yq data.yaml`
- Eliminates ALL escaping issues—handles comments, quotes, newlines, any complexity
- Temp files created in session scratchpad, cleaned up after execution

### Error Handling
- **Enhanced errors with context**: Catch jq/yq syntax errors and add helpful context
- Format: `jq syntax error at line X: [original error]. Check for [common issue hints]`
- Provide actionable guidance: unclosed brackets, missing semicolons, undefined functions
- Distinguish between jq/yq syntax errors vs. our tool errors (missing file, timeout)

### Query Limits
- **Same limits as simple queries**: No special treatment for multiline complexity
- 30-second timeout (consistent with current simple queries)
- 100 results max (consistent with bounded output principle)
- Complexity of expression doesn't change protection needs

### Agent Guidance
- **Simple example in tool description**: Add one multiline example to docstring
- Show that comments and line breaks work: "# comment\n.field | select(...)"
- Keep examples brief—agents can reference jq/yq docs for advanced syntax
- Don't overload docstrings with complexity tiers

### Claude's Discretion
- Temp file naming strategy (random suffix, timestamp, etc.)
- Exact common error patterns to detect and enhance (bracket matching, etc.)
- Cleanup timing for temp files (immediate vs. batch cleanup)
- Whether to preserve temp files on error for debugging

</decisions>

<specifics>
## Specific Ideas

**Real-world example that must work:**
```jq
# Step 1: Create a lookup map from parent -> [children]
(
  .nodes as $all_nodes |
  reduce ($all_nodes | keys[]) as $node_name ({};
    ($all_nodes[$node_name].depends_on.nodes[]?) as $parent_node |
    .[$parent_node] += [$node_name]
  )
) as $lineage_map |

# Step 2: Define recursive function
def get_all_descendants($model_name):
  ($lineage_map[$model_name] // []) as $direct_children |
  $direct_children[] |
  ($direct_children[] | get_all_descendants(.))
;

# Step 3: Start the process
get_all_descendants("model.estrid_dw.fct_transactions")
```

This query includes:
- Multi-line structure with comments
- Nested function definitions
- Complex pipe chains
- String literals with underscores and dots

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 04-1-enhance-jq-yq-multiline*
*Context gathered: 2026-01-27*
