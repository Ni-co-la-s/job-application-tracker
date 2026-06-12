# Job Application Tracker

An automated job search and tracking platform that uses Large Language Models (LLMs) to scrape, evaluate, and organize job postings. The system features a multi-stage LangGraph pipeline that scores job opportunities based on their alignment with your specific resume, technical skills, and experience bank.

<img width="2557" height="1269" alt="Job Application Tracker Dashboard" src="https://github.com/user-attachments/assets/d5705efa-eadb-4dac-b959-543e3e865dd4" />

## Core Features

### Multi-Site Scraping

Using **[JobSpy](https://github.com/speedyapply/JobSpy)** to aggregate listings from Indeed, LinkedIn, Glassdoor, and ZipRecruiter, with deduplication using simhash.

Current scraper guidance:
- **Recommended:** Indeed and LinkedIn
- **ZipRecruiter:** available only in the US and not yet very tested
- **Glassdoor:** sometimes does not retrieve the full description correctly

<img width="2556" height="1272" alt="Scraping configuration" src="https://github.com/user-attachments/assets/8130eac5-a27b-43e4-acaa-5eb2865833d4" />

### Automated Evaluation

Jobs are scored on a 1-10 scale using a customizable LLM pipeline that provides written reasoning for every score.

### Contextual AI Chat

A dedicated interface to interact with job descriptions for drafting cover letters or asking custom questions.

<img width="2558" height="1270" alt="AI Chat Interface" src="https://github.com/user-attachments/assets/9ff160b1-7d74-40d3-82f6-dca3ef45ae95" />

### AI Resume Tailoring

Generate job-specific LaTeX resume edits from a selected job posting, review each search/replacement edit individually, compile an in-app PDF preview, and save the approved PDF to `Resumes/final/`.

The tailoring workflow uses:
- `config/resume.txt` as the full information bank of your experience, projects, and skills.
- `Resumes/tex/<template-name>/resume.tex` as the editable LaTeX target.
- The selected job's stored database description as the target job context.

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
- Optional for resume tailoring: [Tectonic](https://tectonic-typesetting.github.io/) or a TeX distribution with `latexmk` on your PATH. Tectonic is recommended.

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

On first dashboard startup, missing user files are automatically created from tracked `.example` templates.

This includes `.env` and the files in `config/`. Afterwards, you can edit `.env` real API keys, model names, and base URLs either directly in the file or from the dashboard's **User Config → LLM Settings** tab before LLM calls will work.

If you prefer to initialize files manually before the first run:

```bash
# Windows
copy .env.example .env
copy config\*.example config\*

# Linux/macOS
cp .env.example .env
for f in config/*.example; do cp "$f" "${f%.example}"; done
```

4. **Add Resume PDF and/or LaTeX Templates**

Place your resumes in PDF format within `Resumes/final/`. You can have several versions to track how they are performing. The dashboard will automatically detect these for application tracking.
Those will not be passed to LLMs.

For AI Resume Tailoring, place LaTeX sources under:

```text
Resumes/tex/<template-name>/resume.tex
Resumes/tex/<template-name>/*.cls, *.sty, fonts, images, etc.
```

Each template folder should contain one editable `resume.tex` plus any supporting files. The AI only edits `resume.tex`; if resume content is split across `\input` or `\include` files, that content will not be tailored. Keep resume content in `resume.tex` for best results.

## Configuration

The system relies on local files in the `config/` directory to personalize the matching logic. You can modify them to match your expectations.

- **searches.txt**: Define job searches using `job_title|location|country` (or `job_title|location|country|linkedin_company_ids`). Can be modified in the **Scraping** tab of the dashboard.
  - Example: `Test engineer|Berlin|Germany`
  - LinkedIn company-targeted example: `Data Scientist|Berlin|Germany|1441,1035`
  - `linkedin_company_ids` is optional and must be comma-separated integers.
  - Where to find LinkedIn company IDs? Open the company page on LinkedIn, go on jobs, pass a query and copy the numeric id from the URL (for example `https://www.linkedin.com/jobs/search/?f_C=1441` → `1441`).
  - LinkedIn supports location clusters (for example regions) in the `location` field, see: https://www.linkedin.com/help/recruiter/answer/a524054
  - Example for LinkedIn cluster search: `Data Scientist|Latin America|worldwide`
  - Site-specific behavior:
    - only `location` is used for LinkedIn and ZipRecruiter
    - `country` is used for Indeed and Glassdoor, `location` helps narrowing down (supported countries: https://github.com/speedyapply/JobSpy?tab=readme-ov-file#supported-countries-for-job-searching)
  - Important: if you use LinkedIn-specific cluster values (like `Latin America|worldwide`) while also scraping Indeed/Glassdoor in the same run, Indeed/Glassdoor may return no results for those entries.
- **resume.txt**: Your resume in plain text for LLM processing. This is different from the resumes in Resumes/final/ and will be passed to LLMs when scoring the jobs found.
  - Can be modified in the **User Config → Profile Files** tab of the dashboard.
  - For AI Resume Tailoring, this file is treated as the information bank: a superset of your experience and projects that the model may draw from without inventing facts.
- **candidate_skills.txt**: A list of your primary technical skills (one per line). The skills extracted from the jobs will then be matched to them. Can be modified in the **User Config → Profile Files** tab of the dashboard.
- **prompts.json**: Contains the prompts for extraction, matching, scoring, and resume tailoring logic. Can be modified in the **User Config → Prompts** tab of the dashboard.
- **presets.json**: Saved prompt templates for the AI Chat interface. Can be modified in the **AI Tools** tab of the dashboard.
- **queries.json**: Saved SQL analytics queries with their recommended visualization type and description. Can be modified in the **Analytics** tab of the dashboard.
- **interview_stages.json**: Interview stages for tracking application stages (refusal, offers, phone screening...). Defaults are created from `interview_stages.json.example`. Be careful changing this after you have saved stages in the database.

## Usage

### Streamlit Dashboard

The primary interface. It allows you to run scrapers, browse matches, use AI tools and run analytics with SQL.

```bash
uv run streamlit run dashboard.py
```

### AI Resume Tailoring Setup

The Resume Tailoring tab requires its own dedicated LLM configuration. It does not fall back to the chat or scoring model. Set these variables in `.env`:

```env
RESUME_TAILORING_MODEL=gpt-4o-mini
RESUME_TAILORING_API_KEY=sk-...
RESUME_TAILORING_BASE_URL=https://api.openai.com/v1
```

The tab compiles PDFs using a system LaTeX engine:

1. Prefer `tectonic` if available.
2. Fall back to `latexmk -pdf`.
3. For fontspec templates, select the XeLaTeX or LuaLaTeX option in the UI, which uses `latexmk -pdfxe` or `latexmk -pdflua`.

Some pdflatex-only templates may need tweaks when compiled with Tectonic or XeLaTeX/LuaLaTeX.

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
