#!/usr/bin/env bash
set -euo pipefail

service_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
schema_dir="$service_dir/../../packages/contracts/schema"
output_dir="$service_dir/src/research_api/schemas/generated"

mkdir -p "$output_dir"

contracts=(
  "ExecutionTaskSchema:execution_task:ExecutionTask"
  "FollowupRequestSchema:followup_request:FollowupRequest"
  "PublicGapSchema:public_gap:PublicGap"
  "RunInsightsSchema:run_insights:RunInsights"
  "PublicClaimCheckSchema:public_claim_check:PublicClaimCheck"
  "AgentEventSchema:agent_event:AgentEvent"
  "BudgetSchema:budget:Budget"
  "CitationSchema:citation:Citation"
  "CitationVerificationSchema:citation_verification:CitationVerification"
  "CreateResearchRunRequestSchema:create_research_run_request:CreateResearchRunRequest"
  "CreateResearchRunResponseSchema:create_research_run_response:CreateResearchRunResponse"
  "EvidenceClaimSchema:evidence_claim:EvidenceClaim"
  "ProviderCallSchema:provider_call:ProviderCall"
  "ReflectionDecisionSchema:reflection_decision:ReflectionDecision"
  "ResearchGapSchema:research_gap:ResearchGap"
  "ResearchPlanSchema:research_plan:ResearchPlan"
  "ResearchRunProjectionSchema:research_run_projection:ResearchRunProjection"
  "ResearchStateSchema:research_state:ResearchState"
  "SourceSchema:source:Source"
  "SubQuestionSchema:sub_question:SubQuestion"
  "UsageSchema:usage:Usage"
  "WatermarkedRunProjectionSchema:watermarked_run_projection:WatermarkedRunProjection"
  "WorkerResultSchema:worker_result:WorkerResult"
)

for contract in "${contracts[@]}"; do
  IFS=: read -r schema module class_name <<< "$contract"
  uv run datamodel-codegen \
    --input "$schema_dir/$schema.json" \
    --input-file-type jsonschema \
    --output "$output_dir/$module.py" \
    --output-model-type pydantic_v2.BaseModel \
    --class-name "$class_name" \
    --snake-case-field \
    --allow-population-by-field-name \
    --use-standard-collections \
    --use-union-operator \
    --target-python-version 3.12 \
    --disable-timestamp \
    --formatters ruff-check ruff-format
done
