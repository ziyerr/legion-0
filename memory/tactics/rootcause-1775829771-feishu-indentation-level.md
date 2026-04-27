---
name: Feishu descendants API rejects indentation_level on creation
description: Any value of bullet/ordered.style.indentation_level in create_document_block_descendant triggers failure (99992402 or 4000501), even with the "valid" enum literals
type: rootcause
---

# Feishu docx descendants API — indentation_level is unsettable at creation

## Symptom

`POST /open-apis/docx/v1/documents/{doc}/blocks/{doc}/descendant` returns:

- `HTTP 400 / code=99992402 "field validation failed"` — with field_violations pointing to `descendants[*].bullet.style.indentation_level`, value `"1"`, description `"options: [NoIndent, OneLevelIndent]"`.

Or, after "fixing" the field to one of the listed enums:

- `HTTP 200 / code=4000501 "open api operation and block not match"`.

The descendants insert silently falls back to flat `/children` in caller code, which drops table rendering.

## Five Whys

1. **Why HTTP 400?** Field validation on `bullet.style.indentation_level = "1"`.
2. **Why was `"1"` sent?** The builder did `str(indent_level)` believing the SDK's `indentation_level: Optional[str]` meant "stringified number".
3. **Why was that a plausible mistake?** The SDK type is `str` with no enum annotation. The only hint is the runtime validator's error message listing `[NoIndent, OneLevelIndent]`.
4. **Why did "OneLevelIndent" also fail?** Because `create_document_block_descendant` does not accept `indentation_level` at all during creation — even enum-valid values return business code 4000501.
5. **Why isn't this documented?** Feishu's error message is double-misleading: first it advertises an enum that, once used, triggers a different error. The field is effectively set-via-update-block-only, but nothing in the SDK or error path says so.

**Structural root cause:** Feishu exposes some block style fields that are accepted by the schema validator but rejected by the operation router on creation. The SDK's `str` annotation plus the validator's "options" hint combine to lure implementations into a configuration that is doubly wrong.

## Reproduction

Matrix against a fresh doc, inserting a single bullet block with different style payloads:

| `indentation_level` value | Result |
|---|---|
| `"1"` (numeric string) | HTTP 400, code 99992402, field validation failed |
| `1` (int) | HTTP 400, code 99992402, type error |
| `"NoIndent"` | HTTP 200, code 4000501, operation and block not match |
| `"OneLevelIndent"` | HTTP 200, code 4000501, operation and block not match |
| field omitted | HTTP 200, code 0, success |

Same behavior for `ordered.style.indentation_level`.

## Definitive fix

**Never set `indentation_level` in descendants-API block payloads.** If visual nesting is needed, either:
1. Flatten nested items to level 0 (acceptable for PRD content).
2. Create blocks first, then issue a follow-up `update_document_block` call to set `indentation_level` (adds a round-trip per list item, not worth it for most content).
3. Prefix nested text with whitespace / unicode bullets in the text run itself.

## Prevention

- When calling an OpenAPI style endpoint from raw JSON (bypassing SDK builders), do not assume SDK field-type annotations correspond to validator rules. Test each style field against a fresh doc with a one-block smoke test before relying on it in production markdown.
- When a "field validation failed" message lists valid enum values, treat them as necessary-but-not-sufficient. Always perform a second smoke test with the supposedly-valid value.
- Descendants-API builders that accept nested markdown should either (a) emit only the minimal style fields known to work on creation, or (b) split creation from styling into two phases.

## Red flag signature

- `code=99992402` with field_violations naming a `style.*` field
- `code=4000501 "open api operation and block not match"` — nearly always means a field in the block payload is legal by schema but illegal for the operation.

## File touched

- `~/.hermes/plugins/prodmind/feishu_api.py` — `markdown_to_descendants.make_block` no longer writes `indentation_level`; parameter retained for call-site backward compatibility but ignored.
