"""
Job Scraper using JobSpy library.

Scrapes jobs from multiple sites and matches against resume using LLM.
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from dotenv import load_dotenv

from jobspy import scrape_jobs
import pandas as pd
from modules.database import JobDatabase
from modules.langgraph_pipeline import run_batch_through_pipeline
from constants import JOBS_DB, SEARCHES_FILE

# Setup logging with environment variable override
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

db = JobDatabase(JOBS_DB)
logger.info("✓ Database initialized")


def read_search_terms_from_file(filepath: str) -> list[dict[str, str | None]]:
    """Read search configurations from file.

    Format: search_term|location|country (one per line)

    Example:
        machine learning|Berlin|Germany
        data science|Munich|Germany
        software engineer|Paris|France

    Args:
        filepath: Path to the search terms file.

    Returns:
        List of search configuration dictionaries.

    Raises:
        SystemExit: If file not found or error reading file.
    """
    searches: list[dict[str, str | None]] = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split("|")
                    if len(parts) >= 1:
                        search = {
                            "search_term": parts[0].strip(),
                            "location": parts[1].strip() if len(parts) > 1 else None,
                            "country": parts[2].strip()
                            if len(parts) > 2
                            else "Germany",
                        }
                        searches.append(search)
        return searches
    except FileNotFoundError:
        logger.error(f"Search terms file not found: {filepath}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error reading search terms file: {e}")
        sys.exit(1)


def main() -> None:
    """Main function for job scraping and matching."""
    parser = argparse.ArgumentParser(
        description="Scrape jobs using JobSpy and match against resume"
    )
    parser.add_argument(
        "--searches-file",
        default=SEARCHES_FILE,
        help=f"Path to file with search terms (format: search_term|location|country). Default: {SEARCHES_FILE}",
    )
    parser.add_argument(
        "--resume", required=True, help="Path to your resume (text file)"
    )
    parser.add_argument(
        "--sites",
        nargs="+",
        default=["indeed", "glassdoor"],
        choices=["indeed", "linkedin", "glassdoor", "zip_recruiter", "google"],
        help="Job sites to scrape (default: indeed linkedin)",
    )
    parser.add_argument(
        "--results-per-site",
        type=int,
        default=50,
        help="Number of results per site per search (default: 50)",
    )
    parser.add_argument(
        "--hours-old",
        type=int,
        default=48,
        help="Only jobs posted in last N hours (default: 24)",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=0,
        help="Minimum LLM score to save to database (default: 0, saves all)",
    )
    parser.add_argument(
        "--proxies", nargs="+", help="Proxy list in format: user:pass@host:port"
    )
    parser.add_argument(
        "--job-type",
        choices=["fulltime", "parttime", "internship", "contract"],
        help="Filter by job type",
    )
    parser.add_argument("--is-remote", action="store_true", help="Only remote jobs")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Number of concurrent LLM requests (default: 10, set to 1 for sequential)",
    )
    parser.add_argument(
        "--heuristic-threshold",
        type=float,
        default=0.35,
        help="Heuristic score threshold for filtering jobs (default: 0.35)",
    )

    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    # Validate resume file
    if not Path(args.resume).exists():
        logger.error(f"Resume file not found: {args.resume}")
        sys.exit(1)

    # Read search terms
    searches = read_search_terms_from_file(args.searches_file)

    if not searches:
        logger.error(f"No search terms found in {args.searches_file}")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("JobSpy Scraper & Matcher")
    logger.info("=" * 60)
    logger.info(f"Resume: {args.resume}")
    logger.info(f"Sites: {', '.join(args.sites)}")
    logger.info(f"Searches: {len(searches)}")
    logger.info(f"Results per site: {args.results_per_site}")
    logger.info(f"Hours old: {args.hours_old}")
    logger.info(f"Min score to save: {args.min_score}")
    logger.info(f"Heuristic threshold: {args.heuristic_threshold}")
    logger.info("=" * 60)

    all_jobs_df = []

    # Scrape each search term
    for i, search in enumerate(searches, 1):
        logger.info(
            f"\n[{i}/{len(searches)}] Scraping: {search['search_term']} in {search['location']}, {search['country']}"
        )

        try:
            # Prepare kwargs
            scrape_kwargs = {
                "site_name": args.sites,
                "search_term": search["search_term"],
                "location": search["location"],
                "country_indeed": search["country"],
                "results_wanted": args.results_per_site,
                "hours_old": args.hours_old,
                "job_type": args.job_type,
                "is_remote": args.is_remote,
                "proxies": args.proxies,
                "description_format": "markdown",
                "verbose": 0,
            }

            # Add LinkedIn-specific parameters if LinkedIn is in the list
            if "linkedin" in args.sites:
                scrape_kwargs["linkedin_fetch_description"] = True  # KEY FIX!
                logger.info(
                    "   LinkedIn: Fetching full descriptions (slower but more complete)"
                )

            jobs_df = scrape_jobs(**scrape_kwargs)

            logger.info(f"Found {len(jobs_df)} jobs")
            all_jobs_df.append(jobs_df)

        except Exception as e:
            logger.error(f"Error scraping search {i}: {e}")
            continue

    if not all_jobs_df:
        logger.warning("No jobs found. Exiting.")
        sys.exit(0)

    all_jobs_df = pd.concat(all_jobs_df, ignore_index=True)

    logger.info(f"\n✓ Total jobs scraped: {len(all_jobs_df)}")
    all_jobs_df = all_jobs_df.drop_duplicates(subset=["job_url"], keep="first")
    logger.info(f"✓ After removing duplicates: {len(all_jobs_df)}")

    # Process jobs through LangGraph pipeline
    logger.info("\n" + "=" * 60)
    logger.info("Processing jobs through LangGraph pipeline...")
    logger.info("=" * 60)

    # Convert dataframe rows to job data dictionaries
    all_jobs_data = []
    for _, row in all_jobs_df.iterrows():
        job_data = {
            "job_url": row.get("job_url"),
            "site": row.get("site"),
            "job_url_direct": row.get("job_url_direct"),
            "title": row.get("title"),
            "company": row.get("company"),
            "location": row.get("location"),
            "date_posted": row.get("date_posted"),
            "job_type": row.get("job_type"),
            "salary_source": row.get("salary_source"),
            "interval": row.get("interval"),
            "min_amount": row.get("min_amount"),
            "max_amount": row.get("max_amount"),
            "currency": row.get("currency"),
            "is_remote": bool(row.get("is_remote")),
            "job_level": row.get("job_level"),
            "job_function": row.get("job_function"),
            "description": row.get("description"),
            "company_industry": row.get("company_industry"),
            "company_url": row.get("company_url"),
            "company_logo": row.get("company_logo"),
            "company_url_direct": row.get("company_url_direct"),
            "company_addresses": row.get("company_addresses"),
            "company_num_employees": row.get("company_num_employees"),
            "company_revenue": row.get("company_revenue"),
            "company_description": row.get("company_description"),
        }
        all_jobs_data.append(job_data)

    pipeline_results = run_batch_through_pipeline(
        all_jobs_data,
        min_score=args.min_score,
        batch_size=args.batch_size,
        heuristic_threshold=args.heuristic_threshold,
    )

    # Process results
    accepted_jobs = []
    low_score_jobs = []
    rejected_jobs = []
    duplicate_jobs = []
    error_jobs = []

    for job_data, result in zip(all_jobs_data, pipeline_results):
        status = result.get("status", "error")

        if status == "duplicate":
            duplicate_jobs.append((job_data, result))
        elif status == "error":
            error_jobs.append((job_data, result))
        elif status == "rejected":
            rejected_jobs.append((job_data, result))
        elif status == "low_score":
            low_score_jobs.append((job_data, result))
        elif status == "accepted":
            accepted_jobs.append((job_data, result))

    logger.info("\n✓ Pipeline processing complete:")
    logger.info(f"  - Accepted (high score): {len(accepted_jobs)}")
    logger.info(f"  - Low score: {len(low_score_jobs)}")
    logger.info(f"  - Rejected (heuristic): {len(rejected_jobs)}")
    logger.info(f"  - Duplicates: {len(duplicate_jobs)}")
    logger.info(f"  - Errors: {len(error_jobs)}")

    # Filter by minimum score if specified
    if args.min_score > 0:
        # Filter accepted jobs by min_score
        accepted_jobs = [
            (job, result)
            for job, result in accepted_jobs
            if result.get("llm_score", 0) >= args.min_score
        ]
        # Filter low score jobs by min_score (some might meet the threshold)
        low_score_to_promote = [
            (job, result)
            for job, result in low_score_jobs
            if result.get("llm_score", 0) >= args.min_score
        ]
        accepted_jobs.extend(low_score_to_promote)
        low_score_jobs = [
            (job, result)
            for job, result in low_score_jobs
            if result.get("llm_score", 0) < args.min_score
        ]

        logger.info(f"\n✓ After minimum score filter ({args.min_score}+):")
        logger.info(f"  - Accepted (high score): {len(accepted_jobs)}")
        logger.info(f"  - Low score: {len(low_score_jobs)}")

    logger.info("\n" + "=" * 60)
    logger.info("✓ DONE!")
    logger.info("=" * 60)
    logger.info(f"Jobs saved to database: {len(accepted_jobs)}")

    # Print statistics
    logger.info("\n📊 Statistics:")
    logger.info(f"  Total scraped: {len(all_jobs_df)}")
    logger.info(f"  After URL deduplication: {len(all_jobs_data)}")
    logger.info(f"  Accepted (high score): {len(accepted_jobs)}")
    logger.info(f"  Low score: {len(low_score_jobs)}")
    logger.info(f"  Rejected (heuristic): {len(rejected_jobs)}")
    logger.info(f"  Duplicates: {len(duplicate_jobs)}")
    logger.info(f"  Errors: {len(error_jobs)}")

    # Print top accepted jobs
    if accepted_jobs:
        sorted_jobs = sorted(
            accepted_jobs, key=lambda x: x[1].get("llm_score", 0), reverse=True
        )[:10]
        logger.info("\n🌟 Top 10 Matches:")
        for i, (job_data, result) in enumerate(sorted_jobs, 1):
            score = result.get("llm_score", 0)
            title = job_data.get("title", "Unknown")
            company = job_data.get("company", "Unknown")
            logger.info(f"  {i}. [{score}/10] {title} at {company}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n\nError: {e}", exc_info=True)
        sys.exit(1)
