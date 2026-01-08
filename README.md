# Job Application Tracker

An automated job search and tracking platform that uses Large Language Models (LLMs) to scrape, evaluate, and organize job postings. The system features a multi-stage LangGraph pipeline that scores job opportunities based on their alignment with your specific resume, technical skills, and experience bank.

<img width="2557" height="1269" alt="Job Application Tracker Dashboard" src="https://github.com/user-attachments/assets/d5705efa-eadb-4dac-b959-543e3e865dd4" />

## Core Features

### Multi-Site Scraping

Using **JobSpy** to aggregate listings from Indeed, LinkedIn, Glassdoor, ZipRecruiter, and Google Jobs, with deduplication using simhash.

<img width="2556" height="1272" alt="Scraping configuration" src="https://github.com/user-attachments/assets/8130eac5-a27b-43e4-acaa-5eb2865833d4" />

### Automated Evaluation

Jobs are scored on a 1-10 scale using a customizable LLM pipeline that provides written reasoning for every score.

### Contextual AI Chat

A dedicated interface to interact with job descriptions for drafting cover letters or asking custom questions.

<img width="2558" height="1270" alt="AI Chat Interface" src="https://github.com/user-attachments/assets/9ff160b1-7d74-40d3-82f6-dca3ef45ae95" />

### Data Analytics

Run custom SQL queries for analytics and visualization.

<img width="2559" height="1279" alt="Analytics Dashboard" src="https://github.com/user-attachments/assets/c9ef3d1d-a419-41f4-a62e-a2a7ad22e9e9" />


## Technical Architecture

The system processes every job through a structured LangGraph workflow to ensure accuracy and cost-efficiency:

1. **Deduplication**: Simhash algorithms compare the "fingerprint" of job descriptions against the existing database to ignore redundant listings.
2. **Skill Extraction**: Technical requirements are extracted into a structured JSON format.
3. **Heuristic Matching**: A comparison is performed against your skills to filter out irrelevant roles. 
4. **Deep Scoring**: Non filtered out matches undergo a final evaluation where an LLM compares the full job description against your resume to provide a final fit score.

## Installation

### Prerequisites

- Python 3.12 or higher (not tested on older versions yet)
- `uv` (Recommended package manager) or pip
- An OpenAI-compatible API key or local LLLM setup (Supports OpenAI, DeepSeek, Anthropic, llama.cpp or LM Studio...)

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

or

```bash
pip install -e .
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

Place your resumes in PDF format within `Resumes/final/`. You can have several versions to track how they are performing. The dashboard will automatically detect these for application tracking.
Those will not be passed to LLMs.

## Configuration

The system relies on several plain-text files in the `config/` directory to personalize the matching logic:

- **searches.txt**: Define job searches that need to be made using the format `job_title|location|country`.
- **resume.txt**: Your resume in plain text for LLM processing. This is different from the resumes in Resumes/final/ and will be passed to LLMs when scoring the jobs found.
- **candidate_skills.txt**: A list of your primary technical skills (one per line). The skills extracted from the jobs will then be matched to them.
- **prompts.json**: Contains the prompts for extraction and scoring logic. 
- **presets.json**: Saved prompt templates for the AI Chat interface. Those can be changed from the UI directly
- **interview_stages.json**: Customizable interview stages for tracking application stages (refusal, offers, phone screening...). You can modify, add, or remove stages to match your interview process.

## Usage

### Streamlit Dashboard

The primary interface. It allows you to run scrapers, browse matches, use AI tools and run analytics with SQL.

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
- **Batch Size**: Adjust the `batch-size` parameter based on your API rate limits. For local models, depending on your VRAM and setup, using a smaller batch size is recommended.
- **Score Filtering**: Use the `--min-score` flag in the scraper to only save jobs that meet a certain fit threshold, keeping your database clean.
