// Types mirroring the Readbit API (/api/v1). Kept in one place so a future mobile client can reuse them.

export type Language = "en" | "hi";
export type Depth = "concise" | "balanced" | "comprehensive";

export interface ApiErrorBody {
  code: string;
  message: string;
  retryable: boolean;
  details?: Record<string, unknown>;
}

export interface User {
  id: string;
  email: string | null;
  display_name: string;
  preferred_language: Language;
  content_language: Language;
  theme_preference: "light" | "dark" | "system";
  daily_goal_questions: number;
  created_at: string;
}

export interface Me {
  authenticated: boolean;
  guest: boolean;
  user: User | null;
  guest_expires_at?: string;
  preferred_language?: Language;
}

export interface Job {
  id: string;
  job_type: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  stage: string;
  progress_percent: number;
  attempts: number;
  error: { code: string; message: string } | null;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string | null;
}

export interface Warning {
  code: string;
  message: string;
  pages?: number[];
}

export interface Book {
  id: string;
  title: string;
  title_source: string;
  author: string | null;
  file_format: "pdf" | "epub";
  original_filename: string | null;
  size_bytes: number | null;
  detected_language: string | null;
  processing_status: "uploaded" | "validating" | "extracting" | "structuring" | "chunking" | "indexing" | "ready" | "failed";
  learning_status: string;
  extraction_quality: number | null;
  structure_confidence: number | null;
  warnings: Warning[];
  chapter_count: number;
  page_count: number | null;
  word_count: number;
  estimated_reading_minutes: number | null;
  owner: "guest" | "user";
  created_at: string;
  updated_at: string;
  processing_job: Job | null;
}

export interface Chapter {
  id: string;
  ordinal: number;
  title: string;
  detection_method: string;
  detection_confidence: number;
  word_count: number;
  estimated_reading_minutes: number | null;
}

export interface ReadingState {
  last_view: string;
  last_chapter_id: string | null;
  last_depth: Depth;
  last_position: Record<string, unknown>;
  chapters_read: string[];
  updated_at: string | null;
}

export interface Evidence {
  id: string;
  chunk_id: string;
  chapter_id: string | null;
  passage: string | null;
  section_title: string | null;
  source_type: "pdf" | "epub";
  page_label: string | null;
  page_number: number | null;
  epub_location: string | null;
  character_start: number | null;
  character_end: number | null;
  excerpt: string;
  extraction_confidence: number;
  passage_text?: string | null;
}

export interface Claim {
  text: string;
  evidence_ids: string[];
  passage_ids?: string[];
  support?: string;
}

export interface SummarySection {
  heading: string;
  content: string;
  key_concepts: string[];
  evidence_ids: string[];
}

export interface SummaryContent {
  title: string;
  scope: "book" | "chapter";
  depth: Depth;
  language: string;
  central_thesis: Claim;
  sections: SummarySection[];
  definitions: { term: string; definition: string; evidence_ids: string[] }[];
  examples: { description: string; evidence_ids: string[] }[];
  caveats: Claim[];
  connections: Claim[];
  conclusion: Claim;
  takeaways: Claim[];
  coverage: {
    source_passages_considered?: number;
    source_passages_cited?: number;
    known_gaps?: string[];
    chapters_total?: number;
    chapters_covered?: number;
    chapters_failed?: string[];
    claims_removed_without_evidence?: number;
  };
  engine: { provider: string; model: string; mode: "extractive" | "generative" };
  reading_minutes: number;
  source_reading_minutes: number;
}

export interface Summary {
  id: string;
  book_id: string;
  chapter_id: string | null;
  scope: "book" | "chapter";
  depth: Depth;
  output_language: string;
  status: "pending" | "generating" | "ready" | "failed";
  content: SummaryContent | null;
  evidence: Record<string, Evidence>;
  error: { code: string; message: string } | null;
}

export interface QaAnswer {
  answerable: boolean;
  answer: string | null;
  confidence: "high" | "medium" | "low";
  citations: Evidence[];
  unanswerable_reason: string | null;
  engine: { provider: string; mode: string; model?: string };
}

export interface Annotation {
  id: string;
  book_id: string;
  annotation_type: "highlight" | "bookmark" | "note";
  source_location: { kind: string; chunk_id?: string; chapter_id?: string | null; summary_id?: string; section_key?: string; passage?: string; start?: number; end?: number };
  selected_text: string | null;
  note_text: string | null;
  color: string | null;
  author: "you";
  created_at: string;
  updated_at: string;
}

export interface Passage {
  id: string;
  passage: string;
  text: string;
  section_title: string | null;
  page_number: number | null;
  page_label: string | null;
  extraction_confidence: number;
}

export interface Lesson {
  chapter_id: string;
  ordinal: number;
  title: string;
  bank_status: "none" | "generating" | "ready" | "failed";
  approved_questions: number;
  questions_answered: number;
  correct: number;
  accuracy: number | null;
  lessons_completed: number;
  completed: boolean;
}

export interface QuizSession {
  id: string;
  book_id: string;
  chapter_id: string | null;
  session_type: "lesson" | "revision";
  status: "preparing" | "active" | "completed" | "unavailable";
  status_message: string | null;
  difficulty: number;
  question_count: number;
  answered_count: number;
  correct_count: number;
}

export interface QuizQuestion {
  id: string;
  question_text: string;
  question_type: "recall" | "comprehension" | "application" | "inference";
  difficulty: 1 | 2 | 3;
  options: { key: "A" | "B" | "C" | "D"; text: string }[];
  position: number | null;
}

export interface Achievement {
  code: string;
  name: string;
  description: string;
  icon_key: string;
  earned?: boolean;
  earned_at?: string | null;
}

export interface AnswerFeedback {
  question_id: string;
  selected_option_key: string;
  is_correct: boolean;
  correct_option_key: string;
  correct_option_text: string;
  explanation: string;
  misconception: string | null;
  evidence: Evidence[];
  already_answered: boolean;
  topic: { id: string; title: string } | null;
  mastery: { score: number; confidence: number } | null;
  session: QuizSession;
  achievements_earned: Achievement[];
}

export interface MasteryItem {
  topic_id: string;
  topic: string;
  chapter_id: string | null;
  mastery_score: number;
  confidence: number;
  attempts: number;
  correct: number;
  weak: boolean;
  next_review_at: string | null;
}

export interface Meta {
  interface_languages: Language[];
  ai_engine: { provider: string; mode: "extractive" | "generative"; can_translate: boolean; question_types: string[] };
  limits: { max_upload_size_mb: number; max_document_pages: number; guest_retention_hours: number; lesson_size: number };
  ocr_enabled: boolean;
}

export interface Dashboard {
  recent_books: Book[];
  continue_reading: { book: { id: string; title: string }; chapter: { id: string; title: string } | null; state: ReadingState; chapters_total: number }[];
  continue_learning: (QuizSession & { book_title: string | null }) | null;
  recently_completed_lessons: { book_id: string; book_title: string; chapter_title: string; correct: number; answered: number; completed_at: string }[];
  weak_concepts: { topic: string; book_id: string; book_title: string; mastery_score: number }[];
  totals: { books: number; questions_answered_recent: number; correct_recent: number };
  streak_days: number;
  daily_goal: { target: number; answered_today: number };
  guest_expires_at: string | null;
}
