"use client";

import { CheckCircle2, XCircle } from "lucide-react";
import clsx from "clsx";
import type { AnswerFeedback, QuizQuestion } from "@/lib/types";
import { useT } from "@/lib/i18n-client";

export function AnswerOption({ optionKey, text, selected, state, disabled, onSelect }: {
  optionKey: string; text: string; selected: boolean; state: "idle" | "correct" | "incorrect" | "reveal"; disabled: boolean; onSelect: () => void;
}) {
  return (
    <label className={clsx(
      "flex cursor-pointer items-start gap-3 rounded-xl border-2 px-4 py-3 transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-accent/40",
      state === "correct" && "border-success bg-success/10",
      state === "incorrect" && "border-danger bg-danger/10",
      state === "reveal" && "border-success/60 bg-success/5",
      state === "idle" && (selected ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-accent/40"),
      disabled && "cursor-default",
    )} data-testid={`option-${optionKey}`}>
      <input type="radio" name="answer" value={optionKey} checked={selected} disabled={disabled} onChange={onSelect} className="sr-only" />
      <span aria-hidden className={clsx("flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-sm font-semibold",
        state === "idle" && selected ? "bg-accent text-accent-ink" : "bg-line/60 text-muted",
        state === "correct" || state === "reveal" ? "!bg-success !text-white" : "", state === "incorrect" ? "!bg-danger !text-white" : "")}>{optionKey}</span>
      <span className="pt-0.5">{text}</span>
      {state === "correct" && <CheckCircle2 className="ml-auto h-5 w-5 shrink-0 text-success" aria-label="correct" />}
      {state === "incorrect" && <XCircle className="ml-auto h-5 w-5 shrink-0 text-danger" aria-label="incorrect" />}
    </label>
  );
}

export function QuizQuestionCard({ question, selected, onSelect, feedback }: {
  question: QuizQuestion; selected: string | null; onSelect: (k: string) => void; feedback: AnswerFeedback | null;
}) {
  const { t } = useT();
  const locked = feedback != null;
  return (
    <fieldset className="space-y-4" data-testid="quiz-question">
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="chip">{t(`quiz.type_${question.question_type}`)}</span>
        <span className="chip">{t("quiz.difficulty")}: {t(`quiz.difficulty${question.difficulty}`)}</span>
      </div>
      <legend className="sr-only">{question.question_text}</legend>
      <p className="text-lg font-medium leading-relaxed" aria-hidden>{question.question_text}</p>
      <div role="radiogroup" aria-label={t("quiz.selectOption")} className="space-y-2.5">
        {question.options.map((o) => {
          let state: "idle" | "correct" | "incorrect" | "reveal" = "idle";
          if (feedback) {
            if (o.key === feedback.correct_option_key) state = o.key === feedback.selected_option_key ? "correct" : "reveal";
            else if (o.key === feedback.selected_option_key) state = "incorrect";
          }
          return <AnswerOption key={o.key} optionKey={o.key} text={o.text} selected={selected === o.key} state={state} disabled={locked} onSelect={() => onSelect(o.key)} />;
        })}
      </div>
    </fieldset>
  );
}
