package server

import (
	"encoding/json"
	"testing"
)

// TestAddCwdToSchema_RawMessage: hand-written raw schemas (jq/yq/hq/duckdb
// style) gain a cwd property.
func TestAddCwdToSchema_RawMessage(t *testing.T) {
	in := json.RawMessage(`{"type":"object","properties":{"results":{"type":"array","items":{}}}}`)
	out, changed := addCwdToSchema(in)
	if !changed {
		t.Fatal("expected amendment")
	}
	var obj map[string]any
	if err := json.Unmarshal(out, &obj); err != nil {
		t.Fatal(err)
	}
	props := obj["properties"].(map[string]any)
	if _, ok := props["cwd"]; !ok {
		t.Fatalf("cwd missing: %s", out)
	}
	if _, ok := props["results"]; !ok {
		t.Fatalf("original property lost: %s", out)
	}
}

// TestAddCwdToSchema_NoDoubleAdd: schemas already declaring cwd are left
// untouched.
func TestAddCwdToSchema_NoDoubleAdd(t *testing.T) {
	in := json.RawMessage(`{"type":"object","properties":{"cwd":{"type":"string"}}}`)
	if _, changed := addCwdToSchema(in); changed {
		t.Fatal("must not re-amend a schema that declares cwd")
	}
}

// TestAddCwdToSchema_Nil: tools without output schemas are skipped.
func TestAddCwdToSchema_Nil(t *testing.T) {
	if _, changed := addCwdToSchema(nil); changed {
		t.Fatal("nil schema must not be amended")
	}
}

// TestAddCwdToSchema_NonObject: only object schemas can carry properties.
func TestAddCwdToSchema_NonObject(t *testing.T) {
	in := json.RawMessage(`{"type":"string"}`)
	if _, changed := addCwdToSchema(in); changed {
		t.Fatal("non-object schema must not be amended")
	}
}

// TestAddCwdToSchema_TypedSchema: auto-inferred schemas arrive as structs that
// marshal to schema JSON — any JSON-marshalable value must work.
func TestAddCwdToSchema_TypedSchema(t *testing.T) {
	in := map[string]any{"type": "object", "properties": map[string]any{"stdout": map[string]any{"type": "string"}}}
	out, changed := addCwdToSchema(in)
	if !changed {
		t.Fatal("expected amendment")
	}
	var obj map[string]any
	if err := json.Unmarshal(out, &obj); err != nil {
		t.Fatal(err)
	}
	if _, ok := obj["properties"].(map[string]any)["cwd"]; !ok {
		t.Fatalf("cwd missing: %s", out)
	}
}
