"use client";

import { memo, useEffect, useState } from "react";
import type { RefObject } from "react";
import { MAX_REQUIREMENTS_TEXT } from "../../lib/research-draft";
import { Field, FieldLabel } from "./workbench-ui";

type QuestionFieldProps = {
  value: string;
  disabled: boolean;
  invalid: boolean;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onValueChange: (value: string) => void;
};

export const ResearchQuestionField = memo(function ResearchQuestionField({
  value,
  disabled,
  invalid,
  textareaRef,
  onValueChange,
}: QuestionFieldProps) {
  const [question, setQuestion] = useState(value);

  useEffect(() => setQuestion(value), [value]);

  return (
    <Field invalid={invalid}>
      <div className="desk-input-label">
        <FieldLabel htmlFor="question">
          What do you need to understand?
        </FieldLabel>
        <span>{question.trim().length}/1000</span>
      </div>
      <textarea
        id="question"
        ref={textareaRef}
        value={question}
        onBlur={() => {
          // Spacebar page-scrolling while the field is focused piles spaces up
          // invisibly. A field holding nothing visible should be empty: the
          // counter then reads honest, and phantom text never enters the draft.
          if (question.length > 0 && question.trim() === "") {
            setQuestion("");
            onValueChange("");
          }
        }}
        onChange={(event) => {
          const next = event.target.value;
          setQuestion(next);
          onValueChange(next);
        }}
        placeholder="Ask a question, compare alternatives, or investigate a decision…"
        maxLength={1000}
        rows={6}
        required
        disabled={disabled}
        aria-invalid={invalid}
        aria-describedby="scope-note"
      />
    </Field>
  );
});

type RequirementsFieldProps = {
  value: string;
  disabled: boolean;
  onValueChange: (value: string) => void;
};

export const ResearchRequirementsField = memo(
  function ResearchRequirementsField({
    value,
    disabled,
    onValueChange,
  }: RequirementsFieldProps) {
    const [requirements, setRequirements] = useState(value);

    useEffect(() => setRequirements(value), [value]);

    return (
      <Field>
        <FieldLabel htmlFor="report-requirements">
          Report requirements
        </FieldLabel>
        <textarea
          id="report-requirements"
          value={requirements}
          onBlur={() => {
            if (requirements.length > 0 && requirements.trim() === "") {
              setRequirements("");
              onValueChange("");
            }
          }}
          onChange={(event) => {
            const next = event.target.value;
            setRequirements(next);
            onValueChange(next);
          }}
          maxLength={MAX_REQUIREMENTS_TEXT}
          rows={4}
          disabled={disabled}
          aria-describedby="requirements-note"
          placeholder="Compare costs and trade-offs\nInclude implementation risks"
        />
        <p id="requirements-note" className="desk-help">
          Optional. One requirement per line, up to 20 requirements and 500
          characters each.
        </p>
      </Field>
    );
  },
);
