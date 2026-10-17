#!/usr/bin/env bash
set -euo pipefail

service_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
schema_dir="$service_dir/../../packages/contracts/schema"
output_dir="$service_dir/src/research_api/schemas/generated"

mkdir -p "$output_dir"

contracts=(
  "ResearchModeSchema:research_mode:ResearchMode"
  "ResearchModeResolutionSchema:research_mode_resolution:ResearchModeResolution"
  "EditResearchPlanRequestSchema:edit_research_plan_request:EditResearchPlanRequest"
  "EditResearchPlanResponseSchema:edit_research_plan_response:EditResearchPlanResponse"
  "CreateProjectRequestSchema:create_project_request:CreateProjectRequest"
  "ProjectSchema:project:Project"
  "ProjectsResponseSchema:projects_response:ProjectsResponse"
  "SaveLibraryItemRequestSchema:save_library_item_request:SaveLibraryItemRequest"
  "OrganizeLibraryItemRequestSchema:organize_library_item_request:OrganizeLibraryItemRequest"
  "LibraryItemSchema:library_item:LibraryItem"
  "LibraryItemsResponseSchema:library_items_response:LibraryItemsResponse"
  "RemoveLibraryItemResponseSchema:remove_library_item_response:RemoveLibraryItemResponse"
  "ReportComparisonRequestSchema:report_comparison_request:ReportComparisonRequest"
  "ReportComparisonSchema:report_comparison:ReportComparison"
  "ComparedReportListSchema:compared_report_list:ComparedReportList"
  "ReportDocumentV1Schema:report_document_v1:ReportDocumentV1"
  "ReportDocumentV2Schema:report_document_v2:ReportDocumentV2"
  "ReportDocumentV3Schema:report_document_v3:ReportDocumentV3"
  "ReportDocumentV4Schema:report_document_v4:ReportDocumentV4"
  "ReportDocumentSchema:report_document:ReportDocument"
  "ApprovalRequestSchema:approval_request:ApprovalRequest"
  "BatchRequestSchema:batch_request:BatchRequest"
  "ScheduleRequestSchema:schedule_request:ScheduleRequest"
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
  # Optional exact schema selection preserves unrelated generated work in shared checkouts.
  if [[ $# -gt 0 && "$schema" != "$1" ]]; then
    continue
  fi
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
    --use-default \
    --target-python-version 3.12 \
    --disable-timestamp \
    --formatters ruff-check ruff-format
done
