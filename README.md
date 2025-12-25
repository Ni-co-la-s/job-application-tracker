# Job Application Tracker

An automated job search and tracking platform that uses Large Language Models (LLMs) to scrape, evaluate, and organize job postings. The system features a multi-stage LangGraph pipeline that scores job opportunities based on their alignment with your specific resume, technical skills, and experience bank.

## Core Features

- **Multi-Site Scraping**: Integrated with JobSpy to aggregate listings from Indeed, LinkedIn, Glassdoor, ZipRecruiter, and Google Jobs.
- **Automated Evaluation**: Jobs are scored on a 1-10 scale using a customizable LLM pipeline that provides written reasoning for every score.
- **Centralized Management**: A Streamlit-based dashboard for browsing matches, tracking application statuses, and managing interview stages.
- **Contextual AI Chat**: A dedicated interface to interact with job descriptions for drafting cover letters or asking custom questions.
- **Data Analytics**: SQL analytics to visualize the info from the database.
- **Duplicate Detection**: Uses Simhash fuzzy matching to identify and filter duplicate postings and reposts.

## Technical Architecture

The system processes every job through a structured LangGraph workflow to ensure accuracy and cost-efficiency:

1. **Deduplication**: Simhash algorithms compare the "fingerprint" of job descriptions against the existing database to ignore redundant listings.
2. **Skill Extraction**: Technical requirements are extracted into a structured JSON format.
3. **Heuristic Matching**: A high-speed comparison is performed against your core skill set to filter out irrelevant roles before high-cost LLM processing.
4. **Deep Scoring**: High-potential matches undergo a final evaluation where an LLM compares the full job description against your resume and experience bank to provide a final fit score.

## Installation

### Prerequisites

- Python 3.12 or higher
- `uv` (Recommended package manager)
- An OpenAI-compatible API key (Supports OpenAI, DeepSeek, Anthropic, or local methods like llama.cpp or LM Studio)

### Setup

1. **Clone the repository**

```bash
git clone 
cd job-application-tracker
```

2. **Install dependencies**

```bash
uv sync
```

3. **Initialize Configuration**

Copy the provided example files and populate them with your data:

```bash
# Windows
copy .env.example .env
copy config\*.example config\*

# Linux/macOS
cp .env.example .env
for f in config/*.example; do cp "$f" "${f%.example}"; done
```

4. **Add Resume PDF**

Place your resume in PDF format within `Resumes/final/`. You can have several versions to track how they are performing. The dashboard will automatically detect these for application tracking.
Those will not be passed to LLMs.

## Configuration

The system relies on several plain-text files in the `config/` directory to personalize the matching logic:

- **searches.txt**: Define job searches that need to be made using the format `job_title|location|country`.
- **resume.txt**: Your resume in plain text for LLM processing. This is different from the resumes in Resumes/final/ and will be passed to LLMs when scoring the jobs found.
- **candidate_skills.txt**: A list of your primary technical skills (one per line). The jobs retrieved will heavily depend on it
- **prompts.json**: Contains the system prompts for extraction and scoring logic. 
- **presets.json**: Saved prompt templates for the AI Chat interface. Those can be changed from the UI directly

## Usage

### Streamlit Dashboard

The primary interface. It allows you to run scrapers, browse matches, and use AI tools.

```bash
uv run streamlit run dashboard.py
```

### Standalone Scraper

Run the scraping and evaluation pipeline from the command line for automated tasks.

```bash
uv run python jobspy_scraper.py --resume config/resume.txt --sites indeed linkedin --hours-old 24
```


## Performance Tips

- **Model Selection**: Use smaller, faster models for extraction and heuristic matching, and more capable models for the final scoring reasoning.
- **Update prompts**: The generic prompts used for skills extraction, matching and scoring are available in config/prompts.json. They can be tuned if the results are not satisfactory to you.   
- **Batch Size**: Adjust the `batch-size` parameter based on your API rate limits. For local models, a batch size of 1-3 is recommended.
- **Score Filtering**: Use the `--min-score` flag in the scraper to only save jobs that meet a certain fit threshold, keeping your database clean.