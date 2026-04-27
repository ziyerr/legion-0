# Requirement Metadata Gate Decisions

## D1 [LOCKED] Gate Before Technical Planning

`design_tech_plan` must run `requirement_metadata_gate` before ADR lookup, LLM invocation, ADR writes, or Feishu document creation.

Rationale: if the input is not an atomic PRD, downstream technical artifacts become speculative and create false confidence.

## D2 [LOCKED] 「无」 Is Valid, Omission Is Not

A dimension that does not apply may pass only when explicitly written as 「无」 or an equivalent not-applicable value.

Rationale: explicit non-applicability forces AIPM/PM to think through each data/action dimension and prevents silent omissions.

## D3 [LOCKED] Gate Failure Is Business Blocking, Not Tool Error

Gate failure returns `success=true` with `blocking_downstream=true`, `feasibility=yellow`, and `missing_info`.

Rationale: incomplete PRD metadata is an intent/input-quality problem, not a runtime failure.

## D4 [LOCKED] AIPM Owns User Confirmation

AIPM/ProdMind and AICTO are independent projects. If AICTO sees that AIPM's design conflicts with the user request, or that AIPM has not discussed the requirement with the user, AICTO must block and ask AIPM to confirm the scenario, design direction, rationale, and boundaries with the user in Feishu.

Rationale: AICTO must not replace AIPM's product discovery role or directly rewrite PRD facts.

## D5 [LOCKED] AICTO Owns Delivery And Technical Acceptance

Once the requirement gate passes, AICTO owns technical planning, legion command, development progress, tests, review, and technical acceptance. AICTO then delivers an evidence-backed acceptance package to AIPM. AIPM owns product acceptance and user-facing reporting.

Rationale: this keeps WHAT/WHY and HOW accountability separate while making handoffs verifiable.

## D6 [LOCKED] Claude Code Official Workflow Absorption

From the referenced Claude Code tutorial video, AICTO absorbs: commandized workflows, project-context loading, tool/MCP integration, team-shared memory/permissions, keybinding discipline, and multi-Claude parallelism. These map to project commands/skills, requirement gate, MCP/tool contracts, shared planning/memory files, and L2 parallel execution.

Rationale: the video reinforces turning recurring agent work into explicit commands, context, tools, and team-shareable protocols rather than ad-hoc prompts.
