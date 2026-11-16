# AMC Movie Tracker — shared website

A website version of `amc_tracker.py` for JD, Meagan and Kevin. It works on iPhone and desktop.
Each person has their own address:

```
https://amc-tracker.streamlit.app/jd
https://amc-tracker.streamlit.app/meagan
https://amc-tracker.streamlit.app/kevin
```

There are no passwords or accounts, so anyone who has a link can open that page.
The original Mac script (`amc_tracker.py` + `run.command`) is separate and unchanged.

---

## What's in it

| Screen | What it does |
|---|---|
| **Home** | Shows a welcome message and your ZIP, theater count and days. It has three buttons: **Run Using My Defaults**, **Change Search Settings** and **My Last 5 Runs**. After a run, the results appear below. Tick movies there and tap **Add selected to tracker**. |
| **Tracker** | The shared 8-column tracker (DATE, MOVIE, USER, A-List Available, Jonathan Purchased, NEEDS REFUND, NEEDS ALTERNATIVE, NOTES), grouped by month. There are two views: **Table**, which is spreadsheet-style and the default on desktop, and **Cards**, which is easier to tap and the default on phones. Every edit saves automatically. **Export** downloads the tracker as Excel or CSV. |
| **Settings** | Change your ZIP, theater count or days. **Save My Defaults** stores them. **Restore My Defaults** puts back what you last saved. You can also run a one-off search without saving anything. |
| **History** | Your last 5 runs. Each one keeps a screenshot, the full results (theaters, dates and every showtime with ticket links) and the search settings. Each run can be downloaded as a screenshot (PNG), Excel or CSV. A 6th run deletes the oldest one. |

How the tracker behaves:
- **Duplicates:** if someone adds a movie that's already in the tracker, their name is added to USER and the dates are combined. Checkboxes and notes stay as they were. The database does this in one step, so two people adding the same movie at the same moment still get only one row.
- **Dates** are shortened: `1 & 2`, `1-3`, `1, 3, 4`, `1-5, 7-9, 11, 12`. Dates in a different month from the month header get the month name: `28-31, Jan 1-3`. You can edit the DATE cell directly by typing in the same format.
- **Automatic notes:** `IMAX`, `Only one theater`, or `IMAX; Only one theater`.
- **Tapping a link on iPhone:** movie and showtime links go to amctheatres.com. On an iPhone with the AMC app installed, iOS usually opens the app for these links. Otherwise they open in Safari.

---

## One-time setup (about 20 minutes)

### 1. Supabase (the shared database)
1. Go to https://supabase.com, sign up, then click **New project**. The free tier is fine.
2. Open **SQL Editor** and click **New query**. Paste the whole contents of `supabase/schema.sql` and click **Run**.
   This creates the tables, the three users and the private `run-screenshots` storage bucket.
3. Open **Project Settings → API Keys** and copy two things:
   - the **Project URL** (`https://xxxx.supabase.co`)
   - the **service_role** key, also called the **secret** key. This key must stay private. It only ever goes into Streamlit's Secrets box.

### 2. GitHub (where the code lives)
1. Create a new **private** repository, for example `amc-tracker-web`.
2. Upload everything in this folder. Do **not** upload a `secrets.toml` file.

### 3. Streamlit Community Cloud (hosting)
1. Go to https://share.streamlit.io, sign in with GitHub and click **Create app**.
2. Choose your repo. Set the main file to `streamlit_app.py`.
3. Pick a custom address under **App URL**, for example `amc-tracker` → `amc-tracker.streamlit.app`.
4. Open **Advanced settings → Secrets** and paste this, filled in:
   ```toml
   AMC_VENDOR_KEY = "your AMC key (the one in run.command)"
   SUPABASE_URL   = "https://xxxx.supabase.co"
   SUPABASE_KEY   = "your service_role / secret key"
   ```
5. Click **Deploy**. Then send each person their link, for example `…streamlit.app/meagan`.
   On iPhone, open the link and tap **Share → Add to Home Screen** to get an app-style icon.

Each person should set their ZIP code in **Settings** the first time they open the site.

---

## Adding another person later
In Supabase **SQL Editor**, run:
```sql
insert into users (slug, display_name) values ('sam', 'Sam');
```
Their page `…/sam` works right away. You don't need to change any code. The slug can only use lowercase letters, numbers, `-` and `_`.

## Trying it on your own computer first
```bash
pip3 install -r requirements.txt
streamlit run streamlit_app.py
```
Then open http://localhost:8501/jd.
If there's no Supabase key, the site saves data to a `local_data/` folder on your computer.
If there's no AMC key, searches return sample movies so you can try everything.
You can also force sample movies by setting `DEMO_MODE = "true"` in your secrets.

## Good to know
- **How long a search takes:** 90 days × 5 theaters means 450 AMC lookups. The site runs 4 at a time, so expect about 1–3 minutes. Keep the page open until it says "Found N movies". The run is saved to History only when it finishes.
- **Free hosting sleeps:** a Streamlit Community Cloud app that nobody has used for a while goes to sleep. The first visit after that takes a little while to wake it up.
- **Custom domain:** a custom domain like `thesite.com` isn't available on free Streamlit hosting, as far as I know. You'd need to move the site to another host to get one. The code would work the same there.

## Files
```
streamlit_app.py          builds one page per user from the database
amcweb/ui.py              Home, Tracker, Settings, History screens
amcweb/amc.py             AMC search (from amc_tracker.py) + showtimes, parallel fetching
amcweb/store.py           Supabase database (and a local-file version for testing)
amcweb/datefmt.py         "1-5, 7-9, 11, 12" date formatting and parsing
amcweb/snapshot.py        draws each run's screenshot PNG
amcweb/exports.py         Excel / CSV exports
supabase/schema.sql       tables, merge function, storage bucket
tests/test_core.py        run with: python3 -m pytest tests
```
