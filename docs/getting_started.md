# Getting started (Windows)

About 30 minutes, once. After this, GitHub refreshes the data on its own.

## 1. Install Python (5 min)
1. Go to python.org/downloads and install the latest Python 3 for Windows.
2. On the first installer screen, tick **"Add python.exe to PATH"**, then Install.
3. Open **PowerShell** and check: `python --version`

## 2. Run the fetcher on your PC (5 min)
In PowerShell:
```
cd "C:\Users\troye\Documents\Claude\Projects\Unemployment Dashboard"
python -m pip install -r requirements.txt
python src\fetchers\fred_fetcher.py UNRATE ICSA CCSA
```
You should see three lines ending in `updated`, and new files in `data\processed\`.
Then fetch everything (about 160 series, ~2 minutes): `python src\fetchers\fred_fetcher.py`

Your API key is read from `config\.env`. That file is excluded from Git, so it never goes online.

## 3. Put the project on GitHub (10 min)
Easiest route is **GitHub Desktop** (desktop.github.com):
1. File > Add local repository > choose the `Unemployment Dashboard` folder > "create a repository".
2. Name it (e.g. `unemployment-early-warning`). Leave "Keep this code private" **unticked** if you want
   free GitHub Pages hosting. Check the file list: `config/.env` must NOT appear (it's ignored).
3. Click **Publish repository**.

## 4. Give GitHub the API key (2 min)
On github.com, open the repository > Settings > Secrets and variables > Actions > New repository secret:
- Name: `FRED_API_KEY`  Value: your key

## 5. Test the scheduled job (2 min)
Repository > **Actions** tab > "Refresh data" > **Run workflow**. A green check means the cloud can
fetch and commit data on its own. From then on it runs every weekday morning automatically.

## 6. Pull updates to your PC
In GitHub Desktop click **Fetch origin / Pull** whenever you want the latest data locally.

## If something fails
Copy the red error text into the Claude project chat. Most first-run errors are a missing package
(`pip install ...`) or a typo in the secret name.
