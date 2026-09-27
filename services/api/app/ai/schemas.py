"""JSON Schemas for every structured model output. Enforced for all providers (including the offline one).

Schemas follow structured-output constraints: every object lists all properties as required and sets
additionalProperties=false; "absent" values are expressed as empty strings/arrays instead of nulls.
"""

from __future__ import annotations

from typing import Any

IDS = {"type": "array", "items": {"type": "string"}}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


CLAIM = _obj({"text": {"type": "string"}, "evidence_ids": IDS})

SUMMARY_SCHEMA = _obj(
    {
        "title": {"type": "string"},
        "central_thesis": CLAIM,
        "sections": {
            "type": "array",
            "items": _obj(
                {
                    "heading": {"type": "string"},
                    "content": {"type": "string"},
                    "key_concepts": {"type": "array", "items": {"type": "string"}},
                    "evidence_ids": IDS,
                }
            ),
        },
        "definitions": {
            "type": "array",
            "items": _obj({"term": {"type": "string"}, "definition": {"type": "string"}, "evidence_ids": IDS}),
        },
        "examples": {"type": "array", "items": _obj({"description": {"type": "string"}, "evidence_ids": IDS})},
        "caveats": {"type": "array", "items": CLAIM},
        "connections": {"type": "array", "items": CLAIM},
        "conclusion": CLAIM,
        "takeaways": {"type": "array", "items": CLAIM},
        "known_gaps": {"type": "array", "items": {"type": "string"}},
        "language_ok": {"type": "boolean"},
    }
)

NOTES_SCHEMA = _obj(
    {
        "notes": {
            "type": "array",
            "items": _obj(
                {
                    "kind": {"type": "string", "enum": ["argument", "reasoning", "example", "definition", "caveat", "conclusion"]},
                    "text": {"type": "string"},
                    "evidence_ids": IDS,
                }
            ),
        },
        "language_ok": {"type": "boolean"},
    }
)

QA_SCHEMA = _obj(
    {
        "answerable": {"type": "boolean"},
        "answer": {"type": "string"},
        "evidence_ids": IDS,
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "unanswerable_reason": {"type": "string"},
        "language_ok": {"type": "boolean"},
    }
)

OPTION = _obj({"key": {"type": "string", "enum": ["A", "B", "C", "D"]}, "text": {"type": "string"}})

QUESTION_ITEM = _obj(
    {
        "question": {"type": "string"},
        "question_type": {"type": "string", "enum": ["recall", "comprehension", "application", "inference"]},
        "difficulty": {"type": "integer", "enum": [1, 2, 3]},
        "topic": {"type": "string"},
        "options": {"type": "array", "items": OPTION, "minItems": 4, "maxItems": 4},
        "correct_key": {"type": "string", "enum": ["A", "B", "C", "D"]},
        "evidence_ids": IDS,
        "explanation": {"type": "string"},
        "misconception": {"type": "string"},
    }
)

QUIZ_SCHEMA = _obj({"questions": {"type": "array", "items": QUESTION_ITEM}, "language_ok": {"type": "boolean"}})

VALIDATOR_SCHEMA = _obj(
    {
        "answer_key": {"type": "string", "enum": ["A", "B", "C", "D", "none"]},
        "checks": _obj(
            {
                "answer_supported": {"type": "boolean"},
                "distractors_incorrect": {"type": "boolean"},
                "unambiguous": {"type": "boolean"},
                "no_external_knowledge": {"type": "boolean"},
                "explanation_supports_answer": {"type": "boolean"},
                "language_ok": {"type": "boolean"},
            }
        ),
        "reason": {"type": "string"},
    }
)

EXPLAINER_SCHEMA = _obj(
    {"explanation": {"type": "string"}, "misconception": {"type": "string"}, "evidence_ids": IDS}
)

CHAPTER_DETECTOR_SCHEMA = _obj(
    {"chapter_start_indices": {"type": "array", "items": {"type": "integer"}}, "confidence": {"type": "string", "enum": ["high", "medium", "low"]}}
)

REPAIR_SCHEMA = _obj({"repaired": {"type": "array", "items": _obj({"id": {"type": "string"}, "text": {"type": "string"}})}})

TRANSLATION_SCHEMA = _obj({"translation": {"type": "string"}, "language_ok": {"type": "boolean"}})

FAITHFULNESS_SCHEMA = _obj(
    {
        "judgements": {
            "type": "array",
            "items": _obj(
                {
                    "claim_index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["supported", "partial", "unsupported"]},
                    "misattributed": {"type": "boolean"},
                    "reason": {"type": "string"},
                }
            ),
        }
    }
)

SCHEMAS: dict[str, dict[str, Any]] = {
    "summary_generator": SUMMARY_SCHEMA,
    "summary_passage_notes": NOTES_SCHEMA,
    "book_summary_aggregator": SUMMARY_SCHEMA,
    "book_qa": QA_SCHEMA,
    "quiz_question_generator": QUIZ_SCHEMA,
    "quiz_question_validator": VALIDATOR_SCHEMA,
    "answer_explainer": EXPLAINER_SCHEMA,
    "chapter_detector": CHAPTER_DETECTOR_SCHEMA,
    "document_extraction_repair": REPAIR_SCHEMA,
    "translation": TRANSLATION_SCHEMA,
    "source_faithfulness_evaluator": FAITHFULNESS_SCHEMA,
}
