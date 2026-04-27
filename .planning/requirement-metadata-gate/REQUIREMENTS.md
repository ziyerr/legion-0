# Requirement Metadata Gate Requirements

## User Requirement

Every requirement entering AICTO must be represented as atomic PRD metadata. Even a single field or button change must explicitly describe all dimensions of 「增删查改显算传」; if a dimension does not apply, it must be written as 「无」 and must not be omitted.

## Functional Requirements

- R1: AICTO must expose a reusable validation tool for requirement metadata.
- R2: The gate must require base atomic metadata: requirement ID, requirement title, atomic object, and acceptance criteria.
- R3: The gate must require full 5W1H: Who, What, Why, When, Where, and business How.
- R4: The gate must require full 「增删查改显算传」: create, delete, query, update, display, compute, and transmit.
- R5: Missing, blank, unknown, TODO, TBD, or pending values must fail the gate.
- R6: Explicit 「无」 / not-applicable values must pass for dimensions that truly do not apply.
- R7: `design_tech_plan` must run the gate before LLM/ADR/Feishu side effects.
- R8: Gate failure must return a structured blocking response with actionable clarification requests and a template.
- R9: The gate must require user-alignment metadata: original user request, AIPM design intent, user-alignment verdict, and Feishu confirmation record.
- R10: If AIPM design conflicts with the user request or has not been discussed with the user, AICTO must request AIPM to confirm the scenario, design direction, rationale, and boundaries with the user in Feishu.
- R11: AICTO must not continue to technical planning, task breakdown, or legion dispatch until AIPM updates the PRD and the gate passes.

## Acceptance

- A1: Complete structured metadata passes.
- A2: Missing dimensions fail and list exact missing sections.
- A3: Explicit 「无」 is accepted.
- A4: `design_tech_plan` does not call LLM when the gate fails.
- A5: Hermes registration exposes the new tool.
- A6: Conflict/unconfirmed user alignment fails and returns `requires_user_feishu_confirmation=true`.
- A7: AICTO can produce an AIPM clarification request without modifying AIPM/ProdMind data.
