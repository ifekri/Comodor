/**
 * A question form, with `@comodor/questions` holding the selection. Every
 * option the Core offered is shown; the write-your-own row is a text field.
 * Nothing is sent until the person answers or dismisses it, and the card
 * stays until the Core says the question is resolved.
 */

import { useState } from "react";

import type { QuestionRequest } from "@comodor/protocol";
import {
  answer,
  answerable,
  begin,
  cancel,
  type FormState,
  isSelected,
  select,
  type as write,
} from "@comodor/questions";
import type { Interaction } from "@comodor/session";

/** The same state, looking at question `index`. */
function at(state: FormState, index: number): FormState {
  return { ...state, at: index, writing: false };
}

export function FormCard({ interaction, onAnswer }: {
  interaction: Interaction;
  onAnswer: (params: Record<string, unknown>) => void;
}) {
  const request = interaction.request as unknown as QuestionRequest;
  // One card per request (the caller keys it by the request's id), so a
  // different request starts clean and a redelivery keeps the selection.
  const [form, setForm] = useState<FormState>(() => begin(request));

  const submitting = interaction.state === "submitting";
  return (
    <section className="card form-card" data-testid="form" data-id={request.id}>
      <h2>{request.title}</h2>
      {request.questions.map((question, index) => {
        const free = question.options.find((option) => option.free);
        return (
          <fieldset key={question.header} className="question">
            <legend>{question.header}</legend>
            <p className="prompt">{question.prompt}</p>
            <div className="options">
              {question.options.filter((option) => !option.free).map((option) => (
                <button key={option.id} type="button" disabled={submitting}
                        className={isSelected(at(form, index), option.id) ? "option chosen" : "option"}
                        aria-pressed={isSelected(at(form, index), option.id)}
                        onClick={() => setForm({ ...select(at(form, index), option.id), at: form.at })}>
                  <span className="option-label">{option.label}</span>
                  {option.description !== undefined && (
                    <span className="option-description">{option.description}</span>
                  )}
                </button>
              ))}
            </div>
            {free !== undefined && (
              <label className="free">
                <span>{free.label}</span>
                <input type="text" disabled={submitting} value={form.written[index] ?? ""}
                       onChange={(event) => {
                         const chosen = select(at(form, index), free.id);
                         setForm({ ...write(chosen, event.target.value), at: form.at, writing: false });
                       }} />
              </label>
            )}
          </fieldset>
        );
      })}
      {interaction.state === "failed" && <p className="card-error">{interaction.error}</p>}
      <div className="actions">
        <button type="button" disabled={submitting || !answerable(form)}
                onClick={() => onAnswer(answer(form) as unknown as Record<string, unknown>)}>
          Answer
        </button>
        <button type="button" disabled={submitting}
                onClick={() => onAnswer(cancel(form) as unknown as Record<string, unknown>)}>
          Dismiss
        </button>
      </div>
    </section>
  );
}
