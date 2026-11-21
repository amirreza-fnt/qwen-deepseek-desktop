# Contributing

Thanks for helping! Bug reports, translations and pull requests are welcome.

## Development setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python main.py              # run the app
python -m pytest -q         # run the tests (set QT_QPA_PLATFORM=offscreen on headless machines)
```

UI previews with sample data (no network, no account needed):

```bash
python main.py --lang en --ui-preview shot.png Dark
python main.py --lang fa --ui-preview-project shot Light
python main.py --lang en --ui-preview-agent shot Light
```

## Translations (English / فارسی)

* Source strings are Persian and wrapped in `tr()` from `app/i18n.py`; English lives in `app/i18n_en.py`.
* Use named placeholders: `tr('فایل {path} پیدا نشد', path=p)`.
* `tests/test_i18n.py` fails if a string has no English entry, placeholders differ, or Persian UI text is not wrapped in `tr()`.
* Want to add another language? Open an issue first — a third dictionary plus a selector entry is all it takes.

## Ground rules

* **Never commit tokens, cookies, emails or personal data** — not in code, tests, screenshots or logs.
* No captcha solving, anti-bot signature forging or cookie exporting. The app only uses the user's own signed-in web session; verification is always completed by the user.
* Keep the review-before-write guarantee of Project mode: nothing touches disk without the user pressing “Apply”, and commands/downloads need explicit approval.
* Add or update tests for behaviour changes; CI runs on Windows and Ubuntu.

## CI

A ready-to-use GitHub Actions workflow (Windows + Ubuntu, Python 3.11/3.12, offscreen Qt) is in [`docs/ci/tests.yml`](docs/ci/tests.yml). Maintainers: copy it to `.github/workflows/tests.yml` to enable it.
