"""
LangGraph-based job processing pipeline:
"""

import logging
import json
from typing import TypedDict, List, Optional, Dict, Any
import time
import asyncio
from itertools import islice
import re

import simhash
from pydantic import BaseModel, Field, ValidationError

from langgraph.graph import StateGraph, END

from modules.llm_config import get_config_manager
from modules.prompts_loader import (
    SKILLS_EXTRACTION_PROMPT,
    SKILLS_MATCHING_PROMPT,
    JOB_SCORING_PROMPT,
    JOB_SCORING_SYSTEM_PROMPT,
)
from modules.database import JobDatabase
from constants import JOBS_DB, CANDIDATE_SKILLS_FILE, RESUME_FILE

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

# ============= Pydantic Models =============


class SkillsExtraction(BaseModel):
    """Structured output for skills extraction"""

    skills: List[str] = Field(
        description="List of technical skills extracted from job description"
    )


class SkillsMatch(BaseModel):
    """Structured output for skills matching"""

    matched: List[str] = Field(description="Skills that exactly match candidate skills")
    partial: List[str] = Field(
        description="Skills that are partially related to candidate skills"
    )
    missing: List[str] = Field(
        description="Skills that are missing from candidate skills"
    )


# ============= State Definition =============


class PipelineState(TypedDict):
    """State for the LangGraph pipeline"""

    # Job data from JobSpy
    job_data: Dict[str, Any]

    # Pipeline processing data
    job_hash: Optional[str]
    is_duplicate: bool
    extracted_skills: Optional[List[str]]
    match_result: Optional[SkillsMatch]
    heuristic_score: Optional[float]
    llm_score: Optional[int]
    llm_reasoning: Optional[str]

    # Error handling
    error: Optional[str]
    should_continue: bool


# ============= Helper Functions =============


