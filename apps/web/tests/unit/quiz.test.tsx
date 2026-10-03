import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { I18nProvider } from "@/lib/i18n-client";
import { QuizQuestionCard } from "@/features/quizzer/QuizQuestionCard";
import type { AnswerFeedback, QuizQuestion } from "@/lib/types";

const question: QuizQuestion = {
  id: "q1", question_text: "What does the author call the cost of an interruption?", question_type: "recall", difficulty: 1, position: 1,
  options: [{ key: "A", text: "switching tax" }, { key: "B", text: "latent pull" }, { key: "C", text: "ritual" }, { key: "D", text: "ledger" }],
};

function wrap(ui: React.ReactNode) {
  return render(<I18nProvider initialLocale="en">{ui}</I18nProvider>);
}

describe("QuizQuestionCard", () => {
  it("renders exactly four selectable options and reports the choice", () => {
    const onSelect = vi.fn();
    wrap(<QuizQuestionCard question={question} selected={null} onSelect={onSelect} feedback={null} />);
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(4);
    fireEvent.click(radios[1]!);
    expect(onSelect).toHaveBeenCalledWith("B");
  });

  it("locks options after feedback and marks correct and incorrect answers", () => {
    const feedback = { correct_option_key: "A", selected_option_key: "B", is_correct: false } as AnswerFeedback;
    wrap(<QuizQuestionCard question={question} selected="B" onSelect={() => undefined} feedback={feedback} />);
    for (const r of screen.getAllByRole("radio")) expect(r).toBeDisabled();
    expect(screen.getByLabelText("incorrect")).toBeInTheDocument();
  });
});
