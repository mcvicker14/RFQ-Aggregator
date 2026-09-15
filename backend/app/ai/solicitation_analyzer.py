"""AI Solicitation Reader (spec §7). Wraps the Anthropic Messages API with a forced
tool-use call so the model's response is always valid, schema-conformant JSON rather
than free text we'd have to hope parses. The prompt explicitly instructs the model to
leave a field null rather than invent a value — see docs/ARCHITECTURE.md §AI
solicitation reader and docs/SECURITY.md. This is a separate code path from the
Principal Pursuit Score (app/services/scoring.py), which is deliberately
non-AI/deterministic.
"""
import logging

from anthropic import Anthropic

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_DOCUMENT_CHARS = 180_000  # generous budget; longer documents are truncated with a note

EXTRACTION_TOOL = {
    "name": "record_solicitation_analysis",
    "description": "Record structured facts extracted from a federal/state/local A/E solicitation document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "executive_summary": {"type": "string", "description": "2-4 sentence plain-English summary of what is being procured."},
            "scope": {"type": "string"},
            "deliverables": {"type": "array", "items": {"type": "string"}},
            "required_disciplines": {"type": "array", "items": {"type": "string"}},
            "relevant_naics": {"type": "array", "items": {"type": "string"}},
            "contract_type": {"type": "string"},
            "evaluation_factors": {"type": "array", "items": {"type": "string"}},
            "page_limits": {"type": ["string", "null"]},
            "required_forms": {"type": "array", "items": {"type": "string"}},
            "key_personnel_requirements": {"type": ["string", "null"]},
            "past_performance_requirements": {"type": ["string", "null"]},
            "submission_instructions": {"type": ["string", "null"]},
            "deadline": {"type": ["string", "null"], "description": "Proposal due date/time exactly as stated in the document."},
            "questions_deadline": {"type": ["string", "null"]},
            "site_visit": {"type": ["string", "null"]},
            "interview_requirements": {"type": ["string", "null"]},
            "small_business_requirements": {"type": ["string", "null"]},
            "subcontracting_requirements": {"type": ["string", "null"]},
            "licensing_requirements": {"type": ["string", "null"]},
            "geographic_restrictions": {"type": ["string", "null"]},
            "top_10_things_to_know": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
            "red_flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Risks, unusual requirements, or ambiguities Principal should notice before pursuing.",
            },
        },
        "required": ["executive_summary", "top_10_things_to_know", "red_flags"],
        "additionalProperties": False,
    },
}

# Keys the tool schema promises — used to defensively filter the model's response
# before it's unpacked onto the AiSolicitationAnalysis ORM model (belt-and-suspenders
# alongside additionalProperties: false above).
ANALYSIS_FIELDS = set(EXTRACTION_TOOL["input_schema"]["properties"].keys())

SYSTEM_PROMPT = """You are a solicitation-analysis assistant for Principal Engineering, an SDVOSB civil \
engineering firm pursuing federal, state, and local A/E work. You will be given the extracted text of a \
solicitation document (RFP, RFQ, Sources Sought, SOW/PWS, or similar).

Extract ONLY what is explicitly stated in the document text. Do not infer, estimate, or fabricate any fact, \
date, requirement, or number that is not present in the text. If a field is not addressed in the document, \
return null (or an empty array) for it rather than guessing. This is a hard requirement — Principal's staff \
will rely on this output as a factual summary, not a creative one.

Populate every field of the record_solicitation_analysis tool as accurately as possible from the text alone."""


class AiNotConfiguredError(RuntimeError):
    pass


class SolicitationAnalyzer:
    def is_configured(self) -> bool:
        return bool(settings.ANTHROPIC_API_KEY)

    def analyze(self, document_text: str) -> dict:
        if not self.is_configured():
            raise AiNotConfiguredError(
                "AI solicitation analysis is not configured. Add ANTHROPIC_API_KEY to the backend "
                "environment (see backend/.env.example)."
            )

        text = document_text.strip()
        truncated = len(text) > MAX_DOCUMENT_CHARS
        if truncated:
            text = text[:MAX_DOCUMENT_CHARS]

        if not text:
            raise ValueError("Document contains no extractable text — cannot run AI analysis on an empty document.")

        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=[EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "record_solicitation_analysis"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Document text{' (truncated to first ' + str(MAX_DOCUMENT_CHARS) + ' characters)' if truncated else ''}:\n\n"
                        f"{text}"
                    ),
                }
            ],
        )

        for block in message.content:
            if block.type == "tool_use" and block.name == "record_solicitation_analysis":
                result = dict(block.input)
                result["_truncated"] = truncated
                result["_model"] = settings.ANTHROPIC_MODEL
                return result

        logger.error("Anthropic response did not include the expected tool_use block: %r", message.content)
        raise RuntimeError("AI analysis failed to return structured data. Please try again.")