def safe_str(value: Any, default: str = "") -> str:
    """Safely convert any value to string, handling NaN, None, floats, etc."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    # Handle NaN (which is a float)
    str_value = str(value)
    if str_value.lower() in ("nan", "none", "nat"):
        return default
    return str_value


def compute_simhash(job_data: Dict[str, Any]) -> str:
    """Compute simhash from company + title + full description"""
    # Use safe_str to handle NaN, None, floats, etc.
    company = safe_str(job_data.get("company", "")).lower().strip()
    title = safe_str(job_data.get("title", "")).lower().strip()
    description = safe_str(job_data.get("description", "")).lower().strip()

    text = f"{company} {title} {description}"
    return str(simhash.Simhash(text).value)


def check_duplicate_in_database(job_hash: str, company: str, db: JobDatabase) -> bool:
    """Check if a similar job exists using fuzzy hash matching"""
    cursor = db.conn.cursor()

    cursor.execute(
        """SELECT id, job_hash, company, title, date_scraped 
           FROM jobs 
           WHERE job_hash IS NOT NULL
           AND date_scraped >= date('now', '-60 days')"""
    )

    job_hash_int = int(job_hash)
    HAMMING_THRESHOLD = 6

    for row in cursor.fetchall():
        db_id, db_hash, db_company, db_title, db_date = row
        db_hash_int = int(db_hash)
        hamming_distance = bin(job_hash_int ^ db_hash_int).count("1")

        if hamming_distance <= HAMMING_THRESHOLD:
            logger.debug(f"Duplicate found: {company} matches DB ID {db_id}")
            return True

    return False


def calculate_heuristic_score(match_result: SkillsMatch) -> float:
    """Compute heuristic score"""
    if not match_result:
        return 0.0

    total_skills = (
        len(match_result.matched)
        + len(match_result.partial)
        + len(match_result.missing)
    )
    if total_skills == 0:
        return 0.0

    score = (len(match_result.matched) + 0.5 * len(match_result.partial)) / total_skills
    return round(score, 3)


def clean_json_string(content: str) -> str:
    """Clean markdown formatting from JSON strings (common in local LLMs)."""
    content = content.strip()
    # Remove ```json ... ``` wrapper
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\n", "", content)
        content = re.sub(r"\n```$", "", content)
    return content.strip()


# ============= Node Functions =============


async def simhash_deduplication(state: PipelineState) -> PipelineState:
    """Node 1: SimHash Deduplication"""
    try:
        job_data = state["job_data"]

        # Use safe_str for logging
        title = safe_str(job_data.get("title", ""), "Unknown")
        company = safe_str(job_data.get("company", ""), "Unknown")

        job_hash = compute_simhash(job_data)
        state["job_hash"] = job_hash

        db = JobDatabase(JOBS_DB)
        is_db_duplicate = check_duplicate_in_database(job_hash, company, db)

        if is_db_duplicate:
            logger.debug(f"✗ DUPLICATE: {title} @ {company}")
            state["is_duplicate"] = True
            state["should_continue"] = False
            return state

        logger.debug(f"✓ New job: {title} @ {company}")
        state["is_duplicate"] = False
        state["should_continue"] = True
        return state

    except Exception as e:
        logger.error(f"Error in deduplication: {e}")
        state["error"] = f"Deduplication failed: {str(e)}"
        state["should_continue"] = False
        return state


async def skills_extraction(state: PipelineState) -> PipelineState:
    """Node 2: Skills Extraction"""
    if not state["should_continue"]:
        return state

    try:
        job_data = state["job_data"]

        # Use safe_str to handle NaN, None, floats, etc.
        description = safe_str(job_data.get("description", ""))

        # Check if description is meaningful
        if not description or len(description) < 100:
            state["extracted_skills"] = []
            return state

        config_manager = get_config_manager()
        config = config_manager.get_config_for_stage("skills_extraction")
        client = config_manager.get_client_for_stage("skills_extraction")

        if not client:
            state["error"] = "LLM client not configured"
            state["should_continue"] = False
            return state

        prompt = SKILLS_EXTRACTION_PROMPT.format(description=description)

        try:
            # 1. Try OpenAI Structured Outputs (Strict Mode)
            response = await asyncio.to_thread(
                client.beta.chat.completions.parse,
                model=config.model,
                messages=[
                    {"role": "system", "content": "You are a useful assistant"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=1000,
                response_format=SkillsExtraction,
            )
            skills_data = response.choices[0].message.parsed

        except Exception:
            # 2. Fallback: Standard JSON Mode (DeepSeek, Local, etc.)
            fallback_prompt = (
                prompt
                + """
            
            RETURN JSON ONLY. The output must be a single JSON object with a "skills" key containing a list of strings.
            Example:
            {
                "skills": ["Python", "AWS", "Docker"]
            }
            """
            )

            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=config.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a useful assistant. Output valid JSON.",
                    },
                    {"role": "user", "content": fallback_prompt},
                ],
                temperature=0.1,
                max_tokens=1000,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            content = clean_json_string(content)

            try:
                skills_data = SkillsExtraction.model_validate_json(content)
            except ValidationError:
                # If model returned bad JSON, log it and return empty
                logger.warning(
                    f"Failed to parse JSON from {config.model}: {content[:100]}..."
                )
                skills_data = SkillsExtraction(skills=[])

        state["extracted_skills"] = skills_data.skills
        logger.debug(f"Extracted {len(skills_data.skills)} skills")
        return state

    except Exception as e:
        logger.error(f"Error in skills extraction: {e}")
        state["error"] = f"Skills extraction failed: {str(e)}"
        state["should_continue"] = False
        return state


async def skills_matching(state: PipelineState) -> PipelineState:
    """Node 3: Skills Matching"""
    if not state["should_continue"]:
        return state

    try:
        candidate_skills = []
        try:
            with open(CANDIDATE_SKILLS_FILE, "r", encoding="utf-8") as f:
                candidate_skills = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.strip().startswith("#")
                ]
        except FileNotFoundError:
            logger.warning(f"{CANDIDATE_SKILLS_FILE} not found")

        job_skills = state.get("extracted_skills", [])

        if not job_skills:
            state["match_result"] = SkillsMatch(matched=[], partial=[], missing=[])
            state["heuristic_score"] = 0.0
            return state

        config_manager = get_config_manager()
        config = config_manager.get_config_for_stage("skills_matching")
        client = config_manager.get_client_for_stage("skills_matching")

        if not client:
            state["error"] = "LLM client not configured"
            state["should_continue"] = False
            return state

        prompt = SKILLS_MATCHING_PROMPT.replace(
            "{candidate_skills}", json.dumps(candidate_skills)
        ).replace("{job_skills}", json.dumps(job_skills))

        try:
            # 1. Try OpenAI Structured Outputs
            response = await asyncio.to_thread(
                client.beta.chat.completions.parse,
                model=config.model,
                messages=[
                    {"role": "system", "content": "You are a useful assistant"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=1000,
                response_format=SkillsMatch,
            )
            match_result = response.choices[0].message.parsed

        except Exception:
            # 2. Fallback: Standard JSON Mode
            fallback_prompt = (
                prompt
                + """
            
            RETURN JSON ONLY. Do not map skills individually. Group them into three lists: "matched", "partial", and "missing".
            
            REQUIRED JSON STRUCTURE:
            {
                "matched": ["Skill A", "Skill B"],
                "partial": ["Skill C"],
                "missing": ["Skill D", "Skill E"]
            }
            """
            )

            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=config.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a useful assistant. Output valid JSON.",
                    },
                    {"role": "user", "content": fallback_prompt},
                ],
                temperature=0.1,
                max_tokens=1000,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            content = clean_json_string(content)

            try:
                match_result = SkillsMatch.model_validate_json(content)
            except ValidationError:
                logger.warning(
                    f"Failed to parse JSON from {config.model} : {content[:1000]}..."
                )
                match_result = SkillsMatch(matched=[], partial=[], missing=[])

        state["match_result"] = match_result
        state["heuristic_score"] = calculate_heuristic_score(match_result)

        logger.debug(f"Matched {len(match_result.matched)} skills")
        return state

    except Exception as e:
        logger.error(f"Error in skills matching: {e}")
        state["error"] = f"Skills matching failed: {str(e)}"
        state["should_continue"] = False
        return state


async def heuristic_filter(state: PipelineState) -> PipelineState:
    """Node 4: Heuristic Filter"""
    if not state["should_continue"]:
        return state

    heuristic_score = state.get("heuristic_score", 0.0)
    heuristic_threshold = state["job_data"].get("_heuristic_threshold", 0.35)

    if heuristic_score < heuristic_threshold:
        state["should_continue"] = False
    else:
        state["should_continue"] = True

    return state


async def job_scoring(state: PipelineState) -> PipelineState:
    """Node 5: Job Scoring"""
    if not state["should_continue"]:
        return state

    try:
        job_data = state["job_data"]

        config_manager = get_config_manager()
        config = config_manager.get_config_for_stage("job_scoring")
        client = config_manager.get_client_for_stage("job_scoring")

        if not client:
            state["error"] = "LLM client not configured"
            state["should_continue"] = False
            return state

        try:
            with open(RESUME_FILE, "r", encoding="utf-8") as f:
                resume = f.read()
        except FileNotFoundError:
            state["error"] = "Resume file not found"
            state["should_continue"] = False
            return state

        # Use safe_str to handle NaN, None, floats for all fields
        prompt = JOB_SCORING_PROMPT.format(
            resume=resume,
            title=safe_str(job_data.get("title", ""), "Unknown"),
            company=safe_str(job_data.get("company", ""), "Unknown"),
            location=safe_str(job_data.get("location", ""), "Not specified"),
            description=safe_str(
                job_data.get("description", ""), "No description available"
            ),
        )

        # Run LLM call in thread pool to avoid blocking event loop
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=config.model,
            messages=[
                {"role": "system", "content": JOB_SCORING_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=3000,
        )

        content = response.choices[0].message.content

        import re

        score = 0
        reasoning = "Unable to parse response"

        score_match = re.search(r"SCORE:\s*(\d+)", content, re.IGNORECASE)
        if score_match:
            score = int(score_match.group(1))
            score = max(1, min(10, score))

        reasoning_match = re.search(
            r"REASONING:\s*(.+)", content, re.IGNORECASE | re.DOTALL
        )
        if reasoning_match:
            reasoning = reasoning_match.group(1).strip()

        state["llm_score"] = score
        state["llm_reasoning"] = reasoning

        title = safe_str(job_data.get("title", ""), "Unknown")
        company = safe_str(job_data.get("company", ""), "Unknown")
        logger.info(f"Score: {score}/10 - {title} @ {company}")

        return state

    except Exception as e:
        logger.error(f"Error in job scoring: {e}")
        state["error"] = f"Job scoring failed: {str(e)}"
        state["should_continue"] = False
        return state


async def save_job(state: PipelineState) -> PipelineState:
    """Node 6: Save to database"""
    try:
        job_data = state["job_data"]
        llm_score = state.get("llm_score", 0)
        min_score = job_data.get("_min_score", 0)

        if llm_score < min_score:
            logger.debug(f"Score {llm_score} below minimum {min_score}, not saving")
            return state

        db = JobDatabase(JOBS_DB)

        job_record = {
            **job_data,
            "job_hash": state.get("job_hash"),
            "extracted_skills": json.dumps(state.get("extracted_skills", [])),
            "matched_skills": json.dumps(
                state.get(
                    "match_result", SkillsMatch(matched=[], partial=[], missing=[])
                ).matched
                if state.get("match_result")
                else []
            ),
            "partial_skills": json.dumps(
                state.get(
                    "match_result", SkillsMatch(matched=[], partial=[], missing=[])
                ).partial
                if state.get("match_result")
                else []
            ),
            "missing_skills": json.dumps(
                state.get(
                    "match_result", SkillsMatch(matched=[], partial=[], missing=[])
                ).missing
                if state.get("match_result")
                else []
            ),
            "heuristic_score": state.get("heuristic_score", 0.0),
            "llm_score": llm_score,
            "llm_reasoning": state.get("llm_reasoning", ""),
        }

        job_record.pop("_min_score", None)
        job_record.pop("_heuristic_threshold", None)

        job_id = db.insert_job(job_record)
        logger.debug(f"Saved job ID {job_id}")

    except Exception as e:
        logger.error(f"Error saving job: {e}")

    return state


# ============= Graph Construction =============


def create_pipeline():
    """Create and configure the LangGraph pipeline"""

    workflow = StateGraph(PipelineState)

    # Add nodes
    workflow.add_node("simhash_deduplication", simhash_deduplication)
    workflow.add_node("skills_extraction", skills_extraction)
    workflow.add_node("skills_matching", skills_matching)
    workflow.add_node("heuristic_filter", heuristic_filter)
    workflow.add_node("job_scoring", job_scoring)
    workflow.add_node("save_job", save_job)

    # Set entry point
    workflow.set_entry_point("simhash_deduplication")

    # Add edges
    workflow.add_conditional_edges(
        "simhash_deduplication",
        lambda state: END if state.get("is_duplicate", False) else "skills_extraction",
    )

    workflow.add_edge("skills_extraction", "skills_matching")
    workflow.add_edge("skills_matching", "heuristic_filter")

    workflow.add_conditional_edges(
        "heuristic_filter",
        lambda state: "job_scoring" if state.get("should_continue", False) else END,
    )

    workflow.add_edge("job_scoring", "save_job")
    workflow.add_edge("save_job", END)

    return workflow.compile()


# ============= Main Pipeline Class =============


def chunked(iterable, size):
    """Split iterable into chunks"""
    it = iter(iterable)
    while chunk := list(islice(it, size)):
        yield chunk


class LangGraphPipeline:
    """Pipeline using LangGraph's batch processing"""

    def __init__(self):
        self.workflow = create_pipeline()
        self.seen_hashes = set()

    async def process_batch(
        self,
        jobs: List[Dict[str, Any]],
        min_score: int = 0,
        batch_size: int = 50,
        heuristic_threshold: float = 0.35,
    ) -> List[Dict[str, Any]]:
        """
        Process jobs in batches using LangGraph's ainvoke with concurrency.

        Args:
            jobs: List of job dictionaries
            min_score: Minimum score to save
            batch_size: Number of jobs to process concurrently
            heuristic_threshold: Heuristic score threshold for filtering (default: 0.35)
        """

        total_start = time.time()
        self.seen_hashes.clear()

        logger.info(f"\n{'=' * 60}")
        logger.info(f"Processing {len(jobs)} jobs with LangGraph batch processing")
        logger.info(f"Batch size: {batch_size} concurrent workflows")
        logger.info(f"{'=' * 60}")

        all_results = []
        num_chunks = (len(jobs) - 1) // batch_size + 1

        for chunk_idx, job_chunk in enumerate(chunked(jobs, batch_size), 1):
            chunk_start = time.time()
            logger.info(
                f"\n--- Chunk {chunk_idx}/{num_chunks} ({len(job_chunk)} jobs) ---"
            )

            # Keep result order aligned with the original job order in this chunk
            chunk_results = [None] * len(job_chunk)

            # Prepare initial states for all non-duplicate jobs in chunk, while retaining their original index
            indexed_states = []
            for idx, job in enumerate(job_chunk):
                job["_min_score"] = min_score
                job["_heuristic_threshold"] = heuristic_threshold

                # Check batch-level duplicates
                job_hash = compute_simhash(job)
                if job_hash in self.seen_hashes:
                    logger.debug(
                        f"Batch duplicate: {job.get('title')} @ {job.get('company')}"
                    )
                    chunk_results[idx] = {
                        "status": "duplicate",
                        "reason": "Duplicate in current batch",
                        "heuristic_score": 0.0,
                        "llm_score": 0,
                        "skills_extracted": 0,
                        "skills_matched": 0,
                    }
                    continue

                self.seen_hashes.add(job_hash)

                indexed_states.append(
                    (
                        idx,
                        {
                            "job_data": job,
                            "job_hash": None,
                            "is_duplicate": False,
                            "extracted_skills": None,
                            "match_result": None,
                            "heuristic_score": None,
                            "llm_score": None,
                            "llm_reasoning": None,
                            "error": None,
                            "should_continue": True,
                        },
                    )
                )

            if indexed_states:
                # Process chunk using ainvoke with asyncio.gather for concurrency
                tasks = [self.workflow.ainvoke(state) for _, state in indexed_states]
                final_states = await asyncio.gather(*tasks, return_exceptions=True)

                # Map outputs back to their original positions
                for (idx, _), final_state in zip(indexed_states, final_states):
                    if isinstance(final_state, Exception):
                        logger.error(f"Workflow error: {final_state}")
                        chunk_results[idx] = {
                            "status": "error",
                            "reason": str(final_state),
                            "heuristic_score": 0.0,
                            "llm_score": 0,
                            "skills_extracted": 0,
                            "skills_matched": 0,
                        }
                    else:
                        chunk_results[idx] = self._format_result(
                            final_state, min_score, heuristic_threshold
                        )

            # Defensive fallback
            for idx, result in enumerate(chunk_results):
                if result is None:
                    chunk_results[idx] = {
                        "status": "error",
                        "reason": "Internal ordering error: missing chunk result",
                        "heuristic_score": 0.0,
                        "llm_score": 0,
                        "skills_extracted": 0,
                        "skills_matched": 0,
                    }

            all_results.extend(chunk_results)

            chunk_time = time.time() - chunk_start
            logger.info(
                f"Chunk {chunk_idx} complete in {chunk_time:.2f}s ({chunk_time / len(job_chunk):.2f}s per job)"
            )

        # Summary
        total_time = time.time() - total_start
        accepted = sum(1 for r in all_results if r["status"] == "accepted")
        duplicates = sum(1 for r in all_results if r["status"] == "duplicate")
        rejected = sum(1 for r in all_results if r["status"] == "rejected")

        logger.info(f"\n{'=' * 60}")
        logger.info(
            f"COMPLETE in {total_time:.2f}s ({total_time / len(jobs):.2f}s per job)"
        )
        logger.info(
            f"  Accepted: {accepted}, Duplicates: {duplicates}, Rejected: {rejected}"
        )
        logger.info(f"{'=' * 60}\n")

        return all_results

    def _format_result(
        self, state: PipelineState, min_score: int, heuristic_threshold: float = 0.35
    ) -> Dict[str, Any]:
        """Format pipeline state into result"""
        if state.get("is_duplicate"):
            status = "duplicate"
            reason = "Duplicate in database"
        elif state.get("error"):
            status = "error"
            reason = state["error"]
        elif state.get("heuristic_score", 0) < heuristic_threshold:
            status = "rejected"
            reason = f"Heuristic score too low: {state.get('heuristic_score', 0)} (threshold: {heuristic_threshold})"
        elif state.get("llm_score", 0) < min_score:
            status = "low_score"
            reason = f"LLM score below minimum: {state.get('llm_score', 0)}"
        else:
            status = "accepted"
            reason = f"High score: {state.get('llm_score', 0)}"

        # Safely get extracted_skills (handle None)
        extracted_skills = state.get("extracted_skills") or []

        # Safely get match_result (handle None)
        match_result = state.get("match_result")
        if match_result and hasattr(match_result, "matched"):
            skills_matched = len(match_result.matched)
        else:
            skills_matched = 0

        return {
            "status": status,
            "reason": reason,
            "heuristic_score": state.get("heuristic_score", 0.0) or 0.0,
            "llm_score": state.get("llm_score", 0) or 0,
            "skills_extracted": len(extracted_skills),
            "skills_matched": skills_matched,
        }


