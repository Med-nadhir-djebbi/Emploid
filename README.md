# Emploid

Search internships and part-time jobs across many sources in one go, review the results in a clean local web page, and apply, either automatically (where the form allows it) or through a link.

Everything runs **on your own computer**. Your resume, answers and results are stored in a folder on your machine and are never uploaded anywhere. The app only talks to the job sites it searches.

## Install

### Easiest: download the app (Windows and Linux)

Get the file for your system from the project's **Releases** page, unpack it, and start it. No Python needed.

- **Windows:** unzip `emploid-windows-x86_64.zip` and double-click `emploid.exe`. Windows may warn that the app is unsigned: choose **More info**, then **Run anyway**.
- **Linux:** `tar xzf emploid-linux-x86_64.tar.gz && ./emploid/emploid`

A window opens (keep it open while you use the app) and the app appears in your browser. Close the window to stop it.

### With Python

You need Python 3.10 or newer.

```bash
pipx install emploid        # or: pip install emploid
emploid
```

`emploid` starts the app and opens it in your browser at http://127.0.0.1:8765. Press Ctrl+C in the terminal to stop it.

From a checkout of this repository instead:

```bash
pip install .
```

### Optional: the apply browser

Searching works straight away. Auto-apply drives a real browser (Chromium), which is a separate ~150 MB download. The app offers to install it the first time you use auto-apply, or you can run:

```bash
emploid install-browser
```

## First steps

1. Open **Settings** and pick your **home country**. This decides which remote jobs you can take and what visa hints mean for you.
2. Open **Profile** and fill in your details and upload your resume. Answer the standard questions (work authorization, sponsorship, and so on).
3. In the left panel choose what to look for. Type keywords such as `software engineering google` (a role plus a company), pick job types, and choose countries on the map.
4. Press **Search**. The first search takes several minutes because it discovers company career boards. Later searches take about a minute and reuse what was found.
5. Select the jobs you like, then **Apply**. You always get a review screen first.
6. Save a search you repeat as a **preset** and run it with one button.

## What it searches

- Job feeds: Remotive, Arbeitnow, RemoteOK, Jobicy, Himalayas, We Work Remotely, Working Nomads, Jobspresso and your own RSS feeds.
- Company career systems: Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee and Workday, plus Google, Amazon and Microsoft careers. The list of companies grows by itself as the app finds new career boards.
- Curated internship lists, EURES (European jobs portal), Landing.jobs, and a short list of international programmes in `src/emploid/programs.json`.
- Adzuna and Jooble when you add a free API key in Settings.

Searching abroad: choose countries on a world map, and use **Visa fit** to hide jobs that rule you out or show only jobs that offer visa or relocation support. The visa badges come from the text of each posting. **Treat them as hints, not promises**, and check with the employer.

Postings in other languages are translated to English. This uses Google's public endpoint, which can throttle heavy use. A free DeepL key in Settings avoids that.

## Auto-apply: read this first

Auto-apply is **off by default**. You turn it on in Settings.

- It works for Greenhouse, Lever and Ashby forms only. Every other site gets a link to open yourself.
- It fills the form with your saved answers, attaches your resume and submits as you. Forms vary, so it can get things wrong or answer a question differently than you would. Use **Dry run** in Settings to watch it fill forms without submitting.
- It never gets past captchas or tricky questions: those jobs come back to you marked "needs you".
- Applications run one at a time with a pause between them.
- You are responsible for what is submitted in your name. Check the Applied tab afterwards.

## Where your data lives

| System | Folder |
| --- | --- |
| Linux | `~/.local/share/emploid` |
| macOS | `~/Library/Application Support/emploid` |
| Windows | `%LOCALAPPDATA%\emploid` |

Run `emploid data-dir` to print it. Use `--data-dir /some/folder` (or the `EMPLOID_DATA` environment variable) to keep it somewhere else. The folder holds your profile, resume, API keys and results, so it is private to your user account. To start over, stop the app and delete it. To move to another computer, copy it.

The server only listens on `127.0.0.1` and refuses requests from other websites, so other pages in your browser can't use it.

## Commands

```
emploid                  start the app and open the page
emploid --port 9000      use another port
emploid --no-browser     don't open the page automatically
emploid doctor           check the setup (data folder, internet, apply browser)
emploid install-browser  download the browser used by auto-apply
emploid data-dir         show where your data is stored
```

## Good to know

- Results come from third-party sites. They can be out of date, wrong or disappear. Always check the posting itself.
- The company-site readers use public endpoints that sites may change. **Settings → Source health** shows which sources worked in the last search.
- The programmes list was compiled by hand. Check each programme's own page for who can apply and the dates.
- Be a good citizen: the app caches responses, spaces out its requests and identifies itself honestly. Please don't point it at sites that forbid automated access.

## Building the downloads

`python packaging/build.py` builds the standalone app for the OS you run it on (needs `pip install pyinstaller`). The GitHub workflow in `.github/workflows/build.yml` builds Windows and Linux on every `v*` tag and attaches them to the release:

```bash
git tag v1.0.0 && git push --tags
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Tests use a throwaway data folder, so they never touch your real data.

## Licence

MIT. See `LICENSE`. This project is not affiliated with LinkedIn or any job site it searches.
