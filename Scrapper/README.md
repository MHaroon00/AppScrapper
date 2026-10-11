# ⭐ Play Store Review Scraper

Collect the **overall reviews** of any Google Play app (every star rating, 1★ to 5★, with no positive/negative split), explore them in a dashboard, and export a clean dataset as **CSV, Excel or JSON**.

## Features
- **Inputs:** App ID or Play Store URL · App name · Total reviews (or *every available review*) · Start date · End date
- **Advanced options:** sort (newest / most relevant), language, store country, star-rating filter, minimum words, English-only, anonymize reviewer names
- **Dashboard:** rating distribution, review volume over time, average rating over time, most-reviewed app versions, most helpful reviews
- **Explore:** search review text, filter by stars or developer reply, sort, and download the filtered subset
- **16 analysis-ready columns:** `review_id, play_review_id, app_id, app_name, user_name, rating, content, word_count, char_count, thumbs_up, app_version, review_date, review_datetime, has_reply, reply_content, replied_at`

## Run the web app
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```
Then open http://localhost:8501.

## Run the tests
```bash
pip install -r requirements-dev.txt
pytest
```
The tests use a **fake Play Store**, so they run offline in a few seconds. They cover URL parsing, every scraping option, exports, the CLI, and a click-through of the web UI.

## Command-line usage
```bash
# 500 newest reviews (all ratings)
python scraper.py --app-id com.spotify.music --app-name Spotify --total-reviews 500

# every review from 2025, saved as CSV + Excel
python scraper.py --app-id com.whatsapp --total-reviews 0 --start-date 2025-01-01 --end-date 2025-12-31 --formats csv,xlsx

# every app in apps_list.txt
python scraper.py --apps apps_list.txt --total-reviews 1000
```
Files are written to `./output/`.

## Project layout
| File | Purpose |
|---|---|
| `streamlit_app.py` | Web app (UI) |
| `fetcher.py` | Scraping engine: paging, filters, retries, early stop |
| `analytics.py` | Summary stats and charts |
| `writer.py` | CSV / Excel / JSON export |
| `utils.py` | App-ID parsing, validation, date helpers |
| `scraper.py` | Command-line interface |
| `assets/style.css`, `.streamlit/config.toml` | Design and theme |
| `tests/` | Pytest suite |

## Notes
- With **Newest first** plus a start date, the scraper stops automatically once it passes the start date, so old date ranges finish quickly.
- The Play Store sometimes returns fewer reviews than the app's public review count. That is a Play Store limit, not a bug.
- Use the data responsibly. Turn on *Anonymize reviewer names* if you publish datasets.

## Run and preview in VS Code

1. Install **Python 3.11 or 3.12** and **Visual Studio Code**. In VS Code, install the Microsoft **Python** extension.
2. Extract this ZIP, then open the `playstore-review-scraper` folder itself using **File → Open Folder**.
3. Open **Terminal → New Terminal** and create a virtual environment:

   **Windows (PowerShell):**
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

   **macOS / Linux:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Start the app from the project root:
   ```bash
   python -m streamlit run streamlit_app.py
   ```
5. Streamlit normally opens a browser automatically. If it does not, visit **http://localhost:8501**.
6. To stop the server, focus the VS Code terminal and press **Ctrl+C**.

### Launch it using VS Code's Run and Debug

The project includes `.vscode/launch.json`. After installing the Python extension and project dependencies, open **Run and Debug** in VS Code and select **Run Play Store Scraper (Streamlit)**, then press the green play button. You can also use the terminal command above, which is the simplest option.

### Quick check

- Enter an app package ID such as `com.spotify.music`, or paste the full Google Play URL.
- Start with a small limit (for example, 100 reviews) to check the interface and connection before scraping a larger dataset.
- The app needs internet access to fetch live Google Play reviews. The UI itself can open locally, but a scrape cannot complete offline.
- If VS Code reports `No module named streamlit` or another missing package, make sure `.venv` is activated in the terminal and run `pip install -r requirements.txt` again. Also select that same `.venv` interpreter using **Python: Select Interpreter** from the Command Palette.

### Run automated tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```