# ============= Utility Functions =============


def run_batch_through_pipeline(
    jobs: List[Dict[str, Any]],
    min_score: int = 0,
    batch_size: int = 50,
    heuristic_threshold: float = 0.35,
) -> List[Dict[str, Any]]:
    """
    Synchronous wrapper for processing jobs.

    Args:
        jobs: List of job dictionaries
        min_score: Minimum score to save
        batch_size: Number of concurrent workflows
                   - OpenAI: 50-100 works well
                   - Local LLMs: 1-5 based on VRAM
        heuristic_threshold: Heuristic score threshold for filtering (default: 0.35)
    """
    pipeline = LangGraphPipeline()
    return asyncio.run(
        pipeline.process_batch(jobs, min_score, batch_size, heuristic_threshold)
    )


async def process_single_job_async(
    job_data: Dict[str, Any],
    min_score: int = 0,
    heuristic_threshold: float = 0.35,
) -> Dict[str, Any]:
    """
    Process a single job through the pipeline asynchronously.

    Args:
        job_data: Job dictionary with all required fields
        min_score: Minimum score to save (default: 0)
        heuristic_threshold: Heuristic score threshold for filtering (default: 0.35)

    Returns:
        Dictionary with processed job data including pipeline results
    """
    # Add pipeline parameters to job data
    job_data["_min_score"] = min_score
    job_data["_heuristic_threshold"] = heuristic_threshold

    # Create initial state
    initial_state = {
        "job_data": job_data,
        "job_hash": None,
        "is_duplicate": False,
        "extracted_skills": None,
        "match_result": None,
        "heuristic_score": None,
        "llm_score": None,
        "llm_reasoning": None,
        "error": None,
        "should_continue": True,
    }

    # Create pipeline and process job
    pipeline = LangGraphPipeline()
    try:
        final_state = await pipeline.workflow.ainvoke(initial_state)

        # Extract results
        result = {
            "job_data": job_data,
            "job_hash": final_state.get("job_hash"),
            "is_duplicate": final_state.get("is_duplicate", False),
            "extracted_skills": final_state.get("extracted_skills", []),
            "match_result": final_state.get("match_result"),
            "heuristic_score": final_state.get("heuristic_score", 0.0),
            "llm_score": final_state.get("llm_score", 0),
            "llm_reasoning": final_state.get("llm_reasoning", ""),
            "error": final_state.get("error"),
            "should_continue": final_state.get("should_continue", False),
            "status": "processed",
        }

        # Check if job was saved
        if not final_state.get("is_duplicate", False) and final_state.get(
            "should_continue", False
        ):
            if final_state.get("llm_score", 0) >= min_score:
                result["status"] = "accepted"
            else:
                result["status"] = "low_score"
        elif final_state.get("is_duplicate", False):
            result["status"] = "duplicate"
        elif final_state.get("error"):
            result["status"] = "error"
        elif not final_state.get("should_continue", False):
            result["status"] = "rejected"

        return result

    except Exception as e:
        logger.error(f"Error processing single job: {e}")
        return {"job_data": job_data, "error": str(e), "status": "error"}


def process_single_job(
    job_data: Dict[str, Any],
    min_score: int = 0,
    heuristic_threshold: float = 0.35,
) -> Dict[str, Any]:
    """
    Synchronous wrapper for processing a single job.

    Args:
        job_data: Job dictionary with all required fields
        min_score: Minimum score to save (default: 0)
        heuristic_threshold: Heuristic score threshold for filtering (default: 0.35)

    Returns:
        Dictionary with processed job data including pipeline results
    """
    return asyncio.run(
        process_single_job_async(job_data, min_score, heuristic_threshold)
    )
